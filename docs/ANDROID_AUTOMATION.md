# Android automation paths for ESPN Fantasy — what is real in 2026

You asked to explore AppFunctions, accessibility hacks, and screenshots. Here is
what each is actually worth, checked in August 2026. **None of these are built
in this repo** — you chose the advisory cockpit, which needs none of them. This
is the map for if you want to go further later.

## 1. AppFunctions — not viable for controlling ESPN

`androidx.appfunctions` reached `1.0.0-alpha10` on 2026-07-01. Still alpha, no
beta or stable. Requires Android 16+. Gemini integration remains a private
preview limited to trusted testers.

The blocker is structural, not maturity: **AppFunctions is a publishing
mechanism.** An app declares functions it is willing to expose; an agent can
then call them. ESPN Fantasy publishes none. No amount of alpha-to-stable
progress changes that — the decision is ESPN's, not Google's.

Where it *would* help: if you build your own companion app, it can publish
AppFunctions so the Android assistant can query *your* draft board by voice.
That is a genuinely nice future feature and it does not depend on ESPN at all.

## 2. Shizuku — the strongest no-root option

Shizuku runs a privileged process via ADB (or root) and lets ordinary apps call
system APIs, including UI hierarchy dumps and synthetic taps. Latest stable is
13.6.0 (r1091). On Android 13+ it can auto-start over trusted Wi-Fi without
root, which removes the usual "re-pair after every reboot" annoyance.

Trade-offs: you must re-authorise after a reboot unless the trusted-Wi-Fi path
works on your device; and driving another app's UI is inherently brittle
against layout changes.

## 3. Accessibility Service — most robust, distribution-limited

A sideloaded app with `BIND_ACCESSIBILITY_SERVICE` can read ESPN's view tree and
dispatch gestures. This is the most reliable way to *read* live draft state off
the screen, and it survives cosmetic layout changes better than pixel matching.

The catch is policy: Google Play restricts accessibility APIs to apps that
genuinely serve users with disabilities, so this is sideload-only. Fine for
personal use, not distributable.

## 4. Screenshots + visual reasoning — universal fallback

MediaProjection capture, or `adb exec-out screencap` from a laptop, feeding
frames to a vision model. Works against anything, including obfuscated or
Canvas-rendered UI. Slowest, most expensive per action, and least precise for
tapping exact coordinates. Worth having as a fallback, not as a primary path.

## Recommendation

For drafting: **none of these.** The ESPN read API already gives you live draft
state within seconds, which is the hard part. The remaining step — tapping a
player you have already decided on — takes you two seconds and carries zero
account risk. Automating it buys nothing and risks a lot.

Where automation genuinely pays off is **in-season, not draft day**: waiver
claims at 3am, lineup locks you would otherwise sleep through, injury-driven
swaps. Those are repetitive, time-boxed, and happen when you are not looking.
If you want that after the draft, Shizuku is where I would start.
