"""Optimal start/sit lineup for a roster."""

from __future__ import annotations

from dataclasses import dataclass

from ..models import League, Player

ELIGIBLE: dict[str, set[str]] = {
    "QB": {"QB"},
    "RB": {"RB"},
    "WR": {"WR"},
    "TE": {"TE"},
    "K": {"K"},
    "DEF": {"DEF"},
    "RB/WR": {"RB", "WR"},
    "WRRB_FLEX": {"RB", "WR"},
    "WR/TE": {"WR", "TE"},
    "REC_FLEX": {"WR", "TE"},
    "FLEX": {"RB", "WR", "TE"},
    "SUPER_FLEX": {"QB", "RB", "WR", "TE"},
}


def eligible(slot: str) -> set[str]:
    return ELIGIBLE.get(slot, {slot})


@dataclass
class Lineup:
    slots: list[tuple[str, Player | None]]  # (slot name, player) in display order
    bench: list[Player]

    @property
    def starters(self) -> list[Player]:
        return [p for _, p in self.slots if p]

    @property
    def projected_total(self) -> float:
        return sum(p.score for p in self.starters)

    def to_dict(self) -> dict:
        return {
            "starters": [{"slot": s, **(p.to_dict() if p else {"name": "EMPTY"})} for s, p in self.slots],
            "bench": [p.to_dict() for p in self.bench],
            "projected_total": round(self.projected_total, 1),
        }


def optimal_lineup(roster: list[Player], slots: dict[str, int]) -> Lineup:
    """Fill the most restrictive slots first; greedy is optimal for nested flex sets."""
    order = sorted(slots, key=lambda s: (len(eligible(s)), s))
    pool = sorted((p for p in roster if not p.is_out), key=lambda p: p.score, reverse=True)
    used: set[str] = set()
    filled: dict[str, list[Player | None]] = {}
    for slot in order:
        filled[slot] = []
        for _ in range(slots[slot]):
            pick = next((p for p in pool if p.id not in used and p.position in eligible(slot)), None)
            if pick:
                used.add(pick.id)
            filled[slot].append(pick)
    display = [s for s in ("QB", "RB", "WR", "TE") if s in slots] + [s for s in slots if s not in ("QB", "RB", "WR", "TE", "K", "DEF")]
    display += [s for s in ("K", "DEF") if s in slots]
    ordered = [(s, p) for s in display for p in filled[s]]
    bench = sorted((p for p in roster if p.id not in used), key=lambda p: p.score, reverse=True)
    return Lineup(slots=ordered, bench=bench)


def lineup_advice(league: League, team_id: str | None = None) -> dict:
    """Compare the team's current starters with the optimal lineup."""
    team = league.team(team_id or league.my_team_id)
    best = optimal_lineup(team.roster, league.slots)
    best_ids = {p.id for p in best.starters}
    current_ids = set(team.starter_ids)
    start = [p for p in best.starters if p.id not in current_ids]
    sit = [p for p in team.roster if p.id in current_ids and p.id not in best_ids]
    warnings = [
        f"{p.label()} is in your lineup but listed {p.injury_status}"
        for p in team.roster
        if p.id in current_ids and (p.is_out or p.injury_status)
    ]
    current_total = sum(p.score for p in team.roster if p.id in current_ids)
    return {
        "team": team.name,
        "week": league.week,
        "optimal": best.to_dict(),
        "start": [p.to_dict() for p in start],
        "sit": [p.to_dict() for p in sit],
        "projected_gain": round(best.projected_total - current_total, 1),
        "injury_warnings": warnings,
    }
