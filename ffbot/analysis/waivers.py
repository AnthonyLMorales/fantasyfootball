"""Waiver-wire pickups and team-strength breakdowns."""

from __future__ import annotations

import difflib

from ..models import League, Player
from .lineup import optimal_lineup
from .value import player_value, replacement_levels


def waiver_suggestions(league: League, limit: int = 10) -> list[dict]:
    """Free agents ranked by how much they'd improve my team, paired with who to drop."""
    me = league.my_team
    levels = replacement_levels(league)
    base = optimal_lineup(me.roster, league.slots)
    trending_ids = {p.id for p in league.trending_adds}
    droppable = sorted(base.bench, key=lambda p: player_value(p, levels))
    drop = droppable[0] if droppable else None

    candidates = {p.id: p for p in league.free_agents}
    for p in league.trending_adds:
        candidates.setdefault(p.id, p)

    ideas = []
    for fa in candidates.values():
        if fa.is_out:
            continue
        roster = [p for p in me.roster if not drop or p.id != drop.id] + [fa]
        gain = optimal_lineup(roster, league.slots).projected_total - base.projected_total
        value_gain = player_value(fa, levels) - (player_value(drop, levels) if drop else 0)
        # A kicker/defense only matters if it would actually start.
        if gain <= 0 and (fa.position in ("K", "DEF") or (value_gain < 1.0 and fa.id not in trending_ids)):
            continue
        ideas.append({
            "add": fa.to_dict(),
            "drop": drop.to_dict() if drop else None,
            "lineup_gain": round(gain, 1),
            "value_gain": round(value_gain, 1),
            "trending": fa.id in trending_ids,
        })
    ideas.sort(key=lambda i: (i["lineup_gain"] + i["value_gain"], i["trending"]), reverse=True)
    return ideas[:limit]


def team_breakdown(league: League, team_id: str | None = None) -> dict:
    """Strength of my starters at each position vs the league average, to spot needs and surpluses."""
    levels = replacement_levels(league)

    def pos_strength(team) -> dict[str, float]:
        lineup = optimal_lineup(team.roster, league.slots)
        out: dict[str, float] = {}
        for p in lineup.starters:
            out[p.position] = out.get(p.position, 0) + p.score
        return out

    all_strength = [pos_strength(t) for t in league.teams]
    positions = sorted({pos for s in all_strength for pos in s})
    avg = {pos: sum(s.get(pos, 0) for s in all_strength) / len(all_strength) for pos in positions}
    team = league.team(team_id or league.my_team_id)
    mine = pos_strength(team)
    lineup = optimal_lineup(team.roster, league.slots)
    bench_value = {}
    for p in lineup.bench:
        bench_value[p.position] = bench_value.get(p.position, 0) + player_value(p, levels)
    ranked = sorted(league.teams, key=lambda t: optimal_lineup(t.roster, league.slots).projected_total, reverse=True)
    return {
        "team": team.name,
        "record": team.record,
        "points_for": round(team.points_for, 1),
        "power_rank": 1 + [t.id for t in ranked].index(team.id),
        "num_teams": len(league.teams),
        "by_position": {
            pos: {
                "my_starters": round(mine.get(pos, 0), 1),
                "league_avg": round(avg[pos], 1),
                "diff": round(mine.get(pos, 0) - avg[pos], 1),
                "bench_value": round(bench_value.get(pos, 0), 1),
            }
            for pos in positions
        },
        "needs": [pos for pos in positions if mine.get(pos, 0) < avg[pos] * 0.92],
        "surplus": [pos for pos in positions if bench_value.get(pos, 0) > 3],
    }


def standings(league: League) -> list[dict]:
    rows = sorted(league.teams, key=lambda t: (t.wins + 0.5 * t.ties, t.points_for), reverse=True)
    return [
        {"rank": i + 1, "team": t.name, "owner": t.owner, "record": t.record,
         "points_for": round(t.points_for, 1), "points_against": round(t.points_against, 1),
         "is_me": t.id == league.my_team_id}
        for i, t in enumerate(rows)
    ]


def find_players(league: League, names: list[str]) -> tuple[list[Player], list[str]]:
    """Fuzzy-match player names against everyone in the league (rosters + free agents)."""
    everyone = league.all_players()
    by_name = {p.name.lower(): p for p in everyone}
    found, missing = [], []
    for raw in names:
        q = raw.strip().lower()
        if not q:
            continue
        if q in by_name:
            found.append(by_name[q])
            continue
        partial = [p for n, p in by_name.items() if q in n]
        if len(partial) == 1:
            found.append(partial[0])
            continue
        close = difflib.get_close_matches(q, list(by_name), n=1, cutoff=0.6)
        if close:
            found.append(by_name[close[0]])
        else:
            missing.append(raw)
    return found, missing
