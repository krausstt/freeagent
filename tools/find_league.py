#!/usr/bin/env python3
"""Find your ESPN league id, extract cookies, and auto-detect your team + draft slot.

    python3 tools/find_league.py --guide                 # just print instructions
    python3 tools/find_league.py --league-id 123456      # public league
    python3 tools/find_league.py --league-id 123456 \\
        --espn-s2 'AEB...' --swid '{XXXX-...}'           # private league

On success it writes ~/.ffdraft.json, locked to your user account, so you never pass the
cookies again.
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ffdraft import config  # noqa: E402
from ffdraft.espn_client import ESPNClient, ESPNError  # noqa: E402

GUIDE = """
FINDING YOUR LEAGUE ID
----------------------
Easiest route on Android:
  1. Open the ESPN Fantasy app, go to your league.
  2. Tap the three-dot menu -> "League Info" -> "Share League".
     (Or open the league in Chrome: fantasy.espn.com/football/league?leagueId=XXXXXXX)
  3. The number after leagueId= is what you need.

If the app will not show a URL, open https://fantasy.espn.com/football/league
in Chrome on your phone while logged in. The address bar shows the leagueId.


EXTRACTING COOKIES (private leagues only)
-----------------------------------------
A private league needs two cookies from a logged-in ESPN session:
espn_s2 (a long URL-encoded string) and SWID (a GUID in curly braces).

Desktop Chrome or Edge (most reliable):
  1. Log in at https://www.espn.com
  2. F12 -> Application -> Storage -> Cookies -> https://www.espn.com
  3. Copy the values of `espn_s2` and `SWID`. Keep the braces on SWID.

Firefox: F12 -> Storage -> Cookies.

Android Chrome has no cookie inspector. Either use a desktop browser once, or
enable remote debugging: connect the phone by USB, enable USB debugging, then
open chrome://inspect on a desktop Chrome and inspect the ESPN tab.

SECURITY: these two cookies are a bearer token for your whole ESPN account.
Anyone who has them can act as you. Do not paste them into a chat, a public
gist, or commit them. This tool stores them in ~/.ffdraft.json with 0600
permissions, outside the repository.
Rotate them by logging out of ESPN everywhere, which invalidates espn_s2.
"""


def detect_team_and_slot(client: ESPNClient, swid: str | None) -> tuple[int | None, int | None]:
    """Match your SWID against league members to find teamId, then the draft slot.

    ESPN's mTeam view lists each team's `owners` as SWID strings, and
    `settings.draftSettings.pickOrder` is the teamId sequence for round one.
    Position in that list is your snake draft slot.
    """
    team_id = None
    draft_slot = None

    data = client.league()
    if swid:
        target = swid.strip().upper()
        if not target.startswith("{"):
            target = "{" + target.strip("{}") + "}"
        for team in data.get("teams", []) or []:
            owners = team.get("owners") or []
            owner_ids = [str(o).upper() if isinstance(o, str) else str(o.get("id", "")).upper()
                         for o in owners]
            if target in owner_ids:
                team_id = team.get("id")
                break

    pick_order = ((data.get("settings", {}) or {}).get("draftSettings", {}) or {}).get("pickOrder")
    if team_id is not None and pick_order:
        try:
            draft_slot = list(pick_order).index(team_id) + 1
        except ValueError:
            draft_slot = None
    return team_id, draft_slot


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--guide", action="store_true", help="print the how-to and exit")
    ap.add_argument("--league-id", type=int)
    ap.add_argument("--season", type=int, default=2026)
    ap.add_argument("--espn-s2")
    ap.add_argument("--swid")
    ap.add_argument("--no-save", action="store_true", help="test only, do not write config")
    args = ap.parse_args()

    if args.guide or not args.league_id:
        print(GUIDE)
        if not args.league_id:
            print("Re-run with --league-id <id> once you have it.")
        return 0

    client = ESPNClient(args.league_id, args.season, args.espn_s2, args.swid)
    try:
        info = client.verify()
    except ESPNError as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        print("\nRun with --guide for cookie extraction instructions.", file=sys.stderr)
        return 2

    print(f"Connected to '{info['league_name']}' ({info['team_count']} teams, "
          f"{info['season']}) via {info['host']}")
    print(f"Authenticated: {info['authenticated']}")

    team_id, draft_slot = None, None
    try:
        team_id, draft_slot = detect_team_and_slot(client, args.swid)
    except ESPNError as exc:
        print(f"note: could not auto-detect team ({exc})")

    if team_id:
        print(f"Detected your teamId: {team_id}")
    else:
        print("Could not auto-detect your teamId. Pass --team-id to ffdraft manually.")
    if draft_slot:
        print(f"Detected your draft slot: {draft_slot}")
    else:
        print("Draft order not published yet. Set --draft-slot once ESPN posts it "
              "(VONA needs it to know when your next pick lands).")

    if not args.no_save:
        creds = config.Credentials(
            league_id=args.league_id, season=args.season,
            espn_s2=args.espn_s2, swid=args.swid,
            team_id=team_id, draft_slot=draft_slot,
        )
        path = config.save(creds)
        print(f"\nSaved to {path}")
        print("Now run: python3 -m ffdraft.cli board")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
