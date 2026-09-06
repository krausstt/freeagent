"""Decision journal: what you chose, what you knew, and what happened.

The point is to separate two things fantasy apps conflate. A conventional app
tells you your start/sit was "wrong" because the benched player outscored the
starter. That is outcome quality, and in a high-variance game it teaches the
wrong lesson: it rewards luck and punishes sound reasoning.

This records the decision together with the information available at the time,
so the two can be judged separately afterwards. Decisions are append-only and
outcomes are stored separately keyed by decision id -- history is never
rewritten, because a journal you can edit after the fact is not evidence.

Critically, this cannot be backfilled. A projection looked up next month is not
the projection you decided on.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Iterator

DECISIONS = "decisions.jsonl"
OUTCOMES = "outcomes.jsonl"


@dataclass
class Option:
    """One choice that was available, with what was known about it then."""
    player_id: int
    name: str
    projected: float
    position: str = ""
    note: str = ""


@dataclass
class Decision:
    id: str
    ts: str
    week: int
    kind: str                       # lineup | waiver | trade | draft
    summary: str
    chosen: Option
    alternatives: list[Option] = field(default_factory=list)
    expected_gain: float = 0.0      # EV of the choice over the next best option
    source: str = "brief"           # brief | manual
    context: dict = field(default_factory=dict)

    def to_json(self) -> str:
        d = asdict(self)
        return json.dumps(d, separators=(",", ":"), sort_keys=True)


def _decision_id(week: int, kind: str, chosen: str, ts: str) -> str:
    """Stable id from the decision's identity, so a re-run cannot duplicate it."""
    raw = f"{week}|{kind}|{chosen}|{ts[:13]}"   # hour precision
    return hashlib.sha256(raw.encode()).hexdigest()[:12]


def record(
    directory: str,
    week: int,
    kind: str,
    summary: str,
    chosen: Option,
    alternatives: list[Option] | None = None,
    expected_gain: float = 0.0,
    source: str = "brief",
    context: dict | None = None,
) -> Decision | None:
    """Append one decision. Returns None if an identical one is already logged.

    Deduplication matters because the brief may be run several times before
    kickoff, and a journal padded with repeats would overstate how much evidence
    it holds.
    """
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    did = _decision_id(week, kind, chosen.name, ts)
    if any(d.id == did for d in load_decisions(directory)):
        return None

    decision = Decision(
        id=did, ts=ts, week=week, kind=kind, summary=summary, chosen=chosen,
        alternatives=alternatives or [], expected_gain=round(expected_gain, 2),
        source=source, context=context or {},
    )
    os.makedirs(directory, exist_ok=True)
    with open(os.path.join(directory, DECISIONS), "a", encoding="utf-8") as fh:
        fh.write(decision.to_json() + "\n")
    return decision


def load_decisions(directory: str) -> list[Decision]:
    path = os.path.join(directory, DECISIONS)
    out: list[Decision] = []
    for row in _read_jsonl(path):
        try:
            out.append(Decision(
                id=row["id"], ts=row["ts"], week=row["week"], kind=row["kind"],
                summary=row["summary"], chosen=Option(**row["chosen"]),
                alternatives=[Option(**a) for a in row.get("alternatives", [])],
                expected_gain=row.get("expected_gain", 0.0),
                source=row.get("source", "brief"), context=row.get("context", {}),
            ))
        except (KeyError, TypeError):
            continue      # a malformed line must not take the whole log with it
    return out


def record_outcome(directory: str, decision_id: str, actuals: dict[int, float]) -> None:
    """Attach what actually happened. Kept apart so decisions stay immutable."""
    os.makedirs(directory, exist_ok=True)
    row = {
        "decision_id": decision_id,
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "actuals": {str(k): v for k, v in actuals.items()},
    }
    with open(os.path.join(directory, OUTCOMES), "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, separators=(",", ":"), sort_keys=True) + "\n")


def load_outcomes(directory: str) -> dict[str, dict[int, float]]:
    """Latest outcome per decision; a later record supersedes an earlier one."""
    out: dict[str, dict[int, float]] = {}
    for row in _read_jsonl(os.path.join(directory, OUTCOMES)):
        try:
            out[row["decision_id"]] = {int(k): float(v) for k, v in row["actuals"].items()}
        except (KeyError, TypeError, ValueError):
            continue
    return out


def _read_jsonl(path: str) -> Iterator[dict]:
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


# ------------------------------------------------------------------ evaluation

@dataclass
class Verdict:
    decision: Decision
    decided_well: bool          # highest projected option, on what was known
    ev_given_up: float          # projected points forgone vs the best option
    worked: bool | None         # did it actually score highest? None = no outcome
    actual_gain: float | None   # realised margin over the best alternative
    label: str

    @property
    def is_unlucky(self) -> bool:
        return self.decided_well and self.worked is False

    @property
    def is_lucky(self) -> bool:
        return not self.decided_well and self.worked is True


def evaluate(directory: str) -> list[Verdict]:
    """Judge each decision twice: on its reasoning, then on its result."""
    outcomes = load_outcomes(directory)
    verdicts: list[Verdict] = []

    for d in load_decisions(directory):
        options = [d.chosen] + d.alternatives
        best_projected = max(options, key=lambda o: o.projected)
        decided_well = d.chosen.player_id == best_projected.player_id
        ev_given_up = round(best_projected.projected - d.chosen.projected, 2)

        actual = outcomes.get(d.id)
        worked: bool | None = None
        actual_gain: float | None = None
        if actual:
            scored = [(o, actual.get(o.player_id)) for o in options]
            known = [(o, v) for o, v in scored if v is not None]
            if known:
                best_actual = max(known, key=lambda t: t[1])
                chosen_actual = actual.get(d.chosen.player_id)
                if chosen_actual is not None:
                    worked = best_actual[0].player_id == d.chosen.player_id
                    others = [v for o, v in known if o.player_id != d.chosen.player_id]
                    actual_gain = round(chosen_actual - max(others), 2) if others else 0.0

        verdicts.append(Verdict(
            decision=d, decided_well=decided_well, ev_given_up=ev_given_up,
            worked=worked, actual_gain=actual_gain,
            label=_label(decided_well, worked),
        ))
    return verdicts


def _label(decided_well: bool, worked: bool | None) -> str:
    if worked is None:
        return "pending"
    if decided_well and worked:
        return "right call, right result"
    if decided_well and not worked:
        return "right call, unlucky"
    if not decided_well and worked:
        return "wrong call, got away with it"
    return "wrong call, punished"


def summarise(verdicts: list[Verdict]) -> dict:
    """Process quality first, results second -- that ordering is the whole point."""
    judged = [v for v in verdicts if v.worked is not None]
    return {
        "decisions": len(verdicts),
        "with_outcome": len(judged),
        "decided_well": sum(1 for v in verdicts if v.decided_well),
        "process_rate": round(
            sum(1 for v in verdicts if v.decided_well) / len(verdicts), 3
        ) if verdicts else None,
        "worked": sum(1 for v in judged if v.worked),
        "unlucky": sum(1 for v in judged if v.is_unlucky),
        "lucky": sum(1 for v in judged if v.is_lucky),
        "total_ev_given_up": round(sum(v.ev_given_up for v in verdicts), 2),
    }
