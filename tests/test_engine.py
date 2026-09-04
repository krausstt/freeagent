"""Tests for the valuation, availability and board layers.

Run: python3 -m pytest tests/ -q     (or: python3 tests/test_engine.py)
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ffdraft.availability import (  # noqa: E402
    calibrate_sigma,
    sigma_for,
    snake_picks,
    survival_probability,
)
from ffdraft.board import DraftBoard  # noqa: E402
from ffdraft.models import Player  # noqa: E402
from ffdraft.roster import optimal_lineup, unfilled_starter_slots  # noqa: E402
from ffdraft.valuation import _jenks_breaks, compute_vorp, starter_demand  # noqa: E402
from tests.fixtures import make_config, make_players  # noqa: E402


def test_snake_picks():
    # 10-team league, slot 3: round 1 pick 3, round 2 pick 18, round 3 pick 23.
    assert snake_picks(3, 10, 3) == [3, 18, 23]
    # Slot 1 and slot 10 are the classic turn.
    assert snake_picks(1, 10, 2) == [1, 20]
    assert snake_picks(10, 10, 2) == [10, 11]
    print("PASS test_snake_picks")


def test_starter_demand_includes_flex():
    cfg = make_config(team_count=10)
    players = make_players()
    demand = starter_demand(cfg, players)
    # 10 teams x 2 RB = 20 dedicated RB, x2 WR = 20 dedicated WR.
    # The 10 FLEX slots must be distributed on top of that.
    assert demand["QB"] == 10
    assert demand["RB"] >= 20 and demand["WR"] >= 20
    total_flex_added = (demand["RB"] - 20) + (demand["WR"] - 20) + (demand["TE"] - 10)
    assert total_flex_added == 10, f"flex should add exactly 10 starters, got {total_flex_added}"
    print(f"PASS test_starter_demand_includes_flex {demand}")


def test_vorp_ordering_and_replacement():
    cfg = make_config()
    players = make_players()
    levels = compute_vorp(cfg, players)
    # Replacement level must be positive and below the positional best.
    for pos, lvl in levels.items():
        best = max(p.proj_points for p in players if p.position == pos)
        assert 0 < lvl < best, f"{pos}: replacement {lvl} not between 0 and {best}"
    # A kicker must never out-rank an elite RB by VORP even though K1 scores
    # more raw points than RB40 -- this is the whole point of VORP.
    best_rb = max(p.vorp for p in players if p.position == "RB")
    best_k = max(p.vorp for p in players if p.position == "K")
    assert best_rb > best_k * 3, f"RB {best_rb:.1f} should dwarf K {best_k:.1f}"
    print(f"PASS test_vorp_ordering_and_replacement levels={ {k: round(v,1) for k,v in levels.items()} }")


def test_jenks_breaks_finds_real_gaps():
    # Three obvious clusters separated by large gaps.
    values = [100.0, 98.0, 97.0, 60.0, 58.0, 57.0, 20.0, 18.0]
    breaks = _jenks_breaks(values, 3)
    assert breaks == [3, 6], f"expected class starts at 3 and 6, got {breaks}"
    print("PASS test_jenks_breaks_finds_real_gaps")


def test_survival_monotonic():
    p = Player(player_id=1, name="X", position="RB", pro_team="KC", adp=20.0)
    # The later the pick, the less likely he survives to it.
    probs = [survival_probability(p, n) for n in (10, 20, 30, 40)]
    assert probs == sorted(probs, reverse=True), probs
    # At his own ADP it should be near a coin flip.
    assert 0.4 < survival_probability(p, 20) < 0.6
    print(f"PASS test_survival_monotonic {[round(x,3) for x in probs]}")


def test_sigma_calibration_reacts_to_a_wild_room():
    players = make_players()
    # Simulate a room that drafts almost exactly to ADP.
    for i, p in enumerate(sorted(players, key=lambda x: x.adp)[:40]):
        p.drafted_at = int(p.adp)
        p.drafted_by = 1
    tight = calibrate_sigma(players)

    players2 = make_players()
    for i, p in enumerate(sorted(players2, key=lambda x: x.adp)[:40]):
        p.drafted_at = int(p.adp) + (25 if i % 2 == 0 else -25)
        p.drafted_by = 1
    wild = calibrate_sigma(players2)

    assert wild > tight, f"chaotic room ({wild:.3f}) must widen sigma vs tight ({tight:.3f})"
    print(f"PASS test_sigma_calibration tight={tight:.3f} wild={wild:.3f}")


def test_optimal_lineup_respects_slots():
    cfg = make_config()
    players = make_players()
    by_name = {p.name: p for p in players}
    # Five RBs, nothing else: only 2 RB + 1 FLEX may start.
    roster = [by_name[f"RB{i}"] for i in range(1, 6)]
    total, assignment = optimal_lineup(roster, cfg)
    started = sum(len(v) for v in assignment.values())
    assert started == 3, f"only 2 RB + 1 FLEX can start, got {started}"
    expected = sum(p.proj_points for p in roster[:3])
    assert abs(total - expected) < 0.01
    print(f"PASS test_optimal_lineup_respects_slots started={started} pts={total:.1f}")


def test_unfilled_starter_slots():
    cfg = make_config()
    players = make_players()
    by_name = {p.name: p for p in players}
    need = unfilled_starter_slots([], cfg)
    assert need["RB"] == 2 and need["WR"] == 2 and need["QB"] == 1
    need2 = unfilled_starter_slots([by_name["QB1"], by_name["RB1"]], cfg)
    assert need2["QB"] == 0 and need2["RB"] == 1
    print("PASS test_unfilled_starter_slots")


def test_board_recommends_and_explains():
    cfg = make_config(my_slot=4)
    players = make_players()
    board = DraftBoard(cfg, players, n_sims=400)
    recs = board.recommend(top_n=5)
    assert len(recs) == 5
    assert all(r.reasons for r in recs), "every recommendation must be explained"
    # Scores must be sorted descending.
    scores = [r.score for r in recs]
    assert scores == sorted(scores, reverse=True)
    # With an empty roster and pick 4 overall, the top rec should be a premium
    # skill position, never a kicker or defense.
    assert recs[0].player.position in ("RB", "WR", "TE", "QB")
    print(f"PASS test_board_recommends_and_explains top={recs[0].player.name} "
          f"score={recs[0].score:.1f} pos={recs[0].player.position}")


def test_board_avoids_stacking_covered_positions():
    cfg = make_config(my_slot=1)
    players = make_players()
    by_name = {p.name: p for p in players}
    # Give ourselves an already-elite QB; the engine should stop valuing QBs.
    by_name["QB1"].drafted_by = 1
    by_name["QB1"].drafted_at = 1
    board = DraftBoard(cfg, players, n_sims=400)
    recs = board.recommend(top_n=8)
    positions = [r.player.position for r in recs]
    assert positions.count("QB") <= 1, f"should not chase QBs after QB1: {positions}"
    print(f"PASS test_board_avoids_stacking_covered_positions {positions}")


def test_survival_is_jointly_consistent():
    """Exactly `gap` players leave the board, so survival probabilities must sum
    to (pool - gap), not to something inflated by independence."""
    from ffdraft.vona import simulate_gap

    cfg = make_config()
    players = make_players()
    compute_vorp(cfg, players)
    gap = 15
    survival, fallback = simulate_gap(players, gap, n_sims=800, pool_cap=100)
    pooled = sorted(players, key=lambda p: p.adp)[:100]
    expected_survivors = len(pooled) - gap
    actual = sum(survival[p.player_id] for p in pooled)
    assert abs(actual - expected_survivors) < 1.0, (
        f"expected ~{expected_survivors} survivors, model says {actual:.2f}"
    )
    assert all(v >= 0 for v in fallback.values())
    print(f"PASS test_survival_is_jointly_consistent survivors={actual:.2f} "
          f"expected={expected_survivors}")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
        except AssertionError as exc:
            failed += 1
            print(f"FAIL {fn.__name__}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"ERROR {fn.__name__}: {type(exc).__name__}: {exc}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
