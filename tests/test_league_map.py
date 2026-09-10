"""League scarcity map tests, run against ESPN-shaped mTeam+mRoster payloads.

The payloads are synthetic but structurally faithful: both projection horizons
in one `stats` list, actual points mixed in, eligibleSlots in ESPN's own order.
Every bug this module has had so far came from mis-reading that shape, not from
the maths.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ffdraft.league_map import (  # noqa: E402
    league_replacement, parse_all_teams, scarcity_map, trade_candidates,
)
from ffdraft.models import LeagueConfig  # noqa: E402

# Schobbetruppe's real shape: 1 QB, 2 RB, 2 WR, 1 TE, 1 RB/WR flex, D/ST, K, 6 BE
SLOTS = {0: 1, 2: 2, 4: 2, 6: 1, 3: 1, 16: 1, 17: 1, 20: 6}

# ESPN lists eligibleSlots in its own order, flex ids included. The parser has to
# pick the dedicated position out of that, not the first id it recognises.
ELIGIBLE = {
    "QB": [0, 7, 20, 21],
    "RB": [2, 3, 23, 7, 20, 21],
    "WR": [3, 4, 5, 23, 7, 20, 21],
    "TE": [5, 6, 23, 7, 20, 21],
    "K": [17, 20, 21],
    "D/ST": [16, 20, 21],
}

_next_id = [1000]


def _cfg(team_count: int = 12, my_team_id: int = 1) -> LeagueConfig:
    return LeagueConfig(
        league_id=461530087, season=2026, name="Schobbetruppe",
        team_count=team_count, roster_slots=dict(SLOTS),
        scoring_type="PPR", ppr=0.5, my_team_id=my_team_id,
    )


def _entry(pos: str, season_pts: float, week_pts: float = 0.0, slot: int = 20) -> dict:
    _next_id[0] += 1
    pid = _next_id[0]
    return {
        "lineupSlotId": slot,
        "playerPoolEntry": {"player": {
            "id": pid,
            "fullName": f"{pos}-{pid}",
            "proTeamId": 12,
            "injuryStatus": "ACTIVE",
            "eligibleSlots": list(ELIGIBLE[pos]),
            "stats": [
                # Actual points first: statSourceId 0 must never be read as a projection.
                {"statSourceId": 0, "scoringPeriodId": 0, "appliedTotal": 41.7},
                {"statSourceId": 1, "scoringPeriodId": 0, "appliedTotal": season_pts},
                {"statSourceId": 1, "scoringPeriodId": 1, "appliedTotal": week_pts},
            ],
        }},
    }


def _team(team_id: int, name: str, spec: list[tuple[str, float]]) -> dict:
    return {
        "id": team_id, "name": name,
        "roster": {"entries": [_entry(pos, pts) for pos, pts in spec]},
    }


def _balanced(pos_scale: float = 1.0) -> list[tuple[str, float]]:
    """A roster that fills every slot at roughly league-average strength."""
    return [
        ("QB", 300.0 * pos_scale),
        ("RB", 200.0 * pos_scale), ("RB", 170.0 * pos_scale), ("RB", 120.0 * pos_scale),
        ("WR", 210.0 * pos_scale), ("WR", 180.0 * pos_scale), ("WR", 140.0 * pos_scale),
        ("TE", 130.0 * pos_scale), ("K", 135.0), ("D/ST", 120.0),
        ("QB", 210.0), ("WR", 95.0), ("RB", 80.0), ("TE", 70.0),
    ]


def _league(*extra_teams: dict) -> dict:
    """A twelve-team league: the given teams, padded with average ones."""
    teams = list(extra_teams)
    for i in range(len(teams) + 1, 13):
        teams.append(_team(i, f"Average {i}", _balanced(1.0 + (i - 6) * 0.01)))
    return {"teams": teams}


# --------------------------------------------------------------------- parsing

def test_keeps_the_two_projection_horizons_apart():
    payload = {"teams": [_team(1, "Mine", [("RB", 262.4)])]}
    payload["teams"][0]["roster"]["entries"][0][
        "playerPoolEntry"]["player"]["stats"][2]["appliedTotal"] = 15.4

    teams = parse_all_teams(payload, week=1)
    p = teams[0].players[0]
    assert p.proj_season == 262.4, p.proj_season
    assert p.proj_points == 15.4, p.proj_points
    assert p.position == "RB", p.position
    print(f"PASS horizons kept apart: season={p.proj_season} week={p.proj_points}")


def test_week_zero_does_not_borrow_the_season_total():
    """Without a week, proj_points stays empty rather than silently holding 2158.9."""
    teams = parse_all_teams({"teams": [_team(1, "Mine", [("RB", 262.4)])]})
    assert teams[0].players[0].proj_points == 0.0
    assert teams[0].players[0].proj_season == 262.4
    print("PASS no week requested -> weekly projection left empty")


def test_out_of_scope_players_are_dropped_not_mis_scored():
    payload = {"teams": [{"id": 1, "name": "Mine", "roster": {"entries": [
        _entry("RB", 200.0),
        {"lineupSlotId": 20, "playerPoolEntry": {"player": {
            "id": 99, "fullName": "Some Coach", "eligibleSlots": [19, 20],
            "stats": [{"statSourceId": 1, "scoringPeriodId": 0, "appliedTotal": 500.0}],
        }}},
    ]}}]}
    teams = parse_all_teams(payload)
    assert [p.position for p in teams[0].players] == ["RB"]
    print("PASS head coach dropped, not scored as a flex")


# ----------------------------------------------------------------- measurement

def test_five_mediocre_backs_do_not_outrank_two_good_ones():
    hoarder = _team(1, "Hoarder", [
        ("QB", 300.0),
        ("RB", 130.0), ("RB", 125.0), ("RB", 120.0), ("RB", 115.0), ("RB", 110.0),
        ("WR", 210.0), ("WR", 180.0), ("TE", 130.0), ("K", 135.0), ("D/ST", 120.0),
    ])
    sharp = _team(2, "Sharp", [
        ("QB", 300.0),
        ("RB", 285.0), ("RB", 240.0), ("RB", 150.0),
        ("WR", 210.0), ("WR", 180.0), ("TE", 130.0), ("K", 135.0), ("D/ST", 120.0),
    ])
    lmap = scarcity_map(parse_all_teams(_league(hoarder, sharp)), _cfg())
    h = lmap.profile(1).positions["RB"]
    s = lmap.profile(2).positions["RB"]

    assert h.count > s.count, "the hoarder should hold more backs"
    assert s.starting > h.starting, f"sharp {s.starting} should beat hoarder {h.starting}"
    assert s.rank < h.rank, f"sharp rank {s.rank} should be better than {h.rank}"
    print(f"PASS 5 mediocre RBs ({h.count} held, {h.starting} starting, rank {h.rank}) "
          f"lose to 3 good ones ({s.count} held, {s.starting}, rank {s.rank})")


def test_surplus_counts_only_value_above_replacement():
    """Bench depth below replacement is a roster spot, not a trade asset."""
    deadweight = _team(1, "Deadweight", [
        ("QB", 300.0), ("RB", 200.0), ("RB", 170.0), ("RB", 120.0),
        ("WR", 210.0), ("WR", 180.0), ("TE", 130.0), ("K", 135.0), ("D/ST", 120.0),
        ("TE", 5.0), ("TE", 4.0), ("TE", 3.0),          # three unstartable tight ends
    ])
    lmap = scarcity_map(parse_all_teams(_league(deadweight)), _cfg())
    te = lmap.profile(1).positions["TE"]
    assert te.count == 4, te.count
    assert te.surplus == 0.0, f"unstartable bench should be worth nothing, got {te.surplus}"
    print(f"PASS 3 unstartable TEs held -> surplus {te.surplus}")


def test_an_empty_starting_slot_scores_below_replacement():
    """A missing kicker must not read the same as a bad kicker."""
    no_kicker = _team(1, "No Kicker", [
        ("QB", 300.0), ("RB", 200.0), ("RB", 170.0), ("RB", 120.0),
        ("WR", 210.0), ("WR", 180.0), ("TE", 130.0), ("D/ST", 120.0),
    ])
    bad_kicker = _team(2, "Bad Kicker", [
        ("QB", 300.0), ("RB", 200.0), ("RB", 170.0), ("RB", 120.0),
        ("WR", 210.0), ("WR", 180.0), ("TE", 130.0), ("D/ST", 120.0), ("K", 100.0),
    ])
    lmap = scarcity_map(parse_all_teams(_league(no_kicker, bad_kicker)), _cfg())
    empty = lmap.profile(1).positions["K"]
    bad = lmap.profile(2).positions["K"]

    assert empty.holes == 1, empty.holes
    assert empty.starting < bad.starting, f"empty {empty.starting} vs bad {bad.starting}"
    assert empty.starting < 0, empty.starting
    assert empty.rank > bad.rank, f"empty rank {empty.rank} vs bad {bad.rank}"
    print(f"PASS empty K slot {empty.starting} ranks below a weak kicker {bad.starting}")


def test_replacement_sits_below_the_worst_starter_in_the_league():
    replacement = scarcity_map(parse_all_teams(_league()), _cfg()).replacement
    for pos in ("QB", "RB", "WR", "TE"):
        assert replacement[pos] > 0, f"{pos} replacement {replacement[pos]}"
    # With 12 teams starting one QB each, the QB baseline must land in the
    # backup tier -- above nothing, but well below a starting quarterback.
    assert replacement["QB"] < 300.0, replacement["QB"]
    print("PASS replacement levels " +
          ", ".join(f"{k}={v:.0f}" for k, v in sorted(replacement.items())))


def test_measuring_unconverted_rosters_raises_instead_of_zeroing():
    """The parser leaves proj_points empty; a zero baseline would hide that."""
    teams = parse_all_teams(_league())          # no week, no basis conversion
    try:
        league_replacement(teams, _cfg())
    except ValueError as exc:
        assert "no projections" in str(exc), exc
        print(f"PASS refused unconverted rosters: {exc}")
        return
    raise AssertionError("expected a ValueError rather than an all-zero baseline")


def test_basis_season_refuses_a_payload_with_no_season_projections():
    payload = {"teams": [_team(1, "Mine", [("RB", 0.0)])]}
    try:
        scarcity_map(parse_all_teams(payload, week=1), _cfg())
    except ValueError as exc:
        assert "season projections" in str(exc), exc
        print(f"PASS refused silently-zero payload: {exc}")
        return
    raise AssertionError("expected a ValueError rather than an all-zero map")


def test_weakest_is_not_the_same_question_as_behind_the_field():
    """Rank 2 of 12 and above median is not a hole, however it sorts."""
    strong = _team(1, "Strong Everywhere", [
        ("QB", 340.0),
        ("RB", 300.0), ("RB", 270.0), ("RB", 240.0),
        ("WR", 300.0), ("WR", 280.0), ("WR", 250.0),
        ("TE", 220.0), ("K", 160.0), ("D/ST", 150.0),
    ])
    lmap = scarcity_map(parse_all_teams(_league(strong)), _cfg())
    prof = lmap.profile(1)
    assert prof.weakest(2), "weakest always returns something to aim at"
    assert prof.below_median() == [], (
        "a team above the median everywhere has no holes: "
        f"{[(s.position, s.vs_median) for s in prof.below_median()]}")

    holed = _team(1, "One Hole", [
        ("QB", 340.0), ("RB", 300.0), ("RB", 270.0), ("RB", 240.0),
        ("WR", 300.0), ("WR", 280.0), ("WR", 250.0),
        ("TE", 220.0), ("K", 160.0),
    ])
    lmap2 = scarcity_map(parse_all_teams(_league(holed)), _cfg())
    behind = lmap2.profile(1).below_median()
    assert [s.position for s in behind] == ["D/ST"], [s.position for s in behind]
    print("PASS above-median team reports no holes; a missing D/ST reports one")


def test_ranks_cover_every_team_exactly_once():
    lmap = scarcity_map(parse_all_teams(_league()), _cfg())
    assert len(lmap.profiles) == 12, len(lmap.profiles)
    for pos in ("QB", "RB", "WR", "TE", "K", "D/ST"):
        ranks = sorted(p.positions[pos].rank for p in lmap.profiles)
        assert ranks == list(range(1, 13)), (pos, ranks)
    assert lmap.standings("RB")[0].positions["RB"].rank == 1
    print("PASS every position ranked 1..12 with no ties or gaps")


# ---------------------------------------------------------------------- trades

def test_no_trade_when_neither_starting_lineup_changes():
    """Two identical benchwarmers swapping hands is not a trade."""
    mine = _team(1, "Mine", _balanced() + [("K", 40.0)])
    theirs = _team(2, "Theirs", _balanced() + [("K", 40.0)])
    lmap = scarcity_map(parse_all_teams(_league(mine, theirs)), _cfg())
    for idea in trade_candidates(lmap, _cfg(), my_team_id=1):
        assert idea.my_gain > 0 and idea.their_gain > 0, idea
    ideas = [i for i in trade_candidates(lmap, _cfg(), my_team_id=1)
             if i.give.proj_points < 50 and i.get.proj_points < 50]
    assert not ideas, f"bench-for-bench swap proposed: {ideas}"
    print("PASS no trade proposed for a swap that changes neither lineup")


def test_complementary_pair_improves_both_lineups():
    """I am deep at RB and empty at WR; they are the mirror image."""
    mine = _team(1, "Mine", [
        ("QB", 300.0),
        ("RB", 285.0), ("RB", 250.0), ("RB", 240.0), ("RB", 230.0),
        ("WR", 120.0), ("WR", 60.0), ("WR", 55.0),
        ("TE", 130.0), ("K", 135.0), ("D/ST", 120.0),
    ])
    partner = _team(2, "Partner", [
        ("QB", 300.0),
        ("RB", 110.0), ("RB", 70.0), ("RB", 65.0),
        ("WR", 290.0), ("WR", 265.0), ("WR", 255.0), ("WR", 245.0),
        ("TE", 130.0), ("K", 135.0), ("D/ST", 120.0),
    ])
    cfg = _cfg()
    lmap = scarcity_map(parse_all_teams(_league(mine, partner)), cfg)
    ideas = trade_candidates(lmap, cfg, my_team_id=1)

    assert ideas, "a mirrored RB/WR pair should produce at least one trade"
    top = ideas[0]
    assert top.partner_id == 2, f"partner should be team 2, got {top.partner_id}"
    assert top.give.position == "RB" and top.get.position == "WR", (top.give, top.get)
    assert top.my_gain > 0 and top.their_gain > 0, top
    assert top.mutual == min(top.my_gain, top.their_gain)
    # The optimiser, not the heuristic, decides: verify the arithmetic directly.
    from ffdraft.roster import optimal_lineup
    me = next(t for t in lmap.teams if t.team_id == 1)
    before, _ = optimal_lineup(me.players, cfg)
    after, _ = optimal_lineup(
        [p for p in me.players if p.player_id != top.give.player_id] + [top.get], cfg
    )
    assert round(after - before, 1) == top.my_gain, (after - before, top.my_gain)
    print(f"PASS trade: give {top.give.name} ({top.give.position}) for "
          f"{top.get.name} ({top.get.position}) -> me +{top.my_gain}, "
          f"them +{top.their_gain}")


def test_never_offers_a_starter_however_good_the_arithmetic_looks():
    """The McCaffrey-for-a-defence bug: dealing an RB1 away leaves a legal
    lineup, so the gain came out positive while the trade was a fleecing."""
    mine = _team(1, "Mine", [
        ("QB", 300.0),
        ("RB", 340.0), ("RB", 250.0), ("RB", 245.0), ("RB", 240.0),
        ("WR", 210.0), ("WR", 180.0), ("WR", 140.0),
        ("TE", 130.0), ("K", 135.0),                      # no D/ST at all
    ])
    partner = _team(2, "Partner", [
        ("QB", 300.0), ("RB", 90.0), ("RB", 70.0),
        ("WR", 210.0), ("WR", 180.0), ("WR", 140.0),
        ("TE", 130.0), ("K", 135.0), ("D/ST", 150.0), ("D/ST", 145.0),
    ])
    cfg = _cfg()
    lmap = scarcity_map(parse_all_teams(_league(mine, partner)), cfg)
    me = next(t for t in lmap.teams if t.team_id == 1)
    from ffdraft.roster import optimal_lineup
    _, assignment = optimal_lineup(me.players, cfg)
    starters = {p.player_id for ps in assignment.values() for p in ps}
    best_rb = max((p for p in me.players if p.position == "RB"),
                  key=lambda p: p.proj_points)

    ideas = trade_candidates(lmap, cfg, my_team_id=1, limit=10)
    offered = {i.give.player_id for i in ideas}
    assert best_rb.player_id not in offered, "offered the RB1"
    assert not (offered & starters), "offered a starter"
    if ideas:
        print(f"PASS {len(ideas)} ideas, none offering a starter "
              f"(RB1 {best_rb.name} withheld); best offers "
              f"{ideas[0].give.name} at {ideas[0].give.proj_points:.0f}")
    else:
        print("PASS no starter offered (no bench-only trade available)")


def test_finds_the_depth_trade_a_pure_lineup_delta_scores_as_zero():
    """A rival's third defence is worth 0 to his starters, so nothing I offer can
    'improve' his lineup -- yet he will take a bench QB for it every time."""
    mine = _team(1, "Mine", [
        ("QB", 330.0), ("RB", 250.0), ("RB", 240.0), ("RB", 230.0),
        ("WR", 260.0), ("WR", 240.0), ("WR", 220.0), ("TE", 200.0), ("K", 150.0),
        ("QB", 265.0),                                   # bench QB, real value
    ])                                                   # ...and no D/ST at all
    partner = _team(2, "Partner", [
        ("QB", 340.0), ("RB", 250.0), ("RB", 240.0), ("RB", 230.0),
        ("WR", 260.0), ("WR", 240.0), ("WR", 220.0), ("TE", 200.0), ("K", 150.0),
        ("QB", 200.0),                                   # worse than my bench QB
        ("D/ST", 150.0), ("D/ST", 140.0),                # one of them is dead weight
    ])
    cfg = _cfg()
    lmap = scarcity_map(parse_all_teams(_league(mine, partner)), cfg)
    ideas = [i for i in trade_candidates(lmap, cfg, my_team_id=1, limit=10)
             if i.partner_id == 2]
    assert ideas, "the spare-defence trade should be found"
    top = ideas[0]
    assert top.get.position == "D/ST", top.get.position
    assert top.argument == "depth", top.argument
    assert top.their_gain == 0.0, top.their_gain
    assert top.my_gain > 0, top.my_gain
    # And the player they send must be one they genuinely cannot start.
    from ffdraft.roster import optimal_lineup
    them = next(t for t in lmap.teams if t.team_id == 2)
    _, assignment = optimal_lineup(them.players, cfg)
    starters = {p.player_id for ps in assignment.values() for p in ps}
    assert top.get.player_id not in starters, "asked them for a starter for free"
    print(f"PASS depth trade found: {top.give.name} for {top.get.name}, "
          f"me +{top.my_gain}, their starters unchanged")


def test_depth_trade_needs_a_real_upgrade_not_a_lateral_move():
    """Equal-value bench swaps are noise; nobody accepts them."""
    mine = _team(1, "Mine", [
        ("QB", 330.0), ("RB", 250.0), ("RB", 240.0), ("RB", 230.0),
        ("WR", 260.0), ("WR", 240.0), ("WR", 220.0), ("TE", 200.0), ("K", 150.0),
        ("QB", 201.0),                        # barely better than theirs
    ])
    partner = _team(2, "Partner", [
        ("QB", 340.0), ("RB", 250.0), ("RB", 240.0), ("RB", 230.0),
        ("WR", 260.0), ("WR", 240.0), ("WR", 220.0), ("TE", 200.0), ("K", 150.0),
        ("QB", 200.0), ("D/ST", 150.0), ("D/ST", 140.0),
    ])
    cfg = _cfg()
    lmap = scarcity_map(parse_all_teams(_league(mine, partner)), cfg)
    lateral = [i for i in trade_candidates(lmap, cfg, my_team_id=1, limit=10)
               if i.partner_id == 2 and i.argument == "depth"
               and i.give.proj_points <= i.get.proj_points * 1.15]
    assert not lateral, f"proposed a lateral bench swap: {lateral}"
    print("PASS lateral bench swap not proposed")


def test_asymmetry_is_disclosed_not_hidden():
    mine = _team(1, "Mine", [
        ("QB", 300.0), ("RB", 240.0), ("RB", 235.0), ("RB", 230.0), ("RB", 225.0),
        ("WR", 210.0), ("WR", 180.0), ("WR", 140.0), ("TE", 130.0), ("K", 135.0),
    ])
    partner = _team(2, "Partner", [
        ("QB", 300.0), ("RB", 60.0), ("RB", 55.0),
        ("WR", 210.0), ("WR", 180.0), ("WR", 140.0),
        ("TE", 130.0), ("K", 135.0), ("D/ST", 130.0), ("D/ST", 125.0),
    ])
    cfg = _cfg()
    lmap = scarcity_map(parse_all_teams(_league(mine, partner)), cfg)
    ideas = trade_candidates(lmap, cfg, my_team_id=1, limit=5)
    assert ideas, "a bench RB for a spare D/ST should be findable"
    for i in ideas:
        assert i.their_edge == round(i.their_gain / i.my_gain, 1), i.their_edge
    top = ideas[0]
    print(f"PASS asymmetry reported: they gain {top.their_edge}x more "
          f"(me +{top.my_gain}, them +{top.their_gain})")


def test_trades_are_ranked_by_my_own_gain():
    mine = _team(1, "Mine", [
        ("QB", 300.0),
        ("RB", 285.0), ("RB", 250.0), ("RB", 240.0), ("RB", 230.0),
        ("WR", 120.0), ("WR", 60.0), ("WR", 55.0),
        ("TE", 130.0), ("K", 135.0), ("D/ST", 120.0),
    ])
    partner = _team(2, "Partner", [
        ("QB", 300.0), ("RB", 110.0), ("RB", 70.0), ("RB", 65.0),
        ("WR", 290.0), ("WR", 265.0), ("WR", 255.0), ("WR", 245.0),
        ("TE", 130.0), ("K", 135.0), ("D/ST", 120.0),
    ])
    cfg = _cfg()
    lmap = scarcity_map(parse_all_teams(_league(mine, partner)), cfg)
    ideas = trade_candidates(lmap, cfg, my_team_id=1, limit=8)
    gains = [i.my_gain for i in ideas]
    assert gains == sorted(gains, reverse=True), gains
    assert len(ideas) <= 8
    print(f"PASS {len(ideas)} ideas ranked by my gain: {gains}")


def test_unknown_team_id_returns_nothing_rather_than_guessing():
    lmap = scarcity_map(parse_all_teams(_league()), _cfg())
    assert trade_candidates(lmap, _cfg(), my_team_id=999) == []
    print("PASS unknown team id -> no ideas")


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(list(globals().items())):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
            except AssertionError as exc:
                failures += 1
                print(f"FAIL {name}: {exc}")
    print(f"\n{'FAILURES: ' + str(failures) if failures else 'all league-map tests pass'}")
    sys.exit(1 if failures else 0)
