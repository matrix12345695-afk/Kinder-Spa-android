-- KINDER SPA ONLY: READ-ONLY PostgreSQL 18 catalog preflight.
-- Run manually using a protected, authorized Render PostgreSQL connection.
-- Does not create/alter/drop anything. No customer rows or secrets are queried.
BEGIN TRANSACTION READ ONLY;
SET LOCAL statement_timeout = '5s';
SET LOCAL lock_timeout = '1s';
SELECT current_database() AS database_name,
       current_setting('server_version_num')::integer / 10000 AS pg_major,
       current_user AS inspected_role,
       EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'kinder') AS kinder_schema_exists;
-- Confirm no conflicting named tables in any non-system schema BEFORE schema creation.
WITH expected(name) AS (
 VALUES ('accounts'),('subscriptions'),('allowances'),('bookings'),
 ('qr_tokens'),('operations'),('audit_events'),('notification_outbox'),
 ('credentials'),('auth_sessions'),('login_buckets'),
 ('telegram_link_codes'),('telegram_bindings'),('telegram_updates'),
 ('telegram_runtime'),('telegram_actions'),
 ('telegram_notification_batches'),('telegram_jobs'),('telegram_qr_cleanup')
)
SELECT e.name AS expected_relation,
       coalesce(n.nspname, '<not present>') AS existing_schema,
       coalesce(c.relkind::text, '') AS relation_type
FROM expected e LEFT JOIN pg_class c ON c.relname=e.name
  LEFT JOIN pg_namespace n ON n.oid=c.relnamespace
   AND n.nspname NOT IN ('pg_catalog','information_schema')
WHERE c.oid IS NULL OR n.oid IS NOT NULL
ORDER BY 1,2;
-- Snapshot schema-owned objects, without inspecting customer data.
SELECT n.nspname AS schema_name, c.relname AS object_name, c.relkind
FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
WHERE n.nspname='kinder'
ORDER BY 1,2;
COMMIT;
