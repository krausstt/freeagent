"""The draft board: turns state into a ranked, explained recommendation."""

from __future__ import annotations

from dataclasses import dataclass, field

from .availability import calibrate_sigma, snake_picks
from .models import LeagueConfig, Player
from .roster import bye_week_conflicts, marginal_starter_value, unfilled_starter_slots
from .valuation import assign_tiers, compute_vorp
from .vona import simulate_gap


@dataclass
class Weights:
    """Tunable scoring weights. Documented defaults, all in projected points."""

    need_bonus: float = 0.30       # uplift when the position still needs a starter
    bench_discount: float = 0.55   # multiplier when the position is already covered
    regret: float = 1.00           # weight on expected points lost by waiting
    bye_penalty: float = 3.00      # points per same-position bye collision


@dataclass
class Recommendation:
    player: Player
    score: float
    vorp: float
    survival: float
    fallback_vorp: float
    regret: float
    need_multiplier: float
    marginal: float
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        p = self.player
        return {
            "playerId": p.player_id,
            "name": p.name,
            "position": p.position,
            "proTeam": p.pro_team,
            "tier": p.tier,
            "adp": round(p.adp, 1),
            "projPoints": round(p.proj_points, 1),
            "injuryStatus": p.injury_status,
            "score": round(self.score, 2),
            "vorp": round(self.vorp, 1),
            "survival": round(self.survival, 3),
            "fallbackVorp": round(self.fallback_vorp, 1),
            "regret": round(self.regret, 1),
            "marginal": round(self.marginal, 1),
            "reasons": self.reasons,
        }


class DraftBoard:
    """Holds draft state and produces recommendations."""

    def __init__(
        self,
        cfg: LeagueConfig,
        players: list[Player],
        weights: Weights | None = None,
        n_sims: int = 3000,
    ) -> None:
        self.cfg = cfg
        self.players = players
        self.weights = weights or Weights()
        self.n_sims = n_sims
        self.replacement = compute_vorp(cfg, players)
        assign_tiers(players)

    # ------------------------------------------------------------------ state

    @property
    def available(self) -> list[Player]:
        return [p for p in self.players if p.available]

    def my_roster(self) -> list[Player]:
        if self.cfg.my_team_id is None:
            return []
        return [p for p in self.players if p.drafted_by == self.cfg.my_team_id]

    def picks_made(self) -> int:
        return sum(1 for p in self.players if not p.available)

    def my_pick_schedule(self) -> list[int]:
        if self.cfg.my_draft_slot is None:
            return []
        rounds = self.cfg.roster_size
        return snake_picks(self.cfg.my_draft_slot, self.cfg.team_count, rounds)

    def current_and_next_pick(self) -> tuple[int | None, int | None]:
        """(my next pick overall, the one after that) given picks already made."""
        schedule = self.my_pick_schedule()
        if not schedule:
            return None, None
        made = self.picks_made()
        upcoming = [n for n in schedule if n > made]
        if not upcoming:
            return None, None
        return upcoming[0], (upcoming[1] if len(upcoming) > 1 else None)

    # ------------------------------------------------------------ recommending

    def recommend(self, top_n: int = 12, candidate_pool: int = 60) -> list[Recommendation]:
        available = self.available
        if not available:
            return []

        my_pick, next_pick = self.current_and_next_pick()
        gap = (next_pick - my_pick - 1) if (my_pick and next_pick) else 0

        # Re-fit the ADP spread to how this specific room is actually drafting.
        slope = calibrate_sigma(self.players)

        survival, fallback = simulate_gap(
            available, gap, slope=slope, n_sims=self.n_sims
        )

        roster = self.my_roster()
        need = unfilled_starter_slots(roster, self.cfg)
        w = self.weights

        # Only score the plausible top of the board; the rest cannot win.
        candidates = sorted(available, key=lambda p: p.vorp, reverse=True)[:candidate_pool]

        recs: list[Recommendation] = []
        for p in candidates:
            surv = survival.get(p.player_id, 1.0)
            fb = fallback.get(p.position, 0.0)
            regret = (1.0 - surv) * max(0.0, p.vorp - fb)

            unfilled = need.get(p.position, 0)
            if unfilled > 0:
                need_mult = 1.0 + w.need_bonus
            elif self._is_flex_useful(p, roster):
                need_mult = 1.0
            else:
                need_mult = w.bench_discount

            byes = bye_week_conflicts(roster, p)
            marginal = marginal_starter_value(roster, p, self.cfg) if roster else p.proj_points

            score = p.vorp * need_mult + w.regret * regret - w.bye_penalty * byes

            recs.append(
                Recommendation(
                    player=p,
                    score=score,
                    vorp=p.vorp,
                    survival=surv,
                    fallback_vorp=fb,
                    regret=regret,
                    need_multiplier=need_mult,
                    marginal=marginal,
                    reasons=self._reasons(p, surv, fb, regret, unfilled, byes, need_mult),
                )
            )

        recs.sort(key=lambda r: r.score, reverse=True)
        return recs[:top_n]

    def _is_flex_useful(self, player: Player, roster: list[Player]) -> bool:
        """Could this player realistically occupy a flex slot?"""
        if player.position not in ("RB", "WR", "TE"):
            return False
        flex_capacity = sum(n for _, n in self.cfg.flex_demand) // max(1, self.cfg.team_count)
        flex_eligible_owned = sum(1 for p in roster if p.position in ("RB", "WR", "TE"))
        starters_needed = sum(
            v for k, v in self.cfg.dedicated_demand.items() if k in ("RB", "WR", "TE")
        ) // max(1, self.cfg.team_count)
        return flex_eligible_owned < starters_needed + flex_capacity

    def _reasons(
        self,
        p: Player,
        surv: float,
        fb: float,
        regret: float,
        unfilled: int,
        byes: int,
        need_mult: float,
    ) -> list[str]:
        out: list[str] = []
        out.append(f"Tier {p.tier} {p.position} - {p.vorp:.0f} pts over replacement")

        if surv < 0.25:
            out.append(f"Very unlikely to last: {surv * 100:.0f}% to reach your next pick")
        elif surv < 0.55:
            out.append(f"Coin-flip to last: {surv * 100:.0f}% to reach your next pick")
        elif surv > 0.85:
            out.append(f"Safe to wait: {surv * 100:.0f}% still there next turn")

        drop = p.vorp - fb
        if drop > 15:
            out.append(f"Big positional cliff - next best {p.position} is {drop:.0f} pts worse")
        elif drop < 3:
            out.append(f"No cliff - {p.position} depth means you can wait")

        if regret > 10:
            out.append(f"Expected cost of passing: {regret:.0f} pts")
        if unfilled > 0:
            out.append(f"Fills a starting slot ({unfilled} {p.position} still open)")
        elif need_mult < 1.0:
            out.append(f"Bench depth only - {p.position} starters already covered")
        if byes:
            out.append(f"Bye-week clash with {byes} rostered {p.position}")
        if p.injury_status.upper() not in ("ACTIVE", "NORMAL"):
            out.append(f"Injury flag: {p.injury_status} (value discounted)")
        return out

    # ---------------------------------------------------------------- summary

    def state_summary(self) -> dict:
        my_pick, next_pick = self.current_and_next_pick()
        return {
            "league": self.cfg.name,
            "season": self.cfg.season,
            "teamCount": self.cfg.team_count,
            "picksMade": self.picks_made(),
            "totalPicks": self.cfg.total_picks,
            "myNextPick": my_pick,
            "pickAfterThat": next_pick,
            "picksUntilNext": (next_pick - my_pick - 1) if (my_pick and next_pick) else 0,
            "calibratedSigmaSlope": round(calibrate_sigma(self.players), 3),
            "replacementLevels": {k: round(v, 1) for k, v in self.replacement.items()},
        }
