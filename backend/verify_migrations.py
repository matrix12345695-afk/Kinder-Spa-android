"""Run first-install migrations only in isolated local PostgreSQL18 kinder_test."""
import os
from pathlib import Path
from uuid import uuid4
import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict
from psycopg.errors import CheckViolation, DuplicateTable

ROOT = Path(__file__).resolve().parent
EXPECTED = set("""accounts subscriptions allowances bookings qr_tokens operations audit_events
notification_outbox credentials auth_sessions login_buckets telegram_link_codes
telegram_bindings telegram_updates telegram_runtime telegram_actions
telegram_notification_batches telegram_jobs telegram_qr_cleanup""".split())

def main():
    dsn = os.environ["KINDER_TEST_DATABASE_URL"]
    p = conninfo_to_dict(dsn)
    if p.get("dbname") != "kinder_test" or p.get("host") not in ("127.0.0.1", "localhost") or p.get("port") != "15439":
        raise RuntimeError("refusing non-disposable or remote database")
    schema = "kinder_migrate_" + uuid4().hex[:12]
    with psycopg.connect(dsn, autocommit=True) as conn:
        try:
            conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
            with conn.transaction():
                conn.execute(sql.SQL("SET LOCAL search_path TO {}").format(sql.Identifier(schema)))
                for name in ("schema.sql", "auth_schema.sql", "telegram_schema.sql"):
                    conn.execute((ROOT/name).read_text(encoding="utf-8"))
            names = {r[0] for r in conn.execute("""SELECT c.relname FROM pg_class c
                JOIN pg_namespace n ON n.oid=c.relnamespace
                WHERE n.nspname=%s AND c.relkind='r'""", (schema,))}
            assert names == EXPECTED, (names - EXPECTED, EXPECTED - names)
            runtime = conn.execute(sql.SQL("SELECT singleton,next_offset FROM {}.telegram_runtime").format(sql.Identifier(schema))).fetchone()
            assert runtime == (1, 0), runtime
            with conn.transaction():
                conn.execute(sql.SQL("SET LOCAL search_path TO {}").format(sql.Identifier(schema)))
                account = conn.execute("INSERT INTO accounts(role) VALUES('client') RETURNING id").fetchone()[0]
                subscription = conn.execute("INSERT INTO subscriptions(client_id) VALUES(%s) RETURNING id", (account,)).fetchone()[0]
                conn.execute("INSERT INTO allowances VALUES(%s,'pool',8,8)", (subscription,))
                for category, quota, remaining in (("massage",7,7),("hydromassage",10,11)):
                    try:
                        with conn.transaction():
                            conn.execute("INSERT INTO allowances VALUES(%s,%s,%s,%s)", (subscription,category,quota,remaining))
                    except CheckViolation:
                        pass
                    else:
                        raise AssertionError("invalid package accepted")
            try:
                with conn.transaction():
                    conn.execute(sql.SQL("SET LOCAL search_path TO {}").format(sql.Identifier(schema)))
                    conn.execute((ROOT/"schema.sql").read_text(encoding="utf-8"))
            except (DuplicateTable, psycopg.errors.DuplicateObject):
                pass
            else:
                raise AssertionError("duplicate first-install unexpectedly accepted")
            print("PASS: 19 tables, singleton, package checks and repeated-install rejection")
        finally:
            conn.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema)))

if __name__ == "__main__":
    main()
