"""Test harness: real PostgreSQL + real uvicorn server, HTTP via urllib.

KINDER_TEST_DATABASE_URL must point at a disposable server (database 'postgres'
is used to create a fresh database per test session). Connections use psycopg
when installed, otherwise the bundled pgwire test client.
"""
import json
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))

BASE_URL = os.environ.get('KINDER_TEST_DATABASE_URL', 'postgresql://postgres@127.0.0.1:55432/postgres')

try:
    import psycopg  # noqa: F401
    from kinder.db import psycopg_connect as CONNECT
except ImportError:
    from pgwire import connect as CONNECT


def _db_url(name):
    head, _, _ = BASE_URL.rpartition('/')
    return f'{head}/{name}'


@pytest.fixture(scope='session')
def database_url():
    name = 'kinder_test_' + uuid.uuid4().hex[:8]
    admin = CONNECT(BASE_URL)
    admin.execute(f'CREATE DATABASE {name}')
    admin.close()
    yield _db_url(name)
    admin = CONNECT(BASE_URL)
    admin.execute(f'DROP DATABASE IF EXISTS {name} WITH (FORCE)')
    admin.close()


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


class Client:
    def __init__(self, base):
        self.base, self.token = base, None

    def call(self, method, path, body=None, token=..., expect=None, raw=False):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(self.base + path, data=data, method=method)
        if data is not None:
            req.add_header('Content-Type', 'application/json')
        tok = self.token if token is ... else token
        if tok:
            req.add_header('Authorization', 'Bearer ' + tok)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                status, payload, headers = r.status, r.read(), dict(r.headers)
        except urllib.error.HTTPError as e:
            status, payload, headers = e.code, e.read(), dict(e.headers)
        if raw:
            return status, payload, headers
        result = json.loads(payload) if payload else None
        if expect is not None:
            assert status == expect, (status, result)
        return status, result

    def get(self, path, **kw):
        return self.call('GET', path, **kw)

    def post(self, path, body=None, **kw):
        return self.call('POST', path, body if body is not None else {}, **kw)

    def patch(self, path, body, **kw):
        return self.call('PATCH', path, body, **kw)

    def login(self, login, password):
        status, data = self.post('/api/login', {'login': login, 'password': password}, token=None)
        assert status == 200, data
        self.token = data['token']
        return self


class FakeTelegram:
    """Records Bot API calls; answers like api.telegram.org."""
    def __init__(self):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        self.calls, self.blocked, self.lock, self.msg_id = [], set(), threading.Lock(), 100
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                method = self.path.rsplit('/', 1)[-1]
                raw = self.rfile.read(int(self.headers.get('content-length', 0)))
                ctype = self.headers.get('content-type', '')
                payload = json.loads(raw) if ctype.startswith('application/json') else {'_multipart': raw}
                if '_multipart' in payload:
                    import re
                    m = re.search(rb'name="chat_id"\r\n\r\n(-?\d+)', raw)
                    payload['chat_id'] = int(m.group(1)) if m else None
                with fake.lock:
                    fake.calls.append((method, payload))
                    fake.msg_id += 1
                    mid = fake.msg_id
                if payload.get('chat_id') in fake.blocked:
                    body, code = {'ok': False, 'error_code': 403, 'description': 'Forbidden: bot was blocked by the user'}, 403
                else:
                    result = {'message_id': mid} if method.startswith('send') else (
                        {'id': 1, 'is_bot': True, 'username': 'kinder_test_bot'} if method == 'getMe' else True)
                    body, code = {'ok': True, 'result': result}, 200
                data = json.dumps(body).encode()
                self.send_response(code)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)
        self.httpd = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.url = f'http://127.0.0.1:{self.httpd.server_address[1]}'
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def take(self, method=None, chat_id=None):
        with self.lock:
            return [p for m, p in self.calls if (method is None or m == method) and (chat_id is None or p.get('chat_id') == chat_id)]

    def wait(self, method, chat_id=None, contains=None, timeout=5.0):
        end = time.time() + timeout
        while time.time() < end:
            for p in self.take(method, chat_id):
                if contains is None or contains in p.get('text', '') or contains.encode() in p.get('_multipart', b''):
                    return p
            time.sleep(0.05)
        raise AssertionError(f'no {method} to {chat_id} containing {contains!r}; got {self.take(None, chat_id)[-5:]}')


@pytest.fixture(scope='session')
def fake_telegram():
    return FakeTelegram()


@pytest.fixture(scope='session')
def server(database_url, fake_telegram):
    import uvicorn
    from kinder import app as appmod
    from kinder.telegram import TelegramAPI
    os.environ['ADMIN_LOGIN'] = 'owner'
    os.environ['ADMIN_PASSWORD'] = 'owner-pass-123'
    os.environ['PUBLIC_URL'] = 'https://kinder.test'
    os.environ['CRON_SECRET'] = 'cron-secret-for-tests'
    application = appmod.create_app(database_url, connect=CONNECT,
                                    telegram_api=TelegramAPI('123:TEST', base=fake_telegram.url))
    port = free_port()
    config = uvicorn.Config(application, host='127.0.0.1', port=port, log_level='warning', lifespan='on')
    srv = uvicorn.Server(config)
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    for _ in range(200):
        if srv.started:
            break
        time.sleep(0.05)
    assert srv.started, 'server did not start'
    yield f'http://127.0.0.1:{port}'
    srv.should_exit = True
    thread.join(5)


@pytest.fixture
def anon(server):
    return Client(server)


@pytest.fixture
def owner(server):
    return Client(server).login('owner', 'owner-pass-123')


@pytest.fixture
def db(database_url):
    conn = CONNECT(database_url)
    yield conn
    conn.close()


@pytest.fixture
def clock():
    from kinder import app as appmod
    holder = {}

    def set_time(dt):
        appmod.CLOCK = lambda: dt
        holder['dt'] = dt
    yield set_time
    appmod.CLOCK = None
