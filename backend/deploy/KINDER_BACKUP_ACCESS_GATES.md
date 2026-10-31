# Kinder Spa: backup and privilege gates (31 October 2026)

Review-only operational checklist. No production SQL, user access, deploy, paid resource, or backup has been created by this document.

## Actual provider facts
- Existing Render PostgreSQL `kinder-spa-db` (`dpg-dbbtkol9fdbs73a7tvqg-a`), PostgreSQL 18, Frankfurt, `available`; 1 GiB disk, plan `0.1c-256mb`, high availability disabled, external IP allowlist empty.
- The Render connector does not expose a backup list, backup restore or verified restore action here. A healthy database and disk are NOT proof of a usable backup.
- Render's published backup documentation says paid PostgreSQL supports continuous PITR and on-demand logical exports; this database is on a paid compute plan. This is **provider-policy eligibility, not independently verified account-specific PITR readiness**. The Render connector cannot call `/recovery` or list/export/restore backups. PITR creates a **new billable instance**, so a restoration test needs explicit cost approval.
- The first read-only worker inspection found that schema `kinder` does not exist. It did NOT inspect all other schema contents or establish that a successful restore exists.

## Preflight: no mutations
1. In the provider's database dashboard, determine whether this exact plan has automated snapshots or point-in-time recovery, the retention window and restore constraints. Record evidence **without displaying connection strings**.
2. Confirm a recoverable backup captured immediately before migration, and prove a restore to an owner-approved isolated destination. Ensure the restore copy is secured, encrypted and deleted according to approved retention, and that the action creates no unapproved charge.
3. Execute the committed read-only catalog preflight using the existing approved Render-side inspector and verify all namespaces, table name collisions and dependencies without exporting personal records.
4. Verify migration success in CI for the exact commit containing the new `verify_migrations.py` job. Prior 207 backend / 24 browser successes do not necessarily certify this additional migration probe.

## Exact proposed schema sequence (owner approval still required)
- Confirm `kinder` does not exist and that this is truly a first-install migration, not an upgrade.
- Use a reviewed migration transaction with explicit `search_path=kinder`: `backend/schema.sql` (8 tables), `backend/auth_schema.sql` (3 tables), `backend/telegram_schema.sql` (8 tables).
- Verify 19 table names, default IDs, constraints, indexes, audit trigger, permissions and Telegram singleton. Leave both live service flags disabled.
- Ensure aborted transaction leaves no application schema and that a committed migration needs an explicit database restore strategy rather than code rollback.
- No `DROP`, `CASCADE`, `IF NOT EXISTS` or ad hoc edits on the live database.

## Least-privilege roles: separate approval and verified SQL required
- Use separate migration operator and runtime identities. Do NOT reuse the database owner in the live API or Telegram worker.
- API role: derive grants from `backend/deploy/api-role.sql` and actual runtime database statements. Database CONNECT and schema USAGE, only specific table SELECT/INSERT/UPDATE/DELETE and required identity sequences; no CREATE, schema ownership, role membership, TRUNCATE or privileged DDL.
- Telegram role: `deploy/telegram-role.sql` is a **review-only** separately scoped candidate based on `telegram_bot.py`, `telegram_delivery.py`, `auth.py` and `store.py`. Synthetic PostgreSQL role tests check exact table privileges and a row-lock/append-only outbox boundary. Do not consider the candidate production-approved without an independent security review. Full-table UPDATE grants required by row locks leave residual authority risk; evaluate narrower column grants or a SECURITY DEFINER/RLS design before live activation.
- Both `audit_events` and `notification_outbox` now have append-only triggers in the **proposed first-install schema**; the latter protects the outbox from mutation even though Telegram needs UPDATE privileges for `SELECT ... FOR UPDATE`. These remain unexecuted production proposals. Grants for Telegram extension are not implied merely by successful API readiness.
- Provision secrets only in Render protected configuration. Delete the privileged `KINDER_INSPECTION_DATABASE_URL` from both active worker environment and `render.yaml` in a coordinated reviewed deployment BEFORE enabling polling. Avoid leaving stale owner credentials on a service.
- Re-run readiness with each dedicated runtime identity and record denied privilege checks, then test actual operations with synthetic accounts.

## Required explicit production approval
Owner must separately approve: exact SQL/hash and target resource, creation of schema and 19 tables, operator/runtime role creation and grants, verified backup/restore evidence, token configuration, and eventually API/public release. The previously approved $7 worker is NOT blanket approval for new cloud resources or DB writes.

No pricing is assumed. No external hosting, VPS, Inventory Bot, or other project secrets are involved.
