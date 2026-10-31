# Kinder Spa UI preview (synthetic data only)

Public review URL: https://kinder-spa-preview.onrender.com

This is a **static, completely offline demo**, created for the project owner to inspect the Russian/Uzbek interface on mobile and desktop. It is not the production administrator panel, API, or a clinical record system.

- Only fabricated client labels (Client #001 etc.), sample subscriptions and sample appointments are included.
- All actions run in browser memory only; reload discards changes.
- No login, real accounts, passwords, database, API requests, QR redemption, Telegram delivery, payments, medical histories or tracking are connected.
- Preview must never be presented as a customer-ready or transactional product.
- Render service: `kinder-spa-preview` (`srv-dbiuhvjbc2fs73bbvohg`), static/free tier with `autoDeploy=no`, Git branch `review/kinder-db-ci-and-restore-gates-20261031`.
- Source: `preview/index.html`. Browser CI: `ci/verify_preview.py`, included in the backend accounting GitHub Action.
- After pushing changes to this branch, the public preview stays at its previous version until an explicitly triggered static deploy.
- Production PostgreSQL schema, role credentials, backup and release approvals remain independent.
