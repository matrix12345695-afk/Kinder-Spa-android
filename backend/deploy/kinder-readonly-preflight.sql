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
-- Relation discovery BEGIN. Read-only. Every expected name must appear,
-- including missing names when pg_catalog contains a same-named system object.
-- Build the filtered relation set BEFORE the outer join; filtering only the
-- namespace join can otherwise drop the expected "not present" row.
WITH expected(name) AS (
 VALUES ('accounts'),('subscriptions'),('allowances'),('bookings'),
 ('qr_tokens'),('operations'),('audit_events'),('notification_outbox'),
 ('credentials'),('auth_sessions'),('login_buckets'),
 ('telegram_link_codes'),('telegram_bindings'),('telegram_updates'),
 ('telegram_runtime'),('telegram_actions'),
 ('telegram_notification_batches'),('telegram_jobs'),('telegram_qr_cleanup')
), existing AS (
 SELECT c.relname, c.relkind, n.nspname
 FROM pg_class c
 JOIN pg_namespace n ON n.oid=c.relnamespace
 WHERE n.nspname NOT IN ('pg_catalog','information_schema','pg_toast')
   AND n.nspname NOT LIKE 'pg_temp_%'
   AND n.nspname NOT LIKE 'pg_toast_temp_%'
)
SELECT e.name AS expected_relation,
       coalesce(x.nspname, '<not present>') AS existing_schema,
       coalesce(x.relkind::text, '') AS relation_type
FROM expected e
LEFT JOIN existing x ON x.relname=e.name
ORDER BY 1,2;
-- Relation discovery END.
-- Snapshot schema-owned objects, without inspecting customer data.
SELECT n.nspname AS schema_name, c.relname AS object_name, c.relkind
FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
WHERE n.nspname='kinder'
ORDER BY 1,2;
COMMIT;
