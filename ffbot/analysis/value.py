"""Player value relative to replacement level (VORP-style).

A 15-point TE is worth more than a 15-point WR if replacement TEs score 6
and replacement WRs score 11. Value = score - replacement score at position.
"""

from __future__ import annotations

from ..models import League, Player
from .lineup import eligible

FLEX_SHARE = {"RB": 0.45, "WR": 0.45, "TE": 0.10}


def starters_per_position(league: League) -> dict[str, float]:
    """How many players at each position the whole league starts each week."""
    per_team: dict[str, float] = {}
    for slot, n in league.slots.items():
        positions = eligible(slot)
        if len(positions) == 1:
            pos = next(iter(positions))
            per_team[pos] = per_team.get(pos, 0) + n
        else:
            shares = {p: FLEX_SHARE.get(p, 0.0) for p in positions}
            if "QB" in positions:  # superflex slots go mostly to QBs
                shares = {p: (0.8 if p == "QB" else 0.2 / (len(positions) - 1)) for p in positions}
            total = sum(shares.values()) or 1
            for pos, share in shares.items():
                per_team[pos] = per_team.get(pos, 0) + n * share / total
    return {pos: n * len(league.teams) for pos, n in per_team.items()}


def replacement_levels(league: League) -> dict[str, float]:
    """Score of the first non-starter at each position across the league."""
    demand = starters_per_position(league)
    levels = {}
    for pos, n in demand.items():
        scores = sorted((p.score for p in league.all_players() if p.position == pos), reverse=True)
        idx = int(round(n))
        levels[pos] = scores[idx] if idx < len(scores) else (scores[-1] if scores else 0.0)
    return levels


def player_value(player: Player, levels: dict[str, float]) -> float:
    if player.is_out:
        # Injured players keep some value (they come back), but heavily discounted.
        return max(0.0, player.score - levels.get(player.position, 0.0)) * 0.35
    return max(0.0, player.score - levels.get(player.position, 0.0))
