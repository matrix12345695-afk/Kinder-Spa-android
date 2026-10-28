from datetime import timedelta
from io import BytesIO
import http.client
import json
import threading
from unittest.mock import patch
from wsgiref.simple_server import make_server, WSGIRequestHandler

import psycopg
from auth_fixtures import Fixture, PASSWORD, REPLACEMENT
from kinder.api import App
import test_postgres as accounting


class ApiTests(Fixture):
    def test_login_and_me_do_not_accept_actor_or_role(self):
        status, result, _ = self.call('POST', '/v1/login', {'login': 'client_fixture', 'password': PASSWORD})
        self.assertEqual(status, 200)
        self.assertEqual(self.call('GET', '/v1/me', token=result['access_token'])[1], {'account_id': self.client, 'role': 'client'})
        self.assertEqual(self.call('POST', '/v1/login', {'login': 'client_fixture', 'password': PASSWORD, 'role': 'admin'})[0], 400)

    def test_missing_fake_and_cookie_credentials_denied(self):
        for headers in ({}, {'HTTP_AUTHORIZATION': 'Bearer '+'a'*43}, {'HTTP_COOKIE': 'access_token=fixture'}, {'QUERY_STRING': 'token=fixture'}):
            self.assertIn(self.call('GET', '/v1/me', environ=headers)[0], (400, 401))

    def test_https_required_and_forwarded_headers_do_not_override(self):
        for headers in ({'wsgi.url_scheme': 'http'}, {'wsgi.url_scheme': 'http', 'HTTP_X_FORWARDED_PROTO': 'https'}):
            status, payload, _ = self.call('GET', '/health', environ=headers)
            self.assertEqual((status, payload), (400, {'error': 'https_required'}))

    def test_origin_rejected_without_cross_origin_or_cookie_surface(self):
        status, _, headers = self.call('GET', '/health', environ={'HTTP_ORIGIN': 'https://foreign.invalid'})
        self.assertEqual(status, 403)
        self.assertNotIn('Access-Control-Allow-Origin', headers)
        self.assertNotIn('Set-Cookie', headers)

    def test_response_headers_disable_caching_including_login(self):
        status, _, headers = self.call('POST', '/v1/login', {'login': 'client_fixture', 'password': PASSWORD})
        self.assertEqual(status, 200)
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertEqual(headers['X-Content-Type-Options'], 'nosniff')
        self.assertEqual(headers['Strict-Transport-Security'], 'max-age=31536000')

    def test_bad_json_duplicate_keys_nonfinite_and_wrong_types(self):
        for raw in (b'[]', b'{', b'{"login":"x","login":"y","password":"x"}', b'{"login":NaN,"password":"x"}'):
            self.assertEqual(self.call('POST', '/v1/login', raw=raw)[0], 400)
        self.assertEqual(self.call('POST', '/v1/login', {}, environ={'CONTENT_LENGTH': '99999'})[0], 400)
        self.assertEqual(self.call('POST', '/v1/login', {}, environ={'HTTP_TRANSFER_ENCODING': 'chunked'})[0], 400)
        self.assertEqual(self.call('POST', '/v1/login', {}, environ={'CONTENT_TYPE': 'text/plain'})[0], 400)

    def test_client_cannot_create_clients_or_grant_packages(self):
        token = self.login()
        self.assertEqual(self.call('POST', '/v1/clients', {'login': 'new_fixture', 'password': PASSWORD}, token=token)[0], 403)
        self.assertEqual(self.call('POST', '/v1/subscriptions', {'client_id': self.other, 'quotas': {'pool': 4}, 'key': 'grant_attempt'}, token=token)[0], 403)

    def test_admin_creates_client_login_and_subscription(self):
        token = self.login('admin_fixture')
        status, client, _ = self.call('POST', '/v1/clients', {'login': 'api_fixture', 'password': PASSWORD}, token=token)
        self.assertEqual(status, 201)
        self.assertEqual(set(client), {'client_id', 'login'})
        status, sub, _ = self.call('POST', '/v1/subscriptions', {'client_id': client['client_id'], 'quotas': {'pool': 8}, 'key': 'api_subscribe'}, token=token)
        self.assertEqual(status, 201)
        self.assertEqual(sub['quotas'], {'pool': 8})
        listed = self.call('GET', '/v1/clients', token=token)[1]['items']
        self.assertTrue(any(row['client_id'] == client['client_id'] for row in listed))

    def test_client_lists_only_own_records_and_pagination_is_bounded(self):
        client, other = self.login(), self.login('other_fixture')
        self.assertEqual(len(self.call('GET', '/v1/subscriptions', token=client)[1]['items']), 1)
        self.assertEqual(self.call('GET', '/v1/subscriptions', token=other)[1]['items'], [])
        self.assertEqual(self.call('GET', '/v1/clients', token=client)[0], 403)
        self.assertEqual(self.call('GET', '/v1/subscriptions', token=client, environ={'QUERY_STRING': 'client_id='+str(self.other)})[0], 400)
        self.assertEqual(self.call('GET', '/v1/subscriptions', token=client, environ={'QUERY_STRING': 'after=99999'})[1]['items'], [])

    def test_booking_injection_foreign_ownership_and_invalid_numbers_denied(self):
        args = {'subscription_id': self.subscription, 'category': 'pool', 'starts_at': accounting.START.isoformat(), 'minutes': 45, 'key': 'api_booking_1'}
        token = self.login('other_fixture')
        self.assertEqual(self.call('POST', '/v1/bookings', args, token=token)[0], 403)
        token = self.login()
        for mutation in ({'actor_id': self.other}, {'role': 'admin'}, {'subscription_id': True}, {'starts_at': '2026-11-02T09:00:00'}, {'subscription_id': '1; DROP TABLE accounts'}):
            self.assertIn(self.call('POST', '/v1/bookings', dict(args, **mutation), token=token)[0], (400, 409))
        self.assertEqual(self.remaining(), 4)

    def test_http_business_flow_qr_staff_redemption_and_replay(self):
        client, admin = self.login(), self.login('admin_fixture')
        args = {'subscription_id': self.subscription, 'category': 'pool', 'starts_at': accounting.START.isoformat(), 'minutes': 45, 'key': 'http_booking_1'}
        status, result, _ = self.call('POST', '/v1/bookings', args, token=client)
        self.assertEqual(status, 201)
        booking = result['booking_id']
        self.assertEqual(self.call('POST', '/v1/bookings', args, token=client)[1], result)
        self.assertEqual(len(self.call('GET', '/v1/bookings', token=client)[1]['items']), 1)
        self.assertEqual(self.call('GET', '/v1/bookings', token=self.login('other_fixture'))[1]['items'], [])
        self.now = accounting.START
        # Sessions last8h, so issue fresh logins after moving the synthetic clock2days.
        client, admin = self.login(), self.login('admin_fixture')
        status, qr, _ = self.call('POST', f'/v1/bookings/{booking}/qr', {}, token=client)
        self.assertEqual(status, 200)
        request = {'token': qr['token'], 'key': 'http_redeem_1'}
        self.assertEqual(self.call('POST', f'/v1/bookings/{booking}/redeem', request, token=client)[0], 403)
        self.assertEqual(self.call('POST', f'/v1/bookings/{booking}/redeem', request, token=admin)[1]['state'], 'consumed')
        self.assertEqual(self.call('POST', f'/v1/bookings/{booking}/redeem', dict(request, key='http_replay_2'), token=admin)[0], 409)
        self.assertEqual(self.remaining(), 3)

    def test_http_cancellation_restoration_and_outbox(self):
        booking = self.store.book(self.client, self.subscription, 'pool', accounting.START, 45, 'cancel_fixture')['booking_id']
        self.now = accounting.START-timedelta(hours=14)
        client, admin = self.login(), self.login('admin_fixture')
        self.assertEqual(self.call('POST', f'/v1/bookings/{booking}/cancel', {'key': 'cancel_api_1'}, token=client)[1]['state'], 'forfeited')
        status, result, _ = self.call('POST', f'/v1/bookings/{booking}/restore', {'reason': 'critical situation', 'key': 'restore_api_1'}, token=admin)
        self.assertEqual((status, result['remaining']), (200, 4))
        self.assertEqual(self.count('notification_outbox'), 1)

    def test_http_logout_and_password_reset_revoke_sessions(self):
        client, admin = self.login(), self.login('admin_fixture')
        self.assertEqual(self.call('POST', f'/v1/clients/{self.client}/password', {'password': REPLACEMENT}, token=admin)[0], 200)
        self.assertEqual(self.call('GET', '/v1/me', token=client)[0], 401)
        client = self.login(password=REPLACEMENT)
        self.assertEqual(self.call('POST', '/v1/logout', {}, token=client)[0], 200)
        self.assertEqual(self.call('GET', '/v1/me', token=client)[0], 401)

    def test_rate_limit_is_http429_and_forwarded_ip_does_not_bypass(self):
        for i in range(5):
            self.assertEqual(self.call('POST', '/v1/login', {'login': 'client_fixture', 'password': REPLACEMENT}, environ={'HTTP_X_FORWARDED_FOR': '192.0.2.'+str(i)})[0], 401)
        status, _, headers = self.call('POST', '/v1/login', {'login': 'client_fixture', 'password': PASSWORD})
        self.assertEqual(status, 429)
        self.assertEqual(headers['Retry-After'], '600')

    def test_database_errors_and_unexpected_exceptions_are_redacted(self):
        marker = 'fixture-sensitive-connection-or-password'
        for exc, expected in ((psycopg.OperationalError(marker), 503), (RuntimeError(marker), 500)):
            with patch.object(self.app, 'factory', side_effect=exc):
                status, result, _ = self.call('GET', '/health')
            self.assertEqual(status, expected)
            self.assertNotIn(marker, json.dumps(result))

    def test_unknown_path_method_and_no_bootstrap_route(self):
        token = self.login('admin_fixture')
        self.assertEqual(self.call('GET', '/v1/unknown', token=token)[0], 404)
        self.assertEqual(self.call('POST', '/v1/bootstrap', {}, token=token)[0], 404)
        self.assertEqual(self.call('DELETE', '/v1/me', token=token)[0], 405)

    def test_real_loopback_http_request_through_wsgi(self):
        class Quiet(WSGIRequestHandler):
            def log_message(self, *args):
                pass
        # Test transport only; normal App defaults to mandatory HTTPS.
        local = App(self.factory, require_https=False, clock=lambda: self.now)
        server = make_server('127.0.0.1', 0, local, handler_class=Quiet)
        worker = threading.Thread(target=server.handle_request)
        worker.start()
        try:
            conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=5)
            conn.request('POST', '/v1/login', json.dumps({'login': 'client_fixture', 'password': PASSWORD}), {'Content-Type': 'application/json'})
            response = conn.getresponse()
            value = json.loads(response.read())
            self.assertEqual(response.status, 200)
            self.assertEqual(value['token_type'], 'Bearer')
            conn.close()
        finally:
            worker.join(timeout=5)
            server.server_close()
