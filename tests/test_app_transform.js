/* The Android transform, driven against a payload shaped like the real ESPN v3
   response — and carrying the real Week 1 numbers read off both apps.

   The point of this file: the app and the ESPN app appeared to disagree (117.5
   against 56.2) and neither could explain why. They were reporting different
   quantities. This test pins BOTH quantities, for BOTH sides of a real matchup,
   against figures observed in the ESPN app on 2026-09-13.

   Run: node tests/test_app_transform.js
*/

"use strict";

// ---------------------------------------------------------------- DOM shim
// app-late.js builds its chrome at load. None of that is under test; it just
// has to not throw.
let seedForPrev = {};
const stub = () => ({ style: {}, innerHTML: "", textContent: "", onclick: null,
                      hidden: false, appendChild() {}, remove() {},
                      querySelector: () => stub() });
global.window = {};
global.localStorage = { getItem: () => null, setItem: () => {} };
global.document = {
  createElement: stub,
  body: { appendChild() {} },
  getElementById: (id) =>
    id === "data" ? { textContent: JSON.stringify(seedForPrev) } : stub(),
};
global.setTimeout = () => 0;
global.clearTimeout = () => {};

const { transform, winProbability, normCdf } = require("../android/app-late.js");

// ------------------------------------------------------------------ helpers
const ELIGIBLE = {
  QB: [0, 7, 20, 21], RB: [2, 3, 23, 7, 20, 21], WR: [3, 4, 5, 23, 7, 20, 21],
  TE: [5, 6, 23, 7, 20, 21], K: [17, 20, 21], "D/ST": [16, 20, 21],
};
const SLOT_ID = { QB: 0, RB: 2, WR: 4, TE: 6, FLEX: 3, "D/ST": 16, K: 17, BE: 20 };
let pid = 5000;

/* scored === null means the game has not kicked off, which ESPN represents by
   omitting the statSourceId 0 line entirely — NOT by sending a zero. */
function player(name, pos, slot, proj, scored) {
  const stats = [{ statSourceId: 1, scoringPeriodId: 0, appliedTotal: proj * 17 },
                 { statSourceId: 1, scoringPeriodId: 1, appliedTotal: proj }];
  if (scored !== null) stats.push({ statSourceId: 0, scoringPeriodId: 1, appliedTotal: scored });
  return {
    lineupSlotId: SLOT_ID[slot],
    playerPoolEntry: { player: {
      id: ++pid, fullName: name, proTeamId: 12, injuryStatus: "ACTIVE",
      eligibleSlots: ELIGIBLE[pos], stats,
    } },
  };
}

// TheRealTobi's Week 1 starters: projections from the app, points from ESPN.
const MINE = [
  player("Jalen Hurts", "QB", "QB", 20.9, 0.0),
  player("Christian McCaffrey", "RB", "RB", 17.4, 13.8),
  player("Omarion Hampton", "RB", "RB", 17.5, 0.0),
  player("Terry McLaurin", "WR", "FLEX", 12.6, 0.0),
  player("Malik Nabers", "WR", "WR", 14.5, null),      // Monday game, "-" in ESPN
  player("Emeka Egbuka", "WR", "WR", 13.6, 11.3),
  player("Harold Fannin Jr.", "TE", "TE", 10.4, 4.1),
  player("Steelers D/ST", "D/ST", "D/ST", 0.3, 27.0),  // unpopulated projection
  player("Brandon Aubrey", "K", "K", 10.3, null),      // Monday game
  player("Jared Goff", "QB", "BE", 15.5, 11.4),
  player("Kyle Monangai", "RB", "BE", 10.5, 25.4),
];

// Team 15 (A. Steinmeier), same week, same source.
const THEIRS = [
  player("Dak Prescott", "QB", "QB", 17.53, null),
  player("Bijan Robinson", "RB", "RB", 19.65, 31.3),
  player("Jordan Love", "RB", "RB", 13.85, 0.0),
  player("Bhayshul Tuten", "RB", "FLEX", 12.33, 9.8),
  player("Ladd McConkey", "WR", "WR", 13.77, 0.0),
  player("Luther Burden III", "WR", "WR", 10.25, 9.5),
  player("Trey McBride", "TE", "TE", 18.02, 3.7),
  player("Browns D/ST", "D/ST", "D/ST", 8.63, 0.5),
  player("Ka'imi Fairbairn", "K", "K", 9.99, 9.0),
];

function payload() {
  return {
    seasonId: 2026, scoringPeriodId: 1,
    settings: { name: "Schobbetruppe", size: 12, rosterSettings: {
      lineupSlotCounts: { 0: 1, 2: 2, 4: 2, 6: 1, 3: 1, 16: 1, 17: 1, 20: 6 } } },
    teams: [
      { id: 1, name: "TheRealTobi", roster: { entries: MINE } },
      { id: 15, name: "Team 15", roster: { entries: THEIRS } },
    ],
    schedule: [{ matchupPeriodId: 1, home: { teamId: 1 }, away: { teamId: 15 } }],
  };
}

let failures = 0;
function check(label, actual, expected) {
  const ok = Math.abs(actual - expected) < 0.051;
  console.log((ok ? "PASS " : "FAIL ") + label + ": " + actual +
              (ok ? "" : "  (expected " + expected + ")"));
  if (!ok) failures++;
}
function assert(label, cond, detail) {
  console.log((cond ? "PASS " : "FAIL ") + label + (cond ? "" : "  " + detail));
  if (!cond) failures++;
}

// ------------------------------------------------------------------- tests
const prev = { waiverWatch: [{ n: "Najee Harris", p: "RB", rostered: 7, trend: 1.4 }],
               flexEligible: ["RB", "WR"] };
seedForPrev = prev;
const out = transform(payload(), null, 1, prev);

// The two numbers that looked like a contradiction, now both produced at once.
check("my projected total (ESPN app: 117.5)", out.week1.projFor, 117.5);
check("my points scored   (ESPN app: 56.2)", out.week1.scoredFor, 56.2);
check("opponent projected (ESPN app: 124.02)", out.week1.projAgainst, 124.0);
assert("per-player rounding does not accumulate into the total",
       out.week1.projAgainst === 124.0,
       "got " + out.week1.projAgainst + " — summing rounded players drifts");
assert("internal raw values are stripped from the saved roster",
       out.roster.every(r => r._raw === undefined), "a _raw leaked into output");
check("opponent scored    (ESPN app: 63.8)", out.week1.scoredAgainst, 63.8);

assert("opponent is named, not blank", out.week1.opponent === "Team 15",
       "got " + JSON.stringify(out.week1.opponent));
assert("win probability is computed, not the old 0.5 placeholder",
       out.week1.winProbability !== 0.5 && out.week1.winProbability > 0 &&
       out.week1.winProbability < 1, "got " + out.week1.winProbability);
assert("trailing on projection => win probability below even",
       out.week1.winProbability < 0.5, "got " + out.week1.winProbability);
assert("waiver watch carried forward, not emptied",
       out.waiverWatch.length === 1 && out.waiverWatch[0].n === "Najee Harris",
       "got " + JSON.stringify(out.waiverWatch));
assert("pull is stamped so staleness can be shown",
       typeof out._fetchedAt === "string" && !isNaN(new Date(out._fetchedAt).getTime()),
       "got " + out._fetchedAt);

// A player whose game has not started must read as "no data", not "scored 0".
const nabers = out.roster.find(r => r.n === "Malik Nabers");
const hurts = out.roster.find(r => r.n === "Jalen Hurts");
assert("not-yet-played reads as null, not 0", nabers.scored === null,
       "got " + nabers.scored);
assert("played-and-scored-zero reads as 0, not null", hurts.scored === 0,
       "got " + hurts.scored);

// Season and weekly projections must not contaminate each other.
const cmc = out.roster.find(r => r.n === "Christian McCaffrey");
check("weekly projection stays weekly", cmc.w1, 17.4);
check("season projection kept separately", cmc.season, 17.4 * 17);

// Bench must not leak into the starting total.
assert("bench excluded from totals (Monangai's 25.4 not counted)",
       out.roster.length === 11 && out.week1.scoredFor === 56.2,
       "roster " + out.roster.length + ", scored " + out.week1.scoredFor);

// Win probability calibration: the seed's 117.5 vs 114.0 read 53% in the app,
// so the margin sigma must reproduce that or the bar moves under everyone.
check("seed matchup reproduces the published 53%",
      Math.round(winProbability(117.5, 114.0) * 100), 53);
check("dead heat is exactly even", Math.round(winProbability(120, 120) * 100), 50);
assert("normCdf is symmetric about zero",
       Math.abs(normCdf(0.7) + normCdf(-0.7) - 1) < 1e-6, "");

// No opponent in the payload => no invented contest.
const solo = payload(); solo.schedule = [];
const alone = transform(solo, null, 1, prev);
assert("missing schedule leaves opponent blank rather than fabricated",
       alone.week1.projAgainst === 0 && alone.week1.opponent === "",
       JSON.stringify(alone.week1));

console.log(failures ? "\nFAILURES: " + failures : "\nall app-transform tests pass");
process.exit(failures ? 1 : 0);
