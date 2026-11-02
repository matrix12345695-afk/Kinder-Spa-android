"""Thin PostgreSQL access layer.

Production uses psycopg 3. Tests may inject another `connect` callable that
returns an object with the same small surface: execute(sql, params) -> cursor
with fetchone()/fetchall() returning dict rows, transaction() context manager
and close(). Only positional %s placeholders are used in this codebase.
"""
from contextlib import contextmanager
from pathlib import Path

HERE = Path(__file__).parent
MIGRATIONS = [HERE / 'schema.sql', HERE / 'schema_002_telegram.sql', HERE / 'schema_003_payments.sql',
              HERE / 'schema_004_schedule.sql', HERE / 'schema_005_lang.sql',
              HERE / 'schema_006_settings.sql']  # append new files, never edit applied ones


def psycopg_connect(url):
    import psycopg
    from psycopg.rows import dict_row
    conn = psycopg.connect(url, autocommit=True, row_factory=dict_row,
                           connect_timeout=10, options='-c search_path=kinder,public -c TimeZone=UTC')
    return conn


class Database:
    def __init__(self, url, connect=None):
        self.url = url
        self._connect = connect or psycopg_connect

    @contextmanager
    def conn(self):
        c = self._connect(self.url)
        try:
            yield c
        finally:
            c.close()

    def migrate(self):
        with self.conn() as c, c.transaction():
            c.execute('SELECT pg_advisory_xact_lock(724001)')
            c.execute('CREATE SCHEMA IF NOT EXISTS kinder')
            c.execute('CREATE TABLE IF NOT EXISTS kinder.schema_version (version integer PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())')
            row = c.execute('SELECT coalesce(max(version), 0) AS v FROM kinder.schema_version').fetchone()
            current = row['v']
            for number, path in enumerate(MIGRATIONS, start=1):
                if number <= current:
                    continue
                c.execute(path.read_text(encoding='utf-8'))
                c.execute('INSERT INTO kinder.schema_version(version) VALUES (%s)', (number,))
            return len(MIGRATIONS)


def sqlstate(exc):
    return getattr(exc, 'sqlstate', None) or getattr(getattr(exc, 'diag', None), 'sqlstate', None)
