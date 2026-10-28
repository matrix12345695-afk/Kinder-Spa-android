"""Transactional PostgreSQL core; caller supplies a server-authenticated account ID.

Never expose actor IDs as an authentication mechanism. No network listener, signup,
password store, Telegram sender, clinical data or database bootstrap is provided here.
Every public write owns one outer transaction on an autocommit connection.
"""
from datetime import timedelta
import hashlib
import json
import re
import secrets

from psycopg import pq
from psycopg.types.json import Jsonb
from . import policy

Rejected = policy.Rejected


def positive(value):
    if type(value) is not int or value <= 0:
        raise Rejected('invalid_identity')
    return value


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False).encode()).hexdigest()


def token_hash(token):
    if not isinstance(token, str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}', token):
        raise Rejected('invalid_qr')
    return hashlib.sha256(token.encode('ascii')).hexdigest()


class Store:
    def __init__(self, connection, *, clock=None, authorize=None):
        self.conn = connection
        self.authorize = authorize
        # Clock injection is for synthetic tests; production must use PostgreSQL time.
        self.clock = clock

    def _idle(self):
        if not self.conn.autocommit or self.conn.info.transaction_status != pq.TransactionStatus.IDLE:
            raise Rejected('outer_transaction_required')

    def _now(self):
        return policy.moment(self.clock() if self.clock else
                             self.conn.execute('SELECT clock_timestamp()').fetchone()[0])

    def _actor(self, actor, staff=False):
        positive(actor)
        row = self.conn.execute('SELECT role,enabled FROM accounts WHERE id=%s FOR SHARE', (actor,)).fetchone()
        if not row or row[1] is not True or (staff and row[0] not in ('admin', 'superadmin')):
            raise Rejected('access_denied')
        if self.authorize is not None:
            self.authorize(self.conn, actor)
        return row[0]

    def _audit(self, actor, operation, entity, at, details):
        return self.conn.execute('''INSERT INTO audit_events(actor_id,operation,entity_id,at,details)
            VALUES(%s,%s,%s,%s,%s) RETURNING id''', (actor, operation, entity, at, Jsonb(details))).fetchone()[0]

    def _command(self, actor, operation, key, request, apply, *, staff=False):
        self._idle()
        if not isinstance(key, str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,100}', key):
            raise Rejected('invalid_request_key')
        fingerprint = digest(request)
        with self.conn.transaction():
            self.conn.execute("SET LOCAL lock_timeout TO '3s'")
            self.conn.execute("SET LOCAL statement_timeout TO '5s'")
            role = self._actor(actor, staff)
            self.conn.execute('''INSERT INTO operations(actor_id,operation,request_key,request_hash)
                VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING''', (actor, operation, key, fingerprint))
            previous = self.conn.execute('''SELECT request_hash,result FROM operations
                WHERE actor_id=%s AND operation=%s AND request_key=%s FOR UPDATE''', (actor, operation, key)).fetchone()
            if previous[0] != fingerprint:
                raise Rejected('idempotency_conflict')
            if previous[1] is not None:
                return previous[1]
            result = apply(role)
            self.conn.execute('''UPDATE operations SET result=%s
                WHERE actor_id=%s AND operation=%s AND request_key=%s''', (Jsonb(result), actor, operation, key))
            return result

    def _subscription(self, ident):
        positive(ident)
        row = self.conn.execute('SELECT client_id FROM subscriptions WHERE id=%s FOR UPDATE', (ident,)).fetchone()
        if not row:
            raise Rejected('subscription_missing')
        client = self.conn.execute('SELECT role,enabled FROM accounts WHERE id=%s FOR SHARE', (row[0],)).fetchone()
        if client != ('client', True):
            raise Rejected('client_unavailable')
        return row[0]

    def _booking(self, ident):
        positive(ident)
        pointer = self.conn.execute('SELECT subscription_id FROM bookings WHERE id=%s', (ident,)).fetchone()
        if not pointer:
            raise Rejected('booking_missing')
        # Consistent lock order: subscription -> booking -> token, on ALL operations.
        client = self._subscription(pointer[0])
        row = self.conn.execute('''SELECT subscription_id,category,starts_at,ends_at,state
            FROM bookings WHERE id=%s FOR UPDATE''', (ident,)).fetchone()
        return client, row

    @staticmethod
    def _owner(actor, role, client):
        if role == 'client' and actor != client:
            raise Rejected('access_denied')

    def create_client(self, actor, key):
        def apply(role):
            now = self._now()
            ident = self.conn.execute("INSERT INTO accounts(role) VALUES('client') RETURNING id").fetchone()[0]
            self._audit(actor, 'create_client', ident, now, {})
            return {'client_id': ident}
        return self._command(actor, 'create_client', key, {}, apply, staff=True)

    def issue_subscription(self, actor, client, quotas, key):
        positive(client)
        quotas = policy.packages(quotas)
        def apply(role):
            row = self.conn.execute('SELECT role,enabled FROM accounts WHERE id=%s FOR SHARE', (client,)).fetchone()
            if not row or row != ('client', True):
                raise Rejected('client_unavailable')
            now = self._now()
            ident = self.conn.execute('INSERT INTO subscriptions(client_id) VALUES(%s) RETURNING id', (client,)).fetchone()[0]
            for category, quota in sorted(quotas.items()):
                self.conn.execute('INSERT INTO allowances VALUES(%s,%s,%s,%s)', (ident, category, quota, quota))
            self._audit(actor, 'issue_subscription', ident, now, {'client_id': client, 'quotas': quotas})
            return {'subscription_id': ident, 'quotas': quotas}
        return self._command(actor, 'issue_subscription', key, {'client': client, 'quotas': quotas}, apply, staff=True)

    def book(self, actor, subscription, category, starts_at, minutes, key):
        positive(subscription)
        start, end = policy.appointment(category, starts_at, minutes)
        def apply(role):
            client = self._subscription(subscription)
            self._owner(actor, role, client)
            now = self._now()
            if now >= start:
                raise Rejected('appointment_started')
            allowance = self.conn.execute('''SELECT remaining FROM allowances
                WHERE subscription_id=%s AND category=%s''', (subscription, category)).fetchone()
            if not allowance or allowance[0] <= 0:
                raise Rejected('allowance_unavailable')
            if self.conn.execute('''SELECT 1 FROM bookings WHERE subscription_id=%s AND state IN ('reserved','consumed')
                AND starts_at<%s AND ends_at>%s''', (subscription, end, start)).fetchone():
                raise Rejected('overlapping_booking')
            # Same time cannot be silently rebooked, even after cancellation; an explicit
            # future rebooking endpoint needs its own audit and policy review.
            if self.conn.execute('SELECT 1 FROM bookings WHERE subscription_id=%s AND starts_at=%s', (subscription, start)).fetchone():
                raise Rejected('booking_time_already_recorded')
            ident = self.conn.execute('''INSERT INTO bookings(subscription_id,category,starts_at,ends_at,state)
                VALUES(%s,%s,%s,%s,'reserved') RETURNING id''', (subscription, category, start, end)).fetchone()[0]
            remaining = allowance[0] - 1
            self.conn.execute('UPDATE allowances SET remaining=%s WHERE subscription_id=%s AND category=%s', (remaining, subscription, category))
            self._audit(actor, 'book', ident, now, {'category': category, 'remaining': remaining})
            return {'booking_id': ident, 'state': 'reserved', 'remaining': remaining}
        return self._command(actor, 'book', key, {'subscription': subscription, 'category': category,
            'starts_at': start.isoformat(), 'minutes': minutes}, apply)

    def issue_qr(self, actor, booking):
        self._idle()
        with self.conn.transaction():
            self.conn.execute("SET LOCAL lock_timeout TO '3s'")
            self.conn.execute("SET LOCAL statement_timeout TO '5s'")
            role = self._actor(actor)
            client, row = self._booking(booking)
            self._owner(actor, role, client)
            now = self._now()
            if row[4] != 'reserved' or not row[2] <= now < row[3]:
                raise Rejected('qr_outside_session')
            token = secrets.token_urlsafe(32)
            expires = min(now + timedelta(minutes=2), row[3])
            self.conn.execute('UPDATE qr_tokens SET revoked=true WHERE booking_id=%s', (booking,))
            self.conn.execute('INSERT INTO qr_tokens(token_hash,booking_id,expires_at) VALUES(%s,%s,%s)', (token_hash(token), booking, expires))
            self._audit(actor, 'issue_qr', booking, now, {'expires_at': expires.isoformat()})
            # Raw opaque token exists only in this response; it contains no child/account data.
            return {'token': token, 'expires_at': expires.isoformat(), 'valid_for_seconds': max(0, int((expires-now).total_seconds()))}

    def redeem(self, actor, booking, token, key):
        return self._redeem_hashed(actor, booking, token_hash(token), key)

    def _redeem_hashed(self, actor, booking, hashed, key):
        # Trusted Telegram adapter retains only the hash while awaiting a staff
        # confirmation. No public endpoint accepts this internal representation.
        positive(booking)
        if not isinstance(hashed, str) or not re.fullmatch('[0-9a-f]{64}', hashed):
            raise Rejected('invalid_qr')
        def apply(role):
            client, row = self._booking(booking)
            now = self._now()
            if row[4] != 'reserved' or not row[2] <= now < row[3]:
                raise Rejected('session_unavailable')
            qr = self.conn.execute('''SELECT booking_id,expires_at,used_at,revoked FROM qr_tokens
                WHERE token_hash=%s FOR UPDATE''', (hashed,)).fetchone()
            if not qr or qr[0] != booking or qr[2] is not None or qr[3] or now >= qr[1]:
                raise Rejected('qr_expired_or_used')
            self.conn.execute('UPDATE qr_tokens SET used_at=%s WHERE token_hash=%s', (now, hashed))
            self.conn.execute("UPDATE bookings SET state='consumed' WHERE id=%s", (booking,))
            self.conn.execute('UPDATE qr_tokens SET revoked=true WHERE booking_id=%s', (booking,))
            remaining = self.conn.execute('SELECT remaining FROM allowances WHERE subscription_id=%s AND category=%s', (row[0], row[1])).fetchone()[0]
            event = self._audit(actor, 'redeem', booking, now, {'client_id': client, 'subscription_id': row[0], 'category': row[1], 'remaining': remaining})
            return {'booking_id': booking, 'state': 'consumed', 'remaining': remaining, 'event_id': event}
        return self._command(actor, 'redeem', key, {'booking': booking, 'token_hash': hashed}, apply, staff=True)

    def cancel_pool(self, actor, booking, key):
        positive(booking)
        def apply(role):
            client, row = self._booking(booking)
            self._owner(actor, role, client)
            now = self._now()
            if row[1] != 'pool':
                raise Rejected('non_pool_cancellation_policy_unapproved')
            if row[4] != 'reserved':
                raise Rejected('session_unavailable')
            refunded = policy.pool_refund(row[2], now)
            state = 'cancelled' if refunded else 'forfeited'
            if refunded:
                self.conn.execute('UPDATE allowances SET remaining=remaining+1 WHERE subscription_id=%s AND category=%s', (row[0], row[1]))
            self.conn.execute('UPDATE bookings SET state=%s WHERE id=%s', (state, booking))
            self.conn.execute('UPDATE qr_tokens SET revoked=true WHERE booking_id=%s', (booking,))
            remaining = self.conn.execute('SELECT remaining FROM allowances WHERE subscription_id=%s AND category=%s', (row[0], row[1])).fetchone()[0]
            self._audit(actor, 'cancel_pool', booking, now, {'state': state, 'remaining': remaining, 'refunded': refunded})
            return {'booking_id': booking, 'state': state, 'remaining': remaining}
        return self._command(actor, 'cancel_pool', key, {'booking': booking}, apply)

    def mark_no_show(self, actor, booking, key):
        positive(booking)
        def apply(role):
            _, row = self._booking(booking)
            now = self._now()
            if row[1] != 'pool':
                raise Rejected('non_pool_no_show_policy_unapproved')
            if row[4] != 'reserved' or now < row[3]:
                raise Rejected('no_show_not_due')
            self.conn.execute("UPDATE bookings SET state='no_show' WHERE id=%s", (booking,))
            self.conn.execute('UPDATE qr_tokens SET revoked=true WHERE booking_id=%s', (booking,))
            self._audit(actor, 'mark_no_show', booking, now, {})
            return {'booking_id': booking, 'state': 'no_show'}
        return self._command(actor, 'mark_no_show', key, {'booking': booking}, apply, staff=True)

    def restore_pool(self, actor, booking, justification, key):
        positive(booking)
        justification = policy.reason(justification)
        def apply(role):
            _, row = self._booking(booking)
            now = self._now()
            if row[1] != 'pool' or row[4] not in ('forfeited', 'no_show'):
                raise Rejected('session_not_restorable')
            self.conn.execute('UPDATE allowances SET remaining=remaining+1 WHERE subscription_id=%s AND category=%s', (row[0], row[1]))
            self.conn.execute("UPDATE bookings SET state='restored' WHERE id=%s", (booking,))
            self.conn.execute('UPDATE qr_tokens SET revoked=true WHERE booking_id=%s', (booking,))
            remaining = self.conn.execute('SELECT remaining FROM allowances WHERE subscription_id=%s AND category=%s', (row[0], row[1])).fetchone()[0]
            event = self._audit(actor, 'restore_pool', booking, now, {'reason': justification, 'remaining': remaining})
            self.conn.execute("INSERT INTO notification_outbox(event_id,recipient_role,kind,created_at) VALUES(%s,'superadmin','session_restored',%s)", (event, now))
            return {'booking_id': booking, 'state': 'restored', 'remaining': remaining, 'event_id': event}
        return self._command(actor, 'restore_pool', key, {'booking': booking, 'reason': justification}, apply, staff=True)
