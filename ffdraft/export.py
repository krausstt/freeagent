"""Export a self-contained snapshot for the offline phone cockpit."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from .board import DraftBoard


def build_snapshot(board: DraftBoard, top_n: int = 200) -> dict:
    """Everything the HTML cockpit needs to run entirely offline.

    The cockpit re-computes recommendations in the browser as you tap players
    off the board, so this snapshot carries the full valued pool, not just a
    frozen top-10 list. That is what keeps it useful after pick one.
    """
    pool = sorted(board.players, key=lambda p: p.vorp, reverse=True)[:top_n]
    cfg = board.cfg
    return {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "league": {
            "id": cfg.league_id,
            "name": cfg.name,
            "season": cfg.season,
            "teamCount": cfg.team_count,
            "rosterSlots": cfg.roster_slots,
            "ppr": cfg.ppr,
            "myTeamId": cfg.my_team_id,
            "myDraftSlot": cfg.my_draft_slot,
            "rosterSize": cfg.roster_size,
            "dedicatedDemand": cfg.dedicated_demand,
            "flexSlotsPerTeam": sum(n for _, n in cfg.flex_demand) // max(1, cfg.team_count),
        },
        "replacementLevels": {k: round(v, 1) for k, v in board.replacement.items()},
        "state": board.state_summary(),
        "players": [
            {
                "id": p.player_id,
                "name": p.name,
                "pos": p.position,
                "team": p.pro_team,
                "proj": round(p.proj_points, 1),
                "vorp": round(p.vorp, 1),
                "adp": round(p.adp, 1),
                "tier": p.tier,
                "bye": p.bye_week,
                "inj": p.injury_status,
                "owned": round(p.percent_owned, 1),
                "draftedBy": p.drafted_by,
                "draftedAt": p.drafted_at,
            }
            for p in pool
        ],
        "recommendations": [r.to_dict() for r in board.recommend(top_n=12)],
    }


def write_snapshot(board: DraftBoard, path: str, top_n: int = 200) -> str:
    snapshot = build_snapshot(board, top_n=top_n)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(snapshot, fh, indent=2)
    return path
