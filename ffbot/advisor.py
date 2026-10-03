"""AI advisor: Claude with tools over your leagues' live data.

Claude never invents numbers here — it calls the tools below, which run the
same analysis as the CLI commands, and can search the web for injury news.
"""

from __future__ import annotations

import json
import os

import anthropic

from .analysis import (
    evaluate_trade,
    find_players,
    find_trades,
    lineup_advice,
    standings,
    team_breakdown,
    waiver_suggestions,
)
from .config import LeagueConfig
from .models import League

MODEL = os.environ.get("FFBOT_MODEL", "claude-opus-5-5")

SYSTEM_PROMPT = """You are a sharp, honest fantasy football advisor managing several teams for one person.

Your job: help them win. That means weekly start/sit decisions, waiver pickups, judging trade
offers (accept, decline, or counter), and proposing trades that other managers would realistically accept.

How to work:
- Ground every recommendation in tool data. Call tools before giving numbers; don't guess rosters,
  projections or records. When a question spans several leagues, check each one.
- Use web search for anything time-sensitive the tools can't know: injury updates, practice reports,
  depth-chart changes, suspensions, weather, and trade news. Mention the date of news you rely on.
- Trade verdicts: give a clear ACCEPT / DECLINE / COUNTER, the key reasons (weekly lineup impact,
  rest-of-season value, positional depth, injury risk, playoff schedule if relevant), and a concrete
  counter-offer when declining. The tool's "net" combines weekly lineup points gained and value over
  replacement; treat it as evidence, then apply judgment about news and context it can't see.
- Be concise and decisive. Lead with the decision, then the why. Flag uncertainty honestly.
- You cannot click accept/decline in the apps yourself; tell the user exactly what to do there."""

TOOLS = [
    {
        "name": "list_leagues",
        "description": "List the user's configured fantasy leagues (name and platform). Call first if unsure which league is meant.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "team_overview",
        "description": "Record, power rank, positional strengths/needs vs league average, this week's opponent and lineup issues for the user's team in one league.",
        "input_schema": {
            "type": "object",
            "properties": {"league": {"type": "string", "description": "League name from list_leagues"}},
            "required": ["league"],
        },
    },
    {
        "name": "get_roster",
        "description": "Full roster with projections, season averages and injury status for any team in a league (defaults to the user's team).",
        "input_schema": {
            "type": "object",
            "properties": {
                "league": {"type": "string"},
                "team": {"type": "string", "description": "Team or owner name; omit for the user's team"},
            },
            "required": ["league"],
        },
    },
    {
        "name": "standings",
        "description": "League standings: record, points for/against for every team.",
        "input_schema": {"type": "object", "properties": {"league": {"type": "string"}}, "required": ["league"]},
    },
    {
        "name": "optimize_lineup",
        "description": "Best start/sit lineup for this week vs the current lineup, with injury warnings.",
        "input_schema": {"type": "object", "properties": {"league": {"type": "string"}}, "required": ["league"]},
    },
    {
        "name": "evaluate_trade",
        "description": "Evaluate a trade for the user's team: weekly lineup impact, value over replacement for both sides, depth/injury flags, a verdict, and a counter-offer if it's bad.",
        "input_schema": {
            "type": "object",
            "properties": {
                "league": {"type": "string"},
                "give": {"type": "array", "items": {"type": "string"}, "description": "Player names the user sends"},
                "get": {"type": "array", "items": {"type": "string"}, "description": "Player names the user receives"},
            },
            "required": ["league", "give", "get"],
        },
    },
    {
        "name": "pending_trades",
        "description": "Trade offers currently pending for the user's team (where the platform exposes them), each already evaluated.",
        "input_schema": {"type": "object", "properties": {"league": {"type": "string"}}, "required": ["league"]},
    },
    {
        "name": "find_trades",
        "description": "Search for 1-for-1 and 2-for-1 trades that improve the user's team and that the other manager could plausibly accept.",
        "input_schema": {"type": "object", "properties": {"league": {"type": "string"}}, "required": ["league"]},
    },
    {
        "name": "waiver_suggestions",
        "description": "Best free-agent pickups for the user's team with a suggested drop, including players trending on adds.",
        "input_schema": {"type": "object", "properties": {"league": {"type": "string"}}, "required": ["league"]},
    },
    {
        "name": "player_lookup",
        "description": "Look up players by name in a league: stats, projection, injury status and who rosters them.",
        "input_schema": {
            "type": "object",
            "properties": {"league": {"type": "string"}, "names": {"type": "array", "items": {"type": "string"}}},
            "required": ["league", "names"],
        },
    },
]

WEB_SEARCH_TOOL = {"type": "web_search_20260209", "name": "web_search", "max_uses": 8}


class ToolError(Exception):
    pass


class LeagueStore:
    """Loads each league once per session."""

    def __init__(self, configs: list[LeagueConfig]):
        self.configs = {c.name: c for c in configs}
        self._cache: dict[str, League] = {}

    def resolve(self, name: str) -> League:
        key = next((n for n in self.configs if n.lower() == (name or "").lower()), None)
        if key is None:
            key = next((n for n in self.configs if (name or "").lower() in n.lower()), None)
        if key is None:
            if len(self.configs) == 1:
                key = next(iter(self.configs))
            else:
                raise ToolError(f"Unknown league {name!r}. Leagues: {', '.join(self.configs)}")
        if key not in self._cache:
            self._cache[key] = self.configs[key].load()
        return self._cache[key]


def _team_by_name(league: League, name: str | None):
    if not name:
        return league.my_team
    q = name.lower()
    for t in league.teams:
        if q in t.name.lower() or (t.owner and q in t.owner.lower()):
            return t
    raise ToolError(f"No team matching {name!r}. Teams: {', '.join(t.name for t in league.teams)}")


def _players(league: League, names: list[str]):
    found, missing = find_players(league, names)
    if missing:
        raise ToolError(f"Couldn't find player(s): {', '.join(missing)}. Check spelling or use player_lookup.")
    return found


def run_tool(store: LeagueStore, name: str, args: dict):
    if name == "list_leagues":
        return [{"name": c.name, "platform": c.platform} for c in store.configs.values()]
    league = store.resolve(args.get("league", ""))
    if name == "team_overview":
        opp = league.opponent()
        lineup = lineup_advice(league)
        return {
            "league": league.name, "platform": league.platform, "week": league.week, "scoring": league.scoring,
            **team_breakdown(league),
            "opponent_this_week": opp.name if opp else None,
            "lineup_changes_recommended": {"start": lineup["start"], "sit": lineup["sit"], "gain": lineup["projected_gain"]},
            "injury_warnings": lineup["injury_warnings"],
            "pending_trade_count": len(league.pending_trades),
        }
    if name == "get_roster":
        team = _team_by_name(league, args.get("team"))
        starters = set(team.starter_ids)
        return {
            "team": team.name, "owner": team.owner, "record": team.record,
            "players": [{**p.to_dict(), "starting": p.id in starters} for p in sorted(team.roster, key=lambda p: p.position)],
        }
    if name == "standings":
        return standings(league)
    if name == "optimize_lineup":
        return lineup_advice(league)
    if name == "evaluate_trade":
        give, get = _players(league, args.get("give", [])), _players(league, args.get("get", []))
        mine = {p.id for p in league.my_team.roster}
        if any(p.id not in mine for p in give):
            raise ToolError("Every 'give' player must be on the user's roster.")
        return evaluate_trade(league, give, get)
    if name == "pending_trades":
        if not league.pending_trades:
            note = ("Sleeper's public API does not expose pending trade offers; ask the user which players are involved."
                    if league.platform == "sleeper" else "No pending trades found.")
            return {"pending_trades": [], "note": note}
        return [
            {"trade_id": t.id, "proposed_by_me": t.proposed_by_me,
             **evaluate_trade(league, t.give, t.get, t.other_team_id or None)}
            for t in league.pending_trades
        ]
    if name == "find_trades":
        return find_trades(league)
    if name == "waiver_suggestions":
        return waiver_suggestions(league)
    if name == "player_lookup":
        out = []
        for p in _players(league, args.get("names", [])):
            owner = league.owner_of(p.id)
            out.append({**p.to_dict(), "rostered_by": owner.name if owner else "Free agent"})
        return out
    raise ToolError(f"Unknown tool {name}")


class Advisor:
    def __init__(self, configs: list[LeagueConfig], web_search: bool = True, effort: str = "high"):
        self.client = anthropic.Anthropic()
        self.store = LeagueStore(configs)
        self.tools = TOOLS + ([WEB_SEARCH_TOOL] if web_search else [])
        self.effort = effort
        self.messages: list[dict] = []

    def ask(self, question: str, on_tool=None) -> str:
        """Send one user turn and run the tool loop until Claude answers."""
        self.messages.append({"role": "user", "content": question})
        while True:
            response = self.client.beta.messages.create(
                model=MODEL,
                max_tokens=16000,
                system=SYSTEM_PROMPT,
                tools=self.tools,
                messages=self.messages,
                output_config={"effort": self.effort},
                cache_control={"type": "ephemeral"},
                # If a safety classifier declines, retry server-side on Anthropic's recommended fallback model.
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
            # Keep the full content (thinking, tool calls, search results) so history stays append-only.
            self.messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason == "refusal":
                return "Claude declined to answer that request."
            if response.stop_reason == "pause_turn":
                continue  # long web search; resend so Claude can continue
            if response.stop_reason != "tool_use":
                return "\n".join(b.text for b in response.content if b.type == "text").strip()

            results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                if on_tool:
                    on_tool(block.name, block.input)
                try:
                    content, is_error = json.dumps(run_tool(self.store, block.name, block.input or {}), default=str), False
                except ToolError as e:
                    content, is_error = str(e), True
                except Exception as e:  # provider/network failure: let Claude explain it
                    content, is_error = f"{type(e).__name__}: {e}", True
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": content, "is_error": is_error})
            self.messages.append({"role": "user", "content": results})
