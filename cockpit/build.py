#!/usr/bin/env python3
"""Regenerate the demo data embedded in index.html.

index.html is self-contained on purpose -- it must work with no network in a
draft room -- so the demo dataset lives inline. This script rewrites just the
<script id="seedData"> block, leaving the rest of the page untouched.

    python3 cockpit/build.py
"""

from __future__ import annotations

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))

from ffdraft.board import DraftBoard  # noqa: E402
from ffdraft.export import build_snapshot  # noqa: E402
from tests.fixtures import make_config, make_players  # noqa: E402

PATTERN = re.compile(
    r'(<script id="seedData" type="application/json">)(.*?)(</script>)', re.S
)


def main() -> int:
    board = DraftBoard(make_config(), make_players(), n_sims=2000)
    snapshot = build_snapshot(board, top_n=180)
    snapshot["demo"] = True
    snapshot["league"]["name"] = "Demo League (synthetic data)"
    payload = json.dumps(snapshot, separators=(",", ":"))

    # Guard against breaking out of the script element.
    if "</script>" in payload:
        raise SystemExit("refusing to write: payload contains a closing script tag")

    data_path = os.path.join(HERE, "demo_data.json")
    with open(data_path, "w", encoding="utf-8") as fh:
        fh.write(payload)

    page_path = os.path.join(HERE, "index.html")
    page = open(page_path, encoding="utf-8").read()
    if not PATTERN.search(page):
        raise SystemExit("could not find the seedData script block in index.html")
    page = PATTERN.sub(lambda m: m.group(1) + payload + m.group(3), page, count=1)
    with open(page_path, "w", encoding="utf-8") as fh:
        fh.write(page)

    print(f"embedded {len(snapshot['players'])} players ({len(payload)} bytes) into index.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
