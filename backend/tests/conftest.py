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


@pytest.fixture(scope='session')
def server(database_url):
    import uvicorn
    from kinder import app as appmod
    os.environ['ADMIN_LOGIN'] = 'owner'
    os.environ['ADMIN_PASSWORD'] = 'owner-pass-123'
    application = appmod.create_app(database_url, connect=CONNECT)
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
