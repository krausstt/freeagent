"""Replacement level, VORP, and tier detection.

The single most important number in a draft is not a player's projection, it is
the projection *of the player you could have had instead*. Everything here
exists to compute that baseline honestly.
"""

from __future__ import annotations

from .constants import SCORABLE
from .models import LeagueConfig, Player


def starter_demand(cfg: LeagueConfig, players: list[Player]) -> dict[str, int]:
    """How many players at each position are actually startable league-wide.

    Dedicated slots are trivial (teams x slots). Flex is not: a RB/WR/TE flex is
    filled by whichever position happens to have the best available player, so we
    resolve it by simulating the fill greedily against the real projection pool.
    That makes replacement level responsive to the actual shape of the player
    pool in this season rather than a fixed rule of thumb.
    """
    demand = dict(cfg.dedicated_demand)

    by_pos: dict[str, list[Player]] = {pos: [] for pos in SCORABLE}
    for p in players:
        if p.position in by_pos:
            by_pos[p.position].append(p)
    for pos in by_pos:
        by_pos[pos].sort(key=lambda x: x.proj_points, reverse=True)

    # Walk each flex block, repeatedly taking the best player not already
    # claimed by dedicated demand or an earlier flex allocation.
    for eligible, slots in cfg.flex_demand:
        for _ in range(slots):
            best_pos, best_pts = None, float("-inf")
            for pos in eligible:
                idx = demand.get(pos, 0)
                pool = by_pos.get(pos, [])
                if idx < len(pool) and pool[idx].proj_points > best_pts:
                    best_pos, best_pts = pos, pool[idx].proj_points
            if best_pos is None:
                break
            demand[best_pos] = demand.get(best_pos, 0) + 1

    return demand


def replacement_levels(cfg: LeagueConfig, players: list[Player]) -> dict[str, float]:
    """Projected points of the first player past the last startable one.

    Uses a small window average rather than a single player so one outlier
    projection cannot move the entire baseline for a position.
    """
    demand = starter_demand(cfg, players)
    levels: dict[str, float] = {}

    by_pos: dict[str, list[Player]] = {pos: [] for pos in SCORABLE}
    for p in players:
        if p.position in by_pos:
            by_pos[p.position].append(p)

    for pos, pool in by_pos.items():
        pool.sort(key=lambda x: x.proj_points, reverse=True)
        n = demand.get(pos, 0)
        if not pool:
            levels[pos] = 0.0
            continue
        window = [p.proj_points for p in pool[n : n + 3]]
        if not window:
            window = [pool[-1].proj_points]
        levels[pos] = sum(window) / len(window)

    return levels


def compute_vorp(cfg: LeagueConfig, players: list[Player]) -> dict[str, float]:
    """Assign `vorp` on every player in place. Returns the replacement levels used."""
    levels = replacement_levels(cfg, players)
    for p in players:
        baseline = levels.get(p.position, 0.0)
        # Health discount applies to the surplus, not the raw projection: a
        # replacement-level player who is hurt is still worth ~replacement.
        p.vorp = (p.proj_points - baseline) * p.health_factor
    return levels


# --------------------------------------------------------------------- tiering


def _jenks_breaks(values: list[float], k: int) -> list[int]:
    """Fisher-Jenks natural breaks on a descending-sorted 1-D series.

    Returns the indices at which a new class starts (excluding 0). O(n^2 * k),
    which is nothing for the ~60 players per position we tier.

    Jenks minimises within-class variance, which is exactly what a "tier" means
    in draft terms: players you are genuinely indifferent between.
    """
    n = len(values)
    if n == 0:
        return []
    k = max(1, min(k, n))
    if k == 1:
        return []

    # cost[i][j] = minimal within-class sum of squared deviations for the first
    # i values split into j classes. back[i][j] = start index of the last class.
    INF = float("inf")
    cost = [[INF] * (k + 1) for _ in range(n + 1)]
    back = [[0] * (k + 1) for _ in range(n + 1)]
    cost[0][0] = 0.0

    for i in range(1, n + 1):
        for j in range(1, min(k, i) + 1):
            s = s2 = 0.0
            cnt = 0
            # Extend the last class leftwards from i, tracking variance online.
            for m in range(i, j - 1, -1):
                v = values[m - 1]
                s += v
                s2 += v * v
                cnt += 1
                var = s2 - (s * s) / cnt
                prev = cost[m - 1][j - 1]
                if prev + var < cost[i][j]:
                    cost[i][j] = prev + var
                    back[i][j] = m - 1

    breaks: list[int] = []
    i, j = n, k
    while j > 1:
        start = back[i][j]
        breaks.append(start)
        i, j = start, j - 1
    return sorted(breaks)


def assign_tiers(players: list[Player], max_tiers: int = 8) -> None:
    """Assign `tier` per position, in place.

    Tier 1 is the best. Tiers are computed on VORP within a position, over the
    top `3 * max_tiers` players only -- deep bench fodder has no meaningful tier
    structure and including it distorts the breaks.
    """
    by_pos: dict[str, list[Player]] = {}
    for p in players:
        by_pos.setdefault(p.position, []).append(p)

    for pool in by_pos.values():
        pool.sort(key=lambda x: x.vorp, reverse=True)
        head = pool[: max_tiers * 3]
        values = [p.vorp for p in head]
        breaks = set(_jenks_breaks(values, max_tiers))

        tier = 1
        for i, p in enumerate(head):
            if i in breaks and i != 0:
                tier += 1
            p.tier = tier
        for p in pool[max_tiers * 3 :]:
            p.tier = tier + 1
