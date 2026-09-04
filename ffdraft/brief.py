"""Weekly brief: turn a live snapshot into the handful of decisions that matter.

Deliberately narrow. A weekly report nobody reads is worse than none, so this
surfaces only things that are actionable this week: a lineup that is leaving
points on the bench, a bye that arrives before your next check-in, and an
injury designation that changed since the last poll.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from .constants import SLOT_MAP
from .models import LeagueConfig, Player
from .roster import optimal_lineup
from .season import season_coverage

BENCH_SLOTS = {"BE", "IR", "ER", ""}
HEALTHY = {"ACTIVE", "NORMAL", "PROBABLE"}


@dataclass
class Brief:
    week: int | None
    generated_at: str
    league: str
    lineup_swaps: list[dict] = field(default_factory=list)
    bye_alerts: list[dict] = field(default_factory=list)
    injury_flags: list[dict] = field(default_factory=list)
    current_points: float = 0.0
    optimal_points: float = 0.0

    @property
    def points_left_on_bench(self) -> float:
        return round(self.optimal_points - self.current_points, 1)

    @property
    def has_actions(self) -> bool:
        return bool(self.lineup_swaps or self.bye_alerts or self.injury_flags)


def _starters(roster: list[Player]) -> list[Player]:
    """Players ESPN currently has in a starting slot."""
    return [p for p in roster if (p.lineup_slot or "") not in BENCH_SLOTS]


def lineup_check(cfg: LeagueConfig, roster: list[Player]) -> tuple[float, float, list[dict]]:
    """Compare the lineup ESPN has set against the best legal one.

    Returns (current points, optimal points, swaps). A swap names who to bench
    and who to start; we only report it when the gain clears a threshold,
    because projections are not precise enough to justify churn over 0.3 points.
    """
    current = _starters(roster)
    current_pts = sum(p.proj_points for p in current)
    optimal_pts, assignment = optimal_lineup(roster, cfg)

    best = {p.player_id for players in assignment.values() for p in players}
    now = {p.player_id for p in current}

    benched_wrongly = sorted(
        [p for p in roster if p.player_id in best - now],
        key=lambda p: -p.proj_points,
    )
    started_wrongly = sorted(
        [p for p in roster if p.player_id in now - best],
        key=lambda p: p.proj_points,
    )

    swaps = []
    for bring_in, sit_down in zip(benched_wrongly, started_wrongly):
        gain = bring_in.proj_points - sit_down.proj_points
        if gain < 1.0:
            continue  # projection noise, not a decision
        swaps.append({
            "start": bring_in.name, "startPos": bring_in.position,
            "startProj": round(bring_in.proj_points, 1),
            "bench": sit_down.name, "benchPos": sit_down.position,
            "benchProj": round(sit_down.proj_points, 1),
            "gain": round(gain, 1),
        })
    return round(current_pts, 1), round(optimal_pts, 1), swaps


def bye_alerts(cfg: LeagueConfig, roster: list[Player], week: int | None,
               lookahead: int = 2) -> list[dict]:
    """Byes landing this week or within `lookahead` weeks that break a slot.

    A hole you learn about on Sunday morning is a hole. The point of the brief
    is to surface it while there is still a waiver window.
    """
    if week is None:
        return []
    alerts = []
    for cov in season_coverage(cfg, roster):
        if not (week <= cov.week <= week + lookahead):
            continue
        if cov.short:
            alerts.append({
                "week": cov.week, "severity": "short", "positions": cov.short,
                "onBye": [p.name for p in cov.on_bye],
                "weeksAway": cov.week - week,
            })
        elif cov.no_slack:
            alerts.append({
                "week": cov.week, "severity": "thin", "positions": cov.no_slack,
                "onBye": [p.name for p in cov.on_bye],
                "weeksAway": cov.week - week,
            })
    return alerts


def injury_flags(roster: list[Player], previous: dict[int, str] | None = None) -> list[dict]:
    """Non-healthy designations, marking which ones changed since the last poll."""
    flags = []
    for p in roster:
        status = (p.injury_status or "ACTIVE").upper()
        if status in HEALTHY:
            continue
        was = (previous or {}).get(p.player_id)
        flags.append({
            "name": p.name, "pos": p.position, "status": status,
            "starting": (p.lineup_slot or "") not in BENCH_SLOTS,
            "changed": bool(was and was != status),
            "previous": was,
        })
    # Starters first, then genuinely new news.
    flags.sort(key=lambda f: (not f["starting"], not f["changed"]))
    return flags


def build(cfg: LeagueConfig, roster: list[Player], week: int | None,
          previous_injuries: dict[int, str] | None = None) -> Brief:
    current_pts, optimal_pts, swaps = lineup_check(cfg, roster)
    return Brief(
        week=week,
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        league=cfg.name,
        lineup_swaps=swaps,
        bye_alerts=bye_alerts(cfg, roster, week),
        injury_flags=injury_flags(roster, previous_injuries),
        current_points=current_pts,
        optimal_points=optimal_pts,
    )


def render_markdown(b: Brief) -> str:
    """Human-readable brief. Leads with the action, not the preamble."""
    wk = f"Week {b.week}" if b.week else "Preseason"
    out = [f"# {b.league} — {wk} brief", ""]

    if not b.has_actions:
        out += ["**Nothing to do.** Lineup is optimal, no byes inside two weeks, "
                "no injury designations on the roster.", ""]
    if b.lineup_swaps:
        out += [f"## Lineup — {b.points_left_on_bench} projected points on your bench", ""]
        for s in b.lineup_swaps:
            out.append(f"- **Start {s['start']}** ({s['startPos']}, {s['startProj']}) "
                       f"over {s['bench']} ({s['benchPos']}, {s['benchProj']}) "
                       f"— **+{s['gain']}**")
        out.append("")
    elif b.current_points:
        out += [f"## Lineup is optimal ({b.current_points} projected)", ""]

    if b.bye_alerts:
        out += ["## Byes ahead", ""]
        for a in b.bye_alerts:
            away = a["weeksAway"]
            when = "this week" if away == 0 else "next week" if away == 1 else f"in {away} weeks"
            verb = ("**cannot fill " + ", ".join(a["positions"]) + "**"
                    if a["severity"] == "short"
                    else "no slack at " + ", ".join(a["positions"]))
            out.append(f"- **Week {a['week']}** ({when}) — {verb}. "
                       f"On bye: {', '.join(a['onBye'])}")
        out.append("")

    if b.injury_flags:
        out += ["## Injury designations", ""]
        for f in b.injury_flags:
            where = "STARTING" if f["starting"] else "bench"
            change = f" (was {f['previous']})" if f["changed"] else ""
            out.append(f"- {f['name']} ({f['pos']}, {where}) — **{f['status']}**{change}")
        out.append("")

    out.append(f"_Generated {b.generated_at} from the live ESPN snapshot._")
    return "\n".join(out)
