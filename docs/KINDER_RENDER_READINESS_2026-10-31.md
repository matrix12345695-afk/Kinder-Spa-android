# Kinder Spa: production-readiness checklist (31 Oct 2026)

This document records a verified read-only Render inspection and the required approvals. It is not authorization to execute SQL or enable customers. The owner will supply prices later; do not make up amounts or bind price to the existing subscription rules without review.

## Verified resources
- Render workspace: My Workspace, `tea-d52kjcur433s73ca9810`.
- Existing database: `kinder-spa-db` / `kinder_spa_db`, PostgreSQL 18, Frankfurt, external IP allowlist empty.
- Existing worker: `kinder-spa-telegram` / `srv-dbisj4e7bikc73doom5g`, Frankfurt, single 0.5 CPU / 512 MiB instance, manual deployments, commit `6bce0cc67572575e7abb06d380f7fc0906ddd08b`.
- Render deployment `dep-dbisj4u7bikc73doon20` status `live` on 31 Oct 2026. The worker is an **inspection standby**, not a live bot.

## Redacted read-only inspection result
- PostgreSQL major version: 18
- Negotiated TLS: true
- Read-only metadata probe: true
- Schema `kinder` present: false
- Missing base relations: `accounts`, `subscriptions`, `allowances`, `bookings`, `qr_tokens`, `operations`, `audit_events`, `notification_outbox`, `credentials`, `auth_sessions`, `login_buckets`.
- Runtime role safe: false (inspection uses an operator DB credential; this is not evidence that a future dedicated runtime role is unsafe).
- Readiness: false; Telegram polling disabled.

This inspection does not establish that the database is globally empty, whether an unrelated schema exists, that a backup is restorable, or that future migrations are safe.

## Next non-destructive tasks
1. Review checked-in SQL/schema creation paths and additive Telegram migrations. Compare expected tables, sequences, constraints, privileges, functions, and migration order to an actual read-only catalog inspection.
2. Document the exact empty-schema bootstrap procedure and rollback limitations. Do not assume existing customer data is absent; verify without exposing customer rows.
3. Determine provider-supported backup/restore and test recovery to an isolated environment without modifying or cloning sensitive production data into an unapproved destination.
4. Prepare explicit, reviewed SQL for the 11 base relations, eight Telegram relations if needed, and scoped runtime roles, using placeholders for credentials rather than secrets in Git.
5. Before **any** database DDL/grants/migrations or paid service creation, show the owner exact changes, backup evidence, downtime implications, cost and reversal strategy for separate approval.
6. After approval and verified schema/grants, remove `KINDER_INSPECTION_DATABASE_URL` from both the running worker configuration and its Blueprint, then configure a minimal runtime role through Render protected environment settings.
7. Only then verify the dedicated bot identity using `getMe`, ensure webhook is empty, and request separate approval to enable one live poller. Test QR, roles, cancellation and restoration audit notification with pilot accounts before customer release.

## Fixed business rules (not price-dependent)
- RU / UZ; admin-created accounts; user login/password; client and admin Telegram roles.
- Massages: 10 sessions; hydromassage: 10 sessions; swimming pool: 4, 8, 12.
- Monday–Saturday 09:00–19:00 Asia/Tashkent; Sunday closed.
- Pool slot: 45 minutes (5 changing + 40 swimming).
- Pool cancellation before 19:00 preceding day; otherwise session expires. Admin restoration requires a reason and superadmin Telegram audit notification.

## Price intake pending
Collect an authoritative price sheet and effective date later. Preserve currencies, service/package identifiers, discount/payment rules and historical charged prices. No placeholder prices should be interpreted as live tariff policy.

## Boundary
All Kinder hosting and secrets stay on Render. Do not use VPS, Inventory Bot, its tokens, or other projects. Do not add OpenAI API costs. Do not set up a ChatGPT hourly automation.
