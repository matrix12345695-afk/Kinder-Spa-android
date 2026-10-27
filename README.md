# Kinder Spa 🩵

Kinder Spa is a children's wellness center app and administration system.

## Services (approved scope)
1. **Детский массаж** — children's massage
2. **Гидромассаж** — hydromassage
3. **Бассейн** — swimming pool

Each service has its own description, photos, specialists/instructors where applicable, session duration and optional subscription packages.

## Product architecture
- **Android client app**: username/password issued by admin (no self-registration), available subscriptions, remaining visits, QR code, visit history, service catalog.
- **Private admin web panel**: client and child profiles, service catalog, specialists, photo management, subscription creation/extension/freezing, QR scanning and redemption, audit logs and reports.
- **API and database**: backend on Render, dedicated PostgreSQL `kinder-spa-db`.

## Subscription accounting
- An individual subscription can be limited to a single service category.
- Combined subscriptions can specify allowed categories and per-category visit allowances; do not assume all visits are interchangeable.
- Each QR redemption must record the service category, client, subscription, staff/admin, timestamp, and remaining balances.
- QR tokens must be short-lived and single-use with transactional redemption and anti-replay protection.
- Admin may adjust balances with recorded justification.

## Security
No real customer data, secrets, photos of children, or database passwords in Git. Production rollout requires review of access control, data minimization, backups, and guardians' consent for sensitive information and photos.

## Status
Scaffold / work in progress. Not yet a production-ready app.

## Reviewable backend component

`backend/` contains an isolated PostgreSQL18 accounting prototype and44 automated
checks for subscriptions, one-time QR redemption, pool cancellations and audited
restoration with a superadmin outbox. See [backend/README.md](backend/README.md)
for verified scope and remaining gates. No Android client, HTTP authentication,
Telegram delivery or production deployment is claimed by this increment.
