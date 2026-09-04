#!/usr/bin/env bash
# One-shot setup + proof of concept. Run on any machine that can reach ESPN.
#
#   bash deploy/bootstrap.sh
#
# Prompts for your ESPN cookies without echoing them and without putting them
# in your shell history, writes ~/.ffdraft.json at mode 0600, verifies the
# connection, polls once, and prints your first weekly brief.
set -euo pipefail

LEAGUE_ID="${ESPN_LEAGUE_ID:-461530087}"
SEASON="${ESPN_SEASON:-2026}"
cd "$(dirname "${BASH_SOURCE[0]}")/.."

say() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }

say "1/6  Checking Python"
python3 - <<'PY'
import sys
if sys.version_info < (3, 10):
    sys.exit(f"Python 3.10+ required (X | None syntax); you have {sys.version.split()[0]}")
print(f"Python {sys.version.split()[0]} OK")
PY

say "2/6  Installing dependencies"
python3 -m pip install --user --quiet -r requirements.txt
python3 -c "import requests; print('requests', requests.__version__)"

say "3/6  Is the league readable without cookies?"
if python3 -m ffdraft.cli --league-id "$LEAGUE_ID" --season "$SEASON" verify 2>/dev/null; then
  echo "League is public. No cookies needed."
  NEED_COOKIES=0
else
  echo "League is private (401). Cookies required."
  NEED_COOKIES=1
fi

if [[ "$NEED_COOKIES" == "1" ]]; then
  say "4/6  ESPN cookies"
  echo "From a logged-in espn.com tab: F12 -> Application -> Cookies -> https://www.espn.com"
  echo "Input is hidden and never enters your shell history."
  read -rs -p "  espn_s2: " ESPN_S2; echo
  read -rs -p "  SWID (with braces): " ESPN_SWID; echo
  [[ -n "$ESPN_S2" && -n "$ESPN_SWID" ]] || { echo "Both values are required." >&2; exit 1; }
  ESPN_S2="$ESPN_S2" ESPN_SWID="$ESPN_SWID" \
    python3 tools/find_league.py --league-id "$LEAGUE_ID" --season "$SEASON" \
      --espn-s2 "$ESPN_S2" --swid "$ESPN_SWID"
  unset ESPN_S2 ESPN_SWID
else
  say "4/6  Saving league config (no cookies needed)"
  python3 tools/find_league.py --league-id "$LEAGUE_ID" --season "$SEASON"
fi

chmod 600 "$HOME/.ffdraft.json" 2>/dev/null || true

say "5/6  Polling ESPN once"
python3 tools/poll_espn.py

say "6/6  Your first weekly brief"
python3 tools/weekly_brief.py --write || true

cat <<'DONE'

------------------------------------------------------------------
Proof of concept complete.

  data/live/latest.json      the raw snapshot
  data/live/brief-latest.md  the brief

Next, to make it recurring:
  ./deploy/install.sh        systemd timer, every 3 hours

This copy is standalone - no git repository required. If you later put it in a
repo and want Claude to read your snapshots automatically, add --commit:
  python3 tools/poll_espn.py --commit
------------------------------------------------------------------
DONE
