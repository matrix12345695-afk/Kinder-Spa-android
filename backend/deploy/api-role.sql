-- REVIEW EXAMPLE ONLY. Never called by the API, worker, CI or Blueprint.
-- First inspect the dedicated kinder_spa_db and its actual schema/migrations.
-- Creating a role/access grants requires the owner's explicit operator approval.
-- This fails on an existing role instead of changing its password/authority.
-- No password is stored here. Provision one through an authorized private flow.
BEGIN;
CREATE ROLE kinder_api_runtime LOGIN NOINHERIT NOSUPERUSER NOCREATEDB
    NOCREATEROLE NOREPLICATION NOBYPASSRLS;
GRANT CONNECT ON DATABASE kinder_spa_db TO kinder_api_runtime;
GRANT USAGE ON SCHEMA kinder TO kinder_api_runtime;
GRANT SELECT,INSERT,UPDATE ON kinder.accounts,kinder.allowances,kinder.bookings,
    kinder.qr_tokens,kinder.operations,kinder.credentials,kinder.auth_sessions
    TO kinder_api_runtime;
GRANT SELECT,INSERT,UPDATE ON kinder.subscriptions TO kinder_api_runtime;
GRANT SELECT,INSERT ON kinder.audit_events,kinder.notification_outbox
    TO kinder_api_runtime;
GRANT SELECT,INSERT,UPDATE,DELETE ON kinder.login_buckets TO kinder_api_runtime;
GRANT USAGE ON SEQUENCE kinder.accounts_id_seq,kinder.subscriptions_id_seq,
    kinder.bookings_id_seq,kinder.audit_events_id_seq,kinder.notification_outbox_id_seq
    TO kinder_api_runtime;
-- Only after the separately reviewed Telegram migration, when links are enabled:
-- GRANT SELECT ON kinder.telegram_link_codes,kinder.telegram_bindings,
--     kinder.telegram_updates,kinder.telegram_runtime,kinder.telegram_actions,
--     kinder.telegram_notification_batches,kinder.telegram_jobs,kinder.telegram_qr_cleanup
--     TO kinder_api_runtime;
-- GRANT INSERT,UPDATE ON kinder.telegram_link_codes TO kinder_api_runtime;
-- No CREATE/ownership/memberships or audit UPDATE/DELETE/TRUNCATE are granted.
COMMIT;
