"""Platform-neutral data models shared by every provider and analysis module."""

from __future__ import annotations

from dataclasses import dataclass, field

# Statuses that mean a player will not play this week.
OUT_STATUSES = {"OUT", "IR", "INJURY_RESERVE", "SUSPENSION", "SUSPENDED", "PUP", "NFI", "COV"}


@dataclass
class Player:
    id: str
    name: str
    position: str  # QB, RB, WR, TE, K, DEF
    nfl_team: str = ""
    injury_status: str = ""  # "", Questionable, Doubtful, Out, IR ...
    projected_points: float | None = None  # this week's projection
    season_points: float | None = None  # fantasy points scored so far this season
    games_played: int | None = None

    @property
    def avg_points(self) -> float | None:
        if self.season_points is None or not self.games_played:
            return None
        return self.season_points / self.games_played

    @property
    def is_out(self) -> bool:
        return self.injury_status.upper().replace(" ", "_") in OUT_STATUSES

    @property
    def score(self) -> float:
        """Single number used to rank players for lineups and trades.

        Blends this week's projection with season average so one weird week
        (or a missing projection) doesn't dominate.
        """
        proj, avg = self.projected_points, self.avg_points
        if proj is not None and avg is not None:
            return 0.6 * proj + 0.4 * avg
        if proj is not None:
            return proj
        if avg is not None:
            return avg
        return 0.0

    def label(self) -> str:
        tag = f" ({self.injury_status})" if self.injury_status else ""
        return f"{self.name} {self.position}-{self.nfl_team or 'FA'}{tag}"

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "position": self.position,
            "nfl_team": self.nfl_team,
            "injury_status": self.injury_status or None,
            "projected_points": _r(self.projected_points),
            "avg_points": _r(self.avg_points),
            "season_points": _r(self.season_points),
            "value_score": _r(self.score),
        }


@dataclass
class Team:
    id: str
    name: str
    owner: str = ""
    wins: int = 0
    losses: int = 0
    ties: int = 0
    points_for: float = 0.0
    points_against: float = 0.0
    roster: list[Player] = field(default_factory=list)
    starter_ids: list[str] = field(default_factory=list)

    def player(self, player_id: str) -> Player | None:
        return next((p for p in self.roster if p.id == player_id), None)

    @property
    def record(self) -> str:
        return f"{self.wins}-{self.losses}" + (f"-{self.ties}" if self.ties else "")


@dataclass
class TradeOffer:
    """A trade proposal from the point of view of *my* team."""

    id: str
    other_team_id: str
    give: list[Player]  # players leaving my team
    get: list[Player]  # players coming to my team
    status: str = "PENDING"
    proposed_by_me: bool = False


@dataclass
class League:
    platform: str  # "sleeper" or "espn"
    id: str
    name: str
    season: int
    week: int
    scoring: str  # "ppr", "half_ppr" or "std"
    # Starting slots, e.g. {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1, "K": 1, "DEF": 1}
    slots: dict[str, int]
    teams: list[Team]
    my_team_id: str
    free_agents: list[Player] = field(default_factory=list)
    trending_adds: list[Player] = field(default_factory=list)
    pending_trades: list[TradeOffer] = field(default_factory=list)
    # team_id -> opponent team_id for the current week
    matchups: dict[str, str] = field(default_factory=dict)

    @property
    def my_team(self) -> Team:
        return self.team(self.my_team_id)

    def team(self, team_id: str) -> Team:
        for t in self.teams:
            if t.id == team_id:
                return t
        raise KeyError(f"No team {team_id!r} in league {self.name}")

    def opponent(self, team_id: str | None = None) -> Team | None:
        opp = self.matchups.get(team_id or self.my_team_id)
        return self.team(opp) if opp else None

    def all_players(self) -> list[Player]:
        seen: dict[str, Player] = {}
        for t in self.teams:
            for p in t.roster:
                seen[p.id] = p
        for p in self.free_agents:
            seen.setdefault(p.id, p)
        return list(seen.values())

    def owner_of(self, player_id: str) -> Team | None:
        return next((t for t in self.teams if t.player(player_id)), None)


def _r(x: float | None) -> float | None:
    return None if x is None else round(x, 1)
