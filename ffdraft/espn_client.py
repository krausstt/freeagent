"""Read-only client for ESPN's undocumented Fantasy v3 API.

Scope note (verified, not assumed): ESPN exposes no public write endpoint for
fantasy actions. The maintained `espn-api` client (PyPI 0.30.0) contains zero
POST/PUT/PATCH calls -- its only POST code is a commented-out login flow that
was disabled when ESPN put Google reCAPTCHA in front of authentication. So this
client reads; making a pick stays a human action in the ESPN app.

Two hosts serve the same v3 payloads:
  - fantasy.espn.com/apis/v3/...          (used by espn-api 0.30.0)
  - lm-api-reads.fantasy.espn.com/...     (read-optimised; used by the web app)
We try the read-optimised host first and fall back, because which one is
reachable varies by network and by ESPN's own routing.
"""

from __future__ import annotations

import json
import time
from typing import Any

import requests

HOSTS = (
    "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl",
    "https://fantasy.espn.com/apis/v3/games/ffl",
)

# ESPN 403s requests without a browser-ish UA from some networks.
DEFAULT_UA = (
    "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Mobile Safari/537.36"
)


class ESPNError(RuntimeError):
    """Base for all ESPN client failures."""


class ESPNAuthError(ESPNError):
    """401/403 - cookies missing, expired, or not valid for this league."""


class ESPNNotFound(ESPNError):
    """404 - league id or season does not exist."""


class ESPNClient:
    """Minimal, dependency-light ESPN Fantasy Football reader."""

    def __init__(
        self,
        league_id: int,
        season: int,
        espn_s2: str | None = None,
        swid: str | None = None,
        timeout: int = 20,
        retries: int = 3,
    ) -> None:
        self.league_id = int(league_id)
        self.season = int(season)
        self.timeout = timeout
        self.retries = retries
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": DEFAULT_UA, "Accept": "application/json"})
        if espn_s2 and swid:
            # SWID must keep its braces. Users routinely strip them; put them back.
            swid = swid.strip()
            if not swid.startswith("{"):
                swid = "{" + swid.strip("{}") + "}"
            self.session.cookies.update({"espn_s2": espn_s2.strip(), "SWID": swid})
        self._host: str | None = None

    # ---------------------------------------------------------------- internals

    def _league_path(self) -> str:
        if self.season < 2018:
            return f"/leagueHistory/{self.league_id}?seasonId={self.season}"
        return f"/seasons/{self.season}/segments/0/leagues/{self.league_id}"

    def _request(self, path: str, params: dict | None, headers: dict | None) -> Any:
        """GET `path` against whichever host answers, with backoff on 429/5xx."""
        hosts = (self._host,) if self._host else HOSTS
        last_exc: Exception | None = None

        for host in hosts:
            url = host + path
            for attempt in range(self.retries):
                try:
                    resp = self.session.get(
                        url, params=params, headers=headers, timeout=self.timeout
                    )
                except requests.RequestException as exc:
                    last_exc = exc
                    time.sleep(2**attempt)
                    continue

                if resp.status_code in (401, 403):
                    raise ESPNAuthError(
                        f"ESPN returned {resp.status_code} for league {self.league_id}. "
                        "For a private league you need valid espn_s2 + SWID cookies, and "
                        "the account holding them must be a member of the league. "
                        "Run `python -m tools.find_league --help` for how to extract them."
                    )
                if resp.status_code == 404:
                    raise ESPNNotFound(
                        f"League {self.league_id} not found for season {self.season}. "
                        "Check the leagueId in your ESPN URL and that the season has started."
                    )
                if resp.status_code == 429 or resp.status_code >= 500:
                    last_exc = ESPNError(f"HTTP {resp.status_code} from {host}")
                    time.sleep(2**attempt)
                    continue
                if resp.status_code != 200:
                    last_exc = ESPNError(f"HTTP {resp.status_code} from {host}")
                    break

                self._host = host  # remember the host that worked
                data = resp.json()
                # Pre-2018 leagueHistory returns a single-element list.
                if self.season < 2018 and isinstance(data, list):
                    return data[0]
                return data

        raise ESPNError(f"All ESPN hosts failed for {path}: {last_exc}")

    def _league_get(self, views: list[str], filters: dict | None = None) -> Any:
        headers = {"x-fantasy-filter": json.dumps(filters)} if filters else None
        return self._request(self._league_path(), {"view": views}, headers)

    # ------------------------------------------------------------------- public

    def league(self) -> dict:
        """Settings, teams, rosters and standings in one call."""
        return self._league_get(["mSettings", "mTeam", "mRoster", "mStandings"])

    def settings(self) -> dict:
        return self._league_get(["mSettings"])

    def draft_detail(self) -> dict:
        """Live draft state: `draftDetail.drafted` (bool) and `draftDetail.picks`."""
        return self._league_get(["mDraftDetail"])

    def player_pool(self, limit: int = 700, sort_rank: str = "PPR") -> dict:
        """The draftable player universe with ESPN's own projections and ADP.

        `sort_rank` selects which ESPN draft-rank set to sort by: "PPR" or
        "STANDARD". The response carries both regardless of the sort.
        """
        if sort_rank not in ("PPR", "STANDARD"):
            raise ValueError(f"sort_rank must be 'PPR' or 'STANDARD', got {sort_rank!r}")
        filters = {
            "players": {
                "limit": limit,
                "sortDraftRanks": {
                    "sortPriority": 100,
                    "sortAsc": True,
                    "value": sort_rank,
                },
            }
        }
        return self._league_get(["kona_player_info"], filters)

    def pro_schedule(self) -> dict:
        """NFL team schedules for the season. Used to derive bye weeks."""
        return self._request(
            f"/seasons/{self.season}", {"view": "proTeamSchedules_wl"}, None
        )

    def verify(self) -> dict:
        """Cheap end-to-end connectivity + auth check. Used by tools/verify_espn.py."""
        data = self.settings()
        settings = data.get("settings", {})
        return {
            "ok": True,
            "host": self._host,
            "league_name": settings.get("name", "<unknown>"),
            "team_count": settings.get("size"),
            "season": self.season,
            "authenticated": bool(self.session.cookies.get("espn_s2")),
        }
