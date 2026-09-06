#!/usr/bin/env python3
"""Read and score the decision journal.

    python3 tools/journal.py show           # every decision, newest first
    python3 tools/journal.py score          # process quality vs results
    python3 tools/journal.py outcome <id> 123=18.4 456=7.2
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from ffdraft.journal import evaluate, record_outcome, summarise  # noqa: E402

DEFAULT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "journal")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", default=DEFAULT)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("show")
    sub.add_parser("score")
    p_out = sub.add_parser("outcome")
    p_out.add_argument("decision_id")
    p_out.add_argument("pairs", nargs="+", metavar="PLAYERID=POINTS")
    args = ap.parse_args()

    if args.cmd == "outcome":
        actuals = {}
        for pair in args.pairs:
            if "=" not in pair:
                print(f"expected PLAYERID=POINTS, got {pair!r}", file=sys.stderr)
                return 2
            k, v = pair.split("=", 1)
            actuals[int(k)] = float(v)
        record_outcome(args.dir, args.decision_id, actuals)
        print(f"recorded {len(actuals)} actual(s) for {args.decision_id}")
        return 0

    verdicts = evaluate(args.dir)
    if not verdicts:
        print(f"No decisions logged yet in {args.dir}.")
        print("Run: python3 tools/weekly_brief.py --journal")
        return 0

    if args.cmd == "show":
        print(f"{'ID':<14}{'WK':<4}{'KIND':<9}{'DECISION':<42}{'VERDICT'}")
        print("-" * 100)
        for v in sorted(verdicts, key=lambda x: x.decision.ts, reverse=True):
            d = v.decision
            print(f"{d.id:<14}{d.week:<4}{d.kind:<9}{d.summary[:41]:<42}{v.label}")
        return 0

    s = summarise(verdicts)
    print("DECISION JOURNAL")
    print("-" * 46)
    print(f"  decisions logged      {s['decisions']}")
    print(f"  with a known outcome  {s['with_outcome']}")
    print()
    print("  PROCESS  (judged on what was known at the time)")
    print(f"    best available option chosen   {s['decided_well']}/{s['decisions']}"
          + (f"  ({s['process_rate']:.0%})" if s["process_rate"] is not None else ""))
    print(f"    projected points given up      {s['total_ev_given_up']}")
    print()
    print("  RESULTS  (judged after the fact)")
    print(f"    worked out                     {s['worked']}/{s['with_outcome']}")
    print(f"    right call, unlucky            {s['unlucky']}")
    print(f"    wrong call, got away with it   {s['lucky']}")
    print()
    print("  Process is the number to improve. Results follow it only on average,")
    print("  and a single week says almost nothing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
