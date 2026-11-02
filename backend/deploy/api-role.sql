-- REVIEW-ONLY least-privilege first-install role. NEVER execute automatically.
-- Production grant/change requires exact owner approval and independently verified
-- actual Render backup/recovery. The role must not inherit an owner account.
-- No password or connection secret is embedded in the repository.
BEGIN;
CREATE ROLE kinder_api_runtime LOGIN NOINHERIT NOSUPERUSER NOCREATEDB
    NOCREATEROLE NOREPLICATION NOBYPASSRLS;
GRANT CONNECT ON DATABASE kinder_spa_db TO kinder_api_runtime;
GRANT USAGE ON SCHEMA kinder TO kinder_api_runtime;

GRANT SELECT,INSERT ON kinder.accounts,kinder.subscriptions,kinder.allowances,
    kinder.bookings,kinder.qr_tokens,kinder.operations,kinder.credentials,
    kinder.auth_sessions,kinder.login_buckets,kinder.audit_events,
    kinder.notification_outbox TO kinder_api_runtime;
GRANT DELETE ON kinder.login_buckets TO kinder_api_runtime;

-- SELECT ... FOR SHARE / FOR UPDATE requires a column-scoped UPDATE
-- privilege. GENERATED ALWAYS or guarded identifier columns grant locking,
-- never permission to change the account or subscription identity.
GRANT UPDATE(id) ON kinder.accounts,kinder.subscriptions TO kinder_api_runtime;
GRANT UPDATE(remaining) ON kinder.allowances TO kinder_api_runtime;
GRANT UPDATE(state) ON kinder.bookings TO kinder_api_runtime;
GRANT UPDATE(used_at,revoked) ON kinder.qr_tokens TO kinder_api_runtime;
GRANT UPDATE(result) ON kinder.operations TO kinder_api_runtime;
GRANT UPDATE(account_id,salt,verifier,version) ON kinder.credentials TO kinder_api_runtime;
GRANT UPDATE(token_hash,revoked) ON kinder.auth_sessions TO kinder_api_runtime;
GRANT UPDATE(attempts) ON kinder.login_buckets TO kinder_api_runtime;

-- AUDIT and OUTBOX remain immutable, no UPDATE, DELETE or TRUNCATE privileges.
-- First-install identity sequences, never ALTER SEQUENCE or schema ownership.
GRANT USAGE ON SEQUENCE kinder.accounts_id_seq,kinder.subscriptions_id_seq,
    kinder.bookings_id_seq,kinder.audit_events_id_seq,
    kinder.notification_outbox_id_seq TO kinder_api_runtime;

-- Optional feature: ONLY after Telegram tables and their exact indexes exist,
-- and after review/approval of this separate grant section:
-- GRANT SELECT ON kinder.telegram_link_codes,kinder.telegram_bindings,
--     kinder.telegram_updates,kinder.telegram_runtime,kinder.telegram_actions,
--     kinder.telegram_notification_batches,kinder.telegram_jobs,kinder.telegram_qr_cleanup
--     TO kinder_api_runtime;
-- GRANT INSERT ON kinder.telegram_link_codes TO kinder_api_runtime;
-- GRANT UPDATE(revoked) ON kinder.telegram_link_codes TO kinder_api_runtime;
-- Never grant other Telegram table mutation privileges to the API runtime.
COMMIT;
