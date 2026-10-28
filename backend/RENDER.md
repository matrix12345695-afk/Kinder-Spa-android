# Kinder Spa: Render-only deployment record

Owner decision,28 October2026: every hosted Kinder component and secret belongs
on Render. No VPS install, SSH bridge, systemd unit, token transfer or token
custody is authorized for Kinder. The abandoned local VPS-transfer prototype was
never committed or executed remotely. This decision supersedes older instructions.

## Actual read-only audit

Confirmed workspace: **My Workspace**, matrix12345695@gmail.com,
`tea-d52kjcur433s73ca9810`.

| Component | Verified state on28 October2026 |
| --- | --- |
| PostgreSQL | `kinder-spa-db`, ID `dpg-dbbtkol9fdbs73a7tvqg-a`, Frankfurt, PostgreSQL18, available, existing paid plan `0.1c-256mb`,1GiB. Database name `kinder_spa_db`. |
| External DB access | Empty IP allowlist. Read-only MCP schema query was refused; no tables/data/migrations were inspected and the allowlist was not changed. |
| API/admin hosting | No Kinder service present in the workspace service list. Root `render.yaml` now describes the native Python API/admin pilot; its Render gateway is tested locally, not deployed. |
| Telegram hosting | No Kinder service present. Polling code is a tested draft, not a running bot. |
| Token | Owner reports creation and storage as GitHub Actions secret `KINDER_TELEGRAM_BOT_TOKEN`. Value, username and real Bot API response are unverified. |

No Render resources, environment values, deploys, database schemas or permissions
were changed by this audit. Inventory and unrelated services are excluded.

## Reviewable Telegram proposal

Custom Blueprint path: `backend/deploy/render-telegram.yaml`. It proposes only
`kinder-spa-telegram`, a Python3.12 Background Worker in Frankfurt, one instance,
manual deployments,512MiB/0.5CPU, no disk, Redis, cron or additional database.
The process reads the existing dedicated PostgreSQL using an explicitly reviewed
runtime DSN and role. It does not run migrations or bootstrap accounts.

**This is paid compute, not a free plan. Creating the worker incurs cost even
while live mode is disabled. The owner replied “Продолжай” to the$7/month proposal, treated as approval
of that bounded expense. Do not apply a higher plan or a customer release
without its separate approval.** Current plan/catalog references were
read; the account's checkout must remain within the approved$7/month additional compute limit.

The existing polling transport requires an always-on worker. Render free web
services sleep after15minutes without inbound traffic, so placing this polling
loop in a free web service does not provide continuous delivery. A free webhook
variant would require a separate inbound adapter, reliable background delivery
design and cold-start acceptance; that variant is not implemented or promised.

Blueprint Telegram live mode stays `disabled`. The initial worker mode is
inspection: one read-only metadata report, then idle for internal preflight.
It neither polls Telegram nor serves HTTP. Paid creation is not a free staging
mechanism. Runtime activation still requires reviewed configuration/roles. `autoDeployTrigger: off` prevents source pushes from publishing
new revisions. `maxShutdownDelaySeconds: 180` allows bounded polling/delivery to
finish; forced interruption may leave leased jobs for retry and duplicate an
unconfirmed remote send. No exactly-once claim is made.

## Private configuration

Initial creation needs no bot token: Render resolves only the existing DB
connection as KINDER_INSPECTION_DATABASE_URL, used solely in read-only inspection.
It is never a runtime credential fallback. After schema/role review, remove this
temporary operator binding and open **Environment** for runtime configuration:

- `KINDER_TELEGRAM_BOT_TOKEN`: the separate BotFather token, entered only in
  Render's protected field. Never paste it into chat, code, logs or a URL.
- `KINDER_TELEGRAM_BOT_ID`: exact numeric ID, verified against `getMe` at startup.
- `KINDER_DATABASE_URL`: reviewed least-privilege connection for the existing
  Kinder database, with the explicitly scoped Render-private TLS transport described in GATEWAY.md. Do not automatically reuse a database
  owner connection or weaken certificate checking.
- `KINDER_DATABASE_NAME=kinder_spa_db` and `KINDER_DATABASE_SCHEMA=kinder` are
  proposal values. Inspect the real existing schema before enabling them.
- `KINDER_TELEGRAM_LIVE=approved` only after cost, release and migration gates.

Use **Save only** while preparing environment values. No token is read from
shared `BOT_TOKEN`, files, ULTIMATE or Inventory. Render markers detect accidental
launches outside the intended worker; they cannot attest the underlying host.

The GitHub Actions secret cannot be read back through GitHub APIs, and the
available Render connector has no GitHub-secret import. Therefore the secret is
**not yet bound to Render**. A GitHub workflow would need separately authorized
Render API credentials; none were requested, extracted or created. Keep the
existing secret untouched until a concrete handoff is selected.

## Remaining release gates

1. Review this source and CI and approve the exact release. Keep worker compute
   within the approved$7/month additional limit; no higher plan is authorized.
2. Inspect Kinder DB internally from Render, snapshot/verify restore, determine
   current schema, apply reviewed additive migrations only to Kinder and use a
   least-privilege runtime role. Do not open external networking for this task.
3. Provision the separate HTTPS API/admin service on Render for account access
   and staff self-link bootstrap. No public listener is claimed by this worker.
4. Bind the token privately, verify real `getMe`/empty webhook, activate exactly
   one poller and test genuine Telegram delivery with synthetic pilot accounts.
5. Verify restart/retry/revocation, QR use and restoration notice receipts, record
   the deployed commit/service ID, then approve customer admission separately.

Rollback is a previous reviewed worker release with the current compatible
schema and no competing poller. It does not undo accounting, migrations or sent
messages. Actual Render rollback, schema/backup restoration and delivery remain
unverified. Code preparation is done; deployment and real delivery are pending.

## API gateway increment

See [GATEWAY.md](GATEWAY.md): native Render API/admin launcher, read-only role/
schema/permission inspection,207 backend checks and a repaired root API Blueprint.
No actual service or database write is performed. The connected Render tools have
no worker/Blueprint creation operation; provider Dashboard creation and private
secret entry remain the supported handoff. No new API credential is requested.
