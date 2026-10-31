# Kinder Spa: staff QR camera flow (review only)

Status: code and isolated browser tests in Draft PR #8. **Not deployed to the live admin API.**

## Operator flow
1. Staff signs in to the dedicated Kinder Spa admin panel over HTTPS.
2. Open **Записи / Yozuvlar**, select a reserved booking, choose **Отметить визит / Tashrifni belgilash**.
3. The camera button appears only on secure origins where the browser exposes both `BarcodeDetector` and `navigator.mediaDevices.getUserMedia`. Camera access occurs only after the staff member clicks the button and grants browser permission.
4. Point the rear camera at the client's QR. The scanner accepts only a URL-safe 43-character opaque token. It fills the existing code field but **does not** send any network request or redeem the visit.
5. Staff checks the selection and clicks **Подтвердить / Tasdiqlash**. The existing authenticated, idempotent API remains the authority for validating token lifetime, booking ownership, consumption and account balance.

## Privacy, safety and fallbacks
- No videos, frames or still images are uploaded, stored, logged or transmitted by the scanner. Native `BarcodeDetector` processes the video locally in the browser.
- On success, dialog close, logout, tab hiding or stale camera-permission response, all tracks stop and the video reference is cleared. No background scanning.
- Unsupported browsers, a denied camera permission and detection errors leave the original manual code entry available. There is no third-party JS dependency and no blanket camera permission at page load.
- Every user-facing scanner status is available in RU and UZ. The input remains editable.
- The server, not the scanner, decides whether a booking is valid. A valid-looking 43-character string does not authorize attendance.

## Acceptance
The real Chromium/PostgreSQL browser suite includes a synthetic camera/decoder test proving that scanning populates a one-time token **without auto-redemption**, stops its stream, and only the staff submit action records a visit. Another test simulates a camera permission granted after the dialog has closed and verifies that the late stream is stopped. Existing browser tests cover manual one-time QR entry.

This does not establish support on all real mobile browsers or certify a real physical camera. Conduct a device-specific acceptance test on iOS and Android before production release.
