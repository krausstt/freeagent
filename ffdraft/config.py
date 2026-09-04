"""Credential and league configuration loading.

Precedence: CLI args > environment variables > ~/.ffdraft.json

Credentials are never written to the repo. `~/.ffdraft.json` lives in your home
directory and holds your ESPN session cookies, which are as sensitive as a
password for your ESPN account -- anyone holding them can act as you.
"""

from __future__ import annotations

import getpass
import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

CONFIG_PATH = Path.home() / ".ffdraft.json"


@dataclass
class Credentials:
    league_id: int | None = None
    season: int = 2026
    espn_s2: str | None = None
    swid: str | None = None
    team_id: int | None = None
    draft_slot: int | None = None

    @property
    def is_private(self) -> bool:
        return bool(self.espn_s2 and self.swid)


def load(**overrides) -> Credentials:
    """Merge file, environment and explicit overrides into one Credentials."""
    data: dict = {}
    if CONFIG_PATH.exists():
        try:
            data = json.loads(CONFIG_PATH.read_text())
        except json.JSONDecodeError as exc:
            raise SystemExit(f"{CONFIG_PATH} is not valid JSON: {exc}") from exc

    env_map = {
        "league_id": "ESPN_LEAGUE_ID",
        "season": "ESPN_SEASON",
        "espn_s2": "ESPN_S2",
        "swid": "ESPN_SWID",
        "team_id": "ESPN_TEAM_ID",
        "draft_slot": "ESPN_DRAFT_SLOT",
    }
    for key, env in env_map.items():
        val = os.environ.get(env)
        if val:
            data[key] = val

    for key, val in overrides.items():
        if val is not None:
            data[key] = val

    def as_int(key):
        v = data.get(key)
        return int(v) if v not in (None, "") else None

    return Credentials(
        league_id=as_int("league_id"),
        season=as_int("season") or 2026,
        espn_s2=data.get("espn_s2") or None,
        swid=data.get("swid") or None,
        team_id=as_int("team_id"),
        draft_slot=as_int("draft_slot"),
    )


def restrict_permissions(path: Path) -> str:
    """Make the credential file readable only by its owner.

    On POSIX this is chmod 0600. On Windows chmod does NOT control access --
    NTFS uses ACLs and Path.chmod only toggles the read-only attribute -- so
    pretending 0600 worked there would be a lie. We reset inheritance and grant
    the current user alone, and say plainly if that fails.

    Returns a description of what was actually applied.
    """
    if os.name == "nt":
        try:
            user = os.environ.get("USERNAME") or getpass.getuser()
            for args in (["/inheritance:r"], ["/grant:r", f"{user}:F"]):
                subprocess.run(["icacls", str(path), *args],
                               check=True, capture_output=True)
            return f"ACL restricted to {user}"
        except (subprocess.CalledProcessError, FileNotFoundError, OSError) as exc:
            return (f"WARNING: could not restrict the ACL ({exc}). "
                    f"{path} may be readable by other users on this machine.")
    path.chmod(0o600)
    return "mode 0600"


def save(creds: Credentials) -> Path:
    """Persist credentials to ~/.ffdraft.json, readable only by you."""
    payload = {
        "league_id": creds.league_id,
        "season": creds.season,
        "espn_s2": creds.espn_s2,
        "swid": creds.swid,
        "team_id": creds.team_id,
        "draft_slot": creds.draft_slot,
    }
    CONFIG_PATH.write_text(json.dumps({k: v for k, v in payload.items() if v is not None}, indent=2))
    print(f"  permissions: {restrict_permissions(CONFIG_PATH)}")
    return CONFIG_PATH
