# Running it on Android

Two different things can live on your phone. Be clear which you want:

| | Where | Reliability |
|---|---|---|
| **Reading** the dashboard and brief | already works — it's a hosted page | perfect |
| **Running** the poller | Termux | good enough, with caveats |

If you only want to *see* your team, you already have that. Termux is for
running the ESPN poll on the phone itself.

## ⚠️ Install Termux from F-Droid, not Google Play

**The Play Store version is abandoned.** It was frozen in 2020 to satisfy
Android 10 policy changes and is still dead in 2026 — old packages, and it
fails on the process-execution and file-access operations this needs.

Install from **[F-Droid](https://f-droid.org/en/packages/com.termux/)** or the
[GitHub releases](https://github.com/termux/termux-app/releases).

You **cannot** install one over the other — they use different signing keys, so
if you already have the Play version, uninstall it first.

Install two apps from F-Droid:
1. **Termux** — the terminal
2. **Termux:API** — the permissions half, needed for scheduling

## Setup

In Termux:

```bash
pkg update && pkg install -y git
git clone https://github.com/krausstt/freeagent.git
cd freeagent
bash deploy/termux-setup.sh
```

That installs Python, runs the 22 offline tests **before** touching ESPN,
checks whether your league needs cookies, and polls once.

**Cookies on Android:** Chrome for Android has no cookie inspector, so if your
league is private you have to read `espn_s2` and `SWID` on a desktop once. The
script takes them with hidden input. They last months.

## The GUI

You do not need an APK. The dashboard runs as a local web app:

```bash
python tools/serve.py
```

Open **http://127.0.0.1:8765** in Chrome, then **menu → Add to Home screen**.
Android gives it its own icon and launches it without browser chrome — it looks
and behaves like an app.

It serves the dashboard seeded with your *live* snapshot, plus two controls:
**Refresh from ESPN** (re-polls in place) and **Weekly brief**.

One tap to launch it:

```bash
bash deploy/termux-widget-setup.sh
```

Then install **Termux:Widget** from F-Droid and drop the widget on your home
screen. You get two buttons: *FreeAgent Dashboard* and *FreeAgent Poll*.

The server binds to loopback only. `--host 0.0.0.0` exposes it to your whole
network with no authentication — do not do that on public wifi.

## Scheduling

```bash
bash deploy/termux-schedule.sh
```

Uses Android's JobScheduler via `termux-job-scheduler`, takes a wake lock for
the duration of each poll, and refuses to schedule until a real poll succeeds.

```bash
termux-job-scheduler --pending          # what is scheduled
tail -f data/live/poll.log              # watch it run
bash deploy/termux-schedule.sh --cancel
```

## If setup stops at step 2/6

```
ERROR: Installing pip is forbidden, this will break the python-pip package (termux).
```

Termux ships pip as its own `python-pip` package and blocks `pip install
--upgrade pip` outright, because self-upgrading would desync the package
manager from the files on disk. Fixed in `termux-setup.sh` — `git pull` and
re-run. Nothing was damaged; the script just stopped early.

The same rule applies to anything else you run in Termux: install Python
packages with `pip install <pkg>`, but never upgrade pip itself. Use
`pkg upgrade python-pip` if you need a newer one.

## The honest caveat

**Android Doze will defer background jobs.** A 3-hour poll may land late — an
hour or more if the phone has been idle. For this workload that is harmless:
nothing here needs minute precision, and the brief is a weekly read.

Where it *would* matter is Sunday inactives, which post ~90 minutes before
kickoff. If you want that reliably, poll from a machine that stays awake and
read the result on your phone. Battery optimisation exemption for Termux
(*Settings → Apps → Termux → Battery → Unrestricted*) helps but does not fully
defeat Doze.

## Ranking of the options

1. **Always-on Linux box** — most reliable, what `deploy/install.sh` targets
2. **Windows laptop** — Task Scheduler catches up on wake; good if it is on most days
3. **Android/Termux** — always with you, but Doze makes timing loose
4. **Nothing running** — the dashboard still works from a manual poll

Any of 1–3 beats 4. Pick whichever you will actually keep running.
