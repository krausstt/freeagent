"""League scarcity map: how every roster in the league is shaped, and what that
makes tradeable.

This is the axis ESPN does not span. Every ESPN view is about one team; nothing
in the product tells you that you are eleventh of twelve at running back while
somebody else is second and drowning in them. That comparison is where trades
come from, and the data is sitting in a single public API call.

The measurement rests on one idea: a position's value to a team is what it can
actually *start* there, and its surplus is what it holds beyond that. Five
mediocre backs are not strength. Two good ones plus a startable third is.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field, replace

from .constants import PRO_TEAM_MAP, SCORABLE, SLOT_MAP
from .models import LeagueConfig, Player
from .roster import optimal_lineup, unfilled_starter_slots

# For a "depth" trade the player I send has to out-project the one I get by this
# much before the other side plausibly reads it as an upgrade rather than a
# lateral move nobody bothers to accept.
DEPTH_MARGIN = 1.15


@dataclass
class TeamRoster:
    team_id: int
    name: str
    players: list[Player] = field(default_factory=list)


@dataclass
class PositionStrength:
    position: str
    starting: float          # VORP a team's starters actually contribute here
    surplus: float           # positive VORP sitting on the bench: tradeable
    count: int               # how many at this position are rostered
    holes: int = 0           # dedicated starting slots it cannot fill at all
    rank: int = 0            # 1 = strongest in the league
    vs_median: float = 0.0   # starting VORP minus the league median


@dataclass
class TeamProfile:
    team_id: int
    name: str
    positions: dict[str, PositionStrength]
    starting_points: float

    def weakest(self, n: int = 2) -> list[PositionStrength]:
        """The n positions furthest below the field, sign ignored.

        A team can be above the median everywhere and still have a weakest
        position worth upgrading, so this deliberately does not filter. Anything
        that reports these as *holes* has to check the sign itself -- see
        below_median().
        """
        return sorted(self.positions.values(), key=lambda s: s.vs_median)[:n]

    def below_median(self) -> list[PositionStrength]:
        """Positions actually behind the field, weakest first. May be empty."""
        return [s for s in self.weakest(len(self.positions)) if s.vs_median < 0]

    def surplus_positions(self, minimum: float = 3.0) -> list[PositionStrength]:
        return sorted(
            [s for s in self.positions.values() if s.surplus >= minimum],
            key=lambda s: -s.surplus,
        )


@dataclass
class LeagueMap:
    """Profiles, the replacement levels they were measured against, and the
    rosters they were measured from -- kept together so a caller cannot pair
    profiles built on season projections with rosters carrying weekly ones."""

    profiles: list[TeamProfile]
    replacement: dict[str, float]
    teams: list[TeamRoster]
    basis: str               # "season" or "week": what the numbers are denominated in

    def profile(self, team_id: int) -> TeamProfile | None:
        return next((p for p in self.profiles if p.team_id == team_id), None)

    def standings(self, position: str) -> list[TeamProfile]:
        """Every team at one position, strongest first."""
        return sorted(
            (p for p in self.profiles if position in p.positions),
            key=lambda p: p.positions[position].rank,
        )


# ------------------------------------------------------------------- parsing

def parse_all_teams(league_json: dict, week: int = 0) -> list[TeamRoster]:
    """Every team's roster from one mTeam+mRoster payload.

    Captures both projection horizons into their own fields. ESPN returns them
    in the same `stats` list, distinguished only by `scoringPeriodId`, and they
    differ by roughly 17x -- collapsing them into one field is how a weekly
    lineup ends up reading 2158.9 points.
    """
    out: list[TeamRoster] = []
    for team in league_json.get("teams", []) or []:
        name = (team.get("name") or "").strip() or " ".join(
            p for p in (team.get("location"), team.get("nickname")) if p
        ).strip() or f"Team {team.get('id')}"

        players: list[Player] = []
        for entry in (team.get("roster", {}) or {}).get("entries", []) or []:
            info = (entry.get("playerPoolEntry", {}) or {}).get("player", {}) or {}
            eligible = info.get("eligibleSlots", []) or []
            position = next(
                (SLOT_MAP[s] for s in eligible if SLOT_MAP.get(s) in SCORABLE), None
            )
            if position is None:
                continue  # IDP, head coach, punter: out of scope, not mis-scored

            proj_season = 0.0
            proj_week = 0.0
            for stat in info.get("stats", []) or []:
                if stat.get("statSourceId") != 1:
                    continue  # 0 == actual points already scored
                period = stat.get("scoringPeriodId")
                value = float(stat.get("appliedTotal", 0.0) or 0.0)
                if period == 0:
                    proj_season = value
                elif week and period == week:
                    proj_week = value

            players.append(Player(
                player_id=int(info.get("id", 0)),
                name=info.get("fullName", "?"),
                position=position,
                pro_team=PRO_TEAM_MAP.get(info.get("proTeamId", 0), ""),
                proj_points=proj_week,
                proj_season=proj_season,
                injury_status=info.get("injuryStatus", "ACTIVE") or "ACTIVE",
                eligible_slots=tuple(eligible),
                lineup_slot=SLOT_MAP.get(entry.get("lineupSlotId", -1), ""),
            ))
        out.append(TeamRoster(team_id=team.get("id", 0), name=name, players=players))
    return out


def _on_basis(teams: list[TeamRoster], basis: str) -> list[TeamRoster]:
    """Rosters with `proj_points` set to the requested horizon.

    The lineup optimiser reads `proj_points`, so the choice of horizon has to be
    made once, explicitly, rather than wherever a projection happens to be read.
    """
    if basis == "week":
        return teams
    if basis != "season":
        raise ValueError(f"basis must be 'season' or 'week', got {basis!r}")
    if not any(p.proj_season for t in teams for p in t.players):
        raise ValueError(
            "no season projections in this payload -- request kona_player_info "
            "or pass basis='week'"
        )
    return [
        TeamRoster(t.team_id, t.name,
                   [replace(p, proj_points=p.proj_season) for p in t.players])
        for t in teams
    ]


# --------------------------------------------------------------- measurement

def league_replacement(teams: list[TeamRoster], cfg: LeagueConfig) -> dict[str, float]:
    """Replacement level measured from the league's own rosters.

    Deliberately not the best free agent. For trade reasoning the question is
    "what would I start instead", and the answer comes from rosters, not the
    waiver wire. Concretely: the replacement at a position is the best player
    nobody in the league can fit into a starting slot -- drop below that and
    somebody is benching someone better.

    Starter counts come from running the real lineup optimiser on every team,
    so flex is allocated the way it would actually be used rather than assumed.
    """
    if not any(p.proj_points for t in teams for p in t.players):
        # Every projection zero means the horizon was never chosen: the rosters
        # went in straight from the parser. Returning a zero baseline would make
        # every team look exactly average instead of showing the mistake.
        raise ValueError(
            "rosters carry no projections -- run them through scarcity_map(), "
            "which sets the horizon, rather than measuring the parser output"
        )

    started: dict[str, int] = {pos: 0 for pos in SCORABLE}
    for team in teams:
        _, assignment = optimal_lineup(team.players, cfg)
        for players in assignment.values():
            for p in players:
                if p.position in started:
                    started[p.position] += 1

    pools: dict[str, list[float]] = {pos: [] for pos in SCORABLE}
    for team in teams:
        for p in team.players:
            if p.position in pools:
                pools[p.position].append(p.proj_points)

    levels: dict[str, float] = {}
    for pos, pool in pools.items():
        pool.sort(reverse=True)
        n = started.get(pos, 0)
        if not pool:
            levels[pos] = 0.0
        elif n < len(pool):
            # Average a small window so one outlier cannot move the baseline.
            window = pool[n:n + 3]
            levels[pos] = sum(window) / len(window)
        else:
            levels[pos] = pool[-1]
    return levels


def profile_team(
    team: TeamRoster, cfg: LeagueConfig, replacement: dict[str, float]
) -> TeamProfile:
    """Split each position into what starts and what sits behind it."""
    total, assignment = optimal_lineup(team.players, cfg)
    starting_ids = {p.player_id for players in assignment.values() for p in players}
    holes = unfilled_starter_slots(team.players, cfg)

    positions: dict[str, PositionStrength] = {}
    for pos in SCORABLE:
        at_pos = [p for p in team.players if p.position == pos]
        base = replacement.get(pos, 0.0)
        starting = sum(
            (p.proj_points - base) for p in at_pos if p.player_id in starting_ids
        )
        # An unfilled starting slot is not neutral. Leaving it empty forfeits the
        # replacement-level points anyone else in the league gets from it, so it
        # has to score below zero or a missing kicker reads the same as a bad one.
        missing = holes.get(pos, 0)
        starting -= base * missing
        # Only value above replacement counts as surplus: a benched player worse
        # than replacement is not an asset, he is a roster spot.
        surplus = sum(
            max(0.0, p.proj_points - base)
            for p in at_pos if p.player_id not in starting_ids
        )
        positions[pos] = PositionStrength(
            position=pos, starting=round(starting, 1), surplus=round(surplus, 1),
            count=len(at_pos), holes=missing,
        )
    return TeamProfile(
        team_id=team.team_id, name=team.name,
        positions=positions, starting_points=round(total, 1),
    )


def scarcity_map(
    teams: list[TeamRoster], cfg: LeagueConfig, basis: str = "season"
) -> LeagueMap:
    """Profile every team, then rank each position across the league."""
    adjusted = _on_basis(teams, basis)
    replacement = league_replacement(adjusted, cfg)
    profiles = [profile_team(t, cfg, replacement) for t in adjusted]

    for pos in SCORABLE:
        present = [p for p in profiles if pos in p.positions]
        if not present:
            continue
        median = statistics.median(p.positions[pos].starting for p in present)
        ordered = sorted(present, key=lambda p: -p.positions[pos].starting)
        for rank, prof in enumerate(ordered, start=1):
            prof.positions[pos].rank = rank
            prof.positions[pos].vs_median = round(
                prof.positions[pos].starting - median, 1
            )
    return LeagueMap(
        profiles=profiles, replacement=replacement, teams=adjusted, basis=basis
    )


# ----------------------------------------------------------------- trade ideas

@dataclass
class TradeIdea:
    partner_id: int
    partner_name: str
    give: Player
    get: Player
    my_gain: float           # projected starting points added to MY lineup
    their_gain: float        # ...and to theirs, which is why they might say yes
    rationale: str
    # Why the other side would agree. "lineup": their starters get better.
    # "depth": their starters do not change, but they swap a bench player they
    # cannot use for one worth more -- which is how most real trades actually
    # get accepted, and which a pure lineup delta scores as exactly zero.
    argument: str = "lineup"

    @property
    def mutual(self) -> float:
        return round(min(self.my_gain, self.their_gain), 1)

    @property
    def their_edge(self) -> float:
        """How many times more the other side gains. Above ~3 they accept
        instantly, which is the tell that the asset is worth more than the hole
        it fills."""
        return round(self.their_gain / self.my_gain, 1) if self.my_gain > 0 else 0.0


def trade_candidates(
    lmap: LeagueMap, cfg: LeagueConfig, my_team_id: int, limit: int = 5
) -> list[TradeIdea]:
    """Surplus-for-scarcity pairs, ranked by what they do to MY lineup.

    Not "is this trade fair". Fairness is the wrong test: the useful trade
    converts a bench player I cannot start into a starter I can, and it only
    happens if the other side also improves. Both gains are computed by actually
    re-running the lineup optimiser on both rosters, so a swap that looks good
    on paper but does not change either starting lineup scores zero.

    Two filters apply before that, both on my own side: what I offer has to be a
    bench player at a position where I hold surplus, and what I get has to be at
    a position where I am behind the field. Whether the other side wants it is
    decided by re-optimising their roster, not by guessing from their ranks.
    """
    me = next((t for t in lmap.teams if t.team_id == my_team_id), None)
    my_prof = lmap.profile(my_team_id)
    if me is None or my_prof is None:
        return []

    my_base, my_assignment = optimal_lineup(me.players, cfg)
    my_starters = {p.player_id
                   for players in my_assignment.values() for p in players}
    my_surplus = {s.position for s in my_prof.surplus_positions()}
    my_needs = {s.position for s in my_prof.weakest(3)}
    if not my_surplus or not my_needs:
        return []

    ideas: list[TradeIdea] = []
    their_starters: dict[int, set[int]] = {}
    for team in lmap.teams:
        if team.team_id == my_team_id:
            continue
        their_prof = lmap.profile(team.team_id)
        if their_prof is None:
            continue
        their_base, their_assignment = optimal_lineup(team.players, cfg)
        their_starters[team.team_id] = {
            p.player_id for ps in their_assignment.values() for p in ps
        }

        for give in me.players:
            if give.position not in my_surplus:
                continue
            # Offer from the bench only. Trading a starter away still leaves a
            # legal lineup, so the arithmetic can come out positive while the
            # trade is a fleecing -- this is how "McCaffrey for a defence"
            # scored as the top idea before the constraint went in.
            if give.player_id in my_starters:
                continue
            mine_less = [p for p in me.players if p.player_id != give.player_id]
            for get in team.players:
                if get.position not in my_needs:
                    continue

                mine_after, _ = optimal_lineup(mine_less + [get], cfg)
                my_gain = round(mine_after - my_base, 1)
                if my_gain <= 0:
                    continue
                kept = [p for p in team.players if p.player_id != get.player_id]
                theirs_after, _ = optimal_lineup(kept + [give], cfg)
                their_gain = round(theirs_after - their_base, 1)
                if their_gain < 0:
                    continue

                argument = "lineup"
                if their_gain == 0:
                    # Their starters are untouched. That is not a reason to
                    # discard the trade: if the player they send cannot crack
                    # their lineup and the one they receive out-projects him,
                    # they are trading a dead roster spot for a live one.
                    if get.player_id in their_starters[team.team_id]:
                        continue
                    if give.proj_points <= get.proj_points * DEPTH_MARGIN:
                        continue
                    argument = "depth"

                ideas.append(TradeIdea(
                    partner_id=team.team_id, partner_name=team.name,
                    give=give, get=get, my_gain=my_gain, their_gain=their_gain,
                    rationale=(
                        f"you are {my_prof.positions[get.position].rank} of "
                        f"{len(lmap.profiles)} at {get.position} and "
                        f"{my_prof.positions[give.position].rank} at "
                        f"{give.position}; they are "
                        f"{their_prof.positions[get.position].rank} and "
                        f"{their_prof.positions[give.position].rank}"
                    ),
                    argument=argument,
                ))

    # Rank by my gain, then by how likely it is to be accepted -- a trade nobody
    # takes is worth nothing however good it looks on my side. A partner whose
    # starting lineup improves says yes more readily than one being asked to see
    # the depth argument, so "lineup" outranks "depth" at equal gain to me.
    ideas.sort(key=lambda i: (-i.my_gain, 0 if i.argument == "lineup" else 1,
                              -i.their_gain))
    return ideas[:limit]
