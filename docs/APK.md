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

Android refuses to update an app when the signing key changes. A debug APK is
signed with a key CI regenerates each run, so **debug builds install but can
never be updated in place** — you would have to uninstall and lose local state.

For upgradeable builds, create a keystore once and add it as repository secrets:

```bash
keytool -genkeypair -v -keystore release.jks -keyalg RSA -keysize 4096 \
  -validity 10000 -alias freeagent
base64 -w0 release.jks    # paste as the KEYSTORE_BASE64 secret
```

Repository → Settings → Secrets and variables → Actions:

| Secret | |
|---|---|
| `KEYSTORE_BASE64` | the base64 above |
| `KEYSTORE_PASSWORD` | the store password |
| `KEY_ALIAS` | `freeagent` |
| `KEY_PASSWORD` | the key password |

Keep `release.jks` somewhere safe and out of the repo — `.gitignore` blocks
`*.jks`, but losing it means never being able to update the installed app again.

## Install

1. Install [Obtainium](https://github.com/ImranR98/Obtainium/releases) (F-Droid or GitHub).
2. Add app → `https://github.com/krausstt/freeagent`
3. Obtainium finds the Release and installs the APK, then offers updates.

On first launch the app asks for your league ID and team ID. Schobbetruppe is
public, so the cookie fields stay empty.

## Where the server still helps

The app covers reading and deciding on your phone. A machine that stays awake
still adds two things the phone cannot:

- **Scheduled polling** while the phone sleeps, so the Saturday brief has data.
- **A durable decision log**, pushed to git rather than living in one device's
  app storage.

Neither is required for the app to work. See `docs/PIPELINE.md`.
