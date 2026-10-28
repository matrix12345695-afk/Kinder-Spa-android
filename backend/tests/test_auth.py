from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
import threading
import time
from pathlib import Path

import psycopg
from psycopg import sql
from auth_fixtures import Fixture, PASSWORD, REPLACEMENT
from kinder.auth import Auth, Denied, Limited, make_password, derive, bootstrap_empty_database
from kinder.store import Store, Rejected
import test_postgres as accounting


class AuthTests(Fixture):
    def test_password_salt_and_scrypt_verifier(self):
        first, second = make_password(PASSWORD), make_password(PASSWORD)
        self.assertNotEqual(first, second)
        self.assertEqual(len(first[0]), 16)
        self.assertEqual(len(first[1]), 32)
        self.assertEqual(derive(PASSWORD.encode(), first[0]), first[1])

    def test_malformed_password_cannot_match_dummy_hashing_input(self):
        salt, verifier = make_password('!invalid-password')
        self.conn.execute('UPDATE credentials SET salt=%s,verifier=%s WHERE account_id=%s', (salt, verifier, self.client))
        for malformed in (None, [], 123, 'short'):
            with self.assertRaises(Denied):
                self.login(password=malformed)
        self.assertEqual(self.count('auth_sessions'), 0)

    def test_login_returns_opaque_token_and_role_from_database(self):
        token = self.login('CLIENT_fixture')
        self.assertEqual(len(token), 43)
        self.assertEqual(self.auth.identify(token), (self.client, 'client'))
        raw = self.conn.execute('SELECT json_agg(s)::text FROM auth_sessions s').fetchone()[0]
        self.assertNotIn(token, raw)
        self.assertNotIn(PASSWORD, raw)

    def test_unknown_disabled_wrong_and_malformed_logins_uniform(self):
        for name, password in (('missing_fixture', PASSWORD), ('client_fixture', 'wrong-password'), ('!!!', PASSWORD), ('other_fixture', None)):
            with self.assertRaises(Denied):
                self.auth.login(name, password, '127.0.0.1')
        self.conn.execute('UPDATE accounts SET enabled=false WHERE id=%s', (self.client,))
        with self.assertRaises(Denied):
            self.login()

    def test_logout_revokes_before_next_core_transaction(self):
        token = self.login()
        actor, _ = self.auth.identify(token)
        guarded = Store(self.conn, clock=lambda: self.now, authorize=self.auth.guard(token))
        self.auth.logout(token)
        with self.assertRaises(Denied):
            guarded.book(actor, self.subscription, 'pool', accounting.START, 45, 'revoked_booking')
        self.assertEqual(self.remaining(), 4)

    def test_session_expiration_at_exact_boundary(self):
        token = self.login()
        self.now += timedelta(hours=8)
        with self.assertRaises(Denied):
            self.auth.identify(token)

    def test_disabled_account_blocks_existing_session(self):
        token = self.login()
        self.conn.execute('UPDATE accounts SET enabled=false WHERE id=%s', (self.client,))
        with self.assertRaises(Denied):
            self.auth.identify(token)

    def test_rate_limits_persist_failed_attempts_and_reset_on_next_window(self):
        for _ in range(5):
            with self.assertRaises(Denied):
                self.login(password=REPLACEMENT)
        with self.assertRaises(Limited):
            self.login()
        self.now += timedelta(minutes=10)
        self.assertEqual(len(self.login()), 43)

    def test_ip_limit_covers_many_logins_and_no_scrypt_after_limit(self):
        with patch('kinder.auth.derive', return_value=b'x'*32) as expensive:
            for i in range(30):
                with self.assertRaises(Denied):
                    self.login(name='missing_'+str(i))
            with self.assertRaises(Limited):
                self.login(name='yet_another')
            self.assertEqual(expensive.call_count, 30)

    def test_global_limit_bounds_distinct_source_growth(self):
        with patch('kinder.auth.derive', return_value=b'x'*32) as expensive:
            for i in range(120):
                with self.assertRaises(Denied):
                    self.login(name='missing_'+str(i), ip='127.0.1.'+str(i+1))
            with self.assertRaises(Limited):
                self.login(name='new_missing', ip='127.0.2.1')
            self.assertEqual(expensive.call_count, 120)
        self.assertLessEqual(self.count('login_buckets'), 241)

    def test_client_creation_is_atomic_and_has_no_self_signup(self):
        client = self.login()
        with self.assertRaises(Denied):
            self.auth.create_client(client, 'new_fixture', PASSWORD)
        admin = self.login('admin_fixture')
        created = self.auth.create_client(admin, 'new_fixture', PASSWORD)
        self.assertEqual(self.auth.identify(self.login('new_fixture'))[0], created['client_id'])
        count = self.count('accounts')
        with self.assertRaises(Rejected):
            self.auth.create_client(admin, 'NEW_fixture', PASSWORD)
        self.assertEqual(self.count('accounts'), count)

    def test_reset_revokes_all_client_sessions_and_old_password(self):
        old = self.login()
        admin = self.login('admin_fixture')
        actor, _ = self.auth.identify(old)
        core = Store(self.conn, clock=lambda: self.now, authorize=self.auth.guard(old))
        self.auth.reset_client_password(admin, self.client, REPLACEMENT)
        with self.assertRaises(Denied):
            self.auth.identify(old)
        with self.assertRaises(Denied):
            core.book(actor, self.subscription, 'pool', accounting.START, 45, 'reset_fence_test')
        with self.assertRaises(Denied):
            self.login()
        self.assertEqual(len(self.login(password=REPLACEMENT)), 43)

    def test_client_cannot_reset_and_staff_target_cannot_be_reset(self):
        token = self.login()
        with self.assertRaises(Denied):
            self.auth.reset_client_password(token, self.other, REPLACEMENT)
        admin = self.login('admin_fixture')
        with self.assertRaises(Denied):
            self.auth.reset_client_password(admin, self.superadmin, REPLACEMENT)

    def test_password_and_token_never_enter_audit_or_operations(self):
        admin = self.login('admin_fixture')
        created = self.auth.create_client(admin, 'minimal_fixture', PASSWORD)
        self.auth.reset_client_password(admin, created['client_id'], REPLACEMENT)
        for table in ('audit_events', 'operations', 'login_buckets'):
            raw = self.conn.execute(sql.SQL("SELECT coalesce(json_agg(t)::text,'') FROM {} t").format(sql.Identifier(table))).fetchone()[0]
            for forbidden in (admin, PASSWORD, REPLACEMENT):
                self.assertNotIn(forbidden, raw)

    def test_session_cap_revokes_oldest_of_six_logins(self):
        first = self.login()
        self.now += timedelta(minutes=10)  # Separate throttle windows, same8h lifetime.
        for i in range(5):
            self.now += timedelta(seconds=1)
            latest = self.login()
        with self.assertRaises(Denied):
            self.auth.identify(first)
        self.auth.identify(latest)

    def test_guard_rejects_wrong_actor_and_connection(self):
        token = self.login()
        with self.conn.transaction(), self.assertRaises(Denied):
            self.auth.guard(token)(self.conn, self.other)
        with self.factory() as other, self.assertRaises(Denied):
            self.auth.guard(token)(other, self.client)

    def test_reset_audit_failure_rolls_back_credentials_and_revocation(self):
        admin, client = self.login('admin_fixture'), self.login()
        before = self.conn.execute('SELECT verifier,version FROM credentials WHERE account_id=%s', (self.client,)).fetchone()
        with patch.object(self.auth.core, '_audit', side_effect=RuntimeError('synthetic failure')):
            with self.assertRaises(RuntimeError):
                self.auth.reset_client_password(admin, self.client, REPLACEMENT)
        self.assertEqual(self.conn.execute('SELECT verifier,version FROM credentials WHERE account_id=%s', (self.client,)).fetchone(), before)
        self.auth.identify(client)

    def test_bootstrap_refuses_any_existing_accounts(self):
        with self.assertRaises(Denied):
            bootstrap_empty_database(self.conn, 'operator_fixture', PASSWORD)

    def test_concurrent_attempts_cannot_bypass_login_limit(self):
        barrier = threading.Barrier(8)
        def attempt(i):
            with self.factory() as conn:
                barrier.wait(timeout=5)
                auth = Auth(conn, clock=lambda: self.now)
                try:
                    auth.login('missing_fixture', PASSWORD, '127.0.0.1')
                except Limited:
                    return 'limited'
                except Denied:
                    return 'denied'
        with patch('kinder.auth.derive', return_value=b'x'*32), ThreadPoolExecutor(max_workers=8) as pool:
            outcomes = list(pool.map(attempt, range(8)))
        self.assertEqual(outcomes.count('denied'), 5)
        self.assertEqual(outcomes.count('limited'), 3)

    def test_reset_waits_for_admitted_transaction_before_revoking(self):
        admin, client = self.login('admin_fixture'), self.login()
        entered = threading.Event()
        remote = {}
        def reset():
            with self.factory() as conn:
                auth = Auth(conn, clock=lambda: self.now)
                remote['pid'] = conn.info.backend_pid
                entered.set()
                auth.reset_client_password(admin, self.client, REPLACEMENT)
        with ThreadPoolExecutor(max_workers=1) as pool:
            with self.conn.transaction():
                self.auth.locked(client)
                future = pool.submit(reset)
                self.assertTrue(entered.wait(2))
                deadline = time.monotonic()+2
                while self.conn.info.backend_pid not in self.conn.execute('SELECT pg_blocking_pids(%s)', (remote['pid'],)).fetchone()[0]:
                    self.assertLess(time.monotonic(), deadline)
                    time.sleep(.01)
                self.assertFalse(future.done())
            future.result(timeout=5)
        with self.assertRaises(Denied):
            self.auth.identify(client)

    def test_explicit_empty_database_bootstrap_creates_one_superadmin(self):
        name = self.schema+'_bootstrap'
        self.conn.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(name)))
        try:
            self.conn.execute(sql.SQL('SET search_path TO {}').format(sql.Identifier(name)))
            for file in ('schema.sql', 'auth_schema.sql'):
                self.conn.execute((Path(__file__).parents[1]/file).read_text())
            actor = bootstrap_empty_database(self.conn, 'first_operator', PASSWORD)
            live_auth = Auth(self.conn)
            token = live_auth.login('first_operator', PASSWORD, '127.0.0.1')['access_token']
            self.assertEqual(live_auth.identify(token), (actor, 'superadmin'))
            with self.assertRaises(Denied):
                bootstrap_empty_database(self.conn, 'second_operator', PASSWORD)
        finally:
            self.conn.execute(sql.SQL('SET search_path TO {}').format(sql.Identifier(self.schema)))
            self.conn.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(name)))

    def test_credential_change_during_scrypt_cannot_create_old_password_session(self):
        original = derive
        def reset_during_hash(raw, salt):
            result = original(raw, salt)
            self.conn.execute('UPDATE credentials SET version=version+1 WHERE account_id=%s', (self.client,))
            return result
        with patch('kinder.auth.derive', side_effect=reset_during_hash), self.assertRaises(Denied):
            self.login()
        self.assertEqual(self.count('auth_sessions'), 0)
