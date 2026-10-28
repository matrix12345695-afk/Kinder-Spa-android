# Kinder Spa admin panel: isolated RU/UZ draft

The first working admin interface is served at `/admin` only when an operator
explicitly configures `App(..., browser_origin='https://exact.example')`.
It provides responsive Russian/Uzbek login, loaded-record overview, client creation
and password reset, individual subscription issuance, bookings, pool cancellation,
no-show/restoration with required reason, manual one-time QR-code redemption and
paginated audit history. This is not the full Kinder/Android product or a deployment.

The blue interface uses local HTML/CSS/JavaScript and one local SVG. No framework,
remote font, CDN, analytics/tracker or new production dependency. Desktop1440px and
mobile360px screenshots contain synthetic fixtures only. Dates use Asia/Tashkent;
numeric visit dates work in both languages even without Uzbek ICU month names.
Service capacities, prices, expiring/frozen packages and non-pool cancellation rules
are not invented. Pool packages4/8/12, massage/hydromassage10 remain server-validated.
Other service durations are entered explicitly by the administrator.

## Browser security and session lifecycle

- Default API behavior still rejects browser Origin requests. The opt-in origin
  must be an exact HTTPS origin, without credentials/path/query. Host must match
  the configured authority. Foreign/null/near-match origins and spoofed forwarded
  host/proto headers cannot change this scope. No CORS wildcard/credentials header.
- Native bearer clients still work. The panel uses same-origin fetch and an opaque
  token **only in JavaScript memory**. No localStorage/sessionStorage/cookie/URL token,
  hidden password defaults or console logging. Reload requires a fresh login.
- Login verifies the server role; clients cannot enter the staff interface. Server
  authorization/ownership checks remain authoritative even if UI code is bypassed.
- Logout/session expiry clear the token, passwords, records, dynamic select options,
  identity and counters. A generation fence prevents an older in-flight response
  repopulating the page after logout or session replacement. Back-forward-cache
  restoration also clears the session. A failed logout confirms local exit only;
  the server token expires or can be revoked, not falsely reported as revoked.
- The exact asset allowlist contains HTML, CSS, JavaScript and icon; there is no
  arbitrary-file endpoint. HTTPS/host/origin gates apply before serving assets.
  No-store, nosniff, frame/referrer headers and CSP allow only local scripts/styles/
  connections with no inline scripts/eval or external origins. Untrusted API text,
  including restoration reasons, is inserted with textContent, never innerHTML.
  Forms have POST fallbacks so disabling JavaScript cannot put passwords in URLs.
  Closing a password/QR dialog with Escape also clears its hidden input.
- The audit view reports a superadmin notification as **queued**, not delivered.
  It cannot approve a publication/payment or resolve a UAC owner decision.

## Mutations, uncertain responses and paging

Buttons disable during submission. Accounting forms/dialogs retain the same random
operation key and exact arguments after a lost/503 response. Fields lock for a
same-request retry; modifying an unresolved request cannot silently create a new
key. A real browser fault test consumes an actual successful API response and then
aborts delivery; retrying returns the original receipt, with one subscription row.
No automatic retry is performed. The original key lives only in the current tab;
beforeunload warns about unresolved writes. After reload/new login, inspect saved
records/history before manually issuing a new operation.

Client creation/password reset have no accounting idempotency key. An uncertain
response clears the password and blocks blind retries in that tab until a new
login. Reconcile the client list or verify the new login before another reset;
repeated resets revoke sessions again. UI messages do not turn HTTP acceptance
into a delivery/owner-approval claim.

Each list requests at most50 rows per page; explicit Load more appends another page,
up to500 records per tab. Dashboard numbers say **loaded selection**, not global
client/revenue/visit totals. A failed collection refresh shows unavailable data,
not an invented zero. The panel rejects IDs outside JavaScript's safe integer range
rather than rounding them into another person's record. Administrative search,
filters and richer operational reporting remain future work.

## Reproducible acceptance

Use the same new disposable local PostgreSQL18 `kinder_test` fixture as API tests:

```sh
python -m pip install --require-hashes --only-binary=:all: -r backend/requirements.lock
python -m pip install --require-hashes --only-binary=:all: -r backend/browser-requirements.lock
python -m playwright install --with-deps --only-shell chromium
KINDER_TEST_DATABASE_URL=postgresql://postgres:fixture-only@127.0.0.1:15439/kinder_test \
  python backend/run_checks.py
KINDER_TEST_DATABASE_URL=postgresql://postgres:fixture-only@127.0.0.1:15439/kinder_test \
  python backend/run_browser_checks.py
```

Both gates require zero skips:207 PostgreSQL/API/Telegram/gateway checks and24 real
Chromium→WSGI→PostgreSQL tests. Business flows use real endpoints and transactions;
only the explicitly named network-fault tests intercept/lose/delay responses.
Tests deny external page requests/WebSockets. Six desktop/mobile RU/UZ screenshots
are taken only outside password/QR input; no raw request traces or token artifacts.
`accounting-evidence/report.json` and `admin-evidence/browser-report.json` bind the
exact Git revision and all component/static source hashes. Browser version is
recorded; CI installs the Chromium revision belonging to fixed Playwright1.62.0.

Test-only wheels are hash-pinned: Playwright1.62.0 (Apache-2.0), pyee13.0.1 (MIT),
greenlet3.5.5 (MIT/PSF-2.0), typing-extensions4.16.0 (PSF-2.0). They do not become
runtime dependencies or ship a public agent. Core production requirements stay
unchanged. Local tests may use `KINDER_TEST_CHROMIUM=/usr/bin/chromium`; this override
is not used in CI, and the actual browser version is recorded independently.

The browser fixture binds HTTP only on127.0.0.1 and opts into require_https=False
with that exact loopback origin. This exception is limited to tests. Real HTTPS,
gateway time/resource/concurrency caps, staff bootstrap/credential procedures,
least-privilege roles, migrations, backup/recovery, actual notification sender and
owner approval remain deployment gates. No service/DSN, real credentials/customer
data, Render/billing/production writes or UAC runtime scope are configured here.
Production Android binding/distribution, client/child profiles, photos, camera QR scanning, capacity, full business
reports and the production-ready admin experience remain unfinished.

See [TELEGRAM.md](TELEGRAM.md) for the separate client/staff Telegram draft and its70 synthetic protocol checks. A real BotFather identity/token, live delivery and production approval remain open.
