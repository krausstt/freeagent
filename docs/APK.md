# Native Android app

An APK you install through [Obtainium](https://github.com/ImranR98/Obtainium),
which tracks GitHub Releases and updates automatically.

## Why it is built in CI, not locally

The Android SDK and every AndroidX artifact live on `dl.google.com`, which is
blocked by the network policy of the environment this project is developed in
(403 at the egress proxy, verified). GitHub's runners ship the SDK, so the build
happens there. **The consequence is honest: the first CI runs are the first real
compile this code has ever had.** Expect to iterate through a failure or two.

## What it actually is

A WebView around the same dashboard, with ESPN fetched natively in Kotlin.

That last part is the whole reason a native app helps. ESPN sends no CORS
headers, so a page loaded from `file://` cannot call the API from JavaScript.
Kotlin has no such restriction. **So the app needs no backend at all** — the
phone talks to ESPN directly, the same way Termux does.

Deliberately dependency-free: a plain `Activity`, a `WebView`, and
`HttpURLConnection`. No Compose, no AppCompat, no OkHttp. Every library is a
version that can fail to resolve in CI, and none of them are needed here.

The WebView asset is generated at build time from `dashboard/index.html`, so the
dashboard stays the single source of truth and an improvement there reaches the
app with no manual copying.

## Build it

Actions → **Android APK** → *Run workflow*. That produces a Release with the APK
attached.

Every push touching `android/` or `dashboard/` also builds (without releasing),
so breakage surfaces on the commit that caused it.

## Signing, and why it matters for Obtainium

Android refuses to update an app when the signing key changes, and CI generates
a throwaway debug key on every run. So without a stable key, **every update is
an uninstall and a reinstall**. A debug APK is also marked `debuggable`, which
lets any other app on the phone read what this one stores — reason enough not to
put ESPN credentials in one.

The key is created once, by CI, and stored in this repository **encrypted**.
The only thing you have to type is one password.

### Setup, once

1. Repository → **Settings → Secrets and variables → Actions → New secret**
   - Name: `KEYSTORE_PASSPHRASE`
   - Value: any password you choose. Write it down — losing it means no further
     update can ever install over the app, only a reinstall.
2. **Actions → Android APK → Run workflow**, tick
   **"One time only: create the app signing key"**, run it.

CI then generates a 4096-bit RSA key with `keytool`, encrypts it with that
passphrase (`openssl enc -aes-256-cbc -pbkdf2 -iter 200000`), commits
`android/release.jks.enc`, and signs the APK with it. The private key exists in
the clear only on the runner, for the length of one job.

Every later run decrypts the same key, so Obtainium updates install in place.

### Why not a base64 secret

The usual recipe pastes the whole keystore into `KEYSTORE_BASE64`. That means
generating it on a machine with a JDK and pasting 4 KB of base64 into a form —
awkward from a phone, which is where this project is actually administered. An
encrypted blob in the repo needs one short secret instead, and is no less safe:
the blob is useless without the passphrase.

### If the key is ever lost or rotated

The bootstrap step refuses to overwrite an existing `android/release.jks.enc`,
because replacing it silently would break updates for an already-installed app.
To rotate deliberately: delete that file, update the secret, uninstall the app
from the phone, and bootstrap again.
