# Handoff

State of the system for whoever picks this up next. Written 2026-09-10 — the
day the season starts.

Everything below is either verifiable from this checkout or flagged as
unverified. Where something has never run against live ESPN data, it says so.

## First five minutes

```bash
git clone https://github.com/krausstt/freeagent && cd freeagent
for t in tests/test_*.py; do echo "$t"; python3 "$t" | tail -1; done
python3 tools/league_map.py --from tests/sample_league.raw.json --team-id 1
```

48 tests, no network, no credentials, no dependencies outside the stdlib. If
they pass, the engine is intact and you can work offline. The league map call
runs against a **synthetic** payload (`tests/make_sample_league.py` generates
it) — never read a conclusion about the real league off that file.

## The league

| | |
|---|---|
| League | Schobbetruppe, `leagueId` 461530087, public |
| Format | 12 teams, 0.5 PPR, snake, drafted from slot 7 |
| Team | TheRealTobi (`--list-teams` resolves the id; no SWID needed) |
| Lineup | 1 QB, 2 RB, 2 WR, 1 TE, 1 RB/WR flex, 1 D/ST, 1 K, 6 bench |
| Season | starts 2026-09-10 |

Roster as drafted: `data/roster_2026.json`, read off the app by screenshot.
Its `w1` figures are **week-1** projections (117.5 starting total), not season
totals.

## Why the architecture looks like this

Two constraints, both measured rather than assumed:

**ESPN has no write API.** Verified against `espn-api` 0.30.0, which contains
zero POST/PUT/PATCH calls. So the system advises; the human executes in the
app. Every output is phrased as a decision for Tobi to make, not an action
taken.

**Claude Cloud cannot reach ESPN.** `lm-api-reads.fantasy.espn.com` returns 403
through the agent proxy, as does `dl.google.com`. Tobi's phone and laptop reach
ESPN fine. GitHub is reachable from both. Hence:

```
phone/laptop  --poll-->  ESPN  --snapshot-->  GitHub  --read-->  Claude
                                    GitHub Actions  --build-->  APK
```

A cloud agent can therefore reason about the league but cannot fetch it. Do not
spend time debugging the 403; use `--from` with a saved payload instead.

## Built and tested offline

| Module | What it settles |
|---|---|
| `ffdraft/valuation.py`, `board.py`, `vona.py` | VORP, Fisher-Jenks tiers, survival Monte Carlo |
| `ffdraft/roster.py` | optimal lineup, marginal starter value, flex allocation |
| `ffdraft/season.py` | bye coverage; single-slot positions (D/ST, K) excluded from "thin" |
| `ffdraft/brief.py` | weekly lineup swaps, gains under 1.0 suppressed as noise |
| `ffdraft/journal.py` | decision quality vs outcome quality, append-only |
| `ffdraft/league_map.py` | **new** — 12-way positional strength, replacement level, trade search |

## Built, never run against live ESPN data

- `tools/poll_espn.py` — `data/live/` is empty; **no snapshot has ever been
  captured**. This is the biggest single unknown in the repo. The parser is
  exercised only against hand-built payloads.
- `tools/league_map.py` without `--from`.
- The Android app's native fetch bridge. The data *transform* is verified via a
  mocked bridge (it reproduces 117.5 and flags weeks 9 and 14); the actual
  `HttpURLConnection` call to ESPN has never been observed succeeding.

## Not built

- Journal sync between the Python side and the app's `SharedPreferences` store.
- Waiver competition model (who else needs this player, and what they'll bid).
- Playoff-week planning (weeks 15–17 opponents and their byes).
- Scarcity map wiring into the poller snapshot, the weekly brief, and the
  dashboard. The map currently only exists as a CLI.

## Next steps, in the order they pay off

1. **Snapshot all 12 rosters in the poller.** `tools/poll_espn.py` currently
   keeps only Tobi's roster, so the scarcity map cannot run from a snapshot and
   nothing downstream can use it. `client.league()` already returns
   mSettings+mTeam+mRoster+mStandings in one call — the data is being fetched
   and thrown away. Add the raw payload (or a parsed 12-team block) to the
   snapshot, then feed `scarcity_map()` from it.
2. **Surface the map in the weekly brief and the dashboard.** The single most
   actionable line it produces is "you are Nth of 12 at X" plus the trade ideas.
   Neither surface shows it yet.
3. **Waiver competition.** `kona_league_communication` with
   `ACTIVITY_TRANSACTIONS` returns per-manager timestamps and FAAB bids. Worth
   noting the sample-size limit: 15–30 transactions per manager in season 1
   supports 2–3 gross parameters, not a behavioural model.
4. **Playoff-week planning**, once weeks 15–17 are within projection range.

## Blocked on Tobi

- **APK signing.** `.github/workflows/android.yml` builds a debug APK today
  (829 KB in 94s, run 34043594011). A release APK for Obtainium needs four repo
  secrets — `KEYSTORE_BASE64`, `KEYSTORE_PASSWORD`, `KEY_ALIAS`, `KEY_PASSWORD`
  — generated locally with `keytool`. Android refuses updates across signing
  keys, so whichever keystore is used first is permanent. See `docs/APK.md`.
- **Cookie rotation.** Live `espn_s2` / `SWID` values were pasted into a chat
  transcript. They are password-equivalent for the ESPN account. They were never
  written to disk and a secret scan confirms they never entered this repo, but
  rotating them (log out of ESPN everywhere) is still outstanding.
- **Snowflake MCP** needs authorization in claude.ai connector settings before
  any session can use it.

## Traps already paid for

Each of these was a real bug, caught by a test or by Tobi, and each is the kind
that produces a plausible-looking wrong answer rather than a crash.

- **Two projection horizons.** ESPN returns the season total
  (`scoringPeriodId: 0`) and the current week (`scoringPeriodId: N`) in the same
  `stats` list, distinguished only by that field, differing by ~17x. `Player`
  has `proj_points` (week) and `proj_season` for this reason. They must never
  share a field — that is how a 117-point lineup rendered as 2158.9.
- **Flex eligibility is per-slot.** Slot 3 is RB/WR; slot 23 is RB/WR/TE.
  Counting a TE toward a slot-3 pool overstated bye coverage in week 7 as +2
  when it was actually 0. Read `FLEX_ELIGIBILITY[slot]`, never assume.
- **Single-slot positions sit at +0 by design.** D/ST and K have one starter
  and no flex, so flagging them as "thin" every week buried the two real holes.
- **An empty starting slot is not neutral.** Scoring it 0.0 makes a missing
  kicker read identically to a replacement-level one. It scores `-replacement`.
- **A legal lineup is not a good trade.** Trading a starter away still leaves a
  legal lineup, so a naive gain calculation ranked "McCaffrey for a defence"
  first. Offers come from the bench only.
- **`statSourceId: 0` is points already scored**, not a projection.
- **Termux forbids `pip install --upgrade pip`** and F-Droid is the only working
  source. `deploy/termux-setup.sh` is idempotent for this reason.
- **PowerShell 5.1 has no `&&`.** Windows scripts under `deploy/` are native
  PowerShell; do not ship `unzip`, `bash` or `python3` invocations there.
- **`chmod(0o600)` is a no-op on NTFS.** `config.restrict_permissions()` uses
  `icacls` on Windows and reports what it actually applied.
- **`secrets` is not a context available in a step `if:`.** Hoist it to
  job-level `env:` — see `.github/workflows/android.yml`.

## What this system is for

Not prediction. Decision quality: making the call that was right given what was
knowable, and being able to tell that apart from the call that happened to work.
`ffdraft/journal.py` keeps decisions and outcomes in separate append-only files
so the record is never rewritten after the fact, and reports process first.
`docs/strategy/edge.html` is the longer argument.
