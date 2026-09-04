"""Will he still be there? ADP survival modelling with live calibration.

A draft board that only ranks players is answering the wrong question. The
question is: which of these players will *not* survive until my next pick. That
turns a ranking into a decision.
"""

from __future__ import annotations

import math
import random

from .models import Player

# Default spread of a player's actual draft slot around their ADP.
# Early picks are tightly clustered; late picks scatter badly. These are priors
# only -- `calibrate_sigma` replaces them with this room's observed behaviour as
# soon as there are enough picks on the board.
SIGMA_FLOOR = 4.0
SIGMA_SLOPE = 0.28


def sigma_for(adp: float, slope: float = SIGMA_SLOPE, floor: float = SIGMA_FLOOR) -> float:
    """Std-dev of a player's realised draft position, given their ADP."""
    return max(floor, slope * adp)


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def survival_probability(
    player: Player, pick_number: int, slope: float = SIGMA_SLOPE
) -> float:
    """P(player is still on the board when pick `pick_number` comes around).

    Models the player's realised draft slot D ~ Normal(ADP, sigma) and returns
    P(D >= pick_number).
    """
    sigma = sigma_for(player.adp, slope)
    return 1.0 - _norm_cdf((pick_number - player.adp) / sigma)


def calibrate_sigma(players: list[Player], min_picks: int = 12) -> float:
    """Re-fit the ADP spread from picks already made in THIS draft.

    Every room drafts differently: some slavishly follow ESPN's board, some
    reach wildly. After `min_picks` selections we can measure it instead of
    assuming. Returns a slope for `sigma_for`; falls back to the prior when
    there is not yet enough signal.
    """
    residuals = [
        (p.drafted_at - p.adp, p.adp)
        for p in players
        if p.drafted_at is not None and p.adp > 0
    ]
    if len(residuals) < min_picks:
        return SIGMA_SLOPE

    # Fit sigma = slope * adp by least squares through the origin on |residual|,
    # scaled so that mean |residual| of a normal equals sigma * sqrt(2/pi).
    num = sum(abs(r) * adp for r, adp in residuals)
    den = sum(adp * adp for r, adp in residuals)
    if den <= 0:
        return SIGMA_SLOPE
    slope = (num / den) * math.sqrt(math.pi / 2.0)
    # Clamp to a sane band so one chaotic round cannot destroy the model.
    return min(0.60, max(0.10, slope))


def snake_picks(draft_slot: int, team_count: int, rounds: int) -> list[int]:
    """Overall pick numbers for a given snake draft slot (all 1-indexed)."""
    picks = []
    for rnd in range(1, rounds + 1):
        if rnd % 2 == 1:
            picks.append((rnd - 1) * team_count + draft_slot)
        else:
            picks.append((rnd - 1) * team_count + (team_count - draft_slot + 1))
    return picks


def simulate_survivors(
    available: list[Player],
    picks_until_next: int,
    slope: float = SIGMA_SLOPE,
    n_sims: int = 3000,
    pool_cap: int = 180,
    seed: int | None = None,
) -> dict[int, float]:
    """Monte Carlo P(available at your next pick), keyed by player_id.

    Each simulation draws a realised draft slot for every plausible player and
    treats the `picks_until_next` lowest draws as gone. Sampling jointly (rather
    than multiplying independent survival probabilities) matters: exactly
    `picks_until_next` players come off the board, so their fates are
    negatively correlated. Independent probabilities would overstate how many
    of your targets survive.
    """
    rng = random.Random(seed)
    pool = sorted(available, key=lambda p: p.adp)[:pool_cap]
    if not pool or picks_until_next <= 0:
        return {p.player_id: 1.0 for p in available}

    survived = {p.player_id: 0 for p in pool}
    params = [(p.player_id, p.adp, sigma_for(p.adp, slope)) for p in pool]
    k = min(picks_until_next, len(pool))

    for _ in range(n_sims):
        draws = [(rng.gauss(adp, sigma), pid) for pid, adp, sigma in params]
        draws.sort()
        taken = {pid for _, pid in draws[:k]}
        for pid in survived:
            if pid not in taken:
                survived[pid] += 1

    probs = {pid: c / n_sims for pid, c in survived.items()}
    # Anyone outside the plausible pool is effectively certain to survive.
    for p in available:
        probs.setdefault(p.player_id, 1.0)
    return probs
