"""Synthetic league + player pool for testing without network access."""

from __future__ import annotations

import random

from ffdraft.models import LeagueConfig, Player

# A standard ESPN 10-team PPR roster:
# 1 QB, 2 RB, 2 WR, 1 TE, 1 FLEX(RB/WR/TE), 1 D/ST, 1 K, 7 BE
STANDARD_SLOTS = {0: 1, 2: 2, 4: 2, 6: 1, 23: 1, 16: 1, 17: 1, 20: 7}


def make_config(team_count: int = 10, my_slot: int = 4, my_team_id: int = 1) -> LeagueConfig:
    return LeagueConfig(
        league_id=123456,
        season=2026,
        name="Test League",
        team_count=team_count,
        roster_slots=dict(STANDARD_SLOTS),
        scoring_type="PPR",
        ppr=1.0,
        my_team_id=my_team_id,
        my_draft_slot=my_slot,
    )


# Position pool sizes and a plausible points curve (start, decay) per position.
_CURVES = {
    "QB": (330.0, 0.978, 32),
    "RB": (310.0, 0.962, 70),
    "WR": (300.0, 0.968, 80),
    "TE": (240.0, 0.945, 30),
    "K": (140.0, 0.992, 20),
    "D/ST": (150.0, 0.985, 20),
}


def make_players(seed: int = 7) -> list[Player]:
    """Deterministic pool whose ADP correlates with, but does not equal, value."""
    rng = random.Random(seed)
    players: list[Player] = []
    pid = 1
    for pos, (start, decay, count) in _CURVES.items():
        for i in range(count):
            pts = start * (decay**i)
            players.append(
                Player(
                    player_id=pid,
                    name=f"{pos}{i + 1}",
                    position=pos,
                    pro_team="KC",
                    proj_points=round(pts, 1),
                    bye_week=(pid % 14) + 4,
                )
            )
            pid += 1

    # ADP: rank by points, then add noise so the model has something to model.
    ranked = sorted(players, key=lambda p: p.proj_points, reverse=True)
    # Kickers and defenses always go late regardless of raw projection.
    offense = [p for p in ranked if p.position not in ("K", "D/ST")]
    late = [p for p in ranked if p.position in ("K", "D/ST")]
    for i, p in enumerate(offense):
        p.adp = max(1.0, (i + 1) + rng.gauss(0, 4))
    for i, p in enumerate(late):
        p.adp = 130.0 + i + rng.gauss(0, 5)
    return players
