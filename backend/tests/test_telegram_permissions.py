"""Real PostgreSQL 18 least-privilege Telegram fixtures; synthetic DB only."""
from pathlib import Path
import uuid

import psycopg
from psycopg import sql

from auth_fixtures import Fixture
from kinder.telegram_bot import Bot
from kinder.telegram_delivery import Sender, poll_once


EXPECTED_TABLE = {
    'accounts': 'SELECT',
    'subscriptions': 'SELECT',
    'allowances': 'SELECT',
    'bookings': 'SELECT',
    'qr_tokens': 'SELECT,INSERT',
    'operations': 'SELECT,INSERT',
    'audit_events': 'SELECT,INSERT',
    'notification_outbox': 'SELECT,INSERT',
    'credentials': 'SELECT',
    'auth_sessions': 'SELECT',
    'login_buckets': '',
    'telegram_link_codes': 'SELECT,INSERT',
    'telegram_bindings': 'SELECT,INSERT',
    'telegram_updates': 'SELECT,INSERT',
    'telegram_runtime': 'SELECT',
    'telegram_actions': 'SELECT,INSERT',
    'telegram_notification_batches': 'SELECT,INSERT',
    'telegram_jobs': 'SELECT,INSERT',
    'telegram_qr_cleanup': 'SELECT,INSERT',
}
EXPECTED_UPDATE_COLUMNS = {
    'accounts': {'id'},
    'subscriptions': {'id'},
    'allowances': {'remaining'},
    'bookings': {'state'},
    'qr_tokens': {'used_at', 'revoked'},
    'operations': {'result'},
    'notification_outbox': {'id'},
    'credentials': {'account_id'},
    'auth_sessions': {'token_hash'},
    'telegram_link_codes': {'revoked', 'used_peer', 'used_update'},
    'telegram_bindings': {'active', 'language'},
    'telegram_runtime': {'bot_id', 'username', 'next_offset'},
    'telegram_actions': {'state'},
    'telegram_jobs': {'state', 'error_code', 'attempts', 'lease_id',
                      'lease_until', 'next_at', 'message_id'},
    'telegram_qr_cleanup': {'done', 'attempts', 'delete_at'},
}

ALL_PRIVS = ('SELECT', 'INSERT', 'UPDATE', 'DELETE', 'TRUNCATE', 'REFERENCES', 'TRIGGER')


class TelegramRuntimeRoleTests(Fixture):
    def setUp(self):
        super().setUp()
        self.conn.execute((Path(__file__).parents[1] / 'telegram_schema.sql').read_text())
        self.runtime_role = 'tgr_' + uuid.uuid4().hex
        script = (Path(__file__).parents[1] / 'deploy' / 'telegram-role.sql').read_text()
        # Rewrite *only* literals in the review script for an isolated fixture.
        script = script.replace('kinder_telegram_runtime', self.runtime_role)
        script = script.replace('kinder_spa_db', 'kinder_test')
        script = script.replace('SCHEMA kinder TO', 'SCHEMA ' + self.schema + ' TO')
        script = script.replace('kinder.', self.schema + '.')
        self.conn.execute(script)

    def tearDown(self):
        self.conn.rollback()
        self.conn.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(self.schema)))
        self.conn.execute(sql.SQL('DROP OWNED BY {}').format(sql.Identifier(self.runtime_role)))
        self.conn.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(self.runtime_role)))
        self.conn.close()

    def runtime_factory(self):
        conn = psycopg.connect(self.url, autocommit=True)
        conn.execute(sql.SQL('SET search_path TO {}').format(sql.Identifier(self.schema)))
        conn.execute(sql.SQL('SET ROLE {}').format(sql.Identifier(self.runtime_role)))
        return conn

    def test_exact_grant_matrix_and_forbidden_privileges(self):
        with self.runtime_factory() as conn:
            flags = conn.execute("""SELECT rolsuper, rolcreatedb, rolcreaterole,
                rolreplication, rolbypassrls FROM pg_roles WHERE rolname=current_user""").fetchone()
            self.assertEqual(flags, (False, False, False, False, False))
            self.assertFalse(conn.execute('SELECT has_schema_privilege(current_user,%s,%s)',
                                          (self.schema, 'CREATE')).fetchone()[0])
            for relation, privs in EXPECTED_TABLE.items():
                with self.subTest(relation=relation):
                    for privilege in ALL_PRIVS:
                        granted = conn.execute('SELECT has_table_privilege(current_user,%s,%s)',
                            (self.schema+'.'+relation, privilege)).fetchone()[0]
                        self.assertEqual(granted, privilege in privs.split(','),
                                         (relation, privilege, granted))
                    columns = [r[0] for r in conn.execute("""SELECT attname FROM pg_attribute
                         WHERE attrelid=%s::regclass AND attnum>0 AND NOT attisdropped""",
                         (self.schema+'.'+relation,))]
                    for column in columns:
                        granted = conn.execute(
                            "SELECT has_column_privilege(current_user,%s,%s,'UPDATE')",
                            (self.schema+'.'+relation, column)).fetchone()[0]
                        self.assertEqual(granted, column in EXPECTED_UPDATE_COLUMNS.get(relation,set()),
                                         (relation, column, granted))

    def test_outbox_can_be_locked_but_never_mutated(self):
        event = self.conn.execute("""INSERT INTO audit_events(actor_id,operation,entity_id,at,details)
            VALUES(%s,'fixture',1,clock_timestamp(),'{}'::jsonb) RETURNING id""",
            (self.admin,)).fetchone()[0]
        outbox = self.conn.execute("""INSERT INTO notification_outbox(event_id,recipient_role,kind,created_at)
            VALUES(%s,'superadmin','session_restored',clock_timestamp()) RETURNING id""",
            (event,)).fetchone()[0]
        with self.runtime_factory() as conn:
            with conn.transaction():
                result = conn.execute('SELECT id FROM notification_outbox WHERE id=%s FOR UPDATE',
                                      (outbox,)).fetchone()
                self.assertEqual(result[0], outbox)
            # GENERATED ALWAYS rejects updates to identity columns before
            # reaching our append-only trigger. The same-role UPDATE grant
            # is still sufficient for SELECT ... FOR UPDATE row locking.
            with self.assertRaises(psycopg.errors.GeneratedAlways):
                with conn.transaction():
                    conn.execute('UPDATE notification_outbox SET id=id WHERE id=%s', (outbox,))
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                with conn.transaction():
                    conn.execute('UPDATE notification_outbox SET created_at=clock_timestamp() WHERE id=%s', (outbox,))
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                with conn.transaction():
                    conn.execute('DELETE FROM audit_events WHERE id=%s', (event,))
        self.assertEqual(self.conn.execute('SELECT count(*) FROM notification_outbox WHERE id=%s',
                                           (outbox,)).fetchone()[0], 1)

    def test_row_lock_only_columns_reject_identity_and_auth_changes(self):
        # The bot may lock these rows, but never change client identity,
        # credentials, session revocation or subscription ownership.
        with self.runtime_factory() as conn:
            for relation in ('accounts', 'subscriptions', 'credentials', 'auth_sessions'):
                with conn.transaction():
                    conn.execute('SELECT * FROM ' + relation + ' LIMIT 1 FOR SHARE')
            for command, value, expected_error in (
                ('UPDATE accounts SET id=id WHERE id=%s', self.client,
                 psycopg.errors.GeneratedAlways),
                ('UPDATE subscriptions SET id=id WHERE id=%s', self.subscription,
                 psycopg.errors.GeneratedAlways),
                ('UPDATE credentials SET account_id=account_id WHERE account_id=%s',
                 self.client, psycopg.errors.RaiseException),
            ):
                with self.assertRaises(expected_error):
                    with conn.transaction():
                        conn.execute(command, (value,))
            for command in (
                'UPDATE accounts SET enabled=false WHERE id=%s',
                'UPDATE subscriptions SET client_id=%s WHERE id=%s',
                'UPDATE credentials SET version=version+1 WHERE account_id=%s',
            ):
                values = (self.client, self.subscription) if 'subscriptions' in command else (self.client,)
                with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                    with conn.transaction():
                        conn.execute(command, values)
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                with conn.transaction():
                    conn.execute('UPDATE auth_sessions SET revoked=true')

    def test_runtime_role_completes_restoration_and_superadmin_receipt(self):
        # Exercise a real business write path as the narrowed Telegram role.
        # Earlier checks of an empty polling cycle cannot prove restoration.
        from datetime import timedelta
        from test_postgres import START
        from test_telegram import BOT_ID, FakeAPI, update, callback
        from auth_fixtures import PASSWORD

        self.conn.execute("""INSERT INTO credentials
            SELECT %s,%s,salt,verifier,1 FROM credentials LIMIT 1""",
            (self.superadmin, 'super_fixture'))
        bot = Bot(self.runtime_factory, clock=lambda: self.now)
        bot.configure(BOT_ID, 'KinderFixtureBot')

        admin_token = self.login('admin_fixture')
        super_token = self.auth.login('super_fixture', PASSWORD, '127.0.0.1')['access_token']
        for ident, peer, token in ((100, 202, admin_token), (200, 303, super_token)):
            payload = bot.issue_link(token)['start_payload']
            self.assertTrue(bot.process(update(ident, peer, '/start ' + payload)))

        booking = self.store.book(self.client, self.subscription, 'pool',
                                  START, 45, 'role_restore_book')['booking_id']
        self.now = START - timedelta(hours=13)
        self.store.cancel_pool(self.client, booking, 'role_late_cancel')
        self.assertEqual(self.conn.execute('SELECT state FROM bookings WHERE id=%s',
                                           (booking,)).fetchone()[0], 'forfeited')
        self.assertTrue(bot.process(update(300, 202, '/restore ' + str(booking) +
                                            ' synthetic staff reason')))
        action = self.conn.execute('SELECT id FROM telegram_actions ORDER BY update_id DESC LIMIT 1').fetchone()[0]
        self.assertTrue(bot.process(callback(301, 202, 'do:' + str(action))))
        self.assertEqual(self.conn.execute('SELECT state FROM bookings WHERE id=%s',
                                           (booking,)).fetchone()[0], 'restored')
        self.assertEqual(self.conn.execute('SELECT remaining FROM allowances WHERE subscription_id=%s AND category=%s',
                                           (self.subscription, 'pool')).fetchone()[0], 4)
        self.assertEqual(bot.fanout(), 1)
        fake = FakeAPI()
        sender = Sender(bot, fake)
        for _ in range(20):
            if not sender.send_one():
                break
        result = self.conn.execute("""SELECT j.state,j.message_id,j.payload FROM telegram_jobs j
            WHERE j.outbox_id IS NOT NULL""").fetchone()
        self.assertEqual(result[0], 'delivered')
        self.assertGreater(result[1], 0)
        self.assertNotIn('staff reason', str(result[2]))
        self.assertEqual(self.conn.execute('SELECT count(*) FROM notification_outbox').fetchone()[0], 1)

    def test_worker_can_configure_and_poll_empty_synthetic_queue(self):
        bot = Bot(self.runtime_factory)
        bot.configure(123456789, 'KinderFixtureBot')
        self.assertEqual(bot.fanout(), 0)

        class FakeAPI:
            def call(self, method, arguments):
                assert method == 'getUpdates'
                return []

        api = FakeAPI()
        self.assertEqual(poll_once(bot, api, Sender(bot, api)), 0)
        with self.runtime_factory() as conn:
            self.assertEqual(conn.execute('SELECT bot_id FROM telegram_runtime WHERE singleton=1').fetchone()[0],
                             123456789)
