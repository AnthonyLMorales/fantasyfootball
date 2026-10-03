"""Sleeper provider.

Sleeper's API is public and read-only (no login needed): https://docs.sleeper.com
Projections and season stats come from endpoints the Sleeper app itself uses;
they are undocumented, so failures there are tolerated and the bot falls back
to whatever data it has.
"""

from __future__ import annotations

from collections import Counter

from ..models import League, Player, Team
from .base import ProviderError, cached_json, get_json

API = "https://api.sleeper.app/v1"
APP_API = "https://api.sleeper.app"
FANTASY_POSITIONS = ["QB", "RB", "WR", "TE", "K", "DEF"]
NON_STARTING_SLOTS = {"BN", "IR", "TAXI"}


class SleeperProvider:
    def __init__(self, league_id: str, username: str, name: str | None = None):
        self.league_id = str(league_id)
        self.username = username
        self.display_name = name

    def fetch_raw(self) -> dict:
        state = get_json(f"{API}/state/nfl")
        league = get_json(f"{API}/league/{self.league_id}")
        season = int(league.get("season") or state["season"])
        week = max(1, int(state.get("display_week") or state.get("week") or 1))
        user = get_json(f"{API}/user/{self.username}")
        if not user:
            raise ProviderError(f"Sleeper user {self.username!r} not found")
        return {
            "state": state,
            "league": league,
            "week": week,
            "my_user_id": user["user_id"],
            "users": get_json(f"{API}/league/{self.league_id}/users"),
            "rosters": get_json(f"{API}/league/{self.league_id}/rosters"),
            "matchups": _optional(lambda: get_json(f"{API}/league/{self.league_id}/matchups/{week}"), []),
            "players": cached_json("sleeper_players", 24, lambda: get_json(f"{API}/players/nfl", timeout=120)),
            "projections": _optional(lambda: _app_stats("projections", season, week), []),
            "season_stats": _optional(lambda: _app_stats("stats", season, None), []),
            "trending": _optional(
                lambda: get_json(f"{API}/players/nfl/trending/add", params={"lookback_hours": 48, "limit": 25}), []
            ),
        }

    def load(self) -> League:
        return build_league(self.fetch_raw(), self.display_name)


def _app_stats(kind: str, season: int, week: int | None) -> list:
    path = f"{APP_API}/{kind}/nfl/{season}" + (f"/{week}" if week else "")
    params = [("season_type", "regular")] + [("position[]", p) for p in FANTASY_POSITIONS]
    return get_json(path, params=params)


def _optional(fn, default):
    try:
        return fn()
    except ProviderError:
        return default


def _points_key(league: dict) -> tuple[str, str]:
    rec = float((league.get("scoring_settings") or {}).get("rec", 0) or 0)
    if rec >= 1:
        return "ppr", "pts_ppr"
    if rec >= 0.5:
        return "half_ppr", "pts_half_ppr"
    return "std", "pts_std"


def build_league(raw: dict, display_name: str | None = None) -> League:
    league = raw["league"]
    scoring, pts_key = _points_key(league)
    db: dict = raw["players"]

    proj = {
        str(r["player_id"]): float((r.get("stats") or {}).get(pts_key) or 0)
        for r in raw.get("projections") or []
        if r.get("player_id")
    }
    stats = {
        str(r["player_id"]): r.get("stats") or {}
        for r in raw.get("season_stats") or []
        if r.get("player_id")
    }

    def make_player(pid: str) -> Player:
        info = db.get(pid) or {}
        pos = info.get("position") or (info.get("fantasy_positions") or ["?"])[0]
        if pos == "DEF" or (not info and pid.isalpha()):
            name = f"{info.get('first_name', pid)} {info.get('last_name', 'D/ST')}".strip()
            pos = "DEF"
        else:
            name = info.get("full_name") or f"{info.get('first_name', '')} {info.get('last_name', '')}".strip() or pid
        s = stats.get(pid, {})
        return Player(
            id=pid,
            name=name,
            position=pos,
            nfl_team=info.get("team") or (pid if pos == "DEF" else ""),
            injury_status=info.get("injury_status") or "",
            projected_points=proj.get(pid),
            season_points=float(s[pts_key]) if pts_key in s else None,
            games_played=int(s.get("gp") or 0) or None,
        )

    users = {u["user_id"]: u for u in raw.get("users") or []}
    teams: list[Team] = []
    my_team_id = None
    rostered: set[str] = set()
    for r in raw["rosters"]:
        owner = users.get(r.get("owner_id") or "", {})
        st = r.get("settings") or {}
        players = [str(p) for p in (r.get("players") or [])]
        rostered.update(players)
        team = Team(
            id=str(r["roster_id"]),
            name=(owner.get("metadata") or {}).get("team_name") or owner.get("display_name") or f"Team {r['roster_id']}",
            owner=owner.get("display_name", ""),
            wins=int(st.get("wins", 0)),
            losses=int(st.get("losses", 0)),
            ties=int(st.get("ties", 0)),
            points_for=float(st.get("fpts", 0)) + float(st.get("fpts_decimal", 0)) / 100,
            points_against=float(st.get("fpts_against", 0)) + float(st.get("fpts_against_decimal", 0)) / 100,
            roster=[make_player(p) for p in players],
            starter_ids=[str(p) for p in (r.get("starters") or []) if p and p != "0"],
        )
        teams.append(team)
        if r.get("owner_id") == raw["my_user_id"] or raw["my_user_id"] in (r.get("co_owners") or []):
            my_team_id = team.id
    if my_team_id is None:
        raise ProviderError(f"Could not find your roster in Sleeper league {league.get('name')}")

    slots = Counter(p for p in league.get("roster_positions") or [] if p not in NON_STARTING_SLOTS)

    by_matchup: dict[int, list[str]] = {}
    for m in raw.get("matchups") or []:
        if m.get("matchup_id"):
            by_matchup.setdefault(m["matchup_id"], []).append(str(m["roster_id"]))
    matchups = {}
    for ids in by_matchup.values():
        if len(ids) == 2:
            matchups[ids[0]], matchups[ids[1]] = ids[1], ids[0]

    # Free agents = fantasy-relevant players not on any roster, best projections first.
    fa_ids = [
        pid
        for pid, pts in sorted(proj.items(), key=lambda kv: kv[1], reverse=True)
        if pid not in rostered and pts > 0 and (db.get(pid) or {}).get("position") in FANTASY_POSITIONS
    ][:80]
    trending = [str(t["player_id"]) for t in raw.get("trending") or [] if str(t.get("player_id")) not in rostered]

    return League(
        platform="sleeper",
        id=str(league["league_id"]),
        name=display_name or league.get("name", "Sleeper League"),
        season=int(league.get("season") or raw["state"].get("season")),
        week=int(raw["week"]),
        scoring=scoring,
        slots=dict(slots),
        teams=teams,
        my_team_id=my_team_id,
        free_agents=[make_player(p) for p in fa_ids],
        trending_adds=[make_player(p) for p in trending],
        matchups=matchups,
    )
