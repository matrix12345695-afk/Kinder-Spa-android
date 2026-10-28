# Render API/admin gateway — review component

The root `render.yaml` now describes a native Python Render Web Service for the
existing WSGI API and RU/UZ staff panel. The historical missing-Dockerfile/JWT/
default-admin scaffold is replaced. No default account, migration, JWT secret,
Telegram token or database-owner connection is installed by the gateway.

Status: source and local fixture testing, **not a live Render deployment**.
The separate polling bot remains a Render Background Worker; no Kinder component
is installed on VPS. The owner replied “Продолжай” to the proposed$7/month worker
cost; this is treated as approval of that bounded additional expense, not of
higher plans or customer publication. The API proposal uses the free plan.

## Runtime and transport boundary

`python -m kinder.render_api --run` requires explicit `KINDER_API_LIVE=approved`,
the dedicated Render web-service markers/name, canonical HTTPS `onrender.com`
origin, a valid non-reserved PORT and the dedicated Kinder DSN/schema. It refuses
startup before reading the DSN off the intended Render service or while disabled.
Markers prevent accidental launches, not malicious host impersonation.

Render publicly redirects HTTP to HTTPS and terminates TLS at its edge; it sends
HTTP to the process. The Render-specific adapter assigns the public HTTPS scheme
from that deployment topology, discards Forwarded/X-Forwarded-* claims and never
uses them to select host, origin, account or client IP. The generic `kinder.api.App`
continues to require an actual trusted HTTPS WSGI scheme by default.

**Trust boundary:** other callers on the same Render private workspace network
are trusted internal transport callers. This adapter cannot attest whether a
particular private request traversed the public TLS edge. It must not be deployed
as a general internet-facing HTTP server outside Render, nor be claimed to secure
an untrusted internal network. Only the canonical provider host is supported;
custom domains and private-network isolation need a separate review.

The existing exact Host/Origin, bearer/role/session/version, input and ownership
checks still apply. Login throttling uses the actual socket peer (typically a
Render proxy), **not a proven end-user IP**. Shared-proxy users may share the
30-attempt/10-minute peer bucket; per-login5 and global120 bounds remain. Do not
call this per-client-IP enforcement. Load/rate/abuse acceptance remains a pilot
gate before public customer admission.

Gunicorn26.2.0 (MIT, exact wheel SHA256 in `gateway-requirements.lock`) runs one
sync worker, one thread, backlog32,2048-byte request line,32 headers of4096 bytes,
30-second worker/graceful timeouts and bounded worker recycling. API JSON bodies
remain limited to8192 bytes. The programmatic launcher does not execute a local
gunicorn.conf.py or parse GUNICORN_CMD_ARGS; fixed settings override concurrency
defaults. `0.0.0.0:$PORT` is used only after preflight succeeds.

There are no access logs. The gateway logger emits fixed severity events and
discards raw messages, request/URL/header/body arguments and exception text.
Application errors remain generic. Operational monitoring must use safe counters
and metadata; no claim is made that provider infrastructure never retains its
own HTTP logs. Keep credentials out of URLs and application logs.

## Read-only database preflight

`python -m kinder.render_api --inspect` is an explicit operator-only CLI, not an
HTTP route. It can run while live mode is disabled, but still requires the
dedicated Render service markers and reviewed Kinder DB configuration. The
explicit inspection mode can also run from the future Kinder worker's Shell/SSH;
web serving still refuses a worker. Its report checks the API-role requirements,
not full bot readiness; choose the inspected role accordingly.

The probe starts a read-only transaction, reads PostgreSQL metadata only and
prints a bounded report of version, schema presence, required-table presence and
runtime permissions. It never reads account/password/session/QR/customer rows.
It refuses superuser/CREATEDB/CREATEROLE/replication/BYPASSRLS, other-role
memberships, database/schema creation authority, schema/table ownership,
missing per-operation grants and mutable audit permissions. Use a dedicated
login with direct grants rather than role memberships. The role example in
`deploy/api-role.sql` is review-only and is never executed on startup.

Readiness covers the11 base/auth tables. `KINDER_API_TELEGRAM_LINKS=enabled`
additionally requires the eight Telegram tables and scoped link-code grants;
the default remains disabled. This exposes the existing authenticated self-link
route needed to connect the first staff account after separate operator bootstrap.
The API never reads the bot token or configures/changes a Telegram webhook.

The probe checks presence/role/grants, **not full constraint/column/function
equivalence, data consistency, backup correctness or migration safety**. Those
remain separate reviewed release gates. Production PostgreSQL has not been
inspected: its external allowlist is still empty. Keep it closed and inspect
internally from the eventual Render service using an authorized private DSN.

### Render's internal database TLS

The current provider reference explicitly says internal Render PostgreSQL TLS
uses self-signed certificates and does not support verify-ca/verify-full:
https://render.com/docs/postgresql-creating-connecting#ssl-modes-for-internal-connections
The previous unconditional remote verify-full gate would therefore prevent the
Render-only pilot from connecting to its internal database.

`KINDER_DATABASE_TRANSPORT=render-private-tls` is a separate, explicit policy:
only database `kinder_spa_db` and the pinned host `dpg-dbbtkol9fdbs73a7tvqg-a`
are admitted, with `sslmode=require`, TLS1.2 minimum, GSS fallback disabled and
an actual negotiated-SSL check before schema queries. Confirm this host against
Render's private Connect details before enabling; the instance ID was read, but
connection credentials/actual endpoint were not retrieved. Other hosts/databases,
plaintext/prefer modes, hostaddr/options/service overrides and external lookalikes
are rejected. This trusts Render's private network and DNS; it does **not** verify
server certificate identity and does not protect an untrusted private network.

The default `verified-tls` transport retains verify-full for ordinary remote
connections. There is no plaintext or external-host downgrade fallback. Both
proposed Render manifests explicitly select the scoped private mode. Real
negotiation on Render is still unverified; six synthetic configuration/status
checks exercise the guard, not a real production TLS handshake.

The public `/health` returns only `{"ok":true}` or a generic503. It checks the
same metadata preflight and never exposes its report. A missing table, failed
connection or changed role/grant makes the service unready. Health latency and
failure/recovery on the real Render network remain unverified.

## Deployment and remaining owner action

The API Blueprint has manual deploys, a single free instance, no disk and no new
database. It stays disabled until configuration/schema/role/backup review and an
exact release approval. Applying the disabled template does not produce a healthy
API. Free services sleep after15minutes without inbound traffic and can cold-start;
this is a pilot proposal, not an always-on production commitment.

The current Render connector has no Background Worker or Blueprint creation
operation and cannot import a GitHub Actions Secret. Do not work around this by
installing on VPS, using a cron job, borrowing another project's service or
extracting the connector credential. A provider Dashboard Blueprint/worker form
is the supported handoff for creation and private token entry. No extra Render
API key is requested for this increment.

After a reviewed service exists, enter only its dedicated credentials through
Render **Environment**, using **Save only** while preparing. Set the schema/DSN
only after internal inspection; do not reuse an owner role in the running API.
Bootstrap the first superadmin privately using the existing explicit empty-DB
operator procedure, never HTTP or a default password. Enable Telegram link
issuance only after the additive migration and worker identity are verified.

Real TLS, exact deployed version, DB/role/migration/backup/restore, staff bootstrap,
token binding, Telegram delivery/QR round trip, load/device/accessibility and
customer admission remain pending. A previous compatible application release
does not roll back data, grants, migrations or delivered messages.

## Verification

The26 new gateway checks include actual PostgreSQL18 roles/grants/read-only transactions
and a real Gunicorn HTTP login/me/header-limit flow, with synthetic credentials.
Six additional private-TLS scope/status checks are synthetic. Together they
are included in the205-check backend gate;24 browser and27 native checks
remain separate. Synthetic HTTP behind an emulated Render boundary does not
prove actual Render TLS or deployment. Evidence reports keep both flags false.
