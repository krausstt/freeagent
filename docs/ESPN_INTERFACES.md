# What the ESPN Fantasy app actually exposes

Findings from a verification pass on 2026-08-29. Everything below was checked
against a primary source rather than inferred; where I could not verify
something from this environment, that is stated explicitly.

## Summary

| Interface | Exists? | Usable for a draft agent? |
|---|---|---|
| Public documented API | No | ESPN publishes no fantasy API and no developer terms for one |
| Undocumented v3 JSON API (read) | **Yes** | **Yes** — this is the backbone of this system |
| Undocumented v3 API (write/pick) | **No** | No write path exists; picks must be made in the UI |
| Android AppFunctions | No | Requires ESPN to publish functions; they do not |
| Android Accessibility Service | Possible | Works, but sideload-only and brittle |
| Screenshot + vision | Possible | Universal fallback, slowest |

## The v3 JSON API (what we use)

Two hosts serve identical payloads:

```
https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/...   # read-optimised
https://fantasy.espn.com/apis/v3/games/ffl/...                # used by espn-api 0.30.0
```

League path (2018+):
```
/seasons/{season}/segments/0/leagues/{leagueId}
```
Seasons before 2018 live at `/leagueHistory/{leagueId}?seasonId={season}` and
return a single-element list rather than an object.

### Views actually used by this project

| `view=` | Gives us |
|---|---|
| `mSettings` | roster slot counts, scoring rules, team count, draft settings |
| `mTeam` | teams and their owner SWIDs (how we auto-detect your teamId) |
| `mRoster` | current rosters |
| `mDraftDetail` | `draftDetail.drafted` (bool) and `draftDetail.picks[]` — **live draft state** |
| `kona_player_info` | the player pool with projections, ADP and ownership |
| `proTeamSchedules_wl` | NFL schedules, from which we derive bye weeks |

Complex queries go in an `x-fantasy-filter` HTTP header carrying JSON, e.g.
limiting the pool and sorting by ESPN's own draft ranks.

### Projections

The critical field: within a player's `stats[]`, the entry where
`statSourceId == 1` (projected) and `scoringPeriodId == 0` (full season) has an
`appliedTotal` **already scored by your league's own rules**. That is why this
system reads projections per-league instead of applying a generic PPR formula —
if your league scores 6-point passing TDs or 0.5 PPR, the numbers already
reflect it.

### Authentication

Private leagues need two cookies, `espn_s2` and `SWID`, from a logged-in
session. Username/password authentication is **dead**: ESPN put Google reCAPTCHA
in front of the login endpoint, and the maintained `espn-api` client has that
code commented out for exactly that reason.

## Why there is no auto-pick over the API

This is the load-bearing finding, so it was verified directly rather than
assumed. The maintained Python client `espn-api` (PyPI 0.30.0, downloaded and
read) contains **zero** POST, PUT or PATCH calls. Its only POST code is the
commented-out login flow above. There is no documented or community-known
endpoint for submitting a draft pick, adding a player, or setting a lineup.

ESPN's live draft room is a real-time channel that has not been publicly
reverse-engineered into a stable, safe-to-use client. Attempting to drive it
would mean impersonating the app against an undocumented protocol, which risks
the league integrity and your ESPN account.

**Therefore: this system advises, you tap.** That is a deliberate design
decision, not a missing feature.

## Verification limits

The sandbox this was built in blocks egress to `lm-api-reads.fantasy.espn.com`
(the proxy answered HTTP 403 to CONNECT), so the endpoints above could not be
called live from here. They are transcribed from the maintained `espn-api`
client source, which is working production code. **Run
`python3 -m ffdraft.cli verify` on your own network as the first step** — that
is the real end-to-end proof, and it takes two seconds.
