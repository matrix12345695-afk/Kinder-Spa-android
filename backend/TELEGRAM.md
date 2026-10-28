# Kinder Spa Telegram bot — client and administrator review component

Status: code draft. No real bot identity/token, live Telegram sender or production
service is provisioned. The owner selected **clients and administrator**. This is
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

The **uninstalled** `deploy/` unit proposes a separate dynamic Unix user,
read-only `/opt/kinder-spa/release`, systemd credentials, inaccessible home
directories,512MiB/half-CPU caps and96 file descriptors. No existing service or
Inventory directory is used, changed or restarted.

## Pilot gates and remembered owner action

1. Create a **separate** bot in real `@BotFather` using `/newbot`. Available tools
   cannot create that Telegram identity. Do not send its token in chat, GitHub,
   issue text or a command argument; provision it privately after review.
2. Review an exact source/CI release, dedicated Kinder database/least-privilege
   role, migrations, backup/restore and deployment/rollback. A token alone does
   not approve publishing customer services.
3. Privately provision `/etc/kinder-spa/telegram.env` and `telegram.token`.
   Default live mode is **disabled**. Approved configuration must set
   `KINDER_TELEGRAM_LIVE=approved`, exact bot ID, dedicated `kinder_*` database,
   schema and DSN. Remote DBs require verify-full TLS. Private token-file
   permissions/ownership are checked; Inventory/ULTIMATE paths, symlinks and
   hardlinks are refused before read. No real configuration was read here.
4. The runner verifies `getMe` ID/username and an empty webhook, without deleting
   an existing webhook. A DB lock admits one poller; Telegram401/409 conflicts
   stop with exit2 instead of fighting another process. The example service
   is not installed or running.
5. Bind the superadmin through the authenticated self-link. Verify a genuine
   restoration notification and QR workflow using synthetic pilot accounts.
   Then review public-admission/rate limits, retention, operational alerts,
   physical devices/accessibility and the exact production release approval.

Both hash-lock files are required for tests. `python backend/run_checks.py`
requires165 real PostgreSQL/backend checks, including70 Telegram cases, without
skips. Browser acceptance remains24 checks and Android16 JVM +11 device checks.
Wire fixtures use actual loopback HTTP/multipart photos, native QR decoding and
real PostgreSQL with synthetic credentials. They do not prove live Telegram
delivery, a provisioned BotFather identity or production readiness.
