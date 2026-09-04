"""Weekly brief tests, driven off the real 2026 roster."""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ffdraft.brief import bye_alerts, build, injury_flags, lineup_check, render_markdown  # noqa: E402
from ffdraft.models import LeagueConfig, Player  # noqa: E402

SLOTS = {0: 1, 2: 2, 4: 2, 6: 1, 3: 1, 16: 1, 17: 1, 20: 6}
STARTING = {"QB": "QB", "RB": "RB", "WR": "WR", "TE": "TE", "D/ST": "D/ST", "K": "K"}


def _load(optimal: bool = True):
    path = os.path.join(os.path.dirname(__file__), "..", "data", "roster_2026.json")
    data = json.load(open(path, encoding="utf-8"))
    cfg = LeagueConfig(league_id=0, season=2026, name=data["league"],
                       team_count=data["teamCount"], roster_slots=dict(SLOTS))
    roster = []
    for i, r in enumerate(data["roster"]):
        slot = r["slot"]
        if slot == "FLEX":
            slot = "RB/WR"
        roster.append(Player(
            player_id=i, name=r["n"], position=r["p"], pro_team=r["t"],
            proj_points=r["w1"], bye_week=r["bye"],
            injury_status="QUESTIONABLE" if r.get("q") else "ACTIVE",
            lineup_slot=slot if optimal else "BE"))
    return cfg, roster


def test_optimal_lineup_reports_no_swaps():
    cfg, roster = _load(optimal=True)
    cur, opt, swaps = lineup_check(cfg, roster)
    assert not swaps, f"ESPN's lineup is already optimal; got {swaps}"
    assert abs(cur - 117.5) < 0.1, cur
    print(f"PASS optimal lineup {cur} == best {opt}, no swaps")


def test_detects_a_genuinely_bad_lineup():
    """Bench the top RB and start the worst one; the brief must catch it."""
    cfg, roster = _load(optimal=True)
    by = {p.name: p for p in roster}
    by["Omarion Hampton"].lineup_slot = "BE"          # 17.5 benched
    by["Jacory Croskey-Merritt"].lineup_slot = "RB"   # 7.3 started
    cur, opt, swaps = lineup_check(cfg, roster)
    assert swaps, "should have flagged the swap"
    top = swaps[0]
    assert top["start"] == "Omarion Hampton" and top["bench"] == "Jacory Croskey-Merritt"
    assert abs(top["gain"] - 10.2) < 0.1, top
    assert opt > cur
    print(f"PASS caught bad lineup: start {top['start']} over {top['bench']} (+{top['gain']})")


def test_ignores_sub_point_noise():
    """Projections are not precise enough to justify churn over a fraction of a point."""
    cfg, roster = _load(optimal=True)
    by = {p.name: p for p in roster}
    by["Malik Nabers"].proj_points = 14.5    # starter
    by["Michael Wilson"].proj_points = 14.9  # bench, only +0.4 better
    by["Malik Nabers"].lineup_slot = "WR"
    by["Michael Wilson"].lineup_slot = "BE"
    _, _, swaps = lineup_check(cfg, roster)
    assert not any(s["gain"] < 1.0 for s in swaps), swaps
    print("PASS sub-point differences do not generate advice")


def test_bye_alert_fires_before_the_hole_arrives():
    cfg, roster = _load()
    at7 = bye_alerts(cfg, roster, week=7)
    assert any(a["week"] == 9 and a["severity"] == "short" for a in at7), at7
    # ...and is silent when the hole is still far away.
    at3 = bye_alerts(cfg, roster, week=3)
    assert not any(a["week"] == 9 for a in at3), at3
    print(f"PASS week 9 D/ST hole surfaces at week 7, silent at week 3")


def test_injury_flags_mark_changes_and_rank_starters_first():
    cfg, roster = _load()
    prev = {p.player_id: "ACTIVE" for p in roster}
    flags = injury_flags(roster, prev)
    assert flags and all(f["status"] == "QUESTIONABLE" for f in flags)
    assert flags[0]["starting"], "starters must sort above bench"
    assert any(f["changed"] for f in flags), "ACTIVE -> QUESTIONABLE must read as changed"
    print(f"PASS {len(flags)} injury flags, starters first, changes marked")


def test_markdown_renders_and_leads_with_the_action():
    cfg, roster = _load(optimal=True)
    by = {p.name: p for p in roster}
    by["Omarion Hampton"].lineup_slot = "BE"
    by["Jacory Croskey-Merritt"].lineup_slot = "RB"
    text = render_markdown(build(cfg, roster, week=8))
    assert "Start Omarion Hampton" in text
    assert "Week 9" in text, "the upcoming D/ST hole must appear"
    assert text.startswith("# "), text[:40]
    print("PASS markdown renders with lineup swap and bye alert")


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
    print(f"\n{len(fns)-failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
