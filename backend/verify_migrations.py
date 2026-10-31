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
    if (p.get("dbname") != "kinder_test"
            or p.get("host") not in ("127.0.0.1", "localhost")
            or p.get("port") != "15439"
            or any(k in p for k in ("hostaddr", "service", "options", "passfile"))):

        raise RuntimeError("refusing non-disposable or remote database")
    schema = "kinder_migrate_" + uuid4().hex[:12]
    with psycopg.connect(dsn, autocommit=True, connect_timeout=3) as conn:
        created = False
        try:
            conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
            created = True
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
            triggers = conn.execute("""SELECT tgname FROM pg_trigger t
                JOIN pg_class c ON c.oid=t.tgrelid
                JOIN pg_namespace n ON n.oid=c.relnamespace
                WHERE n.nspname=%s AND c.relname='audit_events' AND NOT t.tgisinternal""", (schema,)).fetchall()
            assert [t[0] for t in triggers] == ['audit_no_update'], triggers
            outbox_triggers = conn.execute("""SELECT tgname FROM pg_trigger t
                JOIN pg_class c ON c.oid=t.tgrelid
                JOIN pg_namespace n ON n.oid=c.relnamespace
                WHERE n.nspname=%s AND c.relname='notification_outbox'
                    AND NOT t.tgisinternal""", (schema,)).fetchall()
            assert [t[0] for t in outbox_triggers] == ['notification_outbox_no_update'], outbox_triggers
            guards = dict(conn.execute("""SELECT c.relname, t.tgname FROM pg_trigger t
                JOIN pg_class c ON c.oid=t.tgrelid
                JOIN pg_namespace n ON n.oid=c.relnamespace
                WHERE n.nspname=%s AND NOT t.tgisinternal AND
                c.relname IN ('accounts','subscriptions','credentials','auth_sessions')""",
                (schema,)).fetchall())
            assert guards == {'accounts':'accounts_id_immutable',
                              'subscriptions':'subscriptions_id_immutable',
                              'credentials':'credentials_account_immutable',
                              'auth_sessions':'sessions_token_immutable'}, guards
            indexes = {r[0] for r in conn.execute("""SELECT indexname FROM pg_indexes
                WHERE schemaname=%s""", (schema,))}
            assert {'qr_booking', 'sessions_by_account', 'telegram_one_account',
                    'telegram_one_peer', 'telegram_ready'} <= indexes, indexes
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
            print("PASS: 19 tables, append-only triggers, indexes, singleton, quota checks, repeated-install rejection")
        finally:
            # Never delete a schema if CREATE SCHEMA itself failed, even on a UUID collision.
            if created:
                conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))

if __name__ == "__main__":
    main()
