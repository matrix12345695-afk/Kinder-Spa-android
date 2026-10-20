# Kinder Spa security checklist

- Repository is currently public. Change visibility to private before adding any proprietary material.
- Never commit admin passwords, database URLs, JWT secrets, photo uploads, or customer data.
- Parent/guardian accounts only. Do not expose children's medical records in profile or QR payload.
- Server must validate QR expiration and one-time redemption inside a database transaction.
- Add brute-force protection, admin password rotation, audit logs and backups before launch.
- Render free resources are suitable for prototype tests only; paid upgrades require owner approval.
