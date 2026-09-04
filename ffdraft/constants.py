"""ESPN v3 API enums.

Transcribed from the maintained `espn-api` client (PyPI 0.30.0,
espn_api/football/constant.py). These are ESPN's own integer codes; they are
stable across seasons but are NOT documented by ESPN, so treat any lookup miss
as data we don't understand rather than something to silently default.
"""

# lineupSlotId -> label. Used for both roster slots and player eligibility.
SLOT_MAP = {
    0: "QB", 1: "TQB", 2: "RB", 3: "RB/WR", 4: "WR", 5: "WR/TE", 6: "TE",
    7: "OP", 8: "DT", 9: "DE", 10: "LB", 11: "DL", 12: "CB", 13: "S",
    14: "DB", 15: "DP", 16: "D/ST", 17: "K", 18: "P", 19: "HC", 20: "BE",
    21: "IR", 22: "", 23: "RB/WR/TE", 24: "ER", 25: "Rookie",
}

# The positions we actually value. Everything else (IDP, HC, P) is out of scope
# for a standard redraft league and is filtered out rather than mis-scored.
SCORABLE = ("QB", "RB", "WR", "TE", "K", "D/ST")

# Slots that hold a starter. BE/IR/ER never count toward starter demand.
BENCH_SLOTS = {20, 21, 24}

# Flex slots -> the positions that may fill them.
FLEX_ELIGIBILITY = {
    3: ("RB", "WR"),
    5: ("WR", "TE"),
    7: ("QB", "RB", "WR", "TE"),   # OP / superflex
    23: ("RB", "WR", "TE"),
}

PRO_TEAM_MAP = {
    0: "FA", 1: "ATL", 2: "BUF", 3: "CHI", 4: "CIN", 5: "CLE", 6: "DAL",
    7: "DEN", 8: "DET", 9: "GB", 10: "TEN", 11: "IND", 12: "KC", 13: "LV",
    14: "LAR", 15: "MIA", 16: "MIN", 17: "NE", 18: "NO", 19: "NYG", 20: "NYJ",
    21: "PHI", 22: "ARI", 23: "PIT", 24: "LAC", 25: "SF", 26: "SEA", 27: "TB",
    28: "WSH", 29: "CAR", 30: "JAX", 33: "BAL", 34: "HOU",
}

# statSourceId
STAT_ACTUAL = 0
STAT_PROJECTED = 1

# scoringPeriodId 0 == full-season aggregate (as opposed to a single week)
SEASON_PERIOD = 0

# Injury designations that materially reduce expected games played.
INJURY_DISCOUNT = {
    "ACTIVE": 1.00,
    "NORMAL": 1.00,
    "QUESTIONABLE": 0.97,
    "DOUBTFUL": 0.80,
    "OUT": 0.55,
    "SUSPENSION": 0.60,
    "INJURY_RESERVE": 0.25,
    "PROBABLE": 0.99,
}
