"""A deterministic fake league so you can try every command without credentials."""

from __future__ import annotations

import random

from .models import League, Player, Team, TradeOffer

TEAM_NAMES = [
    "My Demo Team", "Gridiron Gurus", "Touchdown Tyrants", "Fourth & Long", "Blitz Brigade",
    "End Zone Elite", "Hail Marys", "Pigskin Prophets", "Red Zone Rebels", "Sack Masters",
]
NFL = ["BUF", "KC", "PHI", "SF", "DAL", "DET", "MIA", "BAL", "CIN", "GB", "LAR", "SEA", "MIN", "HOU"]
# position: (how many to generate, best weekly score, decay per rank)
POOL = {"QB": (26, 26, 0.5), "RB": (75, 22, 0.25), "WR": (75, 21, 0.2), "TE": (26, 15, 0.4),
        "K": (14, 10, 0.2), "DEF": (14, 11, 0.3)}


def demo_league(seed: int = 7) -> League:
    rng = random.Random(seed)
    players: dict[str, list[Player]] = {}
    for pos, (count, top, decay) in POOL.items():
        players[pos] = []
        for i in range(count):
            base = max(1.0, top - decay * i + rng.uniform(-1.5, 1.5))
            gp = 4
            injury = rng.choice(["", "", "", "", "", "", "", "", "Questionable", "Out"]) if pos not in ("K", "DEF") else ""
            players[pos].append(Player(
                id=f"{pos}{i + 1}",
                name=f"{pos} Player {i + 1}" if pos != "DEF" else f"{NFL[i % len(NFL)]} Defense",
                position=pos,
                nfl_team=NFL[i % len(NFL)],
                injury_status=injury,
                projected_points=0.0 if injury == "Out" else round(base + rng.uniform(-2, 2), 1),
                season_points=round(base * gp + rng.uniform(-6, 6), 1),
                games_played=gp,
            ))

    teams = [Team(id=str(i + 1), name=n, owner=f"owner{i + 1}") for i, n in enumerate(TEAM_NAMES)]
    # Snake draft where each team leans RB- or WR-heavy, so rosters have real needs and surpluses.
    needs = {}
    for t in teams:
        rb = rng.randint(3, 7)
        needs[t.id] = {"QB": 2, "RB": rb, "WR": 10 - rb, "TE": 2, "K": 1, "DEF": 1}
    for rnd in range(sum(needs["1"].values())):
        order = teams if rnd % 2 == 0 else list(reversed(teams))
        for t in order:
            open_pos = [pos for pos, n in needs[t.id].items() if n > 0 and players[pos]]
            if rnd < 10:  # kickers and defenses go late
                open_pos = [pos for pos in open_pos if pos not in ("K", "DEF")] or open_pos
            pos = rng.choice(open_pos)
            needs[t.id][pos] -= 1
            t.roster.append(players[pos].pop(0))
    for t in teams:
        t.wins = rng.randint(0, 4)
        t.losses = 4 - t.wins
        t.points_for = round(rng.uniform(380, 520), 1)
        t.points_against = round(rng.uniform(380, 520), 1)
        # Start the earliest-drafted players, except bench the best WR, so there's a lineup fix to find.
        picks = {"QB": 1, "RB": 2, "WR": 3, "TE": 1, "K": 1, "DEF": 1}
        starters = []
        for pos, n in picks.items():
            starters += [p.id for p in t.roster if p.position == pos][:n]
        wrs = [p.id for p in t.roster if p.position == "WR"]
        if len(wrs) > 3:
            starters[starters.index(wrs[0])] = wrs[3]
        t.starter_ids = starters

    free_agents = [p for pos in players.values() for p in pos]
    me, other = teams[0], teams[3]
    offer = TradeOffer(
        id="demo-1",
        other_team_id=other.id,
        give=sorted((p for p in me.roster if p.position == "RB"), key=lambda p: p.score, reverse=True)[:1],
        get=sorted((p for p in other.roster if p.position == "WR"), key=lambda p: p.score)[:2],
    )
    return League(
        platform="demo",
        id="demo",
        name="Demo League",
        season=2026,
        week=5,
        scoring="ppr",
        slots={"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1, "K": 1, "DEF": 1},
        teams=teams,
        my_team_id=me.id,
        free_agents=free_agents,
        trending_adds=free_agents[:3],
        pending_trades=[offer],
        matchups={"1": "2", "2": "1"},
    )
