#!/usr/bin/env python3
"""Render the weekly brief from the latest live snapshot.

    python3 tools/weekly_brief.py                    # print to stdout
    python3 tools/weekly_brief.py --write            # also save data/live/brief-latest.md
    python3 tools/weekly_brief.py --json             # machine-readable

Reads data/live/latest.json, which tools/poll_espn.py produces. Exits 4 if no
snapshot exists yet, so a scheduler can tell "nothing polled" apart from
"polled and nothing to report".
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from ffdraft.brief import build, render_markdown  # noqa: E402
from ffdraft.journal import Option, record  # noqa: E402
from ffdraft.models import LeagueConfig, Player  # noqa: E402

REPO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
DEFAULT_SNAPSHOT = os.path.join(REPO, "data", "live", "latest.json")
DEFAULT_JOURNAL = os.path.join(REPO, "data", "journal")


def load(path: str) -> tuple[LeagueConfig, list[Player], int | None]:
    with open(path, encoding="utf-8") as fh:
        snap = json.load(fh)
    lg = snap["league"]
    cfg = LeagueConfig(
        league_id=lg["id"], season=lg["season"], name=lg.get("name", ""),
        team_count=lg.get("teamCount", 12),
        roster_slots={int(k): int(v) for k, v in (lg.get("rosterSlots") or {}).items()},
        my_team_id=lg.get("myTeamId"),
    )
    roster = [
        Player(player_id=r["id"], name=r["name"], position=r["pos"],
               pro_team=r.get("team", ""), proj_points=float(r.get("proj", 0.0)),
               bye_week=int(r.get("bye", 0) or 0),
               injury_status=r.get("inj", "ACTIVE") or "ACTIVE",
               lineup_slot=r.get("lineupSlot", "") or "")
        for r in snap.get("roster", [])
    ]
    return cfg, roster, lg.get("currentWeek")


def previous_injuries(path: str) -> dict[int, str]:
    """Injury designations from the previous snapshot, so we can flag changes."""
    directory = os.path.dirname(path)
    try:
        snaps = sorted(f for f in os.listdir(directory) if f.startswith("snapshot-"))
    except OSError:
        return {}
    if len(snaps) < 2:
        return {}
    try:
        with open(os.path.join(directory, snaps[-2]), encoding="utf-8") as fh:
            prev = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}
    return {r["id"]: (r.get("inj") or "ACTIVE") for r in prev.get("roster", [])}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--snapshot", default=DEFAULT_SNAPSHOT)
    ap.add_argument("--week", type=int, help="override the scoring period")
    ap.add_argument("--write", action="store_true", help="save brief-latest.md next to the snapshot")
    ap.add_argument("--json", action="store_true", help="emit JSON instead of markdown")
    ap.add_argument("--journal", metavar="DIR", nargs="?", const=DEFAULT_JOURNAL,
                    help="also log each lineup call to the decision journal")
    args = ap.parse_args()

    if not os.path.exists(args.snapshot):
        print(f"No snapshot at {args.snapshot}. Run tools/poll_espn.py first.", file=sys.stderr)
        return 4

    cfg, roster, week = load(args.snapshot)
    brief = build(cfg, roster, args.week if args.week is not None else week,
                  previous_injuries(args.snapshot))

    # Logged before the games, which is the only time it means anything: a
    # projection looked up afterwards is not the one the call was made on.
    if args.journal:
        logged = 0
        for sw in brief.lineup_swaps:
            entry = record(
                args.journal, week=brief.week or 0, kind="lineup",
                summary=f"Start {sw['start']} over {sw['bench']}",
                chosen=Option(sw["startId"], sw["start"], sw["startProj"], sw["startPos"]),
                alternatives=[Option(sw["benchId"], sw["bench"], sw["benchProj"],
                                     sw["benchPos"])],
                expected_gain=sw["gain"],
                context={"leagueId": cfg.league_id, "snapshot": brief.generated_at},
            )
            if entry:
                logged += 1
        print(f"journal: {logged} new decision(s) recorded in {args.journal}",
              file=sys.stderr)

    if args.json:
        print(json.dumps(dataclasses.asdict(brief), indent=2))
    else:
        text = render_markdown(brief)
        print(text)
        if args.write:
            out = os.path.join(os.path.dirname(args.snapshot), "brief-latest.md")
            with open(out, "w", encoding="utf-8") as fh:
                fh.write(text + "\n")
            print(f"\n(written to {out})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
