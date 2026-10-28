# Kinder Spa Telegram bot — client and administrator review component

Status: code draft. Owner reports a separate BotFather token stored in the
GitHub Actions secret `KINDER_TELEGRAM_BOT_TOKEN`; its value and live identity
have not been verified. No Kinder sender or production service is provisioned. The owner selected **clients and administrator**. This is
a separate Kinder bot; Inventory and ULTIMATE credentials/services are excluded.

## Included flow

- RU/UZ private-chat menus; own subscriptions, appointments and history for
  clients. Reads have20-row pages and describe the loaded selection. Staff can
  inspect center records under their current database role.
- In-memory one-time QR images. Staff sends a photo of just the QR or uses
  `/redeem CODE`; the bot resolves its booking and asks for confirmation before
  transactional redemption. Existing expiry/single-use/staff checks still apply.
- Pool cancellation with confirmation and the unchanged strict previous-day19:00
  Asia/Tashkent refund rule. No massage/hydromassage cancellation policy,
  capacity assumption or appointment-creation rule is added.
- Staff `/restore ID reason` with confirmation, audit and durable superadmin
  event. Reasons are not copied to Telegram notification text.
- Staff `/link CLIENT_ID` creates a ten-minute connection link at send time.
  Link plaintext never enters jobs/audit. Existing valid bindings cannot be
  silently taken over. Client accounts/passwords remain administrator-issued.
- `/notifications` distinguishes waiting for a recipient, pending/inflight,
  Telegram-accepted, blocked and failed sends. Acceptance is not reading or
  approval. Current valid superadmins are snapshotted per event; absent recipients
  leave the original event waiting instead of falsely delivered.
- Persistent polling offsets, update deduplication, action idempotency, delivery
  leases,8-attempt bounds,429 retry-after and role/version revocation fences.
  Expired QR messages get best-effort cleanup. Ambiguous network/DB outcomes can
  duplicate delivery; exactly-once messaging/cloud erasure are not promised.

## Binding and authority

`telegram_schema.sql` is an explicit additive migration AFTER the existing
schemas. No API/runner automatically applies it. The HTTPS API opts in with
`App(..., telegram_enabled=True)`; the default remains disabled:

- `POST /v1/telegram/link {}` issues a self-link for the authenticated account,
  including the first staff/superadmin bootstrap.
- `POST /v1/clients/ID/telegram-link {}` lets staff issue **client** links,
  never other staff links. Responses include `start_payload`, expiry and, after
  verified bot configuration, a `https://t.me/...` URL.

Link hashes are bound to an intended account/credential version. The Telegram
sender ID must equal the private chat ID. Groups, forwards, bot senders, usernames
as authority and foreign callback messages are refused. Every read/action/private
send rechecks enabled account, binding, credential version and current role.
Password reset invalidates old bindings; queued messages cannot retain old staff
privileges. Unlink requires confirmation and blocks delayed private replies.

Confirmations are bound to one binding/action/booking and expire within5minutes
(QR confirmations also expire with the QR). A scoped advisory lock serializes
confirm/decline. Accounting, core idempotency and applied action state commit
atomically. A late decline cannot undo an applied operation. Pending redemption
retains only a prevalidated QR hash; no public HTTP route accepts that internal
hash instead of a QR. No balance is changed by photo decoding alone.

## Transport and resource limits

The transport uses fixed HTTPS Bot API/file hosts, a method allowlist, redirect
refusal, bounded responses and redacted exceptions. Message-supplied URLs/files
are never fetched. Photos are limited to2MiB,4million pixels, JPEG/PNG and a
single opaque43-character QR. A fixed decoder child has4s wall/2s CPU/384MiB
address-space limits and an environment without token/DSN. This is resource
confinement, not a general-purpose untrusted-code sandbox. Send/file timeouts
are8s, polling15s, leases45s; no more than8 delivery attempts are admitted.

Hash-pinned wheels: qrcode8.2 (BSD-3-Clause), Pillow13.0.0 (MIT-CMU),
zxing-cpp3.1.1 (Apache-2.0). See `telegram-requirements.lock` and full packaged
licenses in `TELEGRAM_THIRD_PARTY_NOTICES.txt`. QR rendering uses a library matrix
and a bounded stdlib PNG encoder, with no extra encoder dependency.

## Hosting: Render only (owner decision, 28 October 2026)

All Kinder components, including the API, admin panel, Telegram bot, database and
secrets, belong on **Render**. No Kinder code, token, transfer key, service or
configuration may be installed on the VPS. The former systemd unit and token-file
instructions are removed. [RENDER.md](RENDER.md) records the live infrastructure
audit, worker proposal, secret-entry path and remaining deployment gates.

The new uninstalled `deploy/render-telegram.yaml` describes a dedicated Render
Background Worker in Frankfurt, one instance, manual deploys and hash-locked
Python dependencies. It creates **paid compute** if applied, even when bot live
mode is disabled. Owner cost approval is required before creating it. It neither
creates nor changes PostgreSQL. Persistent offsets, jobs and receipts belong in
the existing dedicated Kinder PostgreSQL, never an ephemeral local filesystem.

## Pilot gates and remembered owner action

1. BotFather creation/token storage is owner-reported done. Do not request the
   token in chat or retrieve it from GitHub logs. GitHub Secrets cannot be read
   back or automatically imported by the available Render connector. Provision
   `KINDER_TELEGRAM_BOT_TOKEN` directly in the eventual Kinder Render service's
   **Environment** form; use **Save only** before the approved release.
2. Approve an exact source/CI release and paid worker, inspect the existing
   `kinder-spa-db` internally, review its schema and a least-privilege runtime
   role, migrations and backup/restore. External connections are currently
   denied by the database allowlist; do not open it for this setup.
3. The runner defaults to disabled and requires `--run`/`--once`,
   `KINDER_TELEGRAM_LIVE=approved`, Render's worker/service markers, the exact
   expected bot ID and a matching dedicated token prefix. Render marker checks
   prevent accidental VPS starts; they are not cryptographic host attestation.
   There is no token-file or shared `BOT_TOKEN` fallback. The database must be
   the dedicated `kinder_*` database with verify-full TLS for ordinary remote connections. The explicit
   Render-private transport instead pins the existing Kinder host/database,
   requires TLS1.2+ and verifies negotiated SSL, trusting Render's private network
   rather than a certificate identity. See GATEWAY.md; actual TLS is unverified.
4. The runner verifies `getMe` ID/username and an empty webhook, without deleting
   a webhook. A database lock admits one poller. Telegram401/409 stops the loop;
   do not use Render cron, a free sleeping web service or several pollers as a
   replacement for an always-on worker. The Blueprint is not applied.
5. Bind the superadmin through the authenticated self-link after the separate
   HTTPS API is provisioned on Render. Verify a genuine restoration notice and
   QR workflow with synthetic pilot accounts. Then review public admission,
   retention, alerts, physical devices and the exact production release.

Both hash-lock files are required for tests. `python backend/run_checks.py`
requires205 real PostgreSQL/backend checks, including70 Telegram,8 Render worker,26 API gateway and6 private-TLS guard cases, without
skips. Browser acceptance remains24 checks and Android16 JVM +11 device checks.
Wire fixtures use actual loopback HTTP/multipart photos, native QR decoding and
real PostgreSQL with synthetic credentials. They do not prove live Telegram
delivery, a provisioned BotFather identity or production readiness.
