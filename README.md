# freeagent

A scoring-exact, simulation-driven fantasy football system for ESPN leagues.
Draft engine, in-season bye-coverage analysis, and a weekly brief that tells
you the handful of things worth doing.

Built for **Schobbetruppe** (ESPN league 461530087) — 12 teams, 0.5 PPR, snake.

## Start here

**Windows:** [`docs/WINDOWS.md`](docs/WINDOWS.md)

```powershell
winget install --id Python.Python.3.12 -e     # then reopen PowerShell
git clone https://github.com/krausstt/freeagent.git
cd freeagent
powershell -ExecutionPolicy Bypass -File deploy\bootstrap.ps1
```

**Android (native APK):** [`docs/APK.md`](docs/APK.md) — built by CI, installed
and auto-updated through Obtainium. Talks to ESPN directly; no backend needed.

**Android (Termux):** [`docs/ANDROID.md`](docs/ANDROID.md) — install Termux from
F-Droid, **not** Google Play (that build is abandoned), then
`bash deploy/termux-setup.sh`.

**Linux / macOS:**

```bash
git clone https://github.com/krausstt/freeagent.git
cd freeagent
bash deploy/bootstrap.sh
```

Either bootstrap runs the offline test suite **before** it touches ESPN or asks
for a credential.

## Why the numbers are trustworthy

**Projections are league-exact.** ESPN returns a season projection already
scored by *your* league's rules. The engine reads that instead of applying a
textbook PPR formula, so a 0.5-PPR or 6-point-passing-TD league changes the
advice automatically.

**Replacement level accounts for flex.** "RB24 is replacement" is wrong whenever
a flex exists, because a flex is filled by whichever position is deepest that
season. Starter demand is resolved by simulating flex allocation against the
real pool — and the flex's *eligible positions* are read from the actual lineup
slot, since a RB/WR flex and a RB/WR/TE flex draw from different pools.

**Availability is simulated jointly.** Exactly N players leave the board before
your next pick, so their fates are negatively correlated. Multiplying
independent survival probabilities overstates how many targets survive.

**Advice is expected regret, not a ranking.** A player worth 5 more than
replacement who will certainly be gone is a worse pick than one worth 3 who will
certainly be there. A sorted list cannot express that.

**It stays quiet when nothing matters.** Lineup swaps under 1.0 projected point
are suppressed; projections are not precise enough to justify churn over noise.

## What's here

| Path | |
|---|---|
| `ffdraft/` | the engine — valuation, availability, bye coverage, brief |
| `tools/poll_espn.py` | fetch the live league → `data/live/latest.json` |
| `tools/weekly_brief.py` | snapshot → this week's decisions |
| `tools/find_league.py` | league + cookie discovery, auto-detects your team id |
| `dashboard/index.html` | season command center, opens in any browser |
| `cockpit/index.html` | live draft board |
| `deploy/` | Windows Task Scheduler + systemd/cron |
| `docs/` | Windows guide, pipeline runbook, ESPN interface findings |

## Tests

22, all offline — no network, no credentials:

```
tests/test_engine.py   11   draft valuation, VORP, Jenks tiers, Monte Carlo
tests/test_season.py    5   bye coverage, flex eligibility, single-slot handling
tests/test_brief.py     6   lineup swaps, noise suppression, bye alerts
```

## Two things that are true

**ESPN has no write API.** Verified against the maintained `espn-api` client
(PyPI 0.30.0), which contains zero POST/PUT/PATCH calls — its only POST code is
a commented-out login flow, disabled when ESPN added reCAPTCHA. This system
reads and advises; picks, waivers and lineup changes stay manual in the app.
See [`docs/ESPN_INTERFACES.md`](docs/ESPN_INTERFACES.md).

**Your ESPN cookies are account-password-equivalent.** They live in
`~/.ffdraft.json`, outside this repo, locked to your user account. Never commit
them, never paste them anywhere. Logging out of ESPN everywhere invalidates them.
