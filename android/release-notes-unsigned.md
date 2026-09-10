Install with [Obtainium](https://github.com/ImranR98/Obtainium): add
`https://github.com/krausstt/freeagent` as an app.

**What it is.** The FreeAgent season dashboard as a native app. It talks to the
ESPN API directly from the phone — no backend, no server, nothing to keep
running. ESPN sends no CORS headers, so a web page cannot make that call, which
is the entire reason this is an app rather than a bookmark.

## Read this before installing

This build is **debug-signed**, with two consequences worth knowing:

1. **Updates will not install over it.** CI generates a throwaway signing key on
   every run, and Android refuses an update when the key changes. Each new
   version means uninstall, then reinstall, losing whatever the app has stored.
2. **It is marked debuggable.** Any other app on the phone can attach to the
   process and read what this one keeps, including ESPN credentials if you enter
   any. The Schobbetruppe league is public, so the app works without them — but
   do not put credentials into a debug build.

Fixing both takes one repository secret. See `docs/APK.md`.
