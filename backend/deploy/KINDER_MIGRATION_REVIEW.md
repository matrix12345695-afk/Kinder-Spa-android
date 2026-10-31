# Kinder Spa database migration review packet

**Status: READY FOR REVIEW ONLY. NOT APPROVED FOR PRODUCTION EXECUTION.**

## Evidence from actual Render read-only inspection (31 October 2026)
Worker `srv-dbisj4e7bikc73doom5g`, deploy `dep-dbisj4u7bikc73doon20` LIVE in inspection mode; PostgreSQL 18 private connection negotiated TLS. `kinder` schema absent, all 11 base/auth tables absent. Telegram polling remains disabled; no migrations or grants have run. A schema absence result is not proof the database contains no data in other schemas.

## Existing source migrations reviewed
1. `backend/schema.sql`: eight base tables (`accounts`, `subscriptions`, `allowances`, `bookings`, `qr_tokens`, `operations`, `audit_events`, `notification_outbox`), `immutable_audit()` function, trigger and index.
2. `backend/auth_schema.sql`: three auth tables (`credentials`, `auth_sessions`, `login_buckets`) and session index.
3. `backend/telegram_schema.sql`: eight Telegram tables (`telegram_link_codes`, `telegram_bindings`, `telegram_updates`, `telegram_runtime`, `telegram_actions`, `telegram_notification_batches`, `telegram_jobs`, `telegram_qr_cleanup`), singleton initialization and indexes.

All three scripts use *unqualified* table names. They must not be applied without an explicitly controlled `search_path` to `kinder`, and before any operations the DBA must establish that the exact schema does not already exist and no conflicting objects/previous partial migration are present.

These scripts are first-install SQL, **not upgrade or idempotent migration scripts**. Do not add `IF NOT EXISTS` blindly, and never use `CASCADE` as a workaround. Review exact DDL and PostgreSQL 18 behavior in isolated synthetic tests first.

## Approval gates BEFORE any production SQL writes
- Run and review `deploy/kinder-readonly-preflight.sql` from a trusted Render-side connection, excluding customer rows/secrets from logs.
- Confirm actual DB is `kinder_spa_db`, expected host and PostgreSQL major 18, and no unexpected existing schema/objects. Verify actual database schema scope and potential extension dependencies.
- Identify current backup capability and complete a **verified isolated restore**, with controlled access and retention. Record restore evidence. Do not copy private customer records without authorization.
- Review a least-privilege migration operator distinct from the runtime identity. Separate `kinder_api_runtime` and a narrowly granted Telegram runtime identity where the application requires them. Audit table must never gain UPDATE/DELETE/TRUNCATE for runtime identities.
- Confirm all expected schemas, constraints, indexes, sequences, trigger grants and runtime queries in a disposable PostgreSQL18 environment. Compare migration ownership and grants to the actual permission preflight.
- Owner to approve the exact execution plan, downtime, role changes, snapshot, rollback limitations and any costs.

## Proposed production sequence (NOT EXECUTED)
After all gates and explicit approval, execute in a single reviewed transaction on an authorized Render-only session: begin; establish bounded lock/statement timeouts; create `kinder` schema if proven absent; set `search_path` explicitly for only that transaction; apply base SQL then auth SQL then Telegram SQL using a vetted migration runner; validate expected objects, indexes and constraints; commit only if all validations succeed. Application starts remain disabled. Ensure migration tool handles SQL dollar-quoted PL/pgSQL correctly. Do not copy/paste scripts by splitting on semicolons.

After schema is applied, separately provision restricted credentials via Render's protected interfaces, inspect actual grants and revoke temporary inspection owner connectivity from BOTH service environment and Blueprint before live mode. Do not publish or enable polling in this step.

**Rollback warning:** a failed transaction can roll back schema creation before COMMIT, but later app writes, outbound Telegram messages, a committed migration, and role/backup changes are not generally undone by switching code releases. Restore planning must be explicit.

## Pricing deliberately deferred
No amounts or currency have been invented. Future tariffs must be effective-dated and historical purchase prices must not change when catalog prices are edited. Prices and payment/discount rules require a separate approved design and migration.

## Verified isolated tests (31 October 2026)
- Real disposable PostgreSQL 18 first-install migrations have passed with all **19 tables**, indexes, append-only triggers and identity-column guards. A repeat first-install is rejected.
- The synthetic `pg_dump` / `pg_restore` rehearsal has passed, verifying restored rows, sequence continuity, and audit/outbox immutability. **This is NOT proof of Render PITR or recovery of customer data.**
- The Render API readiness probe now checks that the required audit, notification and immutable-identity triggers are **present, enabled, on the correct table, invoking the expected schema-local function with the expected UPDATE/DELETE event mask**, as well as critical valid indexes. It fails closed if a trigger/index is missing or disabled. This is metadata-only and does not attest to the exact function body, every constraint or a successful production migration.
- Four isolated PostgreSQL regression cases simulate removed/disabled protection and a missing Telegram uniqueness index. 220 backend tests passed in workflow https://github.com/matrix12345695-afk/Kinder-Spa-android/actions/runs/41202926663 (check entire job conclusion before treating browser acceptance as final).
- Live database catalog inspection and **actual recovery point availability/restore evidence remain incomplete** because the Render connector has no backup/restore endpoint and external SQL access is disabled. Operator approval is required for billable recovery.

**Status: READY FOR FURTHER REVIEW ONLY. NOT APPROVED FOR PRODUCTION EXECUTION.**
