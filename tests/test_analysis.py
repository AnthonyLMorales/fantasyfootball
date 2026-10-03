from ffbot.analysis import (
    evaluate_trade,
    find_players,
    find_trades,
    lineup_advice,
    optimal_lineup,
    team_breakdown,
    waiver_suggestions,
)
from ffbot.demo import demo_league
from ffbot.models import Player


def P(pid, pos, proj, injury=""):
    return Player(id=pid, name=pid, position=pos, projected_points=proj, injury_status=injury)


def test_optimal_lineup_fills_flex_and_skips_injured():
    roster = [P("qb", "QB", 20), P("rb1", "RB", 15), P("rb2", "RB", 12), P("rb3", "RB", 11),
              P("wr1", "WR", 14), P("wr2", "WR", 9), P("wr3", "WR", 30, injury="Out"), P("te", "TE", 8)]
    lineup = optimal_lineup(roster, {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1})
    by_slot = [(s, p.id if p else None) for s, p in lineup.slots]
    assert by_slot == [("QB", "qb"), ("RB", "rb1"), ("RB", "rb2"), ("WR", "wr1"), ("WR", "wr2"), ("TE", "te"), ("FLEX", "rb3")]
    assert [p.id for p in lineup.bench] == ["wr3"]


def test_superflex_prefers_second_qb():
    roster = [P("qb1", "QB", 22), P("qb2", "QB", 18), P("wr", "WR", 15)]
    lineup = optimal_lineup(roster, {"QB": 1, "SUPER_FLEX": 1})
    assert {p.id for p in lineup.starters} == {"qb1", "qb2"}


def test_lineup_advice_finds_benched_starter():
    league = demo_league()
    adv = lineup_advice(league)
    assert adv["projected_gain"] > 0
    assert adv["start"] and adv["sit"]


def test_lopsided_trade_is_declined_with_flags():
    league = demo_league()
    me = league.my_team
    best = max(me.roster, key=lambda p: p.score)
    worst_other = min(league.teams[1].roster, key=lambda p: p.score)
    result = evaluate_trade(league, [best], [worst_other])
    assert result["verdict"] == "DECLINE"
    assert result["my_side"]["net"] < 0
    assert result["their_side"]["net"] > 0


def test_reverse_of_lopsided_trade_is_accepted():
    league = demo_league()
    me = league.my_team
    their_best = max((p for p in league.teams[1].roster if not p.is_out), key=lambda p: p.score)
    my_bench = optimal_lineup(me.roster, league.slots).bench
    result = evaluate_trade(league, [my_bench[-1]], [their_best])
    assert result["verdict"] == "ACCEPT"


def test_find_trades_are_win_win():
    league = demo_league()
    ideas = find_trades(league, max_results=5)
    assert ideas
    for idea in ideas:
        assert idea["my_net"] >= 0.5
        assert idea["their_net"] >= -0.25


def test_waivers_and_breakdown_run():
    league = demo_league()
    for idea in waiver_suggestions(league):
        assert idea["add"]["name"]
    b = team_breakdown(league)
    assert 1 <= b["power_rank"] <= b["num_teams"]
    assert "QB" in b["by_position"]


def test_find_players_fuzzy():
    league = demo_league()
    found, missing = find_players(league, ["rb player 1", "WR Playr 12", "Nobody Atall"])
    assert [p.name for p in found] == ["RB Player 1", "WR Player 12"]
    assert missing == ["Nobody Atall"]
