"""Bye-coverage tests, run against the real 2026 roster."""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ffdraft.models import LeagueConfig, Player  # noqa: E402
from ffdraft.season import coverage, problem_weeks, season_coverage  # noqa: E402

# 1 QB, 2 RB, 2 WR, 1 TE, 1 RB/WR flex, 1 D/ST, 1 K, 6 bench
SLOTS = {0: 1, 2: 2, 4: 2, 6: 1, 3: 1, 16: 1, 17: 1, 20: 6}


def _load_roster() -> tuple[LeagueConfig, list[Player]]:
    path = os.path.join(os.path.dirname(__file__), "..", "data", "roster_2026.json")
    data = json.load(open(path, encoding="utf-8"))
    cfg = LeagueConfig(
        league_id=0, season=2026, name=data["league"],
        team_count=data["teamCount"], roster_slots=dict(SLOTS),
    )
    roster = [
        Player(player_id=i, name=r["n"], position=r["p"], pro_team=r["t"],
               proj_points=r["w1"], bye_week=r["bye"])
        for i, r in enumerate(data["roster"])
    ]
    return cfg, roster


def test_identifies_exactly_the_two_broken_weeks():
    cfg, roster = _load_roster()
    weeks = {c.week: c.short for c in problem_weeks(cfg, roster)}
    assert set(weeks) == {9, 14}, f"expected weeks 9 and 14, got {sorted(weeks)}"
    assert weeks[9] == ["D/ST"], weeks[9]
    assert weeks[14] == ["K"], weeks[14]
    print(f"PASS broken weeks {weeks}")


def test_single_slot_positions_are_not_flagged_as_thin():
    """D/ST and K sit at margin 0 every ordinary week; that must not read as a warning."""
    cfg, roster = _load_roster()
    cov = coverage(cfg, roster, 1)  # nobody on bye in week 1
    assert cov.margins["D/ST"] == 0 and cov.margins["K"] == 0
    assert "D/ST" not in cov.no_slack and "K" not in cov.no_slack
    assert not cov.short
    print("PASS single-slot positions excluded from thin warnings")


def test_week_seven_has_no_rb_slack():
    cfg, roster = _load_roster()
    cov = coverage(cfg, roster, 7)
    assert not cov.short, f"week 7 should still be fillable, got {cov.short}"
    assert "RB" in cov.no_slack and "FLEX" in cov.no_slack, cov.no_slack
    print(f"PASS week 7 fillable but no slack at {cov.no_slack}")


def test_bench_qb_covers_the_starter_bye():
    cfg, roster = _load_roster()
    cov = coverage(cfg, roster, 10)  # Hurts on bye
    assert cov.margins["QB"] == 0 and not cov.short
    print("PASS week 10 QB covered by the backup")


def test_only_bye_weeks_are_reported():
    cfg, roster = _load_roster()
    weeks = [c.week for c in season_coverage(cfg, roster)]
    assert weeks == [6, 7, 8, 9, 10, 11, 14], weeks
    print(f"PASS reported weeks {weeks}")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
        except AssertionError as exc:
            failed += 1
            print(f"FAIL {fn.__name__}: {exc}")
    print(f"\n{len(fns)-failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
