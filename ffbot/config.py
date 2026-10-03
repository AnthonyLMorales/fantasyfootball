"""Load config.yaml describing your leagues."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .demo import demo_league
from .models import League
from .providers import ESPNProvider, SleeperProvider

DEFAULT_PATH = Path(os.environ.get("FFBOT_CONFIG", "config.yaml"))


@dataclass
class LeagueConfig:
    name: str
    platform: str
    options: dict = field(default_factory=dict)

    def load(self) -> League:
        o = self.options
        if self.platform == "sleeper":
            return SleeperProvider(league_id=o["league_id"], username=o["username"], name=self.name).load()
        if self.platform == "espn":
            return ESPNProvider(
                league_id=o["league_id"],
                season=o["season"],
                team_id=o.get("team_id"),
                espn_s2=o.get("espn_s2"),
                swid=o.get("swid"),
                name=self.name,
            ).load()
        if self.platform == "demo":
            league = demo_league(int(o.get("seed", 7)))
            league.name = self.name
            return league
        raise ValueError(f"Unknown platform {self.platform!r} for league {self.name!r} (use sleeper, espn or demo)")


def _expand(value):
    if isinstance(value, str):
        return os.path.expandvars(value)
    if isinstance(value, dict):
        return {k: _expand(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand(v) for v in value]
    return value


def load_config(path: Path | str | None = None) -> list[LeagueConfig]:
    path = Path(path or DEFAULT_PATH)
    if not path.exists():
        raise FileNotFoundError(f"{path} not found. Copy config.example.yaml to config.yaml and fill it in.")
    data = _expand(yaml.safe_load(path.read_text()) or {})
    leagues = []
    for i, entry in enumerate(data.get("leagues") or []):
        entry = dict(entry)
        platform = str(entry.pop("platform", "")).lower()
        name = entry.pop("name", f"{platform} league {i + 1}")
        leagues.append(LeagueConfig(name=name, platform=platform, options=entry))
    if not leagues:
        raise ValueError(f"No leagues listed in {path}")
    return leagues
