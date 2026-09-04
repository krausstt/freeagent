#!/data/data/com.termux/files/usr/bin/bash
# Termux (Android) setup. Android is not a normal Linux box, so this differs
# from deploy/bootstrap.sh in three ways that matter:
#
#   * packages come from `pkg`, not apt
#   * there is no systemd, so scheduling uses Android's JobScheduler
#   * Doze will defer background work; we ask for a wake lock and accept drift
#
# Run:  bash deploy/termux-setup.sh
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
LEAGUE_ID="${ESPN_LEAGUE_ID:-461530087}"
SEASON="${ESPN_SEASON:-2026}"

say() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }

if [[ ! -d /data/data/com.termux ]]; then
  echo "This script is for Termux on Android. On a PC use deploy/bootstrap.sh" >&2
  exit 1
fi

say "1/6  Termux packages"
pkg update -y >/dev/null 2>&1 || true
pkg install -y python git termux-api

say "2/6  Python dependency"
# No --user here: Termux's prefix is already user-owned, and the flag warns.
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r requirements.txt
python -c "import requests, sys; print('requests', requests.__version__, '| python', sys.version.split()[0])"

say "3/6  Offline test suite (no network, no credentials)"
python tests/test_engine.py
python tests/test_season.py
python tests/test_brief.py

say "4/6  Does the league need cookies?"
if python -m ffdraft.cli --league-id "$LEAGUE_ID" --season "$SEASON" verify 2>/dev/null; then
  echo "Public league - no cookies needed."
  python tools/find_league.py --league-id "$LEAGUE_ID" --season "$SEASON"
else
  echo
  echo "Private league. You need espn_s2 and SWID from a logged-in espn.com session."
  echo "Android Chrome has no cookie inspector, so get them on a desktop once."
  echo "Input is hidden and stays out of your shell history."
  read -rs -p "  espn_s2: " S2; echo
  read -rs -p "  SWID (with braces): " SWID; echo
  [[ -n "$S2" && -n "$SWID" ]] || { echo "Both values are required." >&2; exit 1; }
  python tools/find_league.py --league-id "$LEAGUE_ID" --season "$SEASON" \
    --espn-s2 "$S2" --swid "$SWID"
  unset S2 SWID
fi

say "5/6  Polling ESPN once"
python tools/poll_espn.py

say "6/6  Your first weekly brief"
python tools/weekly_brief.py --write || true

cat <<'DONE'

------------------------------------------------------------------
Running on Android.

  data/live/latest.json      the snapshot
  data/live/brief-latest.md  the brief

Read the brief any time:
  cd ~/freeagent && python tools/weekly_brief.py

Schedule it every 3 hours (needs the Termux:API app from F-Droid):
  bash deploy/termux-schedule.sh

Honest caveat: Android Doze defers background jobs. A 3-hour poll may land
late, which is harmless here. If you want reliable timing, run the poller on
a machine that stays awake and just read the brief on your phone.
------------------------------------------------------------------
DONE
