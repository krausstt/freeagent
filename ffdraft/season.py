"""In-season roster analysis: bye coverage and lineup feasibility.

The draft engine answers "who should I take". This answers the question that
actually costs people games: "is there a week where I cannot field a legal
lineup, and do I know about it before it arrives?"
"""

from __future__ import annotations

from dataclasses import dataclass

from .constants import FLEX_ELIGIBILITY, SLOT_MAP
from .models import LeagueConfig, Player

# Positions where you normally carry exactly one player. A margin of zero there
# is the ordinary state, not a warning; only a negative margin is news.
SINGLE_SLOT = frozenset({"D/ST", "K"})

REGULAR_SEASON_WEEKS = 18


@dataclass
class WeekCoverage:
    week: int
    margins: dict[str, int]      # position -> spare players above requirement
    on_bye: list[Player]

    @property
    def short(self) -> list[str]:
        """Positions that cannot be filled at all this week."""
        return [pos for pos, m in self.margins.items() if m < 0]

    @property
    def no_slack(self) -> list[str]:
        """Depth positions with exactly enough players - one injury breaks them."""
        return [
            pos
            for pos, m in self.margins.items()
            if m == 0 and pos not in SINGLE_SLOT
        ]


def _requirements(cfg: LeagueConfig) -> tuple[dict[str, int], list[tuple[tuple[str, ...], int]]]:
    """Starter counts per position, plus each flex block and what may fill it.

    Flex eligibility is read from the actual slot id rather than assumed: a
    RB/WR flex and a RB/WR/TE flex draw from different pools, and treating them
    alike silently overstates your coverage.
    """
    need: dict[str, int] = {}
    flex: list[tuple[tuple[str, ...], int]] = []
    for slot, count in cfg.starter_slots.items():
        if slot in FLEX_ELIGIBILITY:
            flex.append((FLEX_ELIGIBILITY[slot], count))
            continue
        label = SLOT_MAP.get(slot, "")
        if label:
            need[label] = need.get(label, 0) + count
    return need, flex


def coverage(cfg: LeagueConfig, roster: list[Player], week: int) -> WeekCoverage:
    """Spare players above requirement at each position for one week."""
    need, flex_blocks = _requirements(cfg)

    positions = set(need) | {pos for eligible, _ in flex_blocks for pos in eligible}
    available = {
        pos: sum(1 for p in roster if p.position == pos and p.bye_week != week)
        for pos in positions
    }

    margins = {pos: available.get(pos, 0) - n for pos, n in need.items()}

    for eligible, count in flex_blocks:
        # Only positions this flex actually accepts may fill it.
        pool = sum(available.get(pos, 0) for pos in eligible)
        claimed = sum(need.get(pos, 0) for pos in eligible)
        label = "FLEX" if len(flex_blocks) == 1 else f"FLEX({'/'.join(eligible)})"
        margins[label] = pool - claimed - count

    return WeekCoverage(
        week=week,
        margins=margins,
        on_bye=[p for p in roster if p.bye_week == week],
    )


def season_coverage(
    cfg: LeagueConfig, roster: list[Player], weeks: int = REGULAR_SEASON_WEEKS
) -> list[WeekCoverage]:
    """Coverage for every week that has at least one player on bye."""
    out = []
    for week in range(1, weeks + 1):
        cov = coverage(cfg, roster, week)
        if cov.on_bye:
            out.append(cov)
    return out


def problem_weeks(cfg: LeagueConfig, roster: list[Player]) -> list[WeekCoverage]:
    """Weeks where a starting slot cannot be filled at all. Fix these first."""
    return [c for c in season_coverage(cfg, roster) if c.short]
