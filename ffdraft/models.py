"""Domain objects and ESPN JSON -> model parsing."""

from __future__ import annotations

from dataclasses import dataclass, field

from .constants import (
    BENCH_SLOTS,
    FLEX_ELIGIBILITY,
    INJURY_DISCOUNT,
    PRO_TEAM_MAP,
    SCORABLE,
    SEASON_PERIOD,
    SLOT_MAP,
    STAT_PROJECTED,
)


@dataclass
class Player:
    player_id: int
    name: str
    position: str
    pro_team: str
    # ESPN's own projection, already scored by THIS league's rules.
    # proj_points is the CURRENT WEEK in season; proj_season is the full-year
    # total. They differ by ~17x, so they must never share a field.
    proj_points: float = 0.0
    proj_season: float = 0.0
    adp: float = 0.0
    espn_rank: float = 0.0
    percent_owned: float = 0.0
    injury_status: str = "ACTIVE"
    bye_week: int = 0
    eligible_slots: tuple[int, ...] = ()
    # Where ESPN currently has this player in the lineup ("QB", "BE", "IR", ...).
    # Empty during a draft; populated by the in-season poller.
    lineup_slot: str = ""
    # Filled in by the valuation pass.
    vorp: float = 0.0
    tier: int = 0
    drafted_by: int | None = None
    drafted_at: int | None = None

    @property
    def available(self) -> bool:
        return self.drafted_by is None

    @property
    def health_factor(self) -> float:
        return INJURY_DISCOUNT.get((self.injury_status or "ACTIVE").upper(), 1.0)

    def __repr__(self) -> str:
        return f"Player({self.name}, {self.position}, proj={self.proj_points:.1f})"


@dataclass
class LeagueConfig:
    """Everything about league shape that the valuation math depends on."""

    league_id: int
    season: int
    name: str = ""
    team_count: int = 10
    roster_slots: dict[int, int] = field(default_factory=dict)  # slotId -> count
    scoring_type: str = "PPR"
    ppr: float = 1.0
    draft_type: str = "SNAKE"
    my_team_id: int | None = None
    my_draft_slot: int | None = None

    @property
    def starter_slots(self) -> dict[int, int]:
        """Slots that field a starter (bench/IR excluded)."""
        return {
            slot: n
            for slot, n in self.roster_slots.items()
            if n > 0 and slot not in BENCH_SLOTS
        }

    @property
    def dedicated_demand(self) -> dict[str, int]:
        """League-wide starter demand per position, excluding flex."""
        demand = {pos: 0 for pos in SCORABLE}
        for slot, n in self.starter_slots.items():
            label = SLOT_MAP.get(slot)
            if label in demand:
                demand[label] += n * self.team_count
        return demand

    @property
    def flex_demand(self) -> list[tuple[tuple[str, ...], int]]:
        """League-wide flex demand as (eligible positions, total slots)."""
        out = []
        for slot, n in self.starter_slots.items():
            if slot in FLEX_ELIGIBILITY:
                out.append((FLEX_ELIGIBILITY[slot], n * self.team_count))
        return out

    @property
    def roster_size(self) -> int:
        return sum(self.roster_slots.values())

    @property
    def total_picks(self) -> int:
        return self.roster_size * self.team_count


def parse_league_config(
    league_json: dict, league_id: int, season: int, my_team_id: int | None = None
) -> LeagueConfig:
    """Build a LeagueConfig from an mSettings (+optional mTeam) payload."""
    settings = league_json.get("settings", {}) or {}
    roster = (settings.get("rosterSettings", {}) or {}).get("lineupSlotCounts", {}) or {}
    slots = {int(k): int(v) for k, v in roster.items() if int(v) > 0}

    scoring = settings.get("scoringSettings", {}) or {}
    # statId 53 == "Each reception". Its point value IS the league's PPR setting,
    # so we read it rather than trusting the coarse scoringType label.
    ppr = 0.0
    for item in scoring.get("scoringItems", []) or []:
        if item.get("statId") == 53:
            ppr = float(item.get("points", 0.0) or 0.0)
            break

    draft_settings = settings.get("draftSettings", {}) or {}

    cfg = LeagueConfig(
        league_id=league_id,
        season=season,
        name=settings.get("name", ""),
        team_count=int(settings.get("size", 10) or 10),
        roster_slots=slots,
        scoring_type=scoring.get("scoringType", "") or "",
        ppr=ppr,
        draft_type=str(draft_settings.get("type", "SNAKE") or "SNAKE"),
        my_team_id=my_team_id,
    )
    if not cfg.roster_slots:
        # Never silently invent a roster: the caller must know this happened,
        # because replacement level is meaningless without real slot counts.
        raise ValueError(
            "League payload contained no rosterSettings.lineupSlotCounts. "
            "Re-fetch with view=mSettings, or pass --roster-override."
        )
    return cfg


def _primary_position(eligible: list[int], name: str) -> str | None:
    """ESPN gives a list of eligible slots; the first non-flex one is the position."""
    for slot in eligible:
        label = SLOT_MAP.get(slot)
        if label in SCORABLE:
            return label
    return None


def parse_players(pool_json: dict, season: int) -> list[Player]:
    """Turn a kona_player_info payload into Player objects.

    Projection source: the stats entry with statSourceId==1 (projected) and
    scoringPeriodId==0 (full season). Its `appliedTotal` is already scored by
    this league's own rules, which is why we read it per-league rather than
    applying a generic PPR formula.
    """
    players: list[Player] = []
    for entry in pool_json.get("players", []) or []:
        info = entry.get("player") or {}
        eligible = info.get("eligibleSlots", []) or []
        pos = _primary_position(eligible, info.get("fullName", ""))
        if pos is None:
            continue  # IDP / HC / punter - out of scope for standard redraft

        proj = 0.0
        for stat in info.get("stats", []) or []:
            if (
                stat.get("seasonId") == season
                and stat.get("statSourceId") == STAT_PROJECTED
                and stat.get("scoringPeriodId") == SEASON_PERIOD
            ):
                proj = float(stat.get("appliedTotal", 0.0) or 0.0)
                break

        ownership = info.get("ownership", {}) or {}
        adp = float(ownership.get("averageDraftPosition", 0.0) or 0.0)

        ranks = info.get("draftRanksByRankType", {}) or {}
        rank_block = ranks.get("PPR") or ranks.get("STANDARD") or {}
        espn_rank = float(rank_block.get("rank", 0.0) or 0.0)

        # An ADP of 0 means "never drafted in ESPN's sample". Fall back to the
        # rank so the availability model still has a usable prior.
        if adp <= 0:
            adp = espn_rank if espn_rank > 0 else 400.0

        players.append(
            Player(
                player_id=int(info.get("id", 0)),
                name=info.get("fullName", "?"),
                position=pos,
                pro_team=PRO_TEAM_MAP.get(info.get("proTeamId", 0), "FA"),
                proj_points=proj,
                adp=adp,
                espn_rank=espn_rank,
                percent_owned=float(ownership.get("percentOwned", 0.0) or 0.0),
                injury_status=info.get("injuryStatus", "ACTIVE") or "ACTIVE",
                eligible_slots=tuple(eligible),
            )
        )
    return players


def apply_draft_state(players: list[Player], draft_json: dict) -> int:
    """Mark already-drafted players from an mDraftDetail payload.

    Returns the number of picks applied.
    """
    detail = draft_json.get("draftDetail", {}) or {}
    picks = detail.get("picks", []) or []
    by_id = {p.player_id: p for p in players}
    applied = 0
    for pick in picks:
        pid = pick.get("playerId")
        player = by_id.get(pid)
        if player is not None:
            player.drafted_by = pick.get("teamId")
            player.drafted_at = pick.get("overallPickNumber")
            applied += 1
    return applied
