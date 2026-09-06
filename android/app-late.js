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
     is the only correct choice for a weekly column. */
  function projections(player, week) {
    var season = 0, wk = 0, stats = player.stats || [];
    for (var i = 0; i < stats.length; i++) {
      var st = stats[i];
      if (st.statSourceId !== 1) continue;
      if (st.scoringPeriodId === 0) season = st.appliedTotal || 0;
      else if (st.scoringPeriodId === week) wk = st.appliedTotal || 0;
    }
    return { week: wk, season: season };
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

  function transform(league, seasonJson, teamId) {
    var s = league.settings || {};
    var slots = (s.rosterSettings || {}).lineupSlotCounts || {};
    var week = league.scoringPeriodId || 1;
    var byes = seasonJson ? byeWeeks(seasonJson) : {};

    var counts = {};
    Object.keys(slots).forEach(function (k) {
      var n = slots[k] | 0, lbl = SLOT[k | 0];
      if (n > 0 && lbl && lbl !== "BE" && lbl !== "IR") counts[lbl] = (counts[lbl] || 0) + n;
    });

    var team = null, teams = league.teams || [];
    for (var i = 0; i < teams.length; i++) if (teams[i].id === teamId) team = teams[i];
    if (!team) throw new Error("Team " + teamId + " not in this league.");

    var roster = [], entries = ((team.roster || {}).entries) || [];
    for (var j = 0; j < entries.length; j++) {
      var e = entries[j];
      var p = ((e.playerPoolEntry || {}).player) || {};
      var pos = primaryPos(p.eligibleSlots);
      if (!pos) continue;
      var pr = projections(p, week);
      var slot = SLOT[e.lineupSlotId] || "BE";
      var pt = PRO[p.proTeamId] || "";
      var inj = (p.injuryStatus || "ACTIVE").toUpperCase();
      roster.push({
        n: p.fullName || "?", p: pos, t: pt,
        bye: byes[pt] || 0,
        w1: Math.round(pr.week * 10) / 10,
        season: Math.round(pr.season * 10) / 10,
        slot: slot,
        q: inj !== "ACTIVE" && inj !== "NORMAL" && inj !== "PROBABLE"
      });
    }

    var starters = roster.filter(function (r) { return r.slot !== "BE" && r.slot !== "IR"; });
    var total = starters.reduce(function (a, r) { return a + r.w1; }, 0);

    return {
      _source: "Live ESPN pull, " + new Date().toISOString(),
      team: team.name || ("Team " + teamId),
      league: s.name || "ESPN league",
      season: league.seasonId || 2026,
      teamCount: s.size || 12,
      currentWeek: week,
      week1: { opponent: "", projFor: Math.round(total * 10) / 10,
               projAgainst: 0, winProbability: 0.5 },
      lineupSlots: counts,
      flexEligible: ["RB", "WR"],
      roster: roster,
      waiverWatch: []
    };
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
    onDone = function () {
      btn.textContent = was; btn.disabled = false;
      var lg, se = null;
      try { lg = JSON.parse(gotLeague); } catch (e) { alert("Bad response from ESPN."); return; }
      if (!lg.ok) { alert("ESPN error:\n\n" + lg.error); return; }
      try { var s = JSON.parse(gotSeason); if (s.ok) se = s.data; } catch (e) { /* byes optional */ }
      try {
        var data = transform(lg.data, se, parseInt(c.teamId, 10));
        localStorage.setItem(KEY_DATA, JSON.stringify(data));
        location.reload();
      } catch (err) { alert("Could not read that league:\n\n" + err.message); }
    };
    Native.fetchLeague(String(c.leagueId), String(c.season || 2026),
      "mSettings,mTeam,mRoster", "__faLeague");
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
})();
