"""Validate read-only Kinder catalog preflight on isolated PostgreSQL18.

Never connects to Render or reads actual customer records.
"""
from pathlib import Path

from auth_fixtures import Fixture


PRE_FLIGHT = Path(__file__).parents[1] / "deploy" / "kinder-readonly-preflight.sql"
EXPECTED = set("""accounts subscriptions allowances bookings qr_tokens operations audit_events
notification_outbox credentials auth_sessions login_buckets telegram_link_codes
telegram_bindings telegram_updates telegram_runtime telegram_actions
telegram_notification_batches telegram_jobs telegram_qr_cleanup""".split())


def discovery_sql():
    source = PRE_FLIGHT.read_text(encoding="utf-8")
    section = source.split("-- Relation discovery BEGIN.", 1)[1].split(
        "-- Relation discovery END.", 1)[0]
    query = section[section.index("WITH expected(name)"):section.index("ORDER BY 1,2;") + len("ORDER BY 1,2;")]
    return query


class ReadonlyPreflightTests(Fixture):
    def discovery(self):
        with self.factory() as conn:
            with conn.transaction():
                conn.execute("SET TRANSACTION READ ONLY")
                return conn.execute(discovery_sql()).fetchall()

    def test_absent_telegram_tables_are_explicitly_reported(self):
        results = self.discovery()
        observed_names = {name for name, _, _ in results}
        self.assertEqual(observed_names, EXPECTED)
        current = {(name, kind) for name, schema, kind in results if schema == self.schema}
        self.assertIn(("accounts", "r"), current)
        self.assertIn(("credentials", "r"), current)
        absent = {name for name, schema, kind in results if schema == "<not present>"}
        self.assertEqual(absent, EXPECTED - {name for name, _ in current})
        self.assertEqual(len(absent), 8)

    def test_conflicting_view_is_reported_not_mistaken_for_table(self):
        self.conn.execute("""CREATE VIEW telegram_runtime AS
            SELECT id AS singleton FROM accounts WHERE FALSE""")
        results = self.discovery()
        matching = [(schema, kind) for name, schema, kind in results
                    if name == "telegram_runtime" and schema == self.schema]
        self.assertEqual(matching, [(self.schema, "v")])
        self.assertNotIn("telegram_runtime",
                         {name for name, schema, kind in results
                          if schema == "<not present>"})
