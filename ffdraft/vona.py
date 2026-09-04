"""Value Over Next Available - what the board looks like when it comes back."""

from __future__ import annotations

import random

from .availability import SIGMA_SLOPE, sigma_for
from .models import Player


def simulate_gap(
    available: list[Player],
    picks_until_next: int,
    slope: float = SIGMA_SLOPE,
    n_sims: int = 3000,
    pool_cap: int = 180,
    seed: int | None = 20260829,
) -> tuple[dict[int, float], dict[str, float]]:
    """Simulate the picks between now and your next turn.

    Returns:
      survival: player_id -> P(still available at your next pick)
      fallback: position -> E[VORP of the best survivor at that position]

    `fallback` is the number that actually decides a draft. If the best RB you
    could get next round is worth 42 VORP and the one in front of you now is
    worth 45, running back is not scarce and you should take the wide receiver.
    """
    rng = random.Random(seed)
    pool = sorted(available, key=lambda p: p.adp)[:pool_cap]

    positions = {p.position for p in available}
    if not pool or picks_until_next <= 0:
        survival = {p.player_id: 1.0 for p in available}
        fallback = {
            pos: max((p.vorp for p in available if p.position == pos), default=0.0)
            for pos in positions
        }
        return survival, fallback

    k = min(picks_until_next, len(pool))
    params = [(p.player_id, p.adp, sigma_for(p.adp, slope)) for p in pool]
    pool_ids = {p.player_id for p in pool}

    # Players outside the plausible pool always survive; they set a floor on the
    # fallback value at their position.
    deep_floor: dict[str, float] = {}
    for p in available:
        if p.player_id not in pool_ids:
            deep_floor[p.position] = max(deep_floor.get(p.position, 0.0), p.vorp)

    survived = {p.player_id: 0 for p in pool}
    fallback_sum: dict[str, float] = {pos: 0.0 for pos in positions}
    by_id = {p.player_id: p for p in pool}

    for _ in range(n_sims):
        draws = [(rng.gauss(adp, sigma), pid) for pid, adp, sigma in params]
        draws.sort()
        taken = {pid for _, pid in draws[:k]}

        best: dict[str, float] = dict(deep_floor)
        for pid in survived:
            if pid not in taken:
                survived[pid] += 1
                p = by_id[pid]
                if p.vorp > best.get(p.position, float("-inf")):
                    best[p.position] = p.vorp
        for pos in fallback_sum:
            fallback_sum[pos] += best.get(pos, deep_floor.get(pos, 0.0))

    survival = {pid: c / n_sims for pid, c in survived.items()}
    for p in available:
        survival.setdefault(p.player_id, 1.0)
    fallback = {pos: total / n_sims for pos, total in fallback_sum.items()}
    return survival, fallback
