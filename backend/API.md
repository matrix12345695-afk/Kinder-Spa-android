# Authenticated Kinder prototype API

**Completed draft:** server-issued login/password, opaque sessions, durable login
rate limits, transaction-bound authorization and bounded JSON endpoints. This does
not complete the Android app, admin web UI or production rollout.

No new Python dependencies. Existing CPython3.12 hashed wheels/PostgreSQL18 are
used. `hashlib.scrypt` (N32768,r8,p1,32-byte result) hashes passwords with independent
16-byte salts; compare uses `hmac.compare_digest`. Passwords are12–128 characters,
at most512UTF8 bytes, with no silent truncation/normalization. Usernames are
case-insensitive ASCII3–64 characters, constrained to letters/digits/underscore/
dot/hyphen and starting with a letter/digit. The real deployment must assess password
policy/resource limits, recovery/rotation and any required authentication hardening.

Bearer sessions contain256 random bits, expire after8 hours, and only SHA256 hashes
are stored. At most5 unexpired active sessions per account; a sixth revokes the oldest.
Logout revokes its session. Admin/superadmin may reset client passwords; reset increments
the credential version and revokes all client sessions. Staff cannot reset another
staff account through this API. Self-service password change/recovery and staff
credential rotation need separate endpoints/operator procedures before a real pilot.

There is no self-registration, staff-creation endpoint or client-provided role/actor
override. The token resolves the account from PostgreSQL and the current database
role controls each operation. API reads recheck session under the same transaction as
their queries. Accounting writes check it **inside Store's write transaction**, holding
account/credential/session locks until commit. An already-admitted transaction may
finish before logout/reset can revoke it; subsequent admissions reject the old session.
Reset cannot undo a committed visit. Expiry is evaluated at transaction admission.

Login attempts, including successes, count in PostgreSQL fixed10-minute windows:
5 per normalized login,30 per actual socket IP,120 globally. Rejections commit counters;
concurrent attempts cannot race past them. A global counter bounds distinct-key storage
and expensive scrypt work. Up to500 rows older than2 windows are cleaned on accepted
admissions. IP/login scopes are SHA256 digests, not plaintext; these hashes are not a
promise of anonymization. The limits intentionally allow temporary denial of login;
there is no permanent account lockout. HTTP429 includes Retry-After600. Gateway-wide
connection/body/rate limits are still required to bound unauthenticated traffic.

## Endpoints

Protected routes require `Authorization: Bearer <opaque token>`. No cookie or query
token authentication. All POST bodies must be JSON objects with **exactly** the named
fields; unknown/duplicate fields, nonfinite values and bodies over8192 bytes reject.
IDs are positive signed64-bit integers (booleans/strings reject). All list endpoints
return at most50 rows, ordered by ID; continue with `?after=<last ID>`.

| Method / path | Body / result | Access |
| --- | --- | --- |
| GET /health | Generic DB/schema readiness | Public, still HTTPS |
| POST /v1/login | login,password → access_token,token_type,expires_at | Public, rate-limited |
| GET /v1/me | account_id,role | Authenticated |
| POST /v1/logout | {} → logged_out | Authenticated |
| GET /v1/audit | At most50 events, reasons and queued-notification flags | Admin/superadmin |
| GET /v1/clients | client_id,login,enabled | Admin/superadmin |
| POST /v1/clients | login,password → client_id,login | Admin/superadmin; always client role |
| POST /v1/clients/ID/password | password → sessions_revoked | Admin/superadmin; client targets only |
| GET /v1/subscriptions | Own allowances, or staff list | Authenticated, ownership-filtered |
| POST /v1/subscriptions | client_id,quotas,key | Admin/superadmin |
| GET /v1/bookings | Own bookings, or staff list | Authenticated, ownership-filtered |
| POST /v1/bookings | subscription_id,category,starts_at,minutes,key | Subscription owner or staff |
| POST /v1/bookings/ID/qr | {} → token,expires_at | Owner or staff, during session |
| POST /v1/bookings/ID/redeem | token,key | Staff only |
| POST /v1/bookings/ID/cancel | key | Owner or staff; pool policy only |
| POST /v1/bookings/ID/no-show | key | Staff only, pool after end |
| POST /v1/bookings/ID/restore | reason,key | Staff only; pool forfeiture/no-show |

Accounting `key` preserves exact retry receipts as before. Client creation instead
uses unique normalized login and a single transaction: duplicates return409 without
creating an extra account. No password or fast password fingerprint is copied into
an idempotency/audit record. After an uncertain create response staff can inspect the
client list. Password reset has no idempotency key; repeating it revokes sessions
again, so reconcile uncertain results before another reset.

Responses, including errors/login/QR, use Cache-Control:no-store, nosniff, restrictive
CSP and referrer/frame headers; HTTPS responses set HSTS. SQL details, password/token
values and tracebacks are never returned or logged by this application. Configure
gateway access/error logs to redact authorization, request bodies and URL arguments.
The API returns stable generic errors, not exception text. A transient DB/lock failure
is503; retry accounting writes with their original key. Browser Origin requests are denied by default. An explicitly configured exact
HTTPS browser_origin enables the local staff panel with a matching Host and Origin
fence, without CORS headers or cookies. Native Android bearer clients remain
independent of this option. See ADMIN.md for the panel and retry/session rules.

## Running / upgrading

This package exports `kinder.api.App(connection_factory)` as a WSGI application; it
does not bind a network port, read a production DSN, run migrations, choose a service
or install a supervisor. Supply a fresh **autocommit** psycopg connection per request.
Use a controlled PostgreSQL search_path/dedicated database and least-privilege DB role.
First apply `schema.sql`, then explicit `auth_schema.sql` only to a new disposable
prototype database. Existing installations need a reviewed migration, backup and
separate recovery plan; neither script is an automated upgrade.

The explicit operator function `bootstrap_empty_database(conn, login, password)`
creates the first superadmin **only if accounts is empty**. It is never invoked at
startup and has no HTTP route. Operator must supply the password privately in memory,
not a shell argument or Git file. Existing populated DBs are deliberately refused.
Client accounts can then be created through authenticated admin requests.

The default application requires trusted `wsgi.url_scheme=https` and uses only
`REMOTE_ADDR` for IP throttling. It ignores X-Forwarded-For/Proto. A gateway must set
scheme/address from a verified transport, without allowing spoofed forwarding headers.
Do not expose a plain wsgiref development server. A reviewed HTTPS WSGI gateway with
request/header/read/worker timeouts, resource/concurrency caps and no secret logging
is a remaining deployment task. `require_https=False` exists only for isolated
loopback tests and must not be used in a real deployment.

The original83 checks require real PostgreSQL18 and zero skips:44 business tests plus39
authentication/API tests. They cover the actual loopback HTTP→WSGI→PostgreSQL login,
business routing, client isolation/role injection, replay, SQL/bad-body rejection,
rate-limit races, credential changes during hashing, revocation after earlier HTTP
identification, and a reset genuinely blocked by an admitted session transaction.
Only synthetic fixtures are used; no real service/data/secret/Telegram access.

ADMIN.md adds the RU/UZ staff panel with10 boundary tests and24 real browser tests.
The separate [native RU/UZ review client](../android/README.md) adds its own
emulator/APK gate; this backend report does not certify Android. Remaining:
production Android binding/distribution, full operational admin features, capacity scheduling, sender for
the durable superadmin outbox, real backup/restore, controlled schema migrations,
production transport/roles/secret setup and exact owner-approved publication.

## Native relative expiry fields

Login responses additionally include `expires_in_seconds` (at most28800).
QR issuance responses additionally include `valid_for_seconds` (at most120,
also capped by session end). Existing absolute timestamps remain unchanged.
Native clients subtract request round-trip time and use a monotonic clock for
local expiry. The server still validates every session and redemption; these
client display fields do not change authorization or single-use accounting.

## Optional Telegram binding

With telegram_enabled=True and the explicit telegram_schema.sql migration, POST /v1/telegram/link issues a self-link and POST /v1/clients/ID/telegram-link lets staff issue a client link. Both require current bearer authentication and empty JSON objects. The feature is disabled by default. See [TELEGRAM.md](TELEGRAM.md); no password is accepted over Telegram and no API endpoint redeems an internal QR hash.
