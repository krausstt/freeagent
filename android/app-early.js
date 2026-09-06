/* Runs BEFORE the dashboard script. If the app has cached a league pull, swap it
   into the seed element so the dashboard initialises from live data instead of
   its built-in copy. Synchronous and tiny by design -- the dashboard's own
   script runs immediately after this one. */
(function () {
  "use strict";
  try {
    var cached = localStorage.getItem("freeagent.data.v1");
    if (!cached) return;
    var el = document.getElementById("data");
    if (el && cached.indexOf("</script") === -1) el.textContent = cached;
  } catch (e) { /* first run, or storage blocked: fall through to seed data */ }
})();
