"""Real PostgreSQL18 acceptance for the REVIEW-ONLY Kinder API runtime role.

The proposed SQL is rewritten only for a disposable fixture database/schema.
This suite NEVER connects to Render, never creates production roles or tables.
"""
from pathlib import Path
import uuid

import psycopg
from psycopg import sql

from auth_fixtures import Fixture, PASSWORD
from kinder.api import App
from kinder.render_api import TABLES, UPDATE_COLUMNS, inspect_database
from test_postgres import START

PRIVS = ('SELECT', 'INSERT', 'UPDATE', 'DELETE', 'TRUNCATE', 'REFERENCES', 'TRIGGER')


class ApiRuntimeRoleTests(Fixture):
    def setUp(self):
        super().setUp()
        self.role = 'kapi_' + uuid.uuid4().hex
        script = (Path(__file__).parents[1] / 'deploy' / 'api-role.sql').read_text()
        script = script.replace('kinder_api_runtime', self.role)
        script = script.replace('kinder_spa_db', 'kinder_test')
        script = script.replace('SCHEMA kinder TO', 'SCHEMA ' + self.schema + ' TO')
        script = script.replace('kinder.', self.schema + '.')
        self.conn.execute(script)
        self.app = App(self.runtime_factory, clock=lambda: self.now)

    def tearDown(self):
        self.conn.rollback()
        self.conn.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(self.schema)))
        self.conn.execute(sql.SQL('DROP OWNED BY {}').format(sql.Identifier(self.role)))
        self.conn.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(self.role)))
        self.conn.close()

    def runtime_factory(self):
        conn = psycopg.connect(self.url, autocommit=True)
        conn.execute(sql.SQL('SET search_path TO {}').format(sql.Identifier(self.schema)))
        conn.execute(sql.SQL('SET ROLE {}').format(sql.Identifier(self.role)))
        return conn

    def test_exact_permissions_and_ready_metadata_without_owner_powers(self):
        with self.runtime_factory() as conn:
            self.assertTrue(inspect_database(self.runtime_factory, self.schema)['ready'])
            role = conn.execute("""SELECT rolsuper,rolcreatedb,rolcreaterole,
                rolreplication,rolbypassrls FROM pg_roles WHERE rolname=current_user""").fetchone()
            self.assertEqual(role, (False, False, False, False, False))
            self.assertFalse(conn.execute('SELECT has_schema_privilege(current_user,%s,%s)',
                                          (self.schema, 'CREATE')).fetchone()[0])
            for table, allowed in TABLES.items():
                with self.subTest(table=table):
                    for priv in PRIVS:
                        have = conn.execute('SELECT has_table_privilege(current_user,%s,%s)',
                            (self.schema + '.' + table, priv)).fetchone()[0]
                        self.assertEqual(have, priv in allowed.split(','),
                                         (table, priv, have))
                    columns = [r[0] for r in conn.execute("""SELECT attname FROM pg_attribute
                        WHERE attrelid=%s::regclass AND attnum>0 AND NOT attisdropped""",
                        (self.schema + '.' + table,))]
                    for column in columns:
                        granted = conn.execute(
                            "SELECT has_column_privilege(current_user,%s,%s,'UPDATE')",
                            (self.schema + '.' + table, column)).fetchone()[0]
                        self.assertEqual(granted, column in UPDATE_COLUMNS.get(table, ()),
                                         (table, column, granted))

    def test_role_executes_real_login_subscription_qr_and_revocation(self):
        status, user, _ = self.call('POST','/v1/login',
            {'login':'admin_fixture','password':PASSWORD})
        self.assertEqual(status, 200, user)
        admin_token = user['access_token']
        status, sub, _ = self.call('POST','/v1/subscriptions',
            {'client_id': self.other, 'quotas': {'pool': 4}, 'key':'api-role-issue'},
            token=admin_token)
        self.assertEqual(status, 201, sub)
        status, booking, _ = self.call('POST','/v1/bookings',
            {'subscription_id': sub['subscription_id'], 'category':'pool',
             'starts_at':START.isoformat(),'minutes':45,'key':'api-role-book'},
            token=admin_token)
        self.assertEqual(status, 201, booking)
        status, customer, _ = self.call('POST','/v1/login',
            {'login':'other_fixture','password':PASSWORD})
        self.assertEqual(status, 200, customer)
        self.now = START
        status, qr, _ = self.call('POST',
            '/v1/bookings/' + str(booking['booking_id']) + '/qr', {},
            token=customer['access_token'])
        self.assertEqual(status, 200, qr)
        self.assertEqual(len(qr['token']), 43)
        status, attendance, _ = self.call('POST',
            '/v1/bookings/' + str(booking['booking_id']) + '/redeem',
            {'token':qr['token'], 'key':'api-role-redeem'}, token=admin_token)
        self.assertEqual(status, 200, attendance)
        self.assertEqual(self.conn.execute(
            'SELECT state FROM bookings WHERE id=%s',
            (booking['booking_id'],)).fetchone()[0], 'consumed')
        self.assertEqual(self.conn.execute(
            "SELECT remaining FROM allowances WHERE subscription_id=%s AND category='pool'",
            (sub['subscription_id'],)).fetchone()[0], 3)
        status, changed, _ = self.call('POST', '/v1/clients/'+str(self.other)+'/password',
            {'password':'new-private-synthetic-password'}, token=admin_token)
        self.assertEqual(status, 200, changed)
        status, _, _ = self.call('GET','/v1/me', token=customer['access_token'])
        self.assertEqual(status, 401)
        with self.runtime_factory() as conn:
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                with conn.transaction():
                    conn.execute('UPDATE accounts SET enabled=false WHERE id=%s', (self.other,))
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                with conn.transaction():
                    conn.execute('UPDATE audit_events SET details=details')
