"""Disposable PostgreSQL 18 pg_dump/pg_restore recovery rehearsal. NEVER production.

Uses only the synthetic GitHub Actions kinder_test on 127.0.0.1:15439, an
ephemeral restore database and the same pinned PostgreSQL18 container image.
No backup archive is uploaded as a CI artifact.
"""
import os
from pathlib import Path
import subprocess
import tempfile

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.errors import RaiseException

ROOT = Path(__file__).resolve().parent
IMAGE = "postgres@sha256:9770878138a2e83abcb10856d30cc3f24dae0d317bb956db6ab9159de6c3c80d"
SCHEMA = "kinder_backup_fixture"
RESTORED = "kinder_restore_test"
TABLES = set("""accounts subscriptions allowances bookings qr_tokens operations audit_events
notification_outbox credentials auth_sessions login_buckets telegram_link_codes
telegram_bindings telegram_updates telegram_runtime telegram_actions
telegram_notification_batches telegram_jobs telegram_qr_cleanup""".split())


def permitted_database():
    dsn = os.environ["KINDER_TEST_DATABASE_URL"]
    info = conninfo_to_dict(dsn)
    if info != {"user": "postgres", "password": "fixture-only",
                "host": "127.0.0.1", "port": "15439", "dbname": "kinder_test"}:
        raise RuntimeError("refusing non-local, non-fixture PostgreSQL connection")
    with psycopg.connect(dsn, connect_timeout=3) as conn:
        if conn.info.server_version // 10000 != 18:
            raise RuntimeError("PostgreSQL 18 is required")
        if conn.execute("SELECT current_database()").fetchone()[0] != "kinder_test":
            raise RuntimeError("wrong disposable database")
    return dsn, info


def archive_command(directory, entrypoint, args):
    command = ["docker", "run", "--rm", "--pull=never", "--network=host",
               "--user", f"{os.getuid()}:{os.getgid()}",
               "--mount", f"type=bind,src={directory},dst=/fixture",
               "--env", "PGPASSWORD=fixture-only",
               "--entrypoint", entrypoint, IMAGE, *args]
    subprocess.run(command, check=True, timeout=90, capture_output=True, text=True)


def prepare(conn):
    if conn.execute("SELECT 1 FROM pg_namespace WHERE nspname=%s", (SCHEMA,)).fetchone():
        raise RuntimeError("unexpected existing fixture schema")
    if conn.execute("SELECT 1 FROM pg_database WHERE datname=%s", (RESTORED,)).fetchone():
        raise RuntimeError("unexpected existing restore database")
    conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(SCHEMA)))
    with conn.transaction():
        conn.execute(sql.SQL("SET LOCAL search_path TO {}").format(sql.Identifier(SCHEMA)))
        for name in ("schema.sql", "auth_schema.sql", "telegram_schema.sql"):
            conn.execute((ROOT / name).read_text(encoding="utf-8"))
        superadmin = conn.execute(
            "INSERT INTO accounts(role) VALUES('superadmin') RETURNING id").fetchone()[0]
        client = conn.execute(
            "INSERT INTO accounts(role) VALUES('client') RETURNING id").fetchone()[0]
        subscription = conn.execute(
            "INSERT INTO subscriptions(client_id) VALUES(%s) RETURNING id",
            (client,)).fetchone()[0]
        conn.execute("INSERT INTO allowances VALUES(%s,'pool',8,7)", (subscription,))
        booking = conn.execute("""INSERT INTO bookings
            (subscription_id,category,starts_at,ends_at,state)
            VALUES(%s,'pool','2026-11-02 09:00+05','2026-11-02 09:45+05','forfeited')
            RETURNING id""", (subscription,)).fetchone()[0]
        event = conn.execute("""INSERT INTO audit_events
            (actor_id,operation,entity_id,at,details)
            VALUES(%s,'pool_forfeited',%s,'2026-11-01 12:00+05',
                '{"fixture":true}'::jsonb) RETURNING id""",
            (superadmin, booking)).fetchone()[0]
        conn.execute("""INSERT INTO notification_outbox
            (event_id,recipient_role,kind,created_at)
            VALUES(%s,'superadmin','session_restored','2026-11-01 12:00+05')""",
            (event,))


def check_restored(dsn):
    restored_dsn = make_conninfo(dsn, dbname=RESTORED)
    with psycopg.connect(restored_dsn, connect_timeout=3, autocommit=True) as conn:
        existing = {r[0] for r in conn.execute("""SELECT c.relname FROM pg_class c
            JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname=%s AND c.relkind='r'""", (SCHEMA,))}
        assert existing == TABLES, (TABLES - existing, existing - TABLES)
        with conn.transaction():
            conn.execute(sql.SQL("SET LOCAL search_path TO {}").format(sql.Identifier(SCHEMA)))
            assert conn.execute("SELECT role FROM accounts ORDER BY id").fetchall() == [
                ('superadmin',), ('client',)]
            assert conn.execute("SELECT category,quota,remaining FROM allowances").fetchall() == [
                ('pool', 8, 7)]
            assert conn.execute("SELECT state FROM bookings").fetchone()[0] == "forfeited"
            assert conn.execute("SELECT count(*) FROM audit_events").fetchone()[0] == 1
            assert conn.execute("SELECT count(*) FROM notification_outbox").fetchone()[0] == 1
            assert conn.execute("SELECT singleton,next_offset FROM telegram_runtime").fetchone() == (1, 0)
        with conn.transaction():
            conn.execute(sql.SQL("SET LOCAL search_path TO {}").format(sql.Identifier(SCHEMA)))
            try:
                with conn.transaction():
                    conn.execute("UPDATE audit_events SET operation='tampered'")
            except RaiseException:
                pass
            else:
                raise AssertionError("restored audit trigger did not reject mutation")
            try:
                with conn.transaction():
                    conn.execute("UPDATE notification_outbox SET kind='session_restored'")
            except RaiseException:
                pass
            else:
                raise AssertionError("restored notification outbox trigger did not reject mutation")
        with conn.transaction():
            conn.execute(sql.SQL("SET LOCAL search_path TO {}").format(sql.Identifier(SCHEMA)))
            result = conn.execute(
                "INSERT INTO accounts(role) VALUES('client') RETURNING id").fetchone()[0]
            assert result == 3, result


def main():
    dsn, _ = permitted_database()
    with psycopg.connect(dsn, autocommit=True, connect_timeout=3) as conn:
        schema_created = False
        restored_created = False
        try:
            prepare(conn)
            schema_created = True
            with tempfile.TemporaryDirectory(prefix="kinder-synthetic-recovery-") as folder:
                archive_command(folder, "pg_dump", [
                    "-h", "127.0.0.1", "-p", "15439", "-U", "postgres",
                    "-d", "kinder_test", "--schema", SCHEMA,
                    "--format=custom", "--file=/fixture/synthetic.dump"])
                if Path(folder, "synthetic.dump").stat().st_size < 1000:
                    raise AssertionError("empty synthetic backup archive")
                conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(RESTORED)))
                restored_created = True
                archive_command(folder, "pg_restore", [
                    "-h", "127.0.0.1", "-p", "15439", "-U", "postgres",
                    "-d", RESTORED, "--no-owner", "--no-privileges",
                    "--exit-on-error", "/fixture/synthetic.dump"])
                check_restored(dsn)
            print("PASS: PostgreSQL18 disposable pg_dump + pg_restore, synthetic rows,")
            print("      audit/outbox triggers, identity sequences; no backup artifact retained")
        finally:
            if restored_created:
                conn.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(
                    sql.Identifier(RESTORED)))
            if schema_created:
                conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(SCHEMA)))


if __name__ == "__main__":
    main()
