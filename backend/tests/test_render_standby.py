"""Pure offline gate tests. No Render, database or Telegram network calls."""
import json
import unittest
from unittest.mock import Mock, patch

from kinder import api_entry


class RenderStandbyTests(unittest.TestCase):
    @staticmethod
    def request(path, method='GET'):
        recorded = {}
        def start(status, headers):
            recorded['status'] = status
            recorded['headers'] = dict(headers)
        payload = b''.join(api_entry.standby_app({
            'PATH_INFO': path, 'REQUEST_METHOD': method,
            'HTTP_AUTHORIZATION': 'Bearer should-be-ignored',
            'HTTP_X_FORWARDED_HOST': 'attacker.invalid',
            'QUERY_STRING': 'token=secret'}, start))
        return recorded, json.loads(payload)

    @staticmethod
    def environ(**overrides):
        data = dict(RENDER='true', RENDER_SERVICE_TYPE='web',
                    RENDER_SERVICE_NAME='kinder-spa-api',
                    RENDER_SERVICE_ID='srv-abc1234567890',
                    KINDER_API_LIVE='disabled', PORT='10000')
        data.update(overrides)
        return data

    def test_health_only_proves_process_alive_not_api_ready(self):
        meta, body = self.request('/health')
        self.assertEqual(meta['status'], '200 OK')
        self.assertEqual(body['mode'], 'standby')
        self.assertFalse(body['accepting_customer_data'])
        self.assertEqual(meta['headers']['Cache-Control'], 'no-store')
        self.assertEqual(meta['headers']['X-Frame-Options'], 'DENY')

    def test_database_readiness_is_explicitly_503(self):
        meta, body = self.request('/ready')
        self.assertTrue(meta['status'].startswith('503'))
        self.assertFalse(body['ready'])

    def test_never_exposes_login_clients_or_any_other_customer_route(self):
        for method, path in (('GET','/'),('GET','/v1/me'),
                             ('GET','/admin'),('POST','/v1/login'),
                             ('POST','/v1/subscriptions'),('POST','/health'),
                             ('GET','/health/'),('GET','/unknown')):
            with self.subTest(method=method,path=path):
                meta, body = self.request(path,method)
                self.assertTrue(meta['status'].startswith('503'))
                self.assertEqual(body, {'error': 'service_not_released'})

    def test_incorrect_render_identity_fails_even_if_live_approved(self):
        for change in (dict(RENDER='false'),dict(RENDER_SERVICE_TYPE='worker'),
                       dict(RENDER_SERVICE_NAME='other'),
                       dict(RENDER_SERVICE_ID='srv-invalid!')):
            with self.subTest(change=change), patch.object(api_entry,'Server') as server:
                self.assertEqual(api_entry.main(self.environ(KINDER_API_LIVE='approved',**change)),2)
                server.assert_not_called()

    def test_disabled_standby_needs_no_credentials_or_database(self):
        with patch.object(api_entry,'Server') as server:
            server.return_value.run.return_value = None
            self.assertEqual(api_entry.main(self.environ()),0)
            server.assert_called_once_with(api_entry.standby_app,10000)
            server.return_value.run.assert_called_once()

    def test_approved_delegates_to_existing_fail_closed_api(self):
        with patch.object(api_entry,'Server') as standby, patch('kinder.render_api.main',
                return_value=2) as live:
            self.assertEqual(api_entry.main(self.environ(KINDER_API_LIVE='approved')),2)
            live.assert_called_once_with(['--run'])
            standby.assert_not_called()

    def test_invalid_mode_or_reserved_port_refuses_listener(self):
        for change in (dict(KINDER_API_LIVE=''),dict(KINDER_API_LIVE='yes'),
                       dict(PORT='18012'),dict(PORT='0'),dict(PORT='999'),
                       dict(PORT='65536'),dict(PORT='10000junk')):
            with self.subTest(change=change), patch.object(api_entry,'Server') as server:
                self.assertEqual(api_entry.main(self.environ(**change)),2)
                server.assert_not_called()
