"""Minimal PostgreSQL wire-protocol client used ONLY by the test-suite.

It mimics the tiny subset of psycopg 3 that kinder.db relies on (dict rows,
%s placeholders, transaction()) so tests can run against a real PostgreSQL
server where psycopg cannot be installed. Trust/cleartext auth only.
Parameters are interpolated as safely quoted literals.
"""
import json
import socket
import struct
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal
from urllib.parse import urlparse, unquote


class PgError(Exception):
    def __init__(self, fields):
        self.sqlstate = fields.get('C')
        super().__init__(f"{fields.get('C')}: {fields.get('M')}")


def quote(v):
    if v is None:
        return 'NULL'
    if isinstance(v, bool):
        return 'true' if v else 'false'
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return repr(v)
    if isinstance(v, Decimal):
        return f"'{v}'::numeric"
    if isinstance(v, datetime):
        return f"'{v.isoformat()}'::timestamptz"
    if isinstance(v, date):
        return f"'{v.isoformat()}'::date"
    if isinstance(v, (bytes, bytearray, memoryview)):
        return f"'\\x{bytes(v).hex()}'::bytea"
    if isinstance(v, (list, tuple)):
        if not v:
            return "'{}'"
        inner = ','.join(quote(i) for i in v)
        return f'ARRAY[{inner}]' + ('::bigint[]' if all(isinstance(i, int) for i in v) else '')
    if isinstance(v, str):
        if '\x00' in v:
            raise PgError({'C': '22021', 'M': 'NUL byte'})
        return "'" + v.replace("'", "''") + "'"
    raise TypeError(type(v))


def interpolate(sql, params):
    if params is None:
        return sql
    out, it, i = [], iter(params), 0
    while i < len(sql):
        ch = sql[i]
        if ch == '%' and i + 1 < len(sql):
            nxt = sql[i + 1]
            if nxt == 's':
                out.append(quote(next(it)))
                i += 2
                continue
            if nxt == '%':
                out.append('%')
                i += 2
                continue
        out.append(ch)
        i += 1
    return ''.join(out)


def parse(oid, raw):
    if raw is None:
        return None
    s = raw.decode('utf-8')
    if oid == 16:
        return s == 't'
    if oid in (20, 21, 23, 26):
        return int(s)
    if oid in (700, 701):
        return float(s)
    if oid == 1700:
        return Decimal(s)
    if oid == 1082:
        return date.fromisoformat(s)
    if oid in (1114, 1184):
        return datetime.fromisoformat(s)
    if oid in (114, 3802):
        return json.loads(s)
    if oid == 17:
        return bytes.fromhex(s[2:])
    if oid in (1016, 1007):
        return [int(p) for p in s.strip('{}').split(',') if p]
    return s


class Cursor:
    def __init__(self, rows):
        self.rows = rows

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return list(self.rows)


class Connection:
    def __init__(self, url):
        u = urlparse(url)
        self.sock = socket.create_connection((u.hostname or '127.0.0.1', u.port or 5432), timeout=30)
        user = unquote(u.username or 'postgres')
        params = {'user': user, 'database': u.path.lstrip('/') or user, 'client_encoding': 'UTF8',
                  'DateStyle': 'ISO', 'TimeZone': 'UTC', 'search_path': 'kinder,public'}
        body = struct.pack('!i', 196608) + b''.join(k.encode() + b'\0' + v.encode() + b'\0' for k, v in params.items()) + b'\0'
        self.sock.sendall(struct.pack('!i', len(body) + 4) + body)
        self.password = unquote(u.password or '')
        self.autocommit = True
        self._wait_ready(auth=True)

    def _recv(self, n):
        buf = b''
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError('server closed connection')
            buf += chunk
        return buf

    def _msg(self):
        kind = self._recv(1)
        length = struct.unpack('!i', self._recv(4))[0]
        return kind, self._recv(length - 4)

    def _wait_ready(self, auth=False):
        rows, desc, error = [], None, None
        while True:
            kind, data = self._msg()
            if kind == b'R':
                code = struct.unpack('!i', data[:4])[0]
                if code == 3:
                    pw = self.password.encode() + b'\0'
                    self.sock.sendall(b'p' + struct.pack('!i', len(pw) + 4) + pw)
                elif code != 0:
                    raise PgError({'C': '28000', 'M': f'unsupported auth {code}'})
            elif kind == b'T':
                n = struct.unpack('!h', data[:2])[0]
                pos, desc = 2, []
                for _ in range(n):
                    end = data.index(b'\0', pos)
                    name = data[pos:end].decode()
                    oid = struct.unpack('!i', data[end + 7:end + 11])[0]
                    desc.append((name, oid))
                    pos = end + 19
            elif kind == b'D':
                n = struct.unpack('!h', data[:2])[0]
                pos, values = 2, []
                for _ in range(n):
                    ln = struct.unpack('!i', data[pos:pos + 4])[0]
                    pos += 4
                    if ln == -1:
                        values.append(None)
                    else:
                        values.append(data[pos:pos + ln])
                        pos += ln
                rows.append({name: parse(oid, v) for (name, oid), v in zip(desc, values)})
            elif kind == b'E':
                fields, pos = {}, 0
                while data[pos:pos + 1] != b'\0':
                    end = data.index(b'\0', pos + 1)
                    fields[chr(data[pos])] = data[pos + 1:end].decode('utf-8', 'replace')
                    pos = end + 1
                error = error or PgError(fields)
            elif kind == b'Z':
                if error:
                    raise error
                return rows
            # ignore S, K, C, N, I and others

    def execute(self, sql, params=None):
        q = interpolate(sql, params).encode('utf-8') + b'\0'
        self.sock.sendall(b'Q' + struct.pack('!i', len(q) + 4) + q)
        return Cursor(self._wait_ready())

    @contextmanager
    def transaction(self):
        self.execute('BEGIN')
        try:
            yield self
        except BaseException:
            self.execute('ROLLBACK')
            raise
        else:
            self.execute('COMMIT')

    def close(self):
        try:
            self.sock.sendall(b'X\0\0\0\4')
        finally:
            self.sock.close()


def connect(url):
    return Connection(url)
