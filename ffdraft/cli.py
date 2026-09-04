"""Command line cockpit.

    python3 -m ffdraft.cli verify          # prove the connection + auth works
    python3 -m ffdraft.cli board           # one-shot recommendations
    python3 -m ffdraft.cli watch           # live loop during the draft
    python3 -m ffdraft.cli export -o d.json  # snapshot for the phone cockpit
"""

from __future__ import annotations

import argparse
import sys
import time

from . import config
from .board import DraftBoard
from .espn_client import ESPNClient, ESPNError
from .export import write_snapshot
from .models import apply_draft_state, parse_league_config, parse_players
from .roster import roster_summary
from .schedule import apply_bye_weeks, bye_weeks

# ------------------------------------------------------------------ rendering

RESET, BOLD, DIM = "\033[0m", "\033[1m", "\033[2m"
POS_COLOR = {
    "QB": "\033[95m", "RB": "\033[92m", "WR": "\033[96m",
    "TE": "\033[93m", "K": "\033[90m", "D/ST": "\033[94m",
}


def _c(text: str, color: str, enabled: bool) -> str:
    return f"{color}{text}{RESET}" if enabled else text


def render_board(board: DraftBoard, top_n: int, color: bool) -> str:
    state = board.state_summary()
    lines: list[str] = []
    head = (
        f"{state['league']} | {state['season']} | pick "
        f"{state['picksMade'] + 1}/{state['totalPicks']}"
    )
    lines.append(_c(head, BOLD, color))

    if state["myNextPick"]:
        lines.append(
            f"Your pick: #{state['myNextPick']}   next after: "
            f"#{state['pickAfterThat']}   {state['picksUntilNext']} picks in between"
        )
    else:
        lines.append(_c("No draft slot configured - set draft_slot to enable VONA.", DIM, color))
    lines.append(_c(f"ADP spread calibrated to this room: sigma slope {state['calibratedSigmaSlope']}", DIM, color))
    lines.append("")

    recs = board.recommend(top_n=top_n)
    if not recs:
        lines.append("No players available.")
        return "\n".join(lines)

    lines.append(
        _c(f"{'#':<3}{'PLAYER':<24}{'POS':<6}{'TIER':<6}{'VORP':>7}{'SURV':>7}{'REGRET':>8}{'SCORE':>8}", BOLD, color)
    )
    lines.append("-" * 69)
    for i, r in enumerate(recs, 1):
        p = r.player
        pos = _c(f"{p.position:<6}", POS_COLOR.get(p.position, ""), color)
        lines.append(
            f"{i:<3}{p.name[:23]:<24}{pos}{p.tier:<6}"
            f"{r.vorp:>7.0f}{r.survival * 100:>6.0f}%{r.regret:>8.0f}{r.score:>8.1f}"
        )

    top = recs[0]
    lines.append("")
    lines.append(_c(f"PICK: {top.player.name} ({top.player.position}, {top.player.pro_team})", BOLD, color))
    for reason in top.reasons:
        lines.append(f"  - {reason}")

    if len(recs) > 1:
        alt = recs[1]
        lines.append("")
        lines.append(_c(f"Alternative: {alt.player.name} ({alt.player.position})", DIM, color))
        lines.append(f"  - {alt.reasons[0] if alt.reasons else ''}")
        lines.append(f"  - {top.score - alt.score:.1f} pts behind the top choice")

    roster = board.my_roster()
    if roster:
        summary = roster_summary(roster, board.cfg)
        lines.append("")
        lines.append(_c(f"Your roster ({summary['size']}/{summary['capacity']}) "
                        f"- projected starters {summary['projected_starting_points']} pts", BOLD, color))
        lines.append(f"  {summary['by_position']}")
        if summary["unfilled_starters"]:
            lines.append(f"  Still need: {summary['unfilled_starters']}")
    return "\n".join(lines)


# --------------------------------------------------------------------- wiring


def build_board(creds, n_sims: int = 3000, pool_limit: int = 700) -> DraftBoard:
    """Fetch everything from ESPN and assemble a ready-to-query board."""
    client = ESPNClient(
        league_id=creds.league_id,
        season=creds.season,
        espn_s2=creds.espn_s2,
        swid=creds.swid,
    )
    league_json = client.settings()
    cfg = parse_league_config(league_json, creds.league_id, creds.season, creds.team_id)
    cfg.my_draft_slot = creds.draft_slot

    players = parse_players(client.player_pool(limit=pool_limit), creds.season)
    if not players:
        raise ESPNError(
            "ESPN returned an empty player pool. This usually means the season "
            "has not been published yet, or the x-fantasy-filter was rejected."
        )

    try:
        resolved = apply_bye_weeks(players, bye_weeks(client.pro_schedule()))
        if resolved == 0:
            print("note: no bye weeks resolved; bye-conflict penalties disabled",
                  file=sys.stderr)
    except ESPNError as exc:
        print(f"note: bye weeks unavailable ({exc}); continuing without them", file=sys.stderr)

    try:
        applied = apply_draft_state(players, client.draft_detail())
        if applied:
            print(f"note: applied {applied} picks already made", file=sys.stderr)
    except ESPNError as exc:
        print(f"note: draft state unavailable ({exc}); treating board as empty", file=sys.stderr)

    return DraftBoard(cfg, players, n_sims=n_sims)


def require_league(creds) -> None:
    if not creds.league_id:
        raise SystemExit(
            "No league id. Pass --league-id, set ESPN_LEAGUE_ID, or run:\n"
            "  python3 tools/find_league.py"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ffdraft", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--league-id", type=int)
    parser.add_argument("--season", type=int)
    parser.add_argument("--team-id", type=int, help="your teamId, for roster awareness")
    parser.add_argument("--draft-slot", type=int, help="your 1-indexed snake draft slot")
    parser.add_argument("--sims", type=int, default=3000, help="Monte Carlo iterations")
    parser.add_argument("--no-color", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("verify", help="check connectivity and authentication")
    p_board = sub.add_parser("board", help="print recommendations once")
    p_board.add_argument("-n", "--top", type=int, default=12)
    p_watch = sub.add_parser("watch", help="refresh recommendations on a loop")
    p_watch.add_argument("-n", "--top", type=int, default=12)
    p_watch.add_argument("--interval", type=int, default=20, help="seconds between polls")
    p_export = sub.add_parser("export", help="write a snapshot for the phone cockpit")
    p_export.add_argument("-o", "--out", default="cockpit_data.json")
    p_export.add_argument("--pool", type=int, default=200)

    args = parser.parse_args(argv)
    creds = config.load(
        league_id=args.league_id, season=args.season,
        team_id=args.team_id, draft_slot=args.draft_slot,
    )
    color = not args.no_color and sys.stdout.isatty()

    try:
        if args.command == "verify":
            require_league(creds)
            client = ESPNClient(creds.league_id, creds.season, creds.espn_s2, creds.swid)
            info = client.verify()
            print("Connection OK")
            for k, v in info.items():
                print(f"  {k}: {v}")
            if not info["authenticated"]:
                print("\nNote: connected without cookies. That works only for public "
                      "leagues. If your league is private this will 401 on other calls.")
            return 0

        require_league(creds)
        board = build_board(creds, n_sims=args.sims)

        if args.command == "board":
            print(render_board(board, args.top, color))
        elif args.command == "watch":
            print("Polling ESPN. Ctrl-C to stop.\n")
            while True:
                board = build_board(creds, n_sims=args.sims)
                print("\033[2J\033[H" if color else "\n" + "=" * 69)
                print(render_board(board, args.top, color))
                time.sleep(args.interval)
        elif args.command == "export":
            path = write_snapshot(board, args.out, top_n=args.pool)
            print(f"Wrote {path}")
            print("Open cockpit/index.html on your phone and load this file.")
        return 0

    except ESPNError as exc:
        print(f"ESPN error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\nStopped.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
