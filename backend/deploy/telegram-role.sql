-- REVIEW ONLY. Never executed in production without separate owner approval.
-- Distinct Kinder Telegram identity, no password or owner DSN in this file.
-- FIRST apply the reviewed base, auth, and Telegram first-install migrations.
-- Any row-lock-only UPDATE(column) grant below MUST be paired with the
-- immutable_identifier() trigger from the base/auth schema.
BEGIN;
CREATE ROLE kinder_telegram_runtime LOGIN NOINHERIT NOSUPERUSER
    NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
GRANT CONNECT ON DATABASE kinder_spa_db TO kinder_telegram_runtime;
GRANT USAGE ON SCHEMA kinder TO kinder_telegram_runtime;

GRANT SELECT ON kinder.accounts,kinder.subscriptions,kinder.credentials,
    kinder.auth_sessions TO kinder_telegram_runtime;
-- PostgreSQL row locks require UPDATE on at least one column. Never allow the
-- worker to update roles, login material, subscription owners, session state.
-- These identifier columns are guarded against ANY UPDATE by migration triggers.
GRANT UPDATE(id) ON kinder.accounts,kinder.subscriptions TO kinder_telegram_runtime;
GRANT UPDATE(account_id) ON kinder.credentials TO kinder_telegram_runtime;
GRANT UPDATE(token_hash) ON kinder.auth_sessions TO kinder_telegram_runtime;

GRANT SELECT ON kinder.allowances,kinder.bookings TO kinder_telegram_runtime;
GRANT UPDATE(remaining) ON kinder.allowances TO kinder_telegram_runtime;
GRANT UPDATE(state) ON kinder.bookings TO kinder_telegram_runtime;

GRANT SELECT,INSERT ON kinder.qr_tokens,kinder.operations TO kinder_telegram_runtime;
GRANT UPDATE(used_at,revoked) ON kinder.qr_tokens TO kinder_telegram_runtime;
GRANT UPDATE(result) ON kinder.operations TO kinder_telegram_runtime;

-- Audit is append-only by trigger, with no UPDATE/DELETE/DDL grants.
GRANT SELECT,INSERT ON kinder.audit_events,kinder.notification_outbox
    TO kinder_telegram_runtime;
-- Required for FOR UPDATE OF notification_outbox. An unconditional
-- append-only trigger rejects attempted updates even when granted this column.
GRANT UPDATE(id) ON kinder.notification_outbox TO kinder_telegram_runtime;

GRANT SELECT,INSERT ON kinder.telegram_link_codes,kinder.telegram_bindings,
    kinder.telegram_actions,kinder.telegram_jobs,kinder.telegram_qr_cleanup
    TO kinder_telegram_runtime;
GRANT UPDATE(revoked,used_peer,used_update) ON kinder.telegram_link_codes
    TO kinder_telegram_runtime;
GRANT UPDATE(active,language) ON kinder.telegram_bindings TO kinder_telegram_runtime;
GRANT UPDATE(state) ON kinder.telegram_actions TO kinder_telegram_runtime;
GRANT UPDATE(state,error_code,attempts,lease_id,lease_until,next_at,message_id)
    ON kinder.telegram_jobs TO kinder_telegram_runtime;
GRANT UPDATE(done,attempts,delete_at) ON kinder.telegram_qr_cleanup
    TO kinder_telegram_runtime;
GRANT SELECT,INSERT ON kinder.telegram_updates,kinder.telegram_notification_batches
    TO kinder_telegram_runtime;
GRANT SELECT ON kinder.telegram_runtime TO kinder_telegram_runtime;
GRANT UPDATE(bot_id,username,next_offset) ON kinder.telegram_runtime
    TO kinder_telegram_runtime;

GRANT USAGE ON SEQUENCE kinder.audit_events_id_seq,
    kinder.notification_outbox_id_seq,kinder.telegram_bindings_id_seq,
    kinder.telegram_jobs_id_seq TO kinder_telegram_runtime;
-- Intentionally no login_buckets access, table-wide UPDATE, DELETE,
-- TRUNCATE, CREATE, DDL, or privileges to change audit_events.
COMMIT;
