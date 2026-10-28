# Kinder Spa: transactional accounting prototype

Transactional backend components, for isolated review. The authenticated WSGI API
and admin-issued password/session module are documented in [API.md](API.md).
The opt-in RU/UZ staff panel is documented in [ADMIN.md](ADMIN.md).
No deployment, Android client or Telegram sender is included.
Never use a client-supplied `actor_id` as authentication. A future server adapter
must derive this ID from a verified session and use a least-privilege database role.
Only an operator can bootstrap staff; `create_client` cannot create a staff role.

Implemented against PostgreSQL18 and CPython3.12:

- Admin-issued client records and individual/combined subscription allowances.
  Massage and hydromassage:10 each; pool:4/8/12. Categories never share balances.
- Booking reserves one allowance atomically, preventing several reservations
  spending the same last visit. Redemption consumes that reservation without a
  second debit. Different subscriptions and facility/instructor capacity are not
  a scheduling system yet; this component does not promise a free physical slot.
- Monday–Saturday09:00–19:00 in Asia/Tashkent. A pool appointment lasts45 minutes
  including5 minutes changing and40 swimming. Last pool start18:15. Other service
  durations are explicit inputs pending catalog configuration; none are invented.
- Cancel pool strictly before19:00 the previous calendar day to return the
  reserved allowance. At19:00 or later, before the session, it is forfeited.
  This also applies to Sunday before a Monday visit. Cancellation after start is
  rejected; staff can mark a pool no-show after the appointment ends.
- Only admin/superadmin can restore a forfeited/no-show pool visit, with a required
  reason. Balance, append-only audit and superadmin notification outbox entry
  commit together. Outbox means queued, **not delivered to Telegram**. Avoid
  medical/child details in reasons; future UI must use reviewed minimal reasons.
- Opaque256-bit QR tokens valid for at most2 minutes and no later than session
  end. Only token hashes persist. Tokens are bound to the booking/category/client
  through the subscription. Reissuing revokes previous tokens. Only staff can
  redeem during the booked session; replay cannot spend twice.
- Idempotency keys bind actor, operation and exact normalized arguments. A retry
  returns the original receipt; reusing a key for different arguments rejects.
  Connection errors after commit still require a retry with that same key.
- PostgreSQL row locks serialize one subscription; every path uses subscription,
  booking, token order. Time checks occur after locks, so waiting across the
  cancellation/QR deadline cannot reuse an earlier timestamp. Actor and client
  activation are revalidated and protected by shared locks for each transaction.
  Local3s lock /5s statement limits bound waits. Retry failed transactions using
  the original operation key. Each Store write requires an idle autocommit
  connection and owns its complete transaction.

## Verification

Use only a new disposable local database named `kinder_test`. Tests reject other
database names/remote hosts. They create and remove random schemas containing
synthetic identities, not production schemas or real child/customer information.
The PostgreSQL18 image and workflow actions are pinned by digest/commit.

```sh
python3.12 -m venv .venv
.venv/bin/pip install --require-hashes --only-binary=:all: -r backend/requirements.lock
KINDER_TEST_DATABASE_URL=postgresql://postgres:fixture-only@127.0.0.1:15439/kinder_test \
  .venv/bin/python backend/run_checks.py
```

The dependency lock targets Linux x86_64/CPython3.12 wheels. It covers all three
packages, including the typing dependency, with exact versions and SHA256.
Psycopg3.3.6/psycopg-binary3.3.6: LGPL-3.0; typing-extensions4.16.0: PSF-2.0.
The binary wheel also bundles libpq and cryptographic libraries with their own
notices; retain those notices for redistribution. No dependency hooks/source
builds or arbitrary GitHub agent code are installed by this prototype.

The original44 business checks include actual PostgreSQL transactions, concurrent last-session
booking, concurrent QR consumption, concurrent restoration, rollback after
outbox/audit errors, exact cancellation boundary and timezone conversion. The
gate requires zero skips and writes `accounting-evidence/report.json` with the
tested Git revision and source hashes. That report contains no QR tokens,
passwords, connection strings, customer data or database dump.

## Remaining before a pilot

The93-check backend draft and24-check browser gate include admin-issued passwords, authenticated HTTP accounting
and persisted login throttling. Guardian/child modeling, RU/UZ UI, Android
application, full admin workflows, scheduling capacity, real Telegram outbox delivery and retry,
backups/restore, production HTTPS gateway/migrations and database roles remain unfinished.
No production service, paid resource, automatic public deployment or production
database is configured here. `schema.sql` is an explicit first-install schema;
it refuses existing names and is not an upgrade script. Existing `render.yaml`
is unchanged. A deploy requires a reviewed runnable application and the owner's
specific release approval.

No changes to cancellation for massage/hydromassage, manual completed-visit undo,
subscription expiry/freezing, pricing, billing or capacity are assumed. Those
business policies need a separate design before such endpoints are exposed.
