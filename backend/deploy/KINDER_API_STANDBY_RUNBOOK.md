# Kinder Spa · staged Render API activation and recovery check

**Status:** Review-only; no production database schema/role changes, customer release, Telegram polling or paid recovery authorized.

## Deployment contract

The public web service `kinder-spa-api` must start from this repository's reviewed feature branch with `python -m kinder.api_entry`. Initially set `KINDER_API_LIVE=disabled` and **do not supply any database, Telegram or client account secrets**. The launcher refuses to run outside Render's dedicated `web` service identity.

| URL | In disabled standby | Meaning |
| --- | --- | --- |
| `GET /health` | HTTP 200, `mode=standby` | Render process is up; **not an API-readiness proof** |
| `GET /ready` | HTTP 503, `ready=false` | Intentionally not ready for customers |
| `/v1/*`, `/admin`, `/` or other requests | HTTP 503 | No client traffic accepted |

The standby app never opens PostgreSQL connections, reads credentials, handles QR, invokes the Telegram API, or serves a real login page. There are no cron tasks, writable files, accounts or customer data. The preview static site remains independent. Only the exact `approved` live flag dispatches to the pre-existing production API, which separately checks canonical Render origin, dedicated service identity, PostgreSQL18 schema and least-privilege role metadata before listening. **Do not set `approved` until all production gates below have passed.**

A free Render web service is suitable for this **nonproduction smoke test**, not for production operation. It can cold-start after inactivity and counts toward included build minutes and outbound bandwidth. Costs may arise if account quota overages are enabled. Keep auto-deploy OFF.

## Verified provider status (2 November 2026)

- Existing `kinder-spa-db`: `dpg-dbbtkol9fdbs73a7tvqg-a`, region Frankfurt, Postgres 18, paid `0.1c-256mb`, available, external IP allowlist empty. This is a **metadata check**, not a backup check.
- Render's SQL connector cannot query the database because its external IP allowlist is empty; **do not loosen the allowlist** for the hosted connector.
- **PITR availability confirmed by owner-provided Render Recovery screenshot on 2 November 2026:** the database page shows **Point-in-Time Recovery**, offering timestamps within the previous **3 days**, and the **Restore database** action. The screenshot does **not** identify a particular recovered timestamp or prove that restoration actually succeeds.
- **Recovery execution NOT VERIFIED**. No `Restore database` action, recovered instance, logical export, or paid tier upgrade was performed. A point-in-time restore typically provisions a separate billable database; get exact cost and approval before beginning.
- The 3-day window is rolling. Immediately before any authorized schema mutation, recheck availability for a point just before migration. This 2 November screenshot does not guarantee a later recovery point.

## Owner's read-only Recovery check

**Completed on 2 November 2026 (availability check only):** Owner supplied a screenshot of Render → `kinder-spa-db` → **Recovery** showing a 3-day PITR window. There was no restore and no confirmed recovered copy. Before requesting any production DDL, obtain a fresh screenshot of the window, an approved recovery plan, and separately approved billable test restore if required. Do not reveal connection strings or execute `Restore database` without distinct authorization.

Official docs:
- https://render.com/docs/postgresql-backups
- https://render.com/docs/free

## Separate production approval gates

1. Confirm exact production DB identity, backup recovery window and a feasible isolated restore with explicit cost/retention approval.
2. Review `deploy/kinder-readonly-preflight.sql`, migration SQL and role grants against a timestamped exact Git commit. Never run the first-install scripts on the existing database until the live schema absence and expected ownership are confirmed.
3. Obtain an explicit DB migration/role grant approval scoped to this Render database and this exact review; preserve a rollback/restore decision log. **No auto-run migrations or schema initialization at startup.**
4. Provision a distinct least-privilege runtime identity in protected Render settings, never in GitHub or chat. Remove temporary privileged worker inspection credentials before switching to live mode.
5. Validate the real API `/ready` and `/health` using read-only database preflight then test synthetic clients in an isolated environment. Existing `render_api` only implements `/health`, so live `/ready` is not yet a production endpoint.
6. Verify actual Android login, booking, QR, restoration reason delivery and real physical-camera behavior with supervised test accounts before any customer release.
7. Obtain separate publication approval, and only then flip `KINDER_API_LIVE=approved`. User notification opt-in, live Telegram delivery and pricing require their own gates.

**Guardrail:** This does not authorize any modification to Inventory Bot, a VPS, any unrelated app, Render billing/plan, or any customer record.
