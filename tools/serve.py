#!/usr/bin/env python3
"""Serve the dashboard as a local web app, backed by live ESPN data.

This is the zero-install GUI: no APK, no Play Store, no build. Run it in
Termux, open the URL in Chrome, and "Add to Home Screen" — Android then treats
it like an app, with its own icon and no browser chrome.

    python tools/serve.py                 # http://127.0.0.1:8765
    python tools/serve.py --port 9000
    python tools/serve.py --host 0.0.0.0  # reachable from your LAN (see warning)

Endpoints:
    /              the dashboard, seeded with your live snapshot
    /api/poll      POST-ish (GET works too): re-poll ESPN, then reload
    /api/brief     the weekly brief as plain text
    /api/snapshot  the raw snapshot JSON

Stdlib only — nothing to install beyond `requests`, which the poller needs.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DASHBOARD = os.path.join(ROOT, "dashboard", "index.html")
SNAPSHOT = os.path.join(ROOT, "data", "live", "latest.json")
SEED_RE = re.compile(r'(<script id="data" type="application/json">)(.*?)(</script>)', re.S)

_poll_lock = threading.Lock()


def snapshot_to_dashboard(snap: dict) -> dict:
    """Reshape a live poll snapshot into what dashboard/index.html expects.

    The poller and the dashboard grew separately and use different field names;
    translating here keeps both free to change independently.
    """
    lg = snap.get("league", {}) or {}
    slots = {int(k): int(v) for k, v in (lg.get("rosterSlots") or {}).items()}

    # lineupSlotId -> the dashboard's slot vocabulary.
    label_for = {0: "QB", 2: "RB", 4: "WR", 6: "TE", 16: "D/ST", 17: "K",
                 3: "FLEX", 23: "FLEX", 5: "FLEX", 7: "FLEX", 20: "BE", 21: "IR"}
    counts: dict[str, int] = {}
    for slot_id, n in slots.items():
        label = label_for.get(slot_id)
        if label and label not in ("BE", "IR"):
            counts[label] = counts.get(label, 0) + n

    roster = []
    for p in snap.get("roster", []) or []:
        slot = p.get("lineupSlot") or "BE"
        if slot in ("RB/WR", "RB/WR/TE", "WR/TE", "OP"):
            slot = "FLEX"
        roster.append({
            "n": p.get("name", "?"), "p": p.get("pos", ""), "t": p.get("team", ""),
            "bye": int(p.get("bye", 0) or 0), "w1": float(p.get("proj", 0.0) or 0.0),
            "slot": slot,
            "q": (p.get("inj", "ACTIVE") or "ACTIVE").upper()
                 not in ("ACTIVE", "NORMAL", "PROBABLE"),
        })

    return {
        "_source": f"Live ESPN snapshot, polled {snap.get('generatedAt', 'unknown')}",
        "team": "TheRealTobi",
        "league": lg.get("name", "ESPN league"),
        "season": lg.get("season", 2026),
        "seasonStart": "2026-09-10",
        "teamCount": lg.get("teamCount", 12),
        "week1": {"opponent": "", "projFor": round(
            sum(p["w1"] for p in roster if p["slot"] not in ("BE", "IR")), 1),
            "projAgainst": 0.0, "winProbability": 0.5},
        "lineupSlots": counts or {"QB": 1, "RB": 2, "WR": 2, "FLEX": 1,
                                  "TE": 1, "D/ST": 1, "K": 1},
        "flexEligible": ["RB", "WR"],
        "roster": roster,
        "waiverWatch": [],
        "currentWeek": lg.get("currentWeek"),
    }


def render_dashboard() -> bytes:
    with open(DASHBOARD, encoding="utf-8") as fh:
        html = fh.read()
    if os.path.exists(SNAPSHOT):
        try:
            with open(SNAPSHOT, encoding="utf-8") as fh:
                data = snapshot_to_dashboard(json.load(fh))
            payload = json.dumps(data, separators=(",", ":"))
            if "</script>" not in payload:
                html = SEED_RE.sub(lambda m: m.group(1) + payload + m.group(3), html, count=1)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            print(f"  warning: could not seed live data ({exc}); serving the built-in copy",
                  file=sys.stderr)
    # A refresh control, injected rather than baked in, so the offline dashboard
    # file stays a standalone artifact with no dependency on this server.
    control = """
<div style="position:fixed;left:0;right:0;bottom:0;display:flex;gap:8px;padding:9px 12px;
  background:var(--surface);border-top:1px solid var(--line);z-index:50">
  <button id="pollBtn" style="flex:1;min-height:44px;border:1px solid var(--accent);
    border-radius:3px;color:var(--accent);background:var(--surface);font:inherit;
    font-size:12px;font-weight:600;letter-spacing:.06em;text-transform:uppercase">
    Refresh from ESPN</button>
  <a href="/api/brief" style="flex:1;min-height:44px;display:flex;align-items:center;
    justify-content:center;border:1px solid var(--line);border-radius:3px;
    color:var(--ink-dim);text-decoration:none;font-size:12px;font-weight:600;
    letter-spacing:.06em;text-transform:uppercase">Weekly brief</a>
</div>
<script>
document.getElementById('pollBtn').onclick = async (e) => {
  const b = e.target; const was = b.textContent;
  b.textContent = 'Polling...'; b.disabled = true;
  try {
    const r = await fetch('/api/poll');
    const t = await r.text();
    if (!r.ok) throw new Error(t);
    location.reload();
  } catch (err) {
    b.textContent = 'Failed - tap to retry';
    b.disabled = false;
    alert('Poll failed:\\n\\n' + err.message);
    setTimeout(() => { b.textContent = was; }, 4000);
  }
};
</script>"""
    return (html + control).encode("utf-8")


def run_poll() -> tuple[bool, str]:
    """Run the poller. Serialised: two concurrent polls would race on latest.json."""
    if not _poll_lock.acquire(blocking=False):
        return False, "A poll is already running."
    try:
        proc = subprocess.run(
            [sys.executable, os.path.join(ROOT, "tools", "poll_espn.py")],
            capture_output=True, text=True, timeout=180, cwd=ROOT)
        out = (proc.stdout + proc.stderr).strip()
        return proc.returncode == 0, out or "(no output)"
    except subprocess.TimeoutExpired:
        return False, "Poll timed out after 180s."
    finally:
        _poll_lock.release()


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes, ctype: str = "text/html; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            self._send(200, render_dashboard())
        elif path == "/api/poll":
            ok, out = run_poll()
            self._send(200 if ok else 500, out.encode("utf-8"), "text/plain; charset=utf-8")
        elif path == "/api/brief":
            proc = subprocess.run(
                [sys.executable, os.path.join(ROOT, "tools", "weekly_brief.py")],
                capture_output=True, text=True, cwd=ROOT)
            body = (proc.stdout or proc.stderr or "(no brief)").strip()
            self._send(200, f"<pre style='white-space:pre-wrap;font:14px/1.5 system-ui;"
                            f"padding:16px;max-width:44em;margin:0 auto'>{body}</pre>"
                            f"<p style='text-align:center'><a href='/'>back</a></p>".encode())
        elif path == "/api/snapshot":
            if not os.path.exists(SNAPSHOT):
                self._send(404, b"no snapshot yet", "text/plain")
                return
            with open(SNAPSHOT, "rb") as fh:
                self._send(200, fh.read(), "application/json")
        else:
            self._send(404, b"not found", "text/plain")

    def log_message(self, fmt, *args):  # quieter than the default
        print(f"  {datetime.now(timezone.utc):%H:%M:%S} {fmt % args}", file=sys.stderr)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="127.0.0.1",
                    help="default is loopback only; 0.0.0.0 exposes it to your network")
    args = ap.parse_args()

    if args.host not in ("127.0.0.1", "localhost", "::1"):
        print(f"WARNING: binding to {args.host} exposes this to your whole network. "
              f"There is no authentication here — do not do this on public wifi.\n",
              file=sys.stderr)

    if not os.path.exists(SNAPSHOT):
        print("No snapshot yet — the dashboard will show its built-in demo data.")
        print("Tap 'Refresh from ESPN' in the page, or run tools/poll_espn.py first.\n")

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    shown = "127.0.0.1" if args.host == "0.0.0.0" else args.host
    print(f"Dashboard:  http://{shown}:{args.port}")
    print("In Chrome:  menu -> Add to Home screen, for an app-like icon.")
    print("Ctrl-C to stop.\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
