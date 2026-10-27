"""Real PostgreSQL transactions and races; synthetic identities only.

The test URL must target a disposable LOCAL database named kinder_test. No skips:
missing configuration fails the suite, never masquerades as PostgreSQL acceptance.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import os
from pathlib import Path
import threading
import unittest
from unittest.mock import patch
import uuid

import psycopg
from psycopg.conninfo import conninfo_to_dict
from psycopg import sql
from kinder.store import Store, Rejected

START = datetime.fromisoformat('2026-11-02T09:00:00+05:00')
BEFORE = START-timedelta(days=2)


class PostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.url = os.environ.get('KINDER_TEST_DATABASE_URL', '')
        parsed = conninfo_to_dict(cls.url) if cls.url else {}
        if (parsed.get('host') not in ('127.0.0.1', 'localhost') or parsed.get('dbname') != 'kinder_test'
                or any(k in parsed for k in ('service', 'hostaddr', 'options'))):
            raise RuntimeError('disposable local kinder_test database required')
        with psycopg.connect(cls.url, autocommit=True) as conn:
            if conn.info.server_version // 10000 != 18:
                raise RuntimeError('PostgreSQL18 required')

    def setUp(self):
        self.schema = 'fixture_'+uuid.uuid4().hex
        self.conn = psycopg.connect(self.url, autocommit=True)
        self.conn.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(self.schema)))
        self.conn.execute(sql.SQL('SET search_path TO {}').format(sql.Identifier(self.schema)))
        self.conn.execute((Path(__file__).parents[1]/'schema.sql').read_text())
        self.admin = self.conn.execute("INSERT INTO accounts(role) VALUES('admin') RETURNING id").fetchone()[0]
        self.superadmin = self.conn.execute("INSERT INTO accounts(role) VALUES('superadmin') RETURNING id").fetchone()[0]
        self.now = BEFORE
        self.store = Store(self.conn, clock=lambda: self.now)
        self.client = self.store.create_client(self.admin, 'create_client_1')['client_id']
        self.other = self.store.create_client(self.admin, 'create_client_2')['client_id']
        self.subscription = self.store.issue_subscription(self.admin, self.client,
                            {'pool': 4, 'massage': 10}, 'subscription_1')['subscription_id']

    def tearDown(self):
        self.conn.rollback()
        self.conn.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(self.schema)))
        self.conn.close()

    def book(self, key='booking_key_1', start=START, actor=None):
        return self.store.book(actor or self.client, self.subscription, 'pool', start, 45, key)['booking_id']

    def remaining(self, category='pool'):
        return self.conn.execute('SELECT remaining FROM allowances WHERE subscription_id=%s AND category=%s',
                                 (self.subscription, category)).fetchone()[0]

    def count(self, table):
        return self.conn.execute(sql.SQL('SELECT count(*) FROM {}').format(sql.Identifier(table))).fetchone()[0]

    def late(self):
        booking = self.book()
        self.now = START-timedelta(hours=13)
        self.store.cancel_pool(self.client, booking, 'late_cancel_1')
        return booking

    def qr(self):
        booking = self.book()
        self.now = START
        token = self.store.issue_qr(self.client, booking)['token']
        return booking, token

    def race(self, calls, *, now=None):
        barrier = threading.Barrier(len(calls))
        def run(call):
            with psycopg.connect(self.url, autocommit=True) as conn:
                conn.execute(sql.SQL('SET search_path TO {}').format(sql.Identifier(self.schema)))
                conn.execute("SET statement_timeout TO '8s'")
                store = Store(conn, clock=lambda: now or self.now)
                barrier.wait(timeout=5)
                try:
                    return ('ok', call(store))
                except Rejected as exc:
                    return ('rejected', str(exc))
        with ThreadPoolExecutor(max_workers=len(calls)) as pool:
            return list(pool.map(run, calls))

    def test_only_admin_issues_accounts_and_packages(self):
        with self.assertRaises(Rejected):
            self.store.create_client(self.client, 'no_client_signup')
        with self.assertRaises(Rejected):
            self.store.issue_subscription(self.client, self.other, {'pool': 4}, 'no_client_grant')
        result = self.store.create_client(self.superadmin, 'super_client_1')
        self.assertGreater(result['client_id'], self.other)

    def test_inactive_or_unknown_actor_denied_even_replay(self):
        self.conn.execute('UPDATE accounts SET enabled=false WHERE id=%s', (self.admin,))
        for actor in (self.admin, 999999, True):
            with self.assertRaises(Rejected):
                self.store.create_client(actor, 'create_client_1')

    def test_subscriptions_cannot_target_staff_or_inactive_client(self):
        for client in (self.admin, self.superadmin):
            with self.assertRaises(Rejected):
                self.store.issue_subscription(self.admin, client, {'pool': 4}, 'invalid_sub_123')
        self.conn.execute('UPDATE accounts SET enabled=false WHERE id=%s', (self.other,))
        with self.assertRaises(Rejected):
            self.store.issue_subscription(self.admin, self.other, {'pool': 4}, 'inactive_sub_1')

    def test_client_cannot_use_another_subscription(self):
        with self.assertRaises(Rejected):
            self.book(actor=self.other)
        self.assertEqual(self.remaining(), 4)

    def test_book_reserves_exact_category_once(self):
        booking = self.book()
        self.assertEqual(self.remaining(), 3)
        self.assertEqual(self.remaining('massage'), 10)
        self.assertEqual(self.book(), booking)
        self.assertEqual(self.remaining(), 3)

    def test_idempotency_conflict_and_utc_equivalent_booking(self):
        booking = self.book()
        self.assertEqual(self.book(start=START.astimezone(__import__('datetime').timezone.utc)), booking)
        with self.assertRaises(Rejected):
            self.book(start=START+timedelta(hours=1))
        self.assertEqual(self.remaining(), 3)

    def test_balance_and_overlap_enforced(self):
        self.book()
        with self.assertRaises(Rejected):
            self.book(key='overlapping_1', start=START+timedelta(minutes=30))
        for i in range(1, 4):
            self.book(key='booking_'+str(i)+'_123', start=START+timedelta(hours=i))
        with self.assertRaises(Rejected):
            self.book(key='empty_balance', start=START+timedelta(hours=5))
        self.assertEqual(self.remaining(), 0)

    def test_simultaneous_same_key_returns_same_booking(self):
        outcomes = self.race([lambda s: s.book(self.client, self.subscription, 'pool', START, 45, 'same_key_123')]*2)
        self.assertTrue(all(x[0] == 'ok' for x in outcomes))
        self.assertEqual(outcomes[0], outcomes[1])
        self.assertEqual(self.remaining(), 3)
        self.assertEqual(self.count('bookings'), 1)

    def test_simultaneous_last_visit_cannot_overspend(self):
        for i in range(3):
            self.book(key='early_book_'+str(i), start=START+timedelta(hours=i))
        calls = [(lambda s, i=i: s.book(self.client, self.subscription, 'pool', START+timedelta(hours=i), 45, 'last_visit_'+str(i))) for i in (3, 4)]
        outcomes = self.race(calls)
        self.assertEqual(sorted(x[0] for x in outcomes), ['ok', 'rejected'])
        self.assertEqual(self.remaining(), 0)

    def test_qr_opaque_short_lived_not_in_database(self):
        booking, token = self.qr()
        self.assertEqual(len(token), 43)
        for table in ('qr_tokens', 'audit_events', 'operations'):
            raw = self.conn.execute(sql.SQL('SELECT coalesce(json_agg(t)::text,\'\') FROM {} t').format(sql.Identifier(table))).fetchone()[0]
            self.assertNotIn(token, raw)
        expires = self.conn.execute('SELECT expires_at FROM qr_tokens').fetchone()[0]
        self.assertEqual((expires-self.now).total_seconds(), 120)

    def test_qr_only_owner_or_staff_and_during_session(self):
        booking = self.book()
        with self.assertRaises(Rejected):
            self.store.issue_qr(self.client, booking)
        self.now = START
        with self.assertRaises(Rejected):
            self.store.issue_qr(self.other, booking)
        self.now += timedelta(minutes=45)
        with self.assertRaises(Rejected):
            self.store.issue_qr(self.client, booking)

    def test_qr_expiry_and_remint_revoke_old(self):
        booking, old = self.qr()
        self.now += timedelta(minutes=2)
        with self.assertRaises(Rejected):
            self.store.redeem(self.admin, booking, old, 'expired_qr_1')
        new = self.store.issue_qr(self.client, booking)['token']
        with self.assertRaises(Rejected):
            self.store.redeem(self.admin, booking, old, 'revoked_qr_1')
        self.assertEqual(self.store.redeem(self.admin, booking, new, 'valid_qr_1')['state'], 'consumed')

    def test_client_cannot_redeem_or_qr_replay(self):
        booking, token = self.qr()
        with self.assertRaises(Rejected):
            self.store.redeem(self.client, booking, token, 'client_redeem')
        first = self.store.redeem(self.admin, booking, token, 'staff_redeem_1')
        self.assertEqual(self.store.redeem(self.admin, booking, token, 'staff_redeem_1'), first)
        with self.assertRaises(Rejected):
            self.store.redeem(self.admin, booking, token, 'staff_replay_2')
        self.assertEqual(self.remaining(), 3)

    def test_qr_cannot_switch_booking(self):
        first = self.book()
        second = self.book(key='second_booking', start=START+timedelta(hours=1))
        self.now = START
        token = self.store.issue_qr(self.client, first)['token']
        self.now += timedelta(hours=1)
        with self.assertRaises(Rejected):
            self.store.redeem(self.admin, second, token, 'wrong_booking')

    def test_concurrent_redemption_exactly_once(self):
        booking, token = self.qr()
        outcomes = self.race([(lambda s, i=i: s.redeem(self.admin, booking, token, 'race_redeem_'+str(i))) for i in range(2)])
        self.assertEqual(sorted(x[0] for x in outcomes), ['ok', 'rejected'])
        self.assertEqual(self.conn.execute("SELECT count(*) FROM audit_events WHERE operation='redeem'").fetchone()[0], 1)

    def test_early_cancel_refunds_and_replay_cannot_double_credit(self):
        booking = self.book()
        self.now = START-timedelta(hours=14, microseconds=1)
        outcome = self.store.cancel_pool(self.client, booking, 'early_cancel_1')
        self.assertEqual(outcome['state'], 'cancelled')
        self.assertEqual(self.store.cancel_pool(self.client, booking, 'early_cancel_1'), outcome)
        with self.assertRaises(Rejected):
            self.store.cancel_pool(self.client, booking, 'double_cancel')
        self.assertEqual(self.remaining(), 4)

    def test_exact19_previous_day_forfeits(self):
        booking = self.book()
        self.now = START-timedelta(hours=14)
        self.assertEqual(self.store.cancel_pool(self.client, booking, 'cutoff_cancel')['state'], 'forfeited')
        self.assertEqual(self.remaining(), 3)

    def test_late_cancel_no_client_restoration(self):
        booking = self.late()
        with self.assertRaises(Rejected):
            self.store.restore_pool(self.client, booking, 'critical situation', 'client_restore')
        self.assertEqual(self.remaining(), 3)

    def test_restoration_requires_reason_and_enqueues_superadmin_atomically(self):
        booking = self.late()
        for reason in ('', '  ', 'ab'):
            with self.assertRaises(Rejected):
                self.store.restore_pool(self.admin, booking, reason, 'missing_reason')
        result = self.store.restore_pool(self.admin, booking, 'critical situation', 'valid_restore_1')
        self.assertEqual(result['remaining'], 4)
        self.assertEqual(self.store.restore_pool(self.admin, booking, 'critical situation', 'valid_restore_1'), result)
        self.assertEqual(self.count('notification_outbox'), 1)
        row = self.conn.execute('''SELECT a.actor_id,a.details,o.recipient_role,o.event_id FROM notification_outbox o
            JOIN audit_events a ON a.id=o.event_id''').fetchone()
        self.assertEqual(row, (self.admin, {'reason': 'critical situation', 'remaining': 4}, 'superadmin', result['event_id']))
        with self.assertRaises(Rejected):
            self.store.restore_pool(self.admin, booking, 'second adjustment', 'duplicate_restore')

    def test_outbox_failure_rolls_back_restoration_balance_and_audit(self):
        booking = self.late()
        before = self.count('audit_events')
        self.conn.execute("ALTER TABLE notification_outbox ADD CONSTRAINT fail_fixture CHECK (false)")
        with self.assertRaises(psycopg.errors.CheckViolation):
            self.store.restore_pool(self.admin, booking, 'critical situation', 'failed_outbox')
        self.assertEqual(self.remaining(), 3)
        self.assertEqual(self.count('audit_events'), before)
        self.assertEqual(self.conn.execute('SELECT state FROM bookings WHERE id=%s', (booking,)).fetchone()[0], 'forfeited')
        self.conn.execute('ALTER TABLE notification_outbox DROP CONSTRAINT fail_fixture')
        self.assertEqual(self.store.restore_pool(self.admin, booking, 'critical situation', 'failed_outbox')['remaining'], 4)

    def test_concurrent_restoration_only_one_credit_and_notice(self):
        booking = self.late()
        outcomes = self.race([(lambda s, i=i: s.restore_pool(self.admin, booking, 'critical situation', 'race_restore_'+str(i))) for i in range(2)])
        self.assertEqual(sorted(x[0] for x in outcomes), ['ok', 'rejected'])
        self.assertEqual(self.remaining(), 4)
        self.assertEqual(self.count('notification_outbox'), 1)

    def test_no_show_only_staff_after_session_end(self):
        booking = self.book()
        with self.assertRaises(Rejected):
            self.store.mark_no_show(self.admin, booking, 'early_no_show')
        self.now = START+timedelta(minutes=45)
        with self.assertRaises(Rejected):
            self.store.mark_no_show(self.client, booking, 'client_no_show')
        self.assertEqual(self.store.mark_no_show(self.admin, booking, 'valid_no_show')['state'], 'no_show')
        self.assertEqual(self.store.restore_pool(self.superadmin, booking, 'critical situation', 'super_restore')['remaining'], 4)

    def test_unapproved_non_pool_cancellation_is_blocked(self):
        booking = self.store.book(self.client, self.subscription, 'massage', START, 30, 'massage_booking')['booking_id']
        for operation in (lambda: self.store.cancel_pool(self.client, booking, 'massage_cancel'),
                          lambda: self.store.mark_no_show(self.admin, booking, 'massage_no_show')):
            with self.assertRaises(Rejected):
                operation()

    def test_consumed_visit_cannot_be_restored_or_cancelled(self):
        booking, token = self.qr()
        self.store.redeem(self.admin, booking, token, 'consume_visit')
        with self.assertRaises(Rejected):
            self.store.restore_pool(self.admin, booking, 'critical situation', 'undo_consumed')
        with self.assertRaises(Rejected):
            self.store.cancel_pool(self.client, booking, 'cancel_consumed')

    def test_audit_cannot_be_rewritten_or_deleted(self):
        with self.assertRaises(psycopg.errors.RaiseException):
            self.conn.execute("UPDATE audit_events SET details='{}'")
        with self.assertRaises(psycopg.errors.RaiseException):
            self.conn.execute('DELETE FROM audit_events')

    def test_transaction_context_cannot_partially_commit(self):
        with self.conn.transaction():
            with self.assertRaises(Rejected):
                self.store.create_client(self.admin, 'nested_attempt')

    def test_default_clock_is_database_clock(self):
        now = Store(self.conn)._now()
        database_now = self.conn.execute('SELECT clock_timestamp()').fetchone()[0]
        self.assertLess(abs((now-database_now).total_seconds()), 2)

    def test_waiting_for_booking_lock_cannot_use_old_cancellation_time(self):
        booking = self.book()
        self.now = START-timedelta(hours=14, microseconds=1)
        original = self.store._booking
        def acquired(ident):
            row = original(ident)
            # Simulate a lock wait that crossed the strict cancellation boundary.
            self.now = START-timedelta(hours=14)
            return row
        with patch.object(self.store, '_booking', side_effect=acquired):
            result = self.store.cancel_pool(self.client, booking, 'waited_cancel')
        self.assertEqual(result['state'], 'forfeited')
        self.assertEqual(self.remaining(), 3)

    def test_waiting_for_lock_cannot_redeem_expired_qr(self):
        booking, token = self.qr()
        original = self.store._booking
        def acquired(ident):
            row = original(ident)
            self.now = START+timedelta(minutes=2)
            return row
        with patch.object(self.store, '_booking', side_effect=acquired), self.assertRaises(Rejected):
            self.store.redeem(self.admin, booking, token, 'waited_redeem')

    def test_disabled_client_blocks_staff_booking_and_existing_qr(self):
        booking, token = self.qr()
        self.conn.execute('UPDATE accounts SET enabled=false WHERE id=%s', (self.client,))
        with self.assertRaises(Rejected):
            self.store.redeem(self.admin, booking, token, 'disabled_redeem')
        with self.assertRaises(Rejected):
            self.book(key='disabled_booking', start=START+timedelta(hours=1), actor=self.admin)

    def test_qr_expiry_is_capped_by_session_end(self):
        booking = self.book()
        self.now = START+timedelta(minutes=44, seconds=50)
        result = self.store.issue_qr(self.client, booking)
        self.assertEqual(datetime.fromisoformat(result['expires_at']), START+timedelta(minutes=45))

    def test_audit_failure_rolls_back_account_and_idempotency_row(self):
        before = self.count('accounts')
        with patch.object(self.store, '_audit', side_effect=RuntimeError('synthetic audit failure')):
            with self.assertRaises(RuntimeError):
                self.store.create_client(self.admin, 'retry_after_audit')
        self.assertEqual(self.count('accounts'), before)
        result = self.store.create_client(self.admin, 'retry_after_audit')
        self.assertGreater(result['client_id'], 0)
        self.assertEqual(self.count('accounts'), before+1)


if __name__ == '__main__':
    unittest.main()
