"""Derive NFL bye weeks from ESPN's pro team schedule payload."""

from __future__ import annotations

from .constants import PRO_TEAM_MAP
from .models import Player


def bye_weeks(pro_schedule_json: dict, regular_season_weeks: int = 18) -> dict[str, int]:
    """Map pro team abbreviation -> bye week.

    ESPN returns `settings.proTeams[]`, each with a `proGamesByScoringPeriod`
    dict keyed by week. A team's bye is the regular-season week absent from
    that dict. Teams with a complete schedule get 0.
    """
    teams = (pro_schedule_json.get("settings", {}) or {}).get("proTeams", []) or []
    out: dict[str, int] = {}
    for team in teams:
        abbrev = team.get("abbrev") or PRO_TEAM_MAP.get(team.get("id", 0), "")
        if not abbrev or abbrev == "FA":
            continue
        played = {int(k) for k in (team.get("proGamesByScoringPeriod", {}) or {})}
        if not played:
            continue
        missing = [w for w in range(1, regular_season_weeks + 1) if w not in played]
        out[abbrev.upper()] = missing[0] if missing else 0
    return out


def apply_bye_weeks(players: list[Player], byes: dict[str, int]) -> int:
    """Stamp bye weeks onto players in place. Returns how many were resolved."""
    hits = 0
    for p in players:
        bye = byes.get(p.pro_team.upper(), 0)
        if bye:
            p.bye_week = bye
            hits += 1
    return hits
