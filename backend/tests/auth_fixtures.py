"""Dedicated local synthetic PostgreSQL fixtures, shared without duplicating tests."""
from io import BytesIO
import json
from pathlib import Path
import unittest

import psycopg
from psycopg import sql
import test_postgres as accounting
from kinder.auth import Auth, make_password
from kinder.api import App

PASSWORD = 'synthetic-fixture-password-1'
REPLACEMENT = 'synthetic-fixture-password-2'


class Fixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        accounting.PostgresTests.setUpClass.__func__(cls)

    def setUp(self):
        accounting.PostgresTests.setUp(self)
        self.conn.execute((Path(__file__).parents[1]/'auth_schema.sql').read_text())
        salt, verifier = make_password(PASSWORD)
        for actor, login in ((self.admin, 'admin_fixture'), (self.client, 'client_fixture'), (self.other, 'other_fixture')):
            self.conn.execute('INSERT INTO credentials(account_id,login,salt,verifier) VALUES(%s,%s,%s,%s)', (actor, login, salt, verifier))
        self.auth = Auth(self.conn, clock=lambda: self.now)
        self.app = App(self.factory, clock=lambda: self.now)

    def tearDown(self):
        accounting.PostgresTests.tearDown(self)

    def factory(self):
        conn = psycopg.connect(self.url, autocommit=True)
        conn.execute(sql.SQL('SET search_path TO {}').format(sql.Identifier(self.schema)))
        return conn

    def login(self, name='client_fixture', password=PASSWORD, ip='127.0.0.1'):
        return self.auth.login(name, password, ip)['access_token']

    def call(self, method, path, value=None, *, token=None, raw=None, environ=None):
        content = raw if raw is not None else json.dumps(value if value is not None else {}).encode()
        e = {'REQUEST_METHOD': method, 'PATH_INFO': path, 'QUERY_STRING': '',
             'CONTENT_TYPE': 'application/json', 'CONTENT_LENGTH': str(len(content)) if method == 'POST' else '0',
             'wsgi.input': BytesIO(content), 'wsgi.url_scheme': 'https', 'REMOTE_ADDR': '127.0.0.1'}
        if token:
            e['HTTP_AUTHORIZATION'] = 'Bearer '+token
        e.update(environ or {})
        status = []
        def start(code, headers):
            status.extend((int(code.split()[0]), dict(headers)))
        raw_result = b''.join(self.app(e, start))
        return status[0], json.loads(raw_result), status[1]

    remaining = accounting.PostgresTests.remaining
    count = accounting.PostgresTests.count
