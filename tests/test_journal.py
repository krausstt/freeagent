"""Decision journal tests: the point is that process and result are judged apart."""

from __future__ import annotations

import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ffdraft.journal import (  # noqa: E402
    Option, evaluate, load_decisions, record, record_outcome, summarise,
)


def _tmp():
    d = tempfile.mkdtemp(prefix="journal-")
    return d


def test_records_and_reloads():
    d = _tmp()
    try:
        got = record(d, week=1, kind="lineup", summary="Start Hampton over Croskey",
                     chosen=Option(1, "Omarion Hampton", 17.5, "RB"),
                     alternatives=[Option(2, "Jacory Croskey-Merritt", 7.3, "RB")],
                     expected_gain=10.2)
        assert got is not None
        back = load_decisions(d)
        assert len(back) == 1
        assert back[0].chosen.name == "Omarion Hampton"
        assert back[0].alternatives[0].projected == 7.3
        print("PASS records and reloads a decision with its options intact")
    finally:
        shutil.rmtree(d)


def test_deduplicates_repeat_runs():
    """The brief may be run several times before kickoff; that is not new evidence."""
    d = _tmp()
    try:
        for _ in range(4):
            record(d, week=1, kind="lineup", summary="same",
                   chosen=Option(1, "Hampton", 17.5), alternatives=[Option(2, "X", 7.3)])
        assert len(load_decisions(d)) == 1
        print("PASS four identical runs produce one entry")
    finally:
        shutil.rmtree(d)


def test_right_call_unlucky_is_not_scored_as_a_mistake():
    """The central case. Best projection chosen; the other guy went off anyway."""
    d = _tmp()
    try:
        dec = record(d, week=1, kind="lineup", summary="start A",
                     chosen=Option(1, "A", 18.4), alternatives=[Option(2, "B", 15.2)])
        record_outcome(d, dec.id, {1: 4.0, 2: 31.0})
        v = evaluate(d)[0]
        assert v.decided_well is True, "chose the higher projection"
        assert v.worked is False, "and it did not work"
        assert v.ev_given_up == 0.0
        assert v.is_unlucky and not v.is_lucky
        assert v.label == "right call, unlucky"
        print(f"PASS {v.label}: process good, result bad, not counted as an error")
    finally:
        shutil.rmtree(d)


def test_wrong_call_that_happened_to_work():
    d = _tmp()
    try:
        dec = record(d, week=2, kind="lineup", summary="start B on a hunch",
                     chosen=Option(2, "B", 9.0), alternatives=[Option(1, "A", 18.4)])
        record_outcome(d, dec.id, {1: 3.0, 2: 22.0})
        v = evaluate(d)[0]
        assert v.decided_well is False
        assert v.worked is True
        assert v.ev_given_up == 9.4, v.ev_given_up
        assert v.is_lucky
        assert v.label == "wrong call, got away with it"
        print(f"PASS {v.label}: gave up {v.ev_given_up} EV and still won")
    finally:
        shutil.rmtree(d)


def test_pending_until_an_outcome_exists():
    d = _tmp()
    try:
        record(d, week=3, kind="waiver", summary="claim X",
               chosen=Option(9, "X", 12.0), alternatives=[Option(8, "Y", 11.0)])
        v = evaluate(d)[0]
        assert v.worked is None and v.label == "pending"
        assert v.actual_gain is None
        print("PASS a decision with no outcome stays pending, not wrong")
    finally:
        shutil.rmtree(d)


def test_summary_leads_with_process_not_results():
    d = _tmp()
    try:
        good = record(d, 1, "lineup", "a", Option(1, "A", 18.0), [Option(2, "B", 12.0)])
        bad = record(d, 2, "lineup", "b", Option(3, "C", 8.0), [Option(4, "D", 15.0)])
        record_outcome(d, good.id, {1: 5.0, 2: 20.0})     # right call, unlucky
        record_outcome(d, bad.id, {3: 25.0, 4: 6.0})      # wrong call, lucky
        s = summarise(evaluate(d))
        assert s["decisions"] == 2 and s["with_outcome"] == 2
        assert s["decided_well"] == 1 and s["process_rate"] == 0.5
        assert s["worked"] == 1
        assert s["unlucky"] == 1 and s["lucky"] == 1
        assert s["total_ev_given_up"] == 7.0
        print(f"PASS summary: process {s['process_rate']}, "
              f"{s['unlucky']} unlucky, {s['lucky']} lucky, {s['total_ev_given_up']} EV given up")
    finally:
        shutil.rmtree(d)


def test_a_corrupt_line_does_not_destroy_the_log():
    d = _tmp()
    try:
        record(d, 1, "lineup", "a", Option(1, "A", 18.0), [Option(2, "B", 12.0)])
        with open(os.path.join(d, "decisions.jsonl"), "a") as fh:
            fh.write("{not json at all\n")
        record(d, 2, "lineup", "b", Option(3, "C", 9.0), [Option(4, "D", 8.0)])
        assert len(load_decisions(d)) == 2, "good lines survive a bad one"
        print("PASS a malformed line is skipped, the rest of the log survives")
    finally:
        shutil.rmtree(d)


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
        except AssertionError as exc:
            failed += 1; print(f"FAIL {fn.__name__}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failed += 1; print(f"ERROR {fn.__name__}: {type(exc).__name__}: {exc}")
    print(f"\n{len(fns)-failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
