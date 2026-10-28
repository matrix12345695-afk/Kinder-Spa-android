"""Bounded JSON WSGI API. No listener, public deployment or schema bootstrap.

Use behind a reviewed HTTPS gateway with bounded request/time/concurrency limits.
Gateway must supply trusted wsgi.url_scheme/REMOTE_ADDR; forwarded headers are
never accepted as security inputs here. Native clients use bearer authorization.
"""
from datetime import datetime
from http import HTTPStatus
import json
import re

import psycopg
from .auth import Auth, Denied, Limited
from .store import Store, Rejected


class BadRequest(Exception):
    pass


def fields(value, names):
    if not isinstance(value, dict) or set(value) != set(names.split()):
        raise BadRequest()
    return value


def ident(value):
    if type(value) is not int or not 1 <= value <= 9223372036854775807:
        raise BadRequest()
    return value


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise BadRequest()
        result[key] = value
    return result


def body(environ):
    if environ.get('HTTP_TRANSFER_ENCODING') or environ.get('CONTENT_TYPE', '').lower() != 'application/json':
        raise BadRequest()
    size = environ.get('CONTENT_LENGTH', '')
    if not re.fullmatch(r'[0-9]{1,5}', size) or not 2 <= int(size) <= 8192:
        raise BadRequest()
    raw = environ['wsgi.input'].read(int(size))
    if len(raw) != int(size):
        raise BadRequest()
    try:
        value = json.loads(raw.decode('utf-8'), object_pairs_hook=unique_object,
                           parse_constant=lambda _: (_ for _ in ()).throw(BadRequest()))
    except (ValueError, UnicodeError, RecursionError):
        raise BadRequest() from None
    if not isinstance(value, dict):
        raise BadRequest()
    return value


class App:
    def __init__(self, connection_factory, *, require_https=True, clock=None):
        self.factory = connection_factory
        self.require_https = require_https
        self.clock = clock

    def __call__(self, environ, start_response):
        status, payload, extra = 500, {'error': 'internal_error'}, []
        try:
            if self.require_https and environ.get('wsgi.url_scheme') != 'https':
                status, payload = 400, {'error': 'https_required'}
            elif environ.get('HTTP_ORIGIN'):
                # No cross-origin browser surface or cookie authentication yet.
                status, payload = 403, {'error': 'origin_not_allowed'}
            else:
                status, payload = self.dispatch(environ)
        except Denied:
            status, payload, extra = 401, {'error': 'authentication_failed'}, [('WWW-Authenticate', 'Bearer')]
        except Limited:
            status, payload, extra = 429, {'error': 'login_rate_limited'}, [('Retry-After', '600')]
        except Rejected as exc:
            status = 403 if str(exc) == 'access_denied' else 409
            payload = {'error': 'access_denied' if status == 403 else 'operation_rejected'}
        except (BadRequest, ValueError, UnicodeError, OverflowError, RecursionError):
            status, payload = 400, {'error': 'bad_request'}
        except psycopg.Error:
            status, payload = 503, {'error': 'temporarily_unavailable'}
        except Exception:
            # Never expose database/SQL errors, passwords, tokens or stack traces.
            status, payload = 500, {'error': 'internal_error'}
        raw = json.dumps(payload, ensure_ascii=False, separators=(',', ':'),
                         default=lambda x: x.isoformat(), allow_nan=False).encode()
        headers = [('Content-Type', 'application/json; charset=utf-8'), ('Content-Length', str(len(raw))),
                   ('Cache-Control', 'no-store'), ('Pragma', 'no-cache'),
                   ('X-Content-Type-Options', 'nosniff'), ('X-Frame-Options', 'DENY'),
                   ('Content-Security-Policy', "default-src 'none'"), ('Referrer-Policy', 'no-referrer')]
        if environ.get('wsgi.url_scheme') == 'https':
            headers.append(('Strict-Transport-Security', 'max-age=31536000'))
        start_response(str(status)+' '+HTTPStatus(status).phrase, headers+extra)
        return [raw]

    def dispatch(self, e):
        method, path = e.get('REQUEST_METHOD'), e.get('PATH_INFO')
        if method not in ('GET', 'POST'):
            return 405, {'error': 'method_not_allowed'}
        if method == 'GET' and e.get('CONTENT_LENGTH', '') not in ('', '0'):
            raise BadRequest()
        query = e.get('QUERY_STRING', '')
        after = 0
        if query:
            if method != 'GET' or path not in ('/v1/clients', '/v1/subscriptions', '/v1/bookings') or not re.fullmatch('after=[0-9]{1,19}', query):
                raise BadRequest()
            after = ident(int(query[6:]))
        data = body(e) if method == 'POST' else None
        conn = self.factory()
        try:
            auth = Auth(conn, clock=self.clock)
            if method == 'GET' and path == '/health':
                ready = conn.execute("SELECT to_regclass('auth_sessions'),to_regclass('allowances')").fetchone()
                return (200, {'ok': True}) if all(ready) else (503, {'error': 'not_ready'})
            if method == 'POST' and path == '/v1/login':
                fields(data, 'login password')
                return 200, auth.login(data['login'], data['password'], e.get('REMOTE_ADDR', ''))
            header = e.get('HTTP_AUTHORIZATION', '')
            if not isinstance(header, str) or not re.fullmatch(r'Bearer [A-Za-z0-9_-]{43}', header):
                raise Denied()
            token = header[7:]
            actor, role = auth.identify(token)
            core = Store(conn, clock=self.clock, authorize=auth.guard(token))
            if method == 'GET':
                with conn.transaction():
                    auth._limits()
                    actor, role = auth.locked(token)
                    if path == '/v1/me':
                        return 200, {'account_id': actor, 'role': role}
                    if path == '/v1/clients':
                        if role not in ('admin', 'superadmin'):
                            return 403, {'error': 'access_denied'}
                        rows = conn.execute('''SELECT a.id,c.login,a.enabled FROM accounts a
                            JOIN credentials c ON c.account_id=a.id WHERE a.role='client' AND a.id>%s ORDER BY a.id LIMIT 50''', (after,)).fetchall()
                        return 200, {'items': [dict(zip(('client_id', 'login', 'enabled'), r)) for r in rows]}
                    if path == '/v1/subscriptions':
                        ids = conn.execute('''SELECT id,client_id FROM subscriptions WHERE id>%s
                            AND (%s OR client_id=%s) ORDER BY id LIMIT 50''', (after, role != 'client', actor)).fetchall()
                        result = []
                        for sub, client in ids:
                            allowances = conn.execute('SELECT category,quota,remaining FROM allowances WHERE subscription_id=%s ORDER BY category', (sub,)).fetchall()
                            result.append({'subscription_id': sub, 'client_id': client,
                                           'allowances': [dict(zip(('category', 'quota', 'remaining'), r)) for r in allowances]})
                        return 200, {'items': result}
                    if path == '/v1/bookings':
                        rows = conn.execute('''SELECT b.id,b.subscription_id,b.category,b.starts_at,b.ends_at,b.state
                            FROM bookings b JOIN subscriptions s ON s.id=b.subscription_id
                            WHERE b.id>%s AND (%s OR s.client_id=%s) ORDER BY b.id LIMIT 50''', (after, role != 'client', actor)).fetchall()
                        return 200, {'items': [dict(zip(('booking_id', 'subscription_id', 'category', 'starts_at', 'ends_at', 'state'), r)) for r in rows]}
                return 404, {'error': 'not_found'}
            if path == '/v1/logout':
                fields(data, '')
                auth.logout(token)
                return 200, {'logged_out': True}
            if path == '/v1/clients':
                fields(data, 'login password')
                if role not in ('admin', 'superadmin'):
                    return 403, {'error': 'access_denied'}
                return 201, auth.create_client(token, data['login'], data['password'])
            reset = re.fullmatch(r'/v1/clients/([1-9][0-9]{0,18})/password', path)
            if reset:
                fields(data, 'password')
                if role not in ('admin', 'superadmin'):
                    return 403, {'error': 'access_denied'}
                auth.reset_client_password(token, ident(int(reset[1])), data['password'])
                return 200, {'sessions_revoked': True}
            if path == '/v1/subscriptions':
                fields(data, 'client_id quotas key')
                return 201, core.issue_subscription(actor, ident(data['client_id']), data['quotas'], data['key'])
            if path == '/v1/bookings':
                fields(data, 'subscription_id category starts_at minutes key')
                if not isinstance(data['starts_at'], str) or len(data['starts_at']) > 40:
                    raise BadRequest()
                return 201, core.book(actor, ident(data['subscription_id']), data['category'],
                                      datetime.fromisoformat(data['starts_at']), data['minutes'], data['key'])
            match = re.fullmatch(r'/v1/bookings/([1-9][0-9]{0,18})/(qr|redeem|cancel|no-show|restore)', path)
            if match:
                booking, action = ident(int(match[1])), match[2]
                if action == 'qr':
                    fields(data, '')
                    return 200, core.issue_qr(actor, booking)
                if action == 'redeem':
                    fields(data, 'token key')
                    return 200, core.redeem(actor, booking, data['token'], data['key'])
                if action == 'restore':
                    fields(data, 'reason key')
                    return 200, core.restore_pool(actor, booking, data['reason'], data['key'])
                fields(data, 'key')
                if action == 'cancel':
                    return 200, core.cancel_pool(actor, booking, data['key'])
                return 200, core.mark_no_show(actor, booking, data['key'])
            return 404, {'error': 'not_found'}
        finally:
            conn.close()
