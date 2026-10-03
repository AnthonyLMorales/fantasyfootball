"""Trade evaluation, accept/decline verdicts, counter-offers and a trade finder."""

from __future__ import annotations

from itertools import combinations

from ..models import League, Player, Team
from .lineup import optimal_lineup
from .value import player_value, replacement_levels

ACCEPT, LEAN_ACCEPT, LEAN_DECLINE, DECLINE = "ACCEPT", "LEAN ACCEPT", "LEAN DECLINE", "DECLINE"


def _impact(league: League, team: Team, outgoing: list[Player], incoming: list[Player], levels) -> dict:
    """How a trade changes one side: weekly starting-lineup points and total roster value."""
    out_ids = {p.id for p in outgoing}
    before = optimal_lineup(team.roster, league.slots)
    new_roster = [p for p in team.roster if p.id not in out_ids] + list(incoming)

    # Receiving more players than you send means cutting your worst bench players.
    extra = len(incoming) - len(outgoing)
    dropped: list[Player] = []
    if extra > 0:
        after_tmp = optimal_lineup(new_roster, league.slots)
        dropped = sorted(after_tmp.bench, key=lambda p: player_value(p, levels))[:extra]
        drop_ids = {p.id for p in dropped}
        new_roster = [p for p in new_roster if p.id not in drop_ids]
    after = optimal_lineup(new_roster, league.slots)

    value_out = sum(player_value(p, levels) for p in outgoing) + sum(player_value(p, levels) for p in dropped)
    value_in = sum(player_value(p, levels) for p in incoming)
    lineup_delta = after.projected_total - before.projected_total
    value_delta = value_in - value_out
    return {
        "lineup_before": round(before.projected_total, 1),
        "lineup_after": round(after.projected_total, 1),
        "lineup_delta": round(lineup_delta, 1),
        "value_in": round(value_in, 1),
        "value_out": round(value_out, 1),
        "value_delta": round(value_delta, 1),
        "would_drop": [p.label() for p in dropped],
        # Weekly lineup points matter now; replacement value matters for the rest of the season.
        "net": round(0.5 * lineup_delta + 0.5 * value_delta, 2),
    }


def _verdict(net: float) -> str:
    if net >= 1.0:
        return ACCEPT
    if net >= 0:
        return LEAN_ACCEPT
    if net > -1.0:
        return LEAN_DECLINE
    return DECLINE


def evaluate_trade(league: League, give: list[Player], get: list[Player], other_team_id: str | None = None) -> dict:
    me = league.my_team
    if other_team_id is None and get:
        owner = league.owner_of(get[0].id)
        other_team_id = owner.id if owner else None
    levels = replacement_levels(league)
    mine = _impact(league, me, give, get, levels)

    flags = []
    for p in get:
        if p.injury_status:
            flags.append(f"You'd receive {p.label()} — injury risk.")
    for p in give:
        if p.is_out:
            flags.append(f"You'd send away {p.label()} who is currently out — selling low or dumping dead weight?")
    give_ids = {p.id for p in give}
    after = [p for p in me.roster if p.id not in give_ids] + list(get)
    for pos, need in league.slots.items():
        if pos in {p.position for p in give}:
            depth = sum(1 for p in after if p.position == pos and not p.is_out)
            if depth < need + 1:
                flags.append(f"After this trade you'd have only {depth} {pos} for {need} starting spot(s) — thin depth.")

    result = {
        "give": [p.to_dict() for p in give],
        "get": [p.to_dict() for p in get],
        "my_side": mine,
        "verdict": _verdict(mine["net"]),
        "flags": flags,
        "replacement_levels": {k: round(v, 1) for k, v in levels.items()},
    }
    if other_team_id:
        other = league.team(other_team_id)
        theirs = _impact(league, other, get, give, levels)
        result["other_team"] = other.name
        result["their_side"] = theirs
        if result["verdict"] in (LEAN_DECLINE, DECLINE):
            counter = suggest_counter(league, give, get, other, levels)
            if counter:
                result["counter_offer"] = counter
    return result


def suggest_counter(league: League, give: list[Player], get: list[Player], other: Team, levels=None) -> dict | None:
    """Smallest add from their roster (or removal from my side) that makes the deal worth it for me."""
    levels = levels or replacement_levels(league)
    me = league.my_team
    options = []
    get_ids = {p.id for p in get}
    for extra in other.roster:
        if extra.id in get_ids:
            continue
        mine = _impact(league, me, give, get + [extra], levels)
        if mine["net"] >= 0.5:
            theirs = _impact(league, other, get + [extra], give, levels)
            options.append((theirs["net"], f"Ask them to add {extra.label()}", mine["net"]))
    if len(give) > 1:
        for p in give:
            reduced = [g for g in give if g.id != p.id]
            mine = _impact(league, me, reduced, get, levels)
            if mine["net"] >= 0.5:
                theirs = _impact(league, other, get, reduced, levels)
                options.append((theirs["net"], f"Keep {p.label()} out of the deal", mine["net"]))
    if not options:
        return None
    # Prefer the counter that hurts them the least (most likely to be accepted).
    their_net, text, my_net = max(options, key=lambda o: o[0])
    return {"suggestion": text, "my_net_after": round(my_net, 2), "their_net_after": round(their_net, 2)}


def find_trades(league: League, max_results: int = 10, pool_size: int = 10) -> list[dict]:
    """Search 1-for-1 and 2-for-1 deals that help me and that the other manager could plausibly accept."""
    levels = replacement_levels(league)
    me = league.my_team

    def top(team: Team) -> list[Player]:
        return sorted((p for p in team.roster if p.position not in ("K", "DEF") and not p.is_out),
                      key=lambda p: player_value(p, levels), reverse=True)[:pool_size]

    my_pool = top(me)
    my_packages = [[p] for p in my_pool] + [list(c) for c in combinations(my_pool, 2)]
    ideas = []
    for other in league.teams:
        if other.id == me.id:
            continue
        for target in top(other):
            for package in my_packages:
                mine = _impact(league, me, package, [target], levels)
                if mine["net"] < 0.5:
                    continue
                theirs = _impact(league, other, [target], package, levels)
                # They must not lose much — fair deals get accepted, fleeces don't.
                if theirs["net"] < -0.25 or theirs["lineup_delta"] < -1.0:
                    continue
                ideas.append({
                    "partner": other.name,
                    "give": [p.label() for p in package],
                    "get": [target.label()],
                    "my_net": mine["net"],
                    "their_net": theirs["net"],
                    "my_lineup_delta": mine["lineup_delta"],
                    "their_lineup_delta": theirs["lineup_delta"],
                })
    # Win-win first: rank by the smaller of the two gains, then my gain.
    ideas.sort(key=lambda i: (min(i["my_net"], i["their_net"]), i["my_net"]), reverse=True)
    # Keep the list varied: each target once, and each of my players in at most two ideas.
    picked, targets, used = [], set(), {}
    for idea in ideas:
        if idea["get"][0] in targets or any(used.get(g, 0) >= 2 for g in idea["give"]):
            continue
        picked.append(idea)
        targets.add(idea["get"][0])
        for g in idea["give"]:
            used[g] = used.get(g, 0) + 1
        if len(picked) == max_results:
            break
    return picked
