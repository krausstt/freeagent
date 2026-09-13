/* Runs AFTER the dashboard script. Owns the app chrome: refresh, settings, and
   the ESPN -> dashboard transform.

   Refresh writes to localStorage and reloads rather than re-rendering in place.
   The dashboard builds its whole view once at load from a single data object,
   so a reload is both simpler and less likely to leave half-updated state than
   reaching into its internals. In a WebView a reload is imperceptible. */
(function () {
  "use strict";
  var HAVE_NATIVE = typeof window.Native !== "undefined";
  var KEY_DATA = "freeagent.data.v1";

  var SLOT = {0:"QB",2:"RB",4:"WR",6:"TE",16:"D/ST",17:"K",
              3:"FLEX",5:"FLEX",7:"FLEX",23:"FLEX",20:"BE",21:"IR",24:"BE"};
  var SCORABLE = {QB:1, RB:1, WR:1, TE:1, K:1, "D/ST":1};
  var PRO = {0:"FA",1:"ATL",2:"BUF",3:"CHI",4:"CIN",5:"CLE",6:"DAL",7:"DEN",8:"DET",
    9:"GB",10:"TEN",11:"IND",12:"KC",13:"LV",14:"LAR",15:"MIA",16:"MIN",17:"NE",
    18:"NO",19:"NYG",20:"NYJ",21:"PHI",22:"ARI",23:"PIT",24:"LAC",25:"SF",26:"SEA",
    27:"TB",28:"WSH",29:"CAR",30:"JAX",33:"BAL",34:"HOU"};

  function cfg() {
    try { return JSON.parse(HAVE_NATIVE ? Native.getConfig() : (localStorage.getItem("freeagent.cfg") || "{}")); }
    catch (e) { return {}; }
  }
  function saveCfg(o) {
    var s = JSON.stringify(o);
    if (HAVE_NATIVE) Native.setConfig(s); else localStorage.setItem("freeagent.cfg", s);
  }

  /* ESPN publishes a projection per scoring period. Period 0 is the season
     total and period N is week N; they differ by roughly 17x, so the weekly one
     is the only correct choice for a weekly column.

     statSourceId 1 is the projection and 0 is what the player has actually
     scored. Reading only the former is why the app could never show the number
     the ESPN app leads with -- 56.2 scored against 130.7 projected -- and why
     the two apps looked like they disagreed when they were measuring different
     things. Both are captured, into separate fields, and never mixed. */
  function projections(player, week) {
    var season = 0, wk = 0, scored = 0, haveScored = false, stats = player.stats || [];
    for (var i = 0; i < stats.length; i++) {
      var st = stats[i];
      if (st.statSourceId === 1) {
        if (st.scoringPeriodId === 0) season = st.appliedTotal || 0;
        else if (st.scoringPeriodId === week) wk = st.appliedTotal || 0;
      } else if (st.statSourceId === 0 && st.scoringPeriodId === week) {
        scored = st.appliedTotal || 0; haveScored = true;
      }
    }
    return { week: wk, season: season, scored: scored, haveScored: haveScored };
  }

  /* Win probability from the projected margin.

     The previous code stored a hardcoded 0.5, which is not a probability, it is
     a placeholder that happened to render. A normal approximation on the margin
     is crude but honest: it moves when the margin moves and it is reproducible.

     SIGMA is the standard deviation of the MARGIN, not of one team. A fantasy
     starting lineup lands around 29 points of weekly dispersion, and the margin
     of two of them is that times sqrt(2). Calibrating this against real results
     is issue #7; until then it is a stated prior, not a measurement. */
  var MARGIN_SIGMA = 41.0;

  function normCdf(z) {
    // Abramowitz & Stegun 26.2.17: |error| < 7.5e-8, far tighter than the
    // uncertainty in SIGMA itself.
    var t = 1 / (1 + 0.2316419 * Math.abs(z));
    var d = 0.3989422804014327 * Math.exp(-z * z / 2);
    var p = d * t * (0.319381530 + t * (-0.356563782 + t * (1.781477937 +
            t * (-1.821255978 + t * 1.330274429))));
    return z > 0 ? 1 - p : p;
  }

  function winProbability(pointsFor, pointsAgainst) {
    return Math.round(normCdf((pointsFor - pointsAgainst) / MARGIN_SIGMA) * 1000) / 1000;
  }

  /* Who this team plays in the given week. mMatchup returns the whole schedule.
     Standard leagues run one scoring period per matchup period, so week N is
     matchup period N; a league with multi-week playoff matchups would need the
     scoringPeriod-to-matchupPeriod mapping instead. */
  function findOpponent(league, teamId, week) {
    var sched = league.schedule || [];
    for (var i = 0; i < sched.length; i++) {
      var m = sched[i] || {};
      if ((m.matchupPeriodId || 0) !== week) continue;
      var h = (m.home || {}).teamId, a = (m.away || {}).teamId;
      if (h === teamId) return a;
      if (a === teamId) return h;
    }
    return null;
  }

  function teamName(league, teamId) {
    var teams = league.teams || [];
    for (var i = 0; i < teams.length; i++) {
      if (teams[i].id !== teamId) continue;
      var t = teams[i];
      var n = (t.name || "").trim();
      if (n) return n;
      return [t.location, t.nickname].filter(Boolean).join(" ").trim() || ("Team " + teamId);
    }
    return "Team " + teamId;
  }

  function primaryPos(eligible) {
    for (var i = 0; i < (eligible || []).length; i++) {
      var lbl = SLOT[eligible[i]];
      if (lbl && SCORABLE[lbl]) return lbl;
    }
    return null;
  }

  /* A team's bye is the regular-season week missing from its schedule. */
  function byeWeeks(seasonJson) {
    var out = {}, teams = ((seasonJson.settings || {}).proTeams) || [];
    for (var i = 0; i < teams.length; i++) {
      var t = teams[i], ab = (t.abbrev || "").toUpperCase();
      if (!ab || ab === "FA") continue;
      var played = t.proGamesByScoringPeriod || {};
      for (var w = 1; w <= 18; w++) {
        if (!played[String(w)]) { out[ab] = w; break; }
      }
    }
    return out;
  }

  function rosterRows(team, week, byes) {
    var rows = [], entries = ((team.roster || {}).entries) || [];
    for (var j = 0; j < entries.length; j++) {
      var e = entries[j];
      var p = ((e.playerPoolEntry || {}).player) || {};
      var pos = primaryPos(p.eligibleSlots);
      if (!pos) continue;
      var pr = projections(p, week);
      var slot = SLOT[e.lineupSlotId] || "BE";
      var pt = PRO[p.proTeamId] || "";
      var inj = (p.injuryStatus || "ACTIVE").toUpperCase();
      rows.push({
        n: p.fullName || "?", p: pos, t: pt,
        bye: byes[pt] || 0,
        w1: Math.round(pr.week * 10) / 10,
        season: Math.round(pr.season * 10) / 10,
        // null, not 0: a player whose game has not kicked off has scored
        // nothing YET, which is a different statement from having scored zero.
        scored: pr.haveScored ? Math.round(pr.scored * 10) / 10 : null,
        /* Unrounded, for totalling. Rounding each player to one decimal and
           then adding nine of them drifts from the figure ESPN publishes --
           the opponent's real 124.02 came out as 124.1 that way. ESPN sums
           first and rounds once, so this does too. Stripped before output. */
        _raw: [pr.week, pr.haveScored ? pr.scored : 0],
        slot: slot,
        q: inj !== "ACTIVE" && inj !== "NORMAL" && inj !== "PROBABLE"
      });
    }
    return rows;
  }

  function startersOf(rows) {
    return rows.filter(function (r) { return r.slot !== "BE" && r.slot !== "IR"; });
  }
  var RAW_PROJ = 0, RAW_SCORED = 1;
  function sumRaw(rows, which) {
    return Math.round(rows.reduce(function (a, r) {
      return a + ((r._raw && r._raw[which]) || 0);
    }, 0) * 10) / 10;
  }
  function anyScored(rows) {
    return rows.some(function (r) { return r.scored !== null && r.scored !== undefined; });
  }

  function transform(league, seasonJson, teamId, prev) {
    prev = prev || {};
    var s = league.settings || {};
    var slots = (s.rosterSettings || {}).lineupSlotCounts || {};
    var week = league.scoringPeriodId || 1;
    var byes = seasonJson ? byeWeeks(seasonJson) : {};

    var counts = {};
    Object.keys(slots).forEach(function (k) {
      var n = slots[k] | 0, lbl = SLOT[k | 0];
      if (n > 0 && lbl && lbl !== "BE" && lbl !== "IR") counts[lbl] = (counts[lbl] || 0) + n;
    });

    var teams = league.teams || [];
    var team = null;
    for (var i = 0; i < teams.length; i++) if (teams[i].id === teamId) team = teams[i];
    if (!team) throw new Error("Team " + teamId + " not in this league.");

    var roster = rosterRows(team, week, byes);
    var mine = startersOf(roster);
    var projFor = sumRaw(mine, RAW_PROJ);
    var scoredFor = anyScored(mine) ? sumRaw(mine, RAW_SCORED) : null;

    /* The opponent, measured exactly as this team is measured. mRoster returns
       every team's roster in the same response, so this costs no extra request
       -- the data was already being fetched and thrown away, which is why the
       matchup card used to collapse to "vs 0.0" after a refresh. */
    var oppId = findOpponent(league, teamId, week);
    var oppName = "", projAgainst = 0, scoredAgainst = null;
    if (oppId !== null && oppId !== undefined) {
      var oppTeam = null;
      for (var k = 0; k < teams.length; k++) if (teams[k].id === oppId) oppTeam = teams[k];
      if (oppTeam) {
        var theirs = startersOf(rosterRows(oppTeam, week, byes));
        projAgainst = sumRaw(theirs, RAW_PROJ);
        scoredAgainst = anyScored(theirs) ? sumRaw(theirs, RAW_SCORED) : null;
        oppName = teamName(league, oppId);
      }
    }

    return {
      _source: "Live ESPN pull",
      _fetchedAt: new Date().toISOString(),
      team: team.name || ("Team " + teamId),
      league: s.name || "ESPN league",
      season: league.seasonId || 2026,
      teamCount: s.size || 12,
      currentWeek: week,
      week1: {
        opponent: oppName,
        projFor: projFor,
        projAgainst: projAgainst,
        scoredFor: scoredFor,
        scoredAgainst: scoredAgainst,
        winProbability: projAgainst > 0 ? winProbability(projFor, projAgainst) : 0.5
      },
      lineupSlots: counts,
      flexEligible: prev.flexEligible || ["RB", "WR"],
      roster: roster.map(function (r) {
        var out = {}; for (var kk in r) if (kk !== "_raw") out[kk] = r[kk];
        return out;
      }),
      /* Not yet live: a useful free-agent list needs kona_player_info with an
         x-fantasy-filter header the native bridge does not pass (issue #13).
         Carrying the previous list forward keeps a populated panel instead of
         replacing four real candidates with an empty array. */
      waiverWatch: prev.waiverWatch || []
    };
  }

  /* Whatever is on screen right now -- the cached pull app-early.js swapped in,
     or the seed. Used so a refresh can carry forward what it cannot yet compute
     rather than blanking it. */
  function prevData() {
    try {
      var el = document.getElementById("data");
      return el ? JSON.parse(el.textContent) : {};
    } catch (e) { return {}; }
  }

  // ---------------------------------------------------------------- fetching
  var pending = 0, gotLeague = null, gotSeason = null, onDone = null;

  window.__faLeague = function (raw) { gotLeague = raw; if (--pending === 0) onDone(); };
  window.__faSeason = function (raw) { gotSeason = raw; if (--pending === 0) onDone(); };

  function refresh(btn) {
    var c = cfg();
    if (!c.leagueId || !c.teamId) { openSettings(); return; }
    if (!HAVE_NATIVE) { alert("Native bridge unavailable — is this the app build?"); return; }

    var was = btn.textContent;
    btn.textContent = "Fetching…"; btn.disabled = true;

    gotLeague = gotSeason = null; pending = 2;

    /* `pending` only ever decrements inside the two native callbacks. If one of
       them never fires -- which is precisely what a connection dropped
       mid-request looks like -- it never reaches zero, onDone never runs, and
       the button stays disabled reading "Fetching…" until the app is
       force-killed. A deadline makes that recoverable. Partial fix for #9. */
    var settled = false;
    var timer = setTimeout(function () {
      if (settled) return;
      settled = true; pending = 0;
      btn.textContent = was; btn.disabled = false;
      alert("ESPN did not respond within 25 seconds.\n\n" +
            "Your existing data is unchanged. Try again when you have signal.");
    }, 25000);

    onDone = function () {
      if (settled) return;
      settled = true; clearTimeout(timer);
      btn.textContent = was; btn.disabled = false;
      var lg, se = null;
      try { lg = JSON.parse(gotLeague); } catch (e) { alert("Bad response from ESPN."); return; }
      if (!lg.ok) { alert("ESPN error:\n\n" + lg.error); return; }
      try { var s = JSON.parse(gotSeason); if (s.ok) se = s.data; } catch (e) { /* byes optional */ }
      try {
        var data = transform(lg.data, se, parseInt(c.teamId, 10), prevData());
        localStorage.setItem(KEY_DATA, JSON.stringify(data));
        location.reload();
      } catch (err) { alert("Could not read that league:\n\n" + err.message); }
    };
    Native.fetchLeague(String(c.leagueId), String(c.season || 2026),
      "mSettings,mTeam,mRoster,mMatchup", "__faLeague");
    Native.fetchSeason(String(c.season || 2026), "proTeamSchedules_wl", "__faSeason");
  }

  // ---------------------------------------------------------------- settings
  function openSettings() {
    var c = cfg();
    var wrap = document.createElement("div");
    wrap.style.cssText = "position:fixed;inset:0;z-index:99;background:var(--ground);" +
      "overflow:auto;padding:18px 16px 90px";
    wrap.innerHTML =
      '<h2 style="font-size:13px;letter-spacing:.12em;text-transform:uppercase;' +
      'color:var(--ink-dim);margin-bottom:14px">Settings</h2>' +
      field("leagueId", "League ID", c.leagueId || "461530087") +
      field("teamId", "Your team ID", c.teamId || "") +
      field("season", "Season", c.season || "2026") +
      '<p style="font-size:12.5px;color:var(--ink-faint);margin:14px 0 6px;line-height:1.5">' +
      'Cookies are only needed for a private league. Schobbetruppe is public, so leave these empty.</p>' +
      field("espn_s2", "espn_s2 (optional)", c.espn_s2 || "") +
      field("swid", "SWID (optional)", c.swid || "") +
      '<div style="display:flex;gap:8px;margin-top:18px">' +
      '<button id="faSave" style="flex:1;min-height:46px;border:1px solid var(--accent);' +
      'border-radius:3px;background:var(--surface);color:var(--accent);font:inherit;' +
      'font-weight:600;letter-spacing:.06em;text-transform:uppercase;font-size:12px">Save</button>' +
      '<button id="faCancel" style="flex:1;min-height:46px;border:1px solid var(--line);' +
      'border-radius:3px;background:var(--surface);color:var(--ink-dim);font:inherit;' +
      'font-weight:600;letter-spacing:.06em;text-transform:uppercase;font-size:12px">Cancel</button>' +
      '</div>';
    document.body.appendChild(wrap);
    wrap.querySelector("#faCancel").onclick = function () { wrap.remove(); };
    wrap.querySelector("#faSave").onclick = function () {
      var o = {};
      ["leagueId","teamId","season","espn_s2","swid"].forEach(function (k) {
        o[k] = wrap.querySelector("#fa_" + k).value.trim();
      });
      saveCfg(o); wrap.remove();
    };
  }

  function field(id, label, val) {
    return '<label style="display:block;margin-bottom:11px">' +
      '<span style="display:block;font-size:10px;letter-spacing:.1em;text-transform:uppercase;' +
      'color:var(--ink-faint);margin-bottom:4px">' + label + '</span>' +
      '<input id="fa_' + id + '" value="' + String(val).replace(/"/g, "&quot;") + '" ' +
      'autocapitalize="off" autocorrect="off" spellcheck="false" ' +
      'style="width:100%;min-height:44px;padding:0 11px;border:1px solid var(--line);' +
      'border-radius:3px;background:var(--surface);color:var(--ink);font:inherit;font-size:15px">' +
      '</label>';
  }

  // ------------------------------------------------------------------ chrome
  var bar = document.createElement("div");
  bar.style.cssText = "position:fixed;left:0;right:0;bottom:0;display:flex;gap:8px;" +
    "padding:9px 12px calc(9px + env(safe-area-inset-bottom));background:var(--surface);" +
    "border-top:1px solid var(--line);z-index:50";
  bar.innerHTML =
    '<button id="faRefresh" style="flex:2;min-height:46px;border:1px solid var(--accent);' +
    'border-radius:3px;color:var(--accent);background:var(--surface);font:inherit;font-size:12px;' +
    'font-weight:600;letter-spacing:.06em;text-transform:uppercase">Refresh from ESPN</button>' +
    '<button id="faSettings" style="flex:1;min-height:46px;border:1px solid var(--line);' +
    'border-radius:3px;color:var(--ink-dim);background:var(--surface);font:inherit;font-size:12px;' +
    'font-weight:600;letter-spacing:.06em;text-transform:uppercase">Settings</button>';
  document.body.appendChild(bar);
  document.getElementById("faRefresh").onclick = function (e) { refresh(e.target); };
  document.getElementById("faSettings").onclick = openSettings;

  if (!cfg().teamId) setTimeout(openSettings, 400);

  /* Test seam. `module` is undefined in a WebView, so this is a no-op in the
     app; under Node it exposes the pure functions so the transform can be
     driven against real ESPN-shaped payloads without a device. */
  if (typeof module !== "undefined" && module.exports) {
    module.exports = { transform: transform, winProbability: winProbability,
                       normCdf: normCdf, projections: projections };
  }
})();
