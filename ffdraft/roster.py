"""Lineup optimisation and roster-aware marginal value.

VORP answers "how good is this player". It does not answer "how much does this
player improve *my* team", which is a different question once you already own
three running backs.
"""

from __future__ import annotations

from .constants import FLEX_ELIGIBILITY, SCORABLE, SLOT_MAP
from .models import LeagueConfig, Player


def optimal_lineup(players: list[Player], cfg: LeagueConfig) -> tuple[float, dict[str, list[Player]]]:
    """Best legal starting lineup from `players`, and the points it scores.

    Dedicated slots are single-position, so taking the best available at each is
    optimal. Flex slots are then filled from whoever is left. Because dedicated
    slots never compete with each other, this greedy fill is exact for standard
    ESPN roster shapes.
    """
    by_pos: dict[str, list[Player]] = {pos: [] for pos in SCORABLE}
    for p in players:
        if p.position in by_pos:
            by_pos[p.position].append(p)
    for pos in by_pos:
        by_pos[pos].sort(key=lambda x: x.proj_points, reverse=True)

    used: dict[str, int] = {pos: 0 for pos in SCORABLE}
    assignment: dict[str, list[Player]] = {}
    total = 0.0

    # Pass 1: dedicated single-position slots.
    for slot, count in sorted(cfg.starter_slots.items()):
        label = SLOT_MAP.get(slot)
        if label not in SCORABLE:
            continue
        picked = []
        for _ in range(count):
            idx = used[label]
            if idx < len(by_pos[label]):
                picked.append(by_pos[label][idx])
                used[label] += 1
        assignment[label] = picked
        total += sum(p.proj_points for p in picked)

    # Pass 2: flex slots, best remaining eligible player each time.
    for slot, count in sorted(cfg.starter_slots.items()):
        if slot not in FLEX_ELIGIBILITY:
            continue
        eligible = FLEX_ELIGIBILITY[slot]
        picked = []
        for _ in range(count):
            best_pos, best_pts = None, float("-inf")
            for pos in eligible:
                idx = used.get(pos, 0)
                if idx < len(by_pos.get(pos, [])) and by_pos[pos][idx].proj_points > best_pts:
                    best_pos, best_pts = pos, by_pos[pos][idx].proj_points
            if best_pos is None:
                break
            picked.append(by_pos[best_pos][used[best_pos]])
            used[best_pos] += 1
        assignment[SLOT_MAP.get(slot, str(slot))] = picked
        total += sum(p.proj_points for p in picked)

    return total, assignment


def marginal_starter_value(roster: list[Player], candidate: Player, cfg: LeagueConfig) -> float:
    """How many projected starting points does `candidate` actually add?

    This is what stops the engine from recommending a fourth tight end just
    because he grades out well in isolation.
    """
    before, _ = optimal_lineup(roster, cfg)
    after, _ = optimal_lineup(roster + [candidate], cfg)
    return after - before


def unfilled_starter_slots(roster: list[Player], cfg: LeagueConfig) -> dict[str, int]:
    """Starter slots at each position this roster cannot yet fill."""
    counts: dict[str, int] = {pos: 0 for pos in SCORABLE}
    for p in roster:
        if p.position in counts:
            counts[p.position] += 1

    need: dict[str, int] = {}
    for slot, n in cfg.starter_slots.items():
        label = SLOT_MAP.get(slot)
        if label in SCORABLE:
            have = min(counts.get(label, 0), n)
            need[label] = need.get(label, 0) + (n - have)
    return need


def roster_summary(roster: list[Player], cfg: LeagueConfig) -> dict:
    total, assignment = optimal_lineup(roster, cfg)
    by_pos: dict[str, int] = {}
    for p in roster:
        by_pos[p.position] = by_pos.get(p.position, 0) + 1
    return {
        "size": len(roster),
        "capacity": cfg.roster_size,
        "projected_starting_points": round(total, 1),
        "by_position": by_pos,
        "unfilled_starters": {k: v for k, v in unfilled_starter_slots(roster, cfg).items() if v > 0},
        "lineup": {
            slot: [p.name for p in players] for slot, players in assignment.items() if players
        },
    }


def bye_week_conflicts(roster: list[Player], candidate: Player) -> int:
    """Starters at the same position already sharing this candidate's bye."""
    if not candidate.bye_week:
        return 0
    return sum(
        1
        for p in roster
        if p.bye_week == candidate.bye_week and p.position == candidate.position
    )
