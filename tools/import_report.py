#!/usr/bin/env python3
"""Turn a research briefing board into a cockpit snapshot.

Why this exists: on draft day you may have a hand-built board (from your own
research, or an analyst report) long before you have ESPN API credentials
working. This converts that board into the same snapshot format
`ffdraft.cli export` produces, so the cockpit and its live simulation work
against it identically.

Projection handling is deliberately conservative. Only values the briefing
states explicitly are used as-is. Everything else is interpolated between
those anchors along positional rank and flagged `projSource: "interpolated"`,
so nothing invented is ever presented as sourced.

    python3 tools/import_report.py data/board_2026_report.json -o snapshot.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ffdraft.availability import snake_picks  # noqa: E402
from ffdraft.models import LeagueConfig, Player  # noqa: E402
from ffdraft.valuation import assign_tiers  # noqa: E402
from ffdraft.vona import simulate_gap  # noqa: E402

TIER_RANK = {"S": 1, "A": 2, "B": 3, "C": 4, "D": 5, "E": 6}


def interpolate(rank: int, anchors: dict[int, float]) -> float:
    """Piecewise-linear projection between the briefing's own stated anchors."""
    ranks = sorted(anchors)
    if rank <= ranks[0]:
        return anchors[ranks[0]]
    if rank >= ranks[-1]:
        # Past the last anchor, continue the final segment's slope but never
        # below zero -- deep bench players are worth little, not negative.
        lo, hi = ranks[-2], ranks[-1]
        slope = (anchors[hi] - anchors[lo]) / (hi - lo)
        return max(0.0, anchors[hi] + slope * (rank - hi))
    for lo, hi in zip(ranks, ranks[1:]):
        if lo <= rank <= hi:
            span = hi - lo
            w = (rank - lo) / span if span else 0.0
            return anchors[lo] + w * (anchors[hi] - anchors[lo])
    return anchors[ranks[-1]]


def build(board: dict) -> dict:
    meta = board["league"]
    replacement = {k: v for k, v in board["replacement"].items() if not k.startswith("_")}
    raw = board["players"]

    cfg = LeagueConfig(
        league_id=0,
        season=2026,
        name="Research board (briefing 2026-08-30)",
        team_count=meta["teams"],
        roster_slots={int(k): int(v) for k, v in meta["rosterSlots"].items()},
        scoring_type=meta["scoring"],
        my_draft_slot=meta["draftSlot"],
        my_team_id=None,
    )

    # Positional rank comes from the briefing's own board order, so the
    # interpolation never assumes anything about an external ranking system.
    pos_rank: dict[str, int] = {}
    entries = []
    for row in sorted(raw, key=lambda r: r["r"]):
        pos = row["p"]
        pos_rank[pos] = pos_rank.get(pos, 0) + 1
        entries.append((row, pos_rank[pos]))

    # Anchors come from the briefing's own positional-rank -> projection table
    # (its stated RB10 / WR10 / QB10 / TE10 values and the replacement markers).
    # Without these the curve misses the mid-round cliff entirely and every
    # unanchored player is valued far too highly.
    anchors: dict[str, dict[int, float]] = {}
    for pos, table in (board.get("projectionAnchors") or {}).items():
        if pos.startswith("_"):
            continue
        anchors[pos] = {int(k): float(v) for k, v in table.items()}
    if not anchors:
        raise SystemExit("board has no projectionAnchors block; refusing to guess a curve")

    # Enforce monotonicity: a lower positional rank must never project below a
    # higher one, or the interpolation produces nonsense between the two.
    for pos, table in anchors.items():
        best = float("inf")
        for rank in sorted(table):
            best = min(best, table[rank])
            table[rank] = best

    players: list[Player] = []
    provenance: dict[int, dict] = {}
    for row, prank in entries:
        pos = row["p"]
        if "proj" in row:
            proj, source = float(row["proj"]), "briefing"
        else:
            pos_anchors = anchors.get(pos)
            if not pos_anchors:
                raise SystemExit(f"no projection anchors for position {pos}")
            proj, source = interpolate(prank, pos_anchors), "interpolated"

        p = Player(
            player_id=row["r"],
            name=row["n"],
            position=pos,
            pro_team="",
            proj_points=round(proj, 1),
            adp=float(row["adp"]),
            espn_rank=float(row["r"]),
        )
        # VORP uses the briefing's own replacement proxies rather than the
        # engine's pool-derived ones: a 73-player board is far too shallow for
        # starter-demand simulation to mean anything.
        p.vorp = round(proj - replacement.get(pos, 0.0), 1)
        players.append(p)
        provenance[row["r"]] = {
            "posRank": prank,
            "projSource": source,
            "impact": row["i"],
            "reportTier": row["t"],
            "note": row.get("note", ""),
        }

    assign_tiers(players)

    schedule = snake_picks(cfg.my_draft_slot, cfg.team_count, cfg.roster_size)
    gap = schedule[1] - schedule[0] - 1
    survival, fallback = simulate_gap(players, gap, n_sims=4000, pool_cap=len(players))

    return {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "sourceNote": board.get("_source", ""),
        "verificationNote": board.get("_verification", ""),
        "league": {
            "id": 0,
            "name": cfg.name,
            "season": 2026,
            "teamCount": cfg.team_count,
            "rosterSlots": cfg.roster_slots,
            "ppr": 0.5,
            "myTeamId": None,
            "myDraftSlot": cfg.my_draft_slot,
            "rosterSize": cfg.roster_size,
            "dedicatedDemand": cfg.dedicated_demand,
            "flexSlotsPerTeam": sum(n for _, n in cfg.flex_demand) // cfg.team_count,
        },
        "replacementLevels": replacement,
        "state": {
            "league": cfg.name,
            "season": 2026,
            "teamCount": cfg.team_count,
            "picksMade": 0,
            "totalPicks": cfg.total_picks,
            "myNextPick": schedule[0],
            "pickAfterThat": schedule[1],
            "picksUntilNext": gap,
            "mySchedule": schedule[:10],
        },
        "players": [
            {
                "id": p.player_id, "name": p.name, "pos": p.position, "team": "",
                "proj": p.proj_points, "vorp": p.vorp, "adp": p.adp, "tier": p.tier,
                "bye": 0, "inj": "ACTIVE", "owned": 0.0,
                "draftedBy": None, "draftedAt": None,
                **provenance[p.player_id],
            }
            for p in sorted(players, key=lambda x: x.vorp, reverse=True)
        ],
        "recommendations": [],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("board")
    ap.add_argument("-o", "--out", default="report_snapshot.json")
    args = ap.parse_args()

    snapshot = build(json.load(open(args.board, encoding="utf-8")))
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(snapshot, fh, separators=(",", ":"))

    briefed = sum(1 for p in snapshot["players"] if p["projSource"] == "briefing")
    print(f"wrote {args.out}: {len(snapshot['players'])} players "
          f"({briefed} briefing-sourced projections, "
          f"{len(snapshot['players']) - briefed} interpolated)")
    print(f"draft slot {snapshot['league']['myDraftSlot']} of "
          f"{snapshot['league']['teamCount']} -> picks "
          f"{snapshot['state']['mySchedule']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
