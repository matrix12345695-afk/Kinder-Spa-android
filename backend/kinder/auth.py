"""Admin-issued passwords and opaque PostgreSQL-backed sessions, no self-signup.

All secrets stay out of audit/idempotency records. Account/session locks fence the
same transaction as each accounting mutation, not just an earlier HTTP check.
"""
from datetime import timedelta
import hashlib
import hmac
import ipaddress
import re
import secrets

import psycopg
from psycopg import pq
from .store import Store, Rejected, token_hash

PASSWORD_N = 32768
SESSION_HOURS = 8
WINDOW_SECONDS = 600


class Denied(Exception):
    pass


class Limited(Exception):
    pass


def username(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{2,63}', value):
        raise Rejected('invalid_login')
    return value.lower()


def password_bytes(value):
    if not isinstance(value, str) or not 12 <= len(value) <= 128 or '\x00' in value:
        raise Rejected('invalid_password')
    raw = value.encode('utf-8')
    if len(raw) > 512:
        raise Rejected('invalid_password')
    return raw


def derive(raw, salt):
    return hashlib.scrypt(raw, salt=salt, n=PASSWORD_N, r=8, p=1, dklen=32, maxmem=64*1024*1024)


def make_password(value):
    raw = password_bytes(value)
    salt = secrets.token_bytes(16)
    return salt, derive(raw, salt)


class Auth:
    def __init__(self, connection, *, clock=None):
        self.conn = connection
        self.core = Store(connection, clock=clock)

    def _limits(self):
        self.conn.execute("SET LOCAL lock_timeout TO '3s'")
        self.conn.execute("SET LOCAL statement_timeout TO '5s'")

    def _throttle(self, login, remote):
        try:
            address = str(ipaddress.ip_address(remote))
        except ValueError:
            raise Denied() from None
        self.core._idle()
        with self.conn.transaction():
            self._limits()
            now = self.core._now()
            window = int(now.timestamp())//WINDOW_SECONDS*WINDOW_SECONDS
            # Global comes first for every request: bounds distinct-key growth and
            # scrypt work even when guesses spread across many logins/IPs.
            for scope, maximum in (('global', 120), ('ip:'+address, 30), ('login:'+login, 5)):
                hashed = hashlib.sha256(scope.encode()).hexdigest()
                self.conn.execute('INSERT INTO login_buckets VALUES(%s,%s,0) ON CONFLICT DO NOTHING', (hashed, window))
                count = self.conn.execute('SELECT attempts FROM login_buckets WHERE scope_hash=%s AND window_start=%s FOR UPDATE', (hashed, window)).fetchone()[0]
                if count >= maximum:
                    return False  # Prior increments COMMIT, even for a rejected request.
                self.conn.execute('UPDATE login_buckets SET attempts=attempts+1 WHERE scope_hash=%s AND window_start=%s', (hashed, window))
            # Bounded cleanup; no IP/login plaintext is stored in this table.
            self.conn.execute('''DELETE FROM login_buckets WHERE ctid IN
                (SELECT ctid FROM login_buckets WHERE window_start<%s LIMIT 500)''', (window-2*WINDOW_SECONDS,))
        return True

    def login(self, login, password, remote):
        self.core._idle()
        # Malformed names/passwords share the same public authentication failure.
        try:
            name = username(login)
        except Rejected:
            name = '!invalid'
        if not self._throttle(name, remote):
            raise Limited()
        try:
            raw = password_bytes(password)
            password_valid = True
        except (Rejected, UnicodeError):
            raw = b'!invalid-password'
            password_valid = False
        row = self.conn.execute('SELECT account_id,salt,verifier,version FROM credentials WHERE login=%s', (name,)).fetchone()
        salt = bytes(row[1]) if row else b'kinder-dummy-salt'
        expected = bytes(row[2]) if row else b'\0'*32
        valid = hmac.compare_digest(derive(raw, salt), expected)
        if not row or not valid or not password_valid:
            raise Denied()
        with self.conn.transaction():
            self._limits()
            # Serialize session creation/reset on this account; the password that
            # was checked must still be exactly the current credential version.
            account = self.conn.execute('SELECT role,enabled FROM accounts WHERE id=%s FOR UPDATE', (row[0],)).fetchone()
            current = self.conn.execute('SELECT salt,verifier,version FROM credentials WHERE account_id=%s FOR SHARE', (row[0],)).fetchone()
            if not account or not account[1] or not current or (bytes(current[0]), bytes(current[1]), current[2]) != (bytes(row[1]), bytes(row[2]), row[3]):
                raise Denied()
            now = self.core._now()
            # Limit active sessions; old/expired rows are retained as history.
            active = self.conn.execute('''SELECT token_hash FROM auth_sessions WHERE account_id=%s
                AND revoked=false AND expires_at>%s ORDER BY created_at,token_hash''', (row[0], now)).fetchall()
            for old, in active[:-4]:
                self.conn.execute('UPDATE auth_sessions SET revoked=true WHERE token_hash=%s', (old,))
            token = secrets.token_urlsafe(32)
            expires = now+timedelta(hours=SESSION_HOURS)
            self.conn.execute('INSERT INTO auth_sessions VALUES(%s,%s,%s,%s,%s,false)', (token_hash(token), row[0], row[3], now, expires))
            self.core._audit(row[0], 'login', row[0], now, {})
            return {'access_token': token, 'token_type': 'Bearer', 'expires_at': expires.isoformat(), 'expires_in_seconds': SESSION_HOURS*3600}

    def locked(self, token, *, actor=None, update=False):
        if self.conn.info.transaction_status != pq.TransactionStatus.INTRANS:
            raise Denied()
        try:
            hashed = token_hash(token)
        except Rejected:
            raise Denied() from None
        pointer = self.conn.execute('SELECT account_id FROM auth_sessions WHERE token_hash=%s', (hashed,)).fetchone()
        if not pointer or (actor is not None and actor != pointer[0]):
            raise Denied()
        ident = pointer[0]
        account = self.conn.execute('SELECT role,enabled FROM accounts WHERE id=%s FOR SHARE', (ident,)).fetchone()
        credential = self.conn.execute('SELECT version FROM credentials WHERE account_id=%s FOR SHARE', (ident,)).fetchone()
        query = 'SELECT credential_version,created_at,expires_at,revoked FROM auth_sessions WHERE token_hash=%s FOR '+('UPDATE' if update else 'SHARE')
        session = self.conn.execute(query, (hashed,)).fetchone()
        now = self.core._now()
        if (not account or not account[1] or not credential or not session or session[3]
                or session[0] != credential[0] or not session[1] <= now < session[2]):
            raise Denied()
        return ident, account[0]

    def identify(self, token):
        self.core._idle()
        with self.conn.transaction():
            self._limits()
            return self.locked(token)

    def guard(self, token):
        def authorize(conn, actor):
            if conn is not self.conn:
                raise Denied()
            self.locked(token, actor=actor)
        return authorize

    def logout(self, token):
        self.core._idle()
        with self.conn.transaction():
            self._limits()
            actor, _ = self.locked(token, update=True)
            self.conn.execute('UPDATE auth_sessions SET revoked=true WHERE token_hash=%s', (token_hash(token),))
            self.core._audit(actor, 'logout', actor, self.core._now(), {})

    def create_client(self, token, login, password):
        name = username(login)
        salt, verifier = make_password(password)
        self.core._idle()
        try:
            with self.conn.transaction():
                self._limits()
                actor, role = self.locked(token)
                if role not in ('admin', 'superadmin'):
                    raise Denied()
                ident = self.conn.execute("INSERT INTO accounts(role) VALUES('client') RETURNING id").fetchone()[0]
                self.conn.execute('INSERT INTO credentials(account_id,login,salt,verifier) VALUES(%s,%s,%s,%s)', (ident, name, salt, verifier))
                self.core._audit(actor, 'create_client_login', ident, self.core._now(), {})
                return {'client_id': ident, 'login': name}
        except psycopg.errors.UniqueViolation:
            raise Rejected('login_unavailable') from None

    def reset_client_password(self, token, client, password):
        salt, verifier = make_password(password)
        self.core._idle()
        with self.conn.transaction():
            self._limits()
            actor, role = self.locked(token)
            if role not in ('admin', 'superadmin'):
                raise Denied()
            row = self.conn.execute('SELECT role FROM accounts WHERE id=%s FOR UPDATE', (client,)).fetchone()
            if row != ('client',):
                raise Denied()
            changed = self.conn.execute('''UPDATE credentials SET salt=%s,verifier=%s,version=version+1
                WHERE account_id=%s RETURNING version''', (salt, verifier, client)).fetchone()
            if not changed:
                raise Denied()
            self.conn.execute('UPDATE auth_sessions SET revoked=true WHERE account_id=%s', (client,))
            self.core._audit(actor, 'reset_client_password', client, self.core._now(), {})


def bootstrap_empty_database(conn, login, password):
    """Explicit operator call only; no HTTP route or automatic startup invocation.

    Only an empty dedicated DB is accepted. Existing installations need a separate
    reviewed migration/bootstrap. Never pass a password as a shell argument.
    """
    core = Store(conn)
    core._idle()
    name = username(login)
    salt, verifier = make_password(password)
    with conn.transaction():
        conn.execute("SET LOCAL lock_timeout TO '3s'")
        conn.execute("SET LOCAL statement_timeout TO '5s'")
        conn.execute('SELECT pg_advisory_xact_lock(74192368)')
        if conn.execute('SELECT EXISTS(SELECT 1 FROM accounts)').fetchone()[0]:
            raise Denied()
        ident = conn.execute("INSERT INTO accounts(role) VALUES('superadmin') RETURNING id").fetchone()[0]
        conn.execute('INSERT INTO credentials(account_id,login,salt,verifier) VALUES(%s,%s,%s,%s)', (ident, name, salt, verifier))
        core._audit(ident, 'operator_bootstrap', ident, core._now(), {})
        return ident
