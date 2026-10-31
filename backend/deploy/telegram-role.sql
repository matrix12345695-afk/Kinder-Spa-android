-- REVIEW ONLY. Execute solely after separate owner approval and verified recovery.
-- Separate Kinder Telegram worker identity, no default password or owner login.
-- The role must be provisioned via an authorized private Render workflow.
-- This SQL is not invoked on startup, by CI against production, or by Blueprint.
-- FIRST apply reviewed Kinder base/auth/Telegram migrations and audit triggers.
BEGIN;
CREATE ROLE kinder_telegram_runtime LOGIN NOINHERIT NOSUPERUSER
    NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
GRANT CONNECT ON DATABASE kinder_spa_db TO kinder_telegram_runtime;
GRANT USAGE ON SCHEMA kinder TO kinder_telegram_runtime;

-- SELECT ... FOR SHARE / FOR UPDATE requires UPDATE privilege under PostgreSQL.
-- The bot does not issue new subscriptions, bookings or user accounts.
GRANT SELECT,UPDATE ON kinder.accounts,kinder.subscriptions,
    kinder.allowances,kinder.bookings,kinder.credentials,kinder.auth_sessions
    TO kinder_telegram_runtime;
GRANT SELECT,INSERT,UPDATE ON kinder.qr_tokens,kinder.operations
    TO kinder_telegram_runtime;

-- Never grant audit-event mutation. The outbox must have the append-only
-- trigger from the reviewed schema so its UPDATE grant allows locks only.
GRANT SELECT,INSERT ON kinder.audit_events TO kinder_telegram_runtime;
GRANT SELECT,INSERT,UPDATE ON kinder.notification_outbox TO kinder_telegram_runtime;

GRANT SELECT,INSERT,UPDATE ON kinder.telegram_link_codes,kinder.telegram_bindings,
    kinder.telegram_actions,kinder.telegram_jobs,kinder.telegram_qr_cleanup
    TO kinder_telegram_runtime;
GRANT SELECT,INSERT ON kinder.telegram_updates,kinder.telegram_notification_batches
    TO kinder_telegram_runtime;
GRANT SELECT,UPDATE ON kinder.telegram_runtime TO kinder_telegram_runtime;

GRANT USAGE ON SEQUENCE kinder.audit_events_id_seq,
    kinder.notification_outbox_id_seq,kinder.telegram_bindings_id_seq,
    kinder.telegram_jobs_id_seq TO kinder_telegram_runtime;

-- Intentionally no login_buckets access, DELETE/TRUNCATE on any relation,
-- schema CREATE, runtime DDL or privilege to modify audit_events.
COMMIT;
