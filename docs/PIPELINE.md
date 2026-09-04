# Automatic polling pipeline

## Where things must run, and why

**The poll has to run somewhere that can reach ESPN. Claude Cloud cannot.**

This was tested, not assumed. From a Claude Cloud session the egress proxy
answers `403 Forbidden` to the CONNECT for both ESPN hosts:

```
connect_rejected: gateway answered 403 to CONNECT (policy denial)
host: lm-api-reads.fantasy.espn.com:443
```

So the split is:

```
   YOUR LINUX SERVER                     GITHUB                  CLAUDE
   ┌────────────────────┐          ┌──────────────┐        ┌──────────────┐
   │ systemd timer /3h  │          │              │        │              │
   │        ↓           │  push    │ data/live/   │  read  │  analysis,   │
   │ poll_espn.py       ├─────────►│ latest.json  ├───────►│  dashboard,  │
   │        ↓           │          │              │        │  start/sit   │
   │ ESPN v3 API        │          │              │        │              │
   └────────────────────┘          └──────────────┘        └──────────────┘
     can reach ESPN                  both can reach          cannot reach
     holds the cookies               this                    ESPN
```

The server does the one job Claude cannot: talk to ESPN. GitHub is the relay,
because both sides can reach it. This also keeps your ESPN session cookies on
hardware you own — they are equivalent to your account password, and putting
them in an ephemeral cloud container is a worse trade than running a cron job.

Reasons to prefer the server beyond the 403:

| | Home server | Claude Cloud |
|---|---|---|
| Can reach ESPN | yes | **no (403)** |
| Cookie storage | your disk, mode 0600 | ephemeral container |
| Runs while you sleep | yes | only when a Routine fires |
| Cost | electricity | session usage |
| Survives container reclaim | n/a | state is lost |

## Do you need a PC?

**Mostly no.** You can do the whole server setup from your phone over SSH
(Termux, JuiceSSH, ConnectBot — anything). One step wants a desktop:

| Step | Phone OK? |
|---|---|
| SSH in, clone, install, run the timer | **yes** |
| Try the league without cookies | **yes** |
| Extract `espn_s2` + `SWID` if the league is private | **desktop browser** |

Android Chrome has no cookie inspector. Do step 4 once on a PC — it takes two
minutes and the cookies last months. (Kiwi Browser on Android can install a
Chrome cookie-viewer extension if you truly have no PC, but it is fiddlier
than just borrowing a laptop.)

---

## Step 1 — SSH to the server

```bash
ssh tobi@your-server
```

## Step 2 — Clone and install

```bash
git clone https://github.com/krausstt/openbrowsertabs.git
cd openbrowsertabs/fantasy
python3 -m pip install --user -r requirements.txt   # only needs `requests`
```

Check Python is 3.10 or newer (`python3 -V`) — the code uses `X | None` type
syntax.

## Step 3 — Try it WITHOUT cookies first

Many ESPN leagues are readable unauthenticated. Test before doing work you may
not need:

```bash
python3 -m ffdraft.cli --league-id 461530087 verify
```

- **Prints league name and team count** → public. Skip step 4 entirely.
- **`ESPN returned 401`** → private. Do step 4.

## Step 4 — Extract cookies (desktop, only if step 3 said 401)

1. Log in at <https://www.espn.com> in Chrome, Edge or Firefox.
2. `F12` → **Application** → Storage → **Cookies** → `https://www.espn.com`
   (Firefox: `F12` → **Storage** → Cookies).
3. Copy the values of **`espn_s2`** (long, URL-encoded) and **`SWID`** (a GUID
   in curly braces — keep the braces).

Then back on the server:

```bash
python3 tools/find_league.py \
  --league-id 461530087 \
  --espn-s2 'AEB...paste...' \
  --swid '{XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX}'
```

That writes `~/.ffdraft.json` at mode 0600 and auto-detects your `teamId` from
your SWID. Use single quotes — `espn_s2` contains `%` and `+`.

> **Security.** These two cookies are a bearer token for your entire ESPN
> account. Never paste them into a chat, a gist, or a systemd unit file (units
> are world-readable). `.gitignore` already blocks `.ffdraft.json`. To revoke,
> log out of ESPN everywhere — that invalidates `espn_s2`.

## Step 5 — Verify, then poll once by hand

```bash
python3 -m ffdraft.cli verify
python3 tools/poll_espn.py            # no --commit yet
cat data/live/latest.json | head -40
```

You should see your roster and the bye-coverage analysis. Exit codes: `0` ok,
`2` ESPN/auth problem, `3` local write problem.

## Step 6 — Let it push to GitHub

Cron has no interactive login, so give git a non-interactive credential. Either
a deploy key:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/ffdraft_deploy -N ''
cat ~/.ssh/ffdraft_deploy.pub
# Add that key at: repo → Settings → Deploy keys → Allow write access
git remote set-url origin git@github.com:krausstt/openbrowsertabs.git
```

…or a fine-grained PAT in `~/.git-credentials` (mode 0600).

Test it:

```bash
python3 tools/poll_espn.py --commit
```

> If `krausstt/openbrowsertabs` is **public**, these snapshots are public too.
> They contain your roster and projections — no credentials — but decide
> whether you want that visible before enabling `--commit`.

## Step 7 — Schedule it

```bash
./deploy/install.sh
```

The installer refuses to schedule anything until `verify` passes, so you never
end up with a timer quietly failing every three hours. Then:

```bash
systemctl list-timers ffdraft-poll.timer     # next run
journalctl -u ffdraft-poll.service -n 50     # the log
sudo systemctl start ffdraft-poll.service    # run now
```

Prefer cron? `deploy/crontab.example` has the equivalent lines, including
optional extra density on NFL Sunday (times in CET/CEST).

## Cadence

Every 3 hours covers the moments that actually matter:

| When | Why |
|---|---|
| Tue night / Wed early | waiver claims process |
| Thu evening | TNF lineup lock |
| **Sun ~17:30 CET** | inactives post ~90 min before the 19:00 CET kickoff |
| Continuous | injury designation changes |

`Persistent=true` means a run missed while the server was off happens on the
next boot rather than being skipped.

## Troubleshooting

| Symptom | Cause |
|---|---|
| `401` from ESPN | cookies expired or the account is not in the league. Redo step 4. |
| `404` | wrong `leagueId`, or the season has not been published yet |
| `no rosterSettings.lineupSlotCounts` | fetched before ESPN published settings; retry later |
| Empty player pool | ESPN rejected the `x-fantasy-filter`; check the season is live |
| Timer never fires | `systemctl status ffdraft-poll.timer`; check `User=` matches the account owning `~/.ffdraft.json` |
| git step warns but poll succeeds | by design — a git failure never loses a snapshot |

## The weekly brief

Once snapshots are landing, the brief turns one into decisions:

```bash
python3 tools/weekly_brief.py            # print it
python3 tools/weekly_brief.py --write    # also save data/live/brief-latest.md
python3 tools/weekly_brief.py --json     # machine-readable
```

It reports only what is actionable this week:

- **Lineup swaps** — anyone on your bench out-projecting a starter, ignoring
  gaps under 1.0 point because projections are not precise enough to justify
  churn over noise.
- **Byes inside two weeks** — flagged while there is still a waiver window,
  separating "cannot fill this slot" from "no injury slack".
- **Injury designations** — starters first, and marked when the status changed
  since the previous snapshot.

Exit code 4 means no snapshot exists yet, so a scheduler can tell "nothing was
polled" apart from "polled and nothing to report".

A Claude Routine fires every Saturday morning, reads the pushed snapshot from
GitHub, and sends the brief as a push notification. It reads the committed
snapshot rather than ESPN, because Claude Cloud cannot reach ESPN. If the
snapshot is more than 48 hours old the brief leads with a stalled-poller
warning instead of confident advice built on stale data.

## What this does not do

It **reads**. ESPN exposes no write endpoint for fantasy actions (verified: the
maintained `espn-api` client has zero POST/PUT/PATCH calls). Waiver claims and
lineup changes stay manual in the app. See `ESPN_INTERFACES.md`.
