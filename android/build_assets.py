#!/usr/bin/env python3
"""Generate the app's WebView asset from the canonical dashboard.

The dashboard is the single source of truth. Rather than keeping a second copy
under android/, this splices the app's early and late scripts around it at build
time, so a dashboard change reaches the app with no manual sync.
"""
from __future__ import annotations

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
DASH = os.path.join(REPO, "dashboard", "index.html")
OUT = os.path.join(HERE, "app", "src", "main", "assets", "index.html")

HEAD = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="color-scheme" content="light dark">
<style>html{-webkit-text-size-adjust:100%}body{margin:0}img{max-width:100%}
[hidden]{display:none!important}</style>
</head><body>
"""


def main() -> int:
    html = open(DASH, encoding="utf-8").read()
    early = open(os.path.join(HERE, "app-early.js"), encoding="utf-8").read()
    late = open(os.path.join(HERE, "app-late.js"), encoding="utf-8").read()

    # The early script must sit between the seed data and the dashboard's own
    # script, so it can swap in cached data before the dashboard reads it.
    anchor = '</script>\n<script>'
    if anchor not in html:
        print("ERROR: could not find the seed/script boundary in dashboard/index.html",
              file=sys.stderr)
        return 1
    html = html.replace(anchor, f"</script>\n<script>\n{early}\n</script>\n<script>", 1)

    out = HEAD + html + f"\n<script>\n{late}\n</script>\n</body></html>"
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write(out)
    print(f"wrote {OUT} ({len(out)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
