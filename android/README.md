# Kinder Spa native Android review client

Java 17, platform Android views, Android 8+ (minSdk26 / targetSdk36), RU/UZ.
This is a review component, not a production release or a connection to a live
customer database. Admin-issued credentials are required; self-registration,
new appointment creation and unapproved capacity rules are not implemented.

## Included flow

- Login, own upcoming appointments, subscriptions and visit history (bounded pagination).
- Pool cancellation with the existing backend deadline/refund policy and an
  idempotency key retained across uncertain responses in the current session.
- A real ZXing QR image containing only a short-lived opaque one-time token.
  Server-relative expiry is reduced by request time and measured monotonically;
  hiding the app clears the QR bitmap. Redemption belongs to the staff panel.
- RU/UZ switching, client-only access, logout and session expiry.

Tokens and appointment records live only in process memory; only language is
stored in preferences. Activity recreation can retain the process session;
process death requires login. Backup, cleartext HTTP, automatic redirects and
credential autofill are disabled in review builds. The review window and QR
dialog use FLAG_SECURE. The app requests INTERNET only, without camera or
storage permissions. No API keys or real customer data belong in this tree.

## Builds and test isolation

Install Java17 and the licensed Android SDK platform36 / build-tools36.0.0.
Set ANDROID_HOME or an untracked android/local.properties sdk.dir. From repo root:

```sh
python android/gradle.py :app:assembleReviewDebug :app:testReviewDebugUnitTest :app:lintReviewDebug
```

Gradle8.13 is downloaded from its official distribution with a pinned SHA256.
AGP8.13.2, runtime/test dependencies, application dependency locks and strict
SHA256 verification metadata are checked in. Updating locks or hashes is a
separate dependency review, not a CI task. ZXingCore3.5.3 is Apache2; the full
upstream license is bundled and available in the app.

`reviewDebug` (`uz.kinderspa.client.review`) is signed with a disposable debug
key. Its default origin is https://example.invalid and login is disabled.
A reviewed HTTPS API may be bound at build time using
`-PkinderApiOrigin=https://reviewed-host.example`; there is no runtime URL editor.
No signing keys, real backend binding, Play upload or production publication are
included. Fixture release builds and unconfigured review release tasks fail.

`fixtureDebug` is a different app ID and allows HTTP only to emulator host
10.0.2.2. It connects to a localhost-only synthetic PostgreSQL fixture, never a
production endpoint. Its screenshot protection exception is only for recording
synthetic UI evidence. Fixture APKs are not distribution artifacts.

`.github/workflows/kinder-android.yml` requires a real build, lint, 16 JVM checks,
10 fixture device scenarios and one review-device privacy check on API35. It
then verifies the actual APK permissions, signature and SDK manifest and six
synthetic screenshots before emitting native-report.json with source/APK hashes.
Only a passing acceptance artifact establishes those device results. Screenshot
artifacts never contain a QR token. Backend checks separately require95 API/core
and24 staff-panel browser scenarios. Android8 device coverage and accessibility
audits on physical devices remain future work; minSdk is not such evidence.
