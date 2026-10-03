import json
from types import SimpleNamespace as NS

import pytest

from ffbot.advisor import Advisor, LeagueStore, ToolError, run_tool
from ffbot.config import LeagueConfig


@pytest.fixture
def store():
    return LeagueStore([LeagueConfig(name="Demo League", platform="demo")])


def test_tools_return_json_serialisable_data(store):
    for name, args in [
        ("list_leagues", {}),
        ("team_overview", {"league": "demo"}),
        ("get_roster", {"league": "demo", "team": "Gridiron"}),
        ("standings", {"league": "demo"}),
        ("optimize_lineup", {"league": "demo"}),
        ("pending_trades", {"league": "demo"}),
        ("find_trades", {"league": "demo"}),
        ("waiver_suggestions", {"league": "demo"}),
        ("player_lookup", {"league": "demo", "names": ["QB Player 1"]}),
        ("evaluate_trade", {"league": "demo", "give": ["RB Player 1"], "get": ["WR Player 2"]}),
    ]:
        json.dumps(run_tool(store, name, args), default=str)


def test_evaluate_trade_rejects_players_not_on_my_roster(store):
    league = store.resolve("demo")
    not_mine = league.teams[1].roster[0].name
    with pytest.raises(ToolError):
        run_tool(store, "evaluate_trade", {"league": "demo", "give": [not_mine], "get": []})


class FakeMessages:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


def test_advisor_runs_tool_loop(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    advisor = Advisor([LeagueConfig(name="Demo League", platform="demo")])
    fake = FakeMessages([
        NS(stop_reason="tool_use", content=[
            NS(type="tool_use", id="t1", name="optimize_lineup", input={"league": "Demo League"}),
            NS(type="tool_use", id="t2", name="player_lookup", input={"league": "Demo League", "names": ["zzz qqq"]}),
        ]),
        NS(stop_reason="end_turn", content=[NS(type="text", text="Start RB Player 14.")]),
    ])
    advisor.client = NS(beta=NS(messages=fake))

    assert advisor.ask("Who should I start?") == "Start RB Player 14."
    assert len(fake.calls) == 2
    first = fake.calls[0]
    assert first["model"] == "claude-opus-5-5"
    assert first["fallbacks"] == "default"
    # Both tool results go back in a single user message; the failed lookup is flagged as an error.
    results = advisor.messages[2]["content"]
    assert [r["tool_use_id"] for r in results] == ["t1", "t2"]
    assert results[0]["is_error"] is False and "optimal" in results[0]["content"]
    assert results[1]["is_error"] is True
