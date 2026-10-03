"""ESPN Fantasy Football provider.

Uses ESPN's (unofficial) v3 JSON API — the same one fantasy.espn.com uses.
Public leagues need only the league id. Private leagues also need the
`espn_s2` and `SWID` cookies from a logged-in browser session (see README).
"""

from __future__ import annotations

import json

from ..models import League, Player, Team, TradeOffer
from .base import ProviderError, get_json

API = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/{season}/segments/0/leagues/{league_id}"

POSITIONS = {1: "QB", 2: "RB", 3: "WR", 4: "TE", 5: "K", 16: "DEF"}
# lineupSlotId -> our slot name (bench / IR are excluded from starting slots)
SLOTS = {0: "QB", 2: "RB", 3: "RB/WR", 4: "WR", 5: "WR/TE", 6: "TE", 7: "SUPER_FLEX", 16: "DEF", 17: "K", 23: "FLEX"}
BENCH_SLOTS = {20, 21}
PRO_TEAMS = {
    0: "FA", 1: "ATL", 2: "BUF", 3: "CHI", 4: "CIN", 5: "CLE", 6: "DAL", 7: "DEN", 8: "DET", 9: "GB",
    10: "TEN", 11: "IND", 12: "KC", 13: "LV", 14: "LAR", 15: "MIA", 16: "MIN", 17: "NE", 18: "NO",
    19: "NYG", 20: "NYJ", 21: "PHI", 22: "ARI", 23: "PIT", 24: "LAC", 25: "SF", 26: "SEA", 27: "TB",
    28: "WSH", 29: "CAR", 30: "JAX", 33: "BAL", 34: "HOU",
}
RECEPTION_STAT_ID = 53


class ESPNProvider:
    def __init__(
        self,
        league_id: str,
        season: int,
        team_id: str | int | None = None,
        espn_s2: str | None = None,
        swid: str | None = None,
        name: str | None = None,
    ):
        self.league_id = str(league_id)
        self.season = int(season)
        self.team_id = str(team_id) if team_id not in (None, "") else None
        self.cookies = {"espn_s2": espn_s2, "SWID": swid} if espn_s2 and swid else None
        self.swid = swid
        self.display_name = name

    @property
    def url(self) -> str:
        return API.format(season=self.season, league_id=self.league_id)

    def _get(self, views: list[str], headers: dict | None = None):
        return get_json(self.url, params=[("view", v) for v in views], cookies=self.cookies, headers=headers)

    def fetch_raw(self) -> dict:
        data = self._get(["mTeam", "mRoster", "mSettings", "mMatchupScore", "mStatus"])
        week = int(data.get("scoringPeriodId") or 1)
        fa_filter = {
            "players": {
                "filterStatus": {"value": ["FREEAGENT", "WAIVERS"]},
                "filterSlotIds": {"value": [0, 2, 4, 6, 16, 17, 23]},
                "limit": 80,
                "sortPercOwned": {"sortPriority": 1, "sortAsc": False},
                "filterRanksForScoringPeriodIds": {"value": [week]},
            }
        }
        try:
            fa = self._get(["kona_player_info"], headers={"x-fantasy-filter": json.dumps(fa_filter)})
        except ProviderError:
            fa = {}
        try:
            # Best-effort: ESPN only returns pending trades to a member of the league.
            pending = self._get(["mPendingTransactions"])
        except ProviderError:
            pending = {}
        return {"league": data, "free_agents": fa.get("players", []), "pending": pending}

    def load(self) -> League:
        return build_league(self.fetch_raw(), team_id=self.team_id, swid=self.swid, display_name=self.display_name)


def _player(entry: dict, season: int, week: int) -> Player:
    p = entry.get("player") or entry.get("playerPoolEntry", {}).get("player") or {}
    proj = season_total = season_avg = None
    for s in p.get("stats") or []:
        if s.get("seasonId") not in (None, season):
            continue
        if s.get("statSourceId") == 1 and s.get("scoringPeriodId") == week:
            proj = float(s.get("appliedTotal") or 0)
        elif s.get("statSourceId") == 0 and s.get("statSplitTypeId") == 0:
            season_total = float(s.get("appliedTotal") or 0)
            season_avg = s.get("appliedAverage")
    games = round(season_total / season_avg) if season_total and season_avg else None
    pos = POSITIONS.get(p.get("defaultPositionId"), "?")
    injury = (p.get("injuryStatus") or "").upper()
    return Player(
        id=str(p.get("id", entry.get("playerId", entry.get("id")))),
        name=p.get("fullName", "Unknown"),
        position=pos,
        nfl_team=PRO_TEAMS.get(p.get("proTeamId"), ""),
        injury_status="" if injury in ("", "ACTIVE", "NORMAL") else injury.replace("_", " ").title(),
        projected_points=proj,
        season_points=season_total,
        games_played=games,
    )


def _team_name(t: dict) -> str:
    if t.get("name"):
        return t["name"]
    return f"{t.get('location', '')} {t.get('nickname', '')}".strip() or f"Team {t['id']}"


def _norm_swid(s: str | None) -> str:
    return (s or "").strip().strip("{}").upper()


def build_league(raw: dict, team_id: str | None = None, swid: str | None = None, display_name: str | None = None) -> League:
    data = raw["league"]
    settings = data.get("settings") or {}
    season = int(data.get("seasonId"))
    week = int(data.get("scoringPeriodId") or 1)

    rec_pts = 0.0
    for item in (settings.get("scoringSettings") or {}).get("scoringItems") or []:
        if item.get("statId") == RECEPTION_STAT_ID:
            rec_pts = float(item.get("points") or 0)
    scoring = "ppr" if rec_pts >= 1 else "half_ppr" if rec_pts >= 0.5 else "std"

    slots: dict[str, int] = {}
    for sid, count in ((settings.get("rosterSettings") or {}).get("lineupSlotCounts") or {}).items():
        name = SLOTS.get(int(sid))
        if name and count and int(sid) not in BENCH_SLOTS:
            slots[name] = slots.get(name, 0) + int(count)

    members = {m["id"]: m for m in data.get("members") or []}
    teams: list[Team] = []
    my_team_id = team_id
    for t in data.get("teams") or []:
        overall = (t.get("record") or {}).get("overall") or {}
        owners = t.get("owners") or [t.get("primaryOwner")]
        owner = members.get(t.get("primaryOwner") or (owners[0] if owners else ""), {})
        entries = (t.get("roster") or {}).get("entries") or []
        team = Team(
            id=str(t["id"]),
            name=_team_name(t),
            owner=owner.get("displayName", ""),
            wins=int(overall.get("wins", 0)),
            losses=int(overall.get("losses", 0)),
            ties=int(overall.get("ties", 0)),
            points_for=float(overall.get("pointsFor", 0)),
            points_against=float(overall.get("pointsAgainst", 0)),
            roster=[_player(e, season, week) for e in entries],
            starter_ids=[str(e["playerId"]) for e in entries if e.get("lineupSlotId") not in BENCH_SLOTS],
        )
        teams.append(team)
        if my_team_id is None and swid and any(_norm_swid(o) == _norm_swid(swid) for o in owners if o):
            my_team_id = team.id
    if my_team_id is None:
        raise ProviderError("Set team_id for your ESPN league in config.yaml (could not detect it from SWID).")

    matchups: dict[str, str] = {}
    for m in data.get("schedule") or []:
        if m.get("matchupPeriodId") != data.get("status", {}).get("currentMatchupPeriod", week):
            continue
        home, away = (m.get("home") or {}).get("teamId"), (m.get("away") or {}).get("teamId")
        if home is not None and away is not None:
            matchups[str(home)], matchups[str(away)] = str(away), str(home)

    league = League(
        platform="espn",
        id=str(data.get("id")),
        name=display_name or settings.get("name") or "ESPN League",
        season=season,
        week=week,
        scoring=scoring,
        slots=slots,
        teams=teams,
        my_team_id=str(my_team_id),
        free_agents=[_player(p, season, week) for p in raw.get("free_agents") or []],
        matchups=matchups,
    )
    league.pending_trades = _pending_trades(raw.get("pending") or {}, league)
    return league


def _pending_trades(pending: dict, league: League) -> list[TradeOffer]:
    """Parse trade proposals involving my team (best-effort; ESPN's shape is undocumented)."""
    me = league.my_team_id
    lookup = {p.id: p for p in league.all_players()}
    offers = []
    for tx in pending.get("pendingTransactions") or pending.get("transactions") or []:
        if tx.get("type") not in ("TRADE_PROPOSAL", "TRADE_UPHOLD") or tx.get("status") not in ("PENDING", None):
            continue
        give, get, other = [], [], None
        for item in tx.get("items") or []:
            pid = str(item.get("playerId"))
            frm, to = str(item.get("fromTeamId")), str(item.get("toTeamId"))
            player = lookup.get(pid) or Player(id=pid, name=f"Player {pid}", position="?")
            if frm == me:
                give.append(player)
                other = to
            elif to == me:
                get.append(player)
                other = frm
        if give or get:
            offers.append(
                TradeOffer(
                    id=str(tx.get("id")),
                    other_team_id=other or "",
                    give=give,
                    get=get,
                    status=tx.get("status") or "PENDING",
                    proposed_by_me=str(tx.get("teamId")) == me,
                )
            )
    return offers
