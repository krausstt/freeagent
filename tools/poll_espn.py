#!/usr/bin/env python3
"""Cron entrypoint: pull the live league from ESPN and write a snapshot.

Designed to run unattended on a machine that can actually reach ESPN. It is
deliberately boring: fetch, write, optionally commit, exit non-zero on failure
so cron or systemd surfaces the problem instead of failing silently for weeks.

    python3 tools/poll_espn.py                      # write data/live/latest.json
    python3 tools/poll_espn.py --commit             # ...and git commit + push it
    python3 tools/poll_espn.py --week 3             # override the scoring period

Exit codes: 0 ok, 2 ESPN/auth failure, 3 local write failure.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import traceback
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from ffdraft import config  # noqa: E402
from ffdraft.constants import PRO_TEAM_MAP, SLOT_MAP  # noqa: E402
from ffdraft.espn_client import ESPNClient, ESPNError  # noqa: E402
from ffdraft.models import LeagueConfig, Player, parse_league_config  # noqa: E402
from ffdraft.schedule import apply_bye_weeks, bye_weeks  # noqa: E402
from ffdraft.season import season_coverage  # noqa: E402

REPO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
OUT_DIR = os.path.join(REPO, "data", "live")


def log(msg: str) -> None:
    print(f"[{datetime.now(timezone.utc):%Y-%m-%d %H:%M:%SZ}] {msg}", flush=True)


def my_roster(league_json: dict, team_id: int) -> list[Player]:
    """Extract one team's roster from an mRoster payload."""
    for team in league_json.get("teams", []) or []:
        if team.get("id") != team_id:
            continue
        out: list[Player] = []
        for entry in (team.get("roster", {}) or {}).get("entries", []) or []:
            pool = entry.get("playerPoolEntry", {}) or {}
            info = pool.get("player", {}) or {}
            eligible = info.get("eligibleSlots", []) or []
            position = next(
                (SLOT_MAP[s] for s in eligible
                 if SLOT_MAP.get(s) in ("QB", "RB", "WR", "TE", "K", "D/ST")),
                None,
            )
            if position is None:
                continue
            proj = 0.0
            for stat in info.get("stats", []) or []:
                if stat.get("statSourceId") == 1 and stat.get("scoringPeriodId") == 0:
                    proj = float(stat.get("appliedTotal", 0.0) or 0.0)
                    break
            out.append(Player(
                player_id=int(info.get("id", 0)),
                name=info.get("fullName", "?"),
                position=position,
                pro_team=PRO_TEAM_MAP.get(info.get("proTeamId", 0), ""),
                proj_points=proj,
                injury_status=info.get("injuryStatus", "ACTIVE") or "ACTIVE",
                eligible_slots=tuple(eligible),
                lineup_slot=SLOT_MAP.get(entry.get("lineupSlotId", -1), ""),
            ))
        return out
    raise ESPNError(f"teamId {team_id} not found in this league")


def find_team_id(league_json: dict, swid: str | None) -> int | None:
    """Match your SWID against league members. Same logic as tools/find_league.py."""
    if not swid:
        return None
    target = swid.strip().upper()
    if not target.startswith("{"):
        target = "{" + target.strip("{}") + "}"
    for team in league_json.get("teams", []) or []:
        for owner in team.get("owners") or []:
            oid = (owner if isinstance(owner, str) else str(owner.get("id", ""))).upper()
            if oid == target:
                return team.get("id")
    return None


def build(client: ESPNClient, cfg: LeagueConfig, team_id: int) -> dict:
    league_json = client.league()
    roster = my_roster(league_json, team_id)

    try:
        resolved = apply_bye_weeks(roster, bye_weeks(client.pro_schedule()))
        log(f"bye weeks resolved for {resolved}/{len(roster)} players")
    except ESPNError as exc:
        log(f"WARN bye weeks unavailable: {exc}")

    coverage = [
        {
            "week": c.week,
            "margins": c.margins,
            "short": c.short,
            "noSlack": c.no_slack,
            "onBye": [p.name for p in c.on_bye],
        }
        for c in season_coverage(cfg, roster)
    ]

    status = (league_json.get("status", {}) or {})
    return {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "league": {
            "id": cfg.league_id, "name": cfg.name, "season": cfg.season,
            "teamCount": cfg.team_count, "rosterSlots": cfg.roster_slots,
            "myTeamId": team_id,
            "currentWeek": status.get("latestScoringPeriod"),
        },
        "roster": [
            {
                "id": p.player_id, "name": p.name, "pos": p.position, "team": p.pro_team,
                "proj": round(p.proj_points, 1), "bye": p.bye_week,
                "inj": p.injury_status,
                "lineupSlot": p.lineup_slot,
            }
            for p in roster
        ],
        "coverage": coverage,
        "problemWeeks": [c["week"] for c in coverage if c["short"]],
    }


def git_commit(paths: list[str]) -> None:
    """Commit and push the snapshot. Never fails the poll on a git problem."""
    try:
        subprocess.run(["git", "-C", REPO, "add", *paths], check=True, capture_output=True)
        status = subprocess.run(["git", "-C", REPO, "diff", "--cached", "--quiet"],
                                capture_output=True)
        if status.returncode == 0:
            log("no snapshot change; skipping commit")
            return
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%MZ")
        subprocess.run(["git", "-C", REPO, "commit", "-m", f"Live snapshot {stamp}"],
                       check=True, capture_output=True)
        subprocess.run(["git", "-C", REPO, "push"], check=True, capture_output=True)
        log("snapshot committed and pushed")
    except subprocess.CalledProcessError as exc:
        log(f"WARN git step failed: {exc.stderr.decode(errors='replace')[:300]}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--commit", action="store_true", help="git commit + push the snapshot")
    ap.add_argument("--out-dir", default=OUT_DIR)
    ap.add_argument("--keep", type=int, default=40, help="dated snapshots to retain")
    args = ap.parse_args()

    creds = config.load()
    if not creds.league_id:
        log("ERROR no league id. Set ESPN_LEAGUE_ID or run tools/find_league.py")
        return 2

    try:
        client = ESPNClient(creds.league_id, creds.season, creds.espn_s2, creds.swid)
        cfg = parse_league_config(client.settings(), creds.league_id, creds.season)
        team_id = creds.team_id or find_team_id(client.league(), creds.swid)
        if not team_id:
            log("ERROR could not resolve your teamId. Set ESPN_TEAM_ID.")
            return 2
        log(f"league '{cfg.name}' | {cfg.team_count} teams | teamId {team_id}")
        snapshot = build(client, cfg, team_id)
    except ESPNError as exc:
        log(f"ERROR ESPN: {exc}")
        return 2
    except Exception:  # noqa: BLE001 - cron needs the traceback in the log
        log("ERROR unexpected:\n" + traceback.format_exc())
        return 2

    try:
        os.makedirs(args.out_dir, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        dated = os.path.join(args.out_dir, f"snapshot-{stamp}.json")
        latest = os.path.join(args.out_dir, "latest.json")
        for path in (dated, latest):
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(snapshot, fh, indent=2)

        # Keep the directory from growing without bound.
        snaps = sorted(f for f in os.listdir(args.out_dir) if f.startswith("snapshot-"))
        for stale in snaps[: max(0, len(snaps) - args.keep)]:
            os.remove(os.path.join(args.out_dir, stale))
    except OSError as exc:
        log(f"ERROR writing snapshot: {exc}")
        return 3

    problems = snapshot["problemWeeks"]
    log(f"wrote {latest} | {len(snapshot['roster'])} players | "
        f"weeks you cannot field a lineup: {problems or 'none'}")

    if args.commit:
        git_commit([os.path.relpath(dated, REPO), os.path.relpath(latest, REPO)])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
