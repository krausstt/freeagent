#!/usr/bin/env python3
"""Where every roster in the league is strong, where it is thin, and what that
makes tradeable.

The one view ESPN structurally cannot show you: it renders your team, and your
opponent's team this week, and never the twelve-way comparison. One public API
call carries all of it.

    python3 tools/league_map.py                     # the full map + trade ideas
    python3 tools/league_map.py --position RB       # one position, all 12 teams
    python3 tools/league_map.py --json              # machine-readable
    python3 tools/league_map.py --from raw.json     # offline, from a saved payload
    python3 tools/league_map.py --save-raw raw.json # keep the payload for later

Numbers are season-long projected points above replacement unless --basis week.
Replacement is measured from the league's own rosters, not the waiver wire: the
question a trade answers is "what would I start instead".

Exit codes: 0 ok, 2 ESPN/auth or data failure, 3 local write failure.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from ffdraft import config  # noqa: E402
from ffdraft.constants import SCORABLE  # noqa: E402
from ffdraft.espn_client import ESPNClient, ESPNError  # noqa: E402
from ffdraft.league_map import (  # noqa: E402
    LeagueMap, parse_all_teams, scarcity_map, trade_candidates,
)
from ffdraft.models import parse_league_config  # noqa: E402


def _bar(value: float, scale: float, width: int = 11) -> str:
    """A signed bar around a zero midpoint, so above/below median reads at a glance."""
    half = width // 2
    n = 0 if scale <= 0 else max(-half, min(half, round(value / scale * half)))
    if n >= 0:
        return " " * half + "|" + "#" * n + " " * (half - n)
    return " " * (half + n) + "#" * -n + "|" + " " * half


def render(lmap: LeagueMap, my_team_id: int | None, top_trades: list) -> str:
    lines: list[str] = []
    horizon = "season" if lmap.basis == "season" else "this week"
    lines.append(f"LEAGUE SCARCITY MAP  ({len(lmap.profiles)} teams, "
                 f"{horizon} projected points above replacement)")
    lines.append("replacement level: " + "  ".join(
        f"{pos} {lmap.replacement.get(pos, 0):.0f}" for pos in SCORABLE))
    lines.append("")

    mine = lmap.profile(my_team_id) if my_team_id else None
    if mine:
        lines.append(f"YOU -- {mine.name}   starting lineup "
                     f"{mine.starting_points:.1f} projected ({horizon}, raw points)")
        lines.append(f"  {'pos':<5} {'rank':>5} {'vs median':>10} {'surplus':>8}  "
                     f"{'held':>4}  shape")
        spread = max((abs(s.vs_median) for s in mine.positions.values()), default=1.0)
        for pos in SCORABLE:
            s = mine.positions.get(pos)
            if not s:
                continue
            flag = "  <-- hole" if s.holes else ""
            lines.append(
                f"  {pos:<5} {s.rank:>2} /{len(lmap.profiles):<2} "
                f"{s.vs_median:>+10.1f} {s.surplus:>8.1f}  {s.count:>4}  "
                f"{_bar(s.vs_median, spread)}{flag}")
        lines.append("")
        behind = mine.below_median()
        if behind:
            lines.append("  behind the field: " + ", ".join(
                f"{s.position} (rank {s.rank}, {s.vs_median:+.0f})" for s in behind[:3]))
        else:
            best_of = mine.weakest(1)[0]
            lines.append(f"  no position behind the field median; least strong is "
                         f"{best_of.position} (rank {best_of.rank}, "
                         f"{best_of.vs_median:+.0f})")
        surplus = ", ".join(f"{s.position} (+{s.surplus:.0f})"
                            for s in mine.surplus_positions()) or "none above the bar"
        lines.append(f"  tradeable surplus: {surplus}")
        lines.append("")

    for pos in SCORABLE:
        standings = lmap.standings(pos)
        if not standings:
            continue
        lines.append(f"{pos}")
        for prof in standings:
            s = prof.positions[pos]
            marker = " *" if prof.team_id == my_team_id else "  "
            note = f"  (+{s.surplus:.0f} on the bench)" if s.surplus >= 3 else ""
            hole = "  NO STARTER" if s.holes else ""
            lines.append(f" {marker}{s.rank:>3}. {prof.name[:30]:<30} "
                         f"{s.starting:>+8.1f}{note}{hole}")
        lines.append("")

    if top_trades:
        lines.append("TRADE IDEAS  (both sides must gain, measured by re-optimising "
                     "both lineups)")
        for i, t in enumerate(top_trades, start=1):
            lines.append(f"  {i}. send {t.give.name} ({t.give.position}) to "
                         f"{t.partner_name}   [{t.argument}]")
            lines.append(f"     for  {t.get.name} ({t.get.position})")
            warn = ("   <-- they gain "
                    f"{t.their_edge:.0f}x more; check what you are giving up"
                    if t.their_edge >= 3 else "")
            lines.append(f"     you +{t.my_gain:.1f}   them +{t.their_gain:.1f}   "
                         f"mutual floor +{t.mutual:.1f}{warn}")
            lines.append(f"     {t.rationale}")
            if t.argument == "depth":
                lines.append("     their starters do not change: the pitch is "
                             "that they upgrade a bench spot they cannot use")
        lines.append("")
        lines.append("  ESPN cannot send these for you -- propose them in the app.")
    elif my_team_id:
        lines.append("TRADE IDEAS: none. No swap of your surplus for your needs "
                     "improves both lineups.")
    return "\n".join(lines)


def to_json(lmap: LeagueMap, my_team_id: int | None, trades: list) -> dict:
    return {
        "basis": lmap.basis,
        "myTeamId": my_team_id,
        "replacement": {k: round(v, 1) for k, v in lmap.replacement.items()},
        "teams": [
            {
                "teamId": p.team_id, "name": p.name,
                "startingPoints": p.starting_points,
                "positions": {
                    pos: {
                        "starting": s.starting, "surplus": s.surplus,
                        "count": s.count, "holes": s.holes,
                        "rank": s.rank, "vsMedian": s.vs_median,
                    }
                    for pos, s in p.positions.items()
                },
            }
            for p in lmap.profiles
        ],
        "trades": [
            {
                "partnerId": t.partner_id, "partnerName": t.partner_name,
                "give": {"id": t.give.player_id, "name": t.give.name,
                         "position": t.give.position},
                "get": {"id": t.get.player_id, "name": t.get.name,
                        "position": t.get.position},
                "myGain": t.my_gain, "theirGain": t.their_gain,
                "mutual": t.mutual, "theirEdge": t.their_edge,
                "argument": t.argument, "rationale": t.rationale,
            }
            for t in trades
        ],
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--from", dest="src", help="read a saved mTeam+mRoster payload")
    ap.add_argument("--save-raw", help="write the fetched payload here")
    ap.add_argument("--basis", choices=("season", "week"), default="season")
    ap.add_argument("--week", type=int, default=0,
                    help="scoring period for --basis week (default: ESPN's current)")
    ap.add_argument("--position", help="show only this position's league table")
    ap.add_argument("--team-id", type=int, help="override which team is yours")
    ap.add_argument("--trades", type=int, default=5, help="how many ideas to show")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    creds = config.load()
    my_team_id = args.team_id or creds.team_id

    try:
        if args.src:
            with open(args.src, encoding="utf-8") as fh:
                league_json = json.load(fh)
            cfg = parse_league_config(
                league_json, creds.league_id or 0, creds.season)
        else:
            if not creds.league_id:
                print("ERROR no league id. Set ESPN_LEAGUE_ID or run "
                      "tools/find_league.py", file=sys.stderr)
                return 2
            client = ESPNClient(creds.league_id, creds.season,
                                creds.espn_s2, creds.swid)
            league_json = client.league()
            cfg = parse_league_config(league_json, creds.league_id, creds.season)
            if args.save_raw:
                with open(args.save_raw, "w", encoding="utf-8") as fh:
                    json.dump(league_json, fh, indent=2)
    except ESPNError as exc:
        print(f"ERROR ESPN: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"ERROR file: {exc}", file=sys.stderr)
        return 3
    except Exception:  # noqa: BLE001
        print("ERROR unexpected:\n" + traceback.format_exc(), file=sys.stderr)
        return 2

    week = args.week
    if args.basis == "week" and not week:
        week = league_json.get("scoringPeriodId") or 1

    try:
        teams = parse_all_teams(league_json, week=week)
        if not teams:
            print("ERROR payload carried no teams -- was mTeam+mRoster requested?",
                  file=sys.stderr)
            return 2
        lmap = scarcity_map(teams, cfg, basis=args.basis)
        trades = (trade_candidates(lmap, cfg, my_team_id, limit=args.trades)
                  if my_team_id else [])
    except ValueError as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(to_json(lmap, my_team_id, trades), indent=2))
        return 0

    if args.position:
        pos = args.position.upper()
        if pos not in SCORABLE:
            print(f"ERROR unknown position {pos!r}; expected one of "
                  f"{', '.join(SCORABLE)}", file=sys.stderr)
            return 2
        for prof in lmap.standings(pos):
            s = prof.positions[pos]
            marker = "*" if prof.team_id == my_team_id else " "
            print(f"{marker}{s.rank:>3}. {prof.name[:28]:<28} {s.starting:>+8.1f}  "
                  f"surplus {s.surplus:>6.1f}  held {s.count}"
                  + ("  NO STARTER" if s.holes else ""))
        return 0

    print(render(lmap, my_team_id, trades))
    return 0


if __name__ == "__main__":
    sys.exit(main())
