"""Command-line interface: `python -m ffbot <command>`."""

from __future__ import annotations

import argparse
import sys

from .analysis import (
    evaluate_trade,
    find_players,
    find_trades,
    lineup_advice,
    standings,
    team_breakdown,
    waiver_suggestions,
)
from .config import LeagueConfig, load_config
from .models import League


def _fmt_player(d: dict) -> str:
    inj = f" [{d['injury_status']}]" if d.get("injury_status") else ""
    proj = d.get("projected_points")
    avg = d.get("avg_points")
    stats = f"proj {proj if proj is not None else '-'} / avg {avg if avg is not None else '-'}"
    return f"{d['name']} ({d['position']}-{d.get('nfl_team') or 'FA'}){inj}  {stats}"


def _leagues(args) -> list[LeagueConfig]:
    if args.demo:
        return [LeagueConfig(name="Demo League", platform="demo")]
    configs = load_config(args.config)
    if args.league:
        q = args.league.lower()
        configs = [c for c in configs if q in c.name.lower()]
        if not configs:
            sys.exit(f"No league matching {args.league!r}")
    return configs


def _each(args):
    for cfg in _leagues(args):
        try:
            league = cfg.load()
        except Exception as e:
            print(f"\n=== {cfg.name} ===\n  Could not load: {e}")
            continue
        print(f"\n=== {league.name} ({league.platform}, week {league.week}, {league.scoring}) ===")
        yield league


def cmd_leagues(args):
    for league in _each(args):
        me = league.my_team
        print(f"  Your team: {me.name}  {me.record}  PF {me.points_for:.1f}")


def print_lineup(league: League):
    adv = lineup_advice(league)
    for row in adv["optimal"]["starters"]:
        print(f"  {row['slot']:<11}{_fmt_player(row) if row['name'] != 'EMPTY' else 'EMPTY — pick someone up!'}")
    if adv["start"] or adv["sit"]:
        print(f"  Changes (+{adv['projected_gain']} pts):")
        for p in adv["start"]:
            print(f"    START {_fmt_player(p)}")
        for p in adv["sit"]:
            print(f"    SIT   {_fmt_player(p)}")
    else:
        print("  Your current lineup is already optimal.")
    for w in adv["injury_warnings"]:
        print(f"  ! {w}")


def cmd_lineup(args):
    for league in _each(args):
        print_lineup(league)


def print_trade(result: dict):
    mine = result["my_side"]
    print(f"  VERDICT: {result['verdict']}  (net {mine['net']:+})")
    print(f"  You give: {', '.join(p['name'] for p in result['give'])}")
    print(f"  You get:  {', '.join(p['name'] for p in result['get'])}")
    print(f"  Your weekly lineup: {mine['lineup_before']} -> {mine['lineup_after']} ({mine['lineup_delta']:+})")
    print(f"  Value over replacement: in {mine['value_in']} / out {mine['value_out']} ({mine['value_delta']:+})")
    if mine["would_drop"]:
        print(f"  You'd need to drop: {', '.join(mine['would_drop'])}")
    if "their_side" in result:
        t = result["their_side"]
        print(f"  {result['other_team']}: lineup {t['lineup_delta']:+}, value {t['value_delta']:+}, net {t['net']:+}")
    for f in result["flags"]:
        print(f"  ! {f}")
    if "counter_offer" in result:
        c = result["counter_offer"]
        print(f"  COUNTER: {c['suggestion']} (your net {c['my_net_after']:+}, theirs {c['their_net_after']:+})")


def cmd_trade(args):
    for league in _each(args):
        give, miss_g = find_players(league, args.give.split(","))
        get, miss_r = find_players(league, args.get.split(","))
        if miss_g or miss_r:
            print(f"  Couldn't find: {', '.join(miss_g + miss_r)}")
            continue
        print_trade(evaluate_trade(league, give, get))


def print_pending(league: League):
    if not league.pending_trades:
        if league.platform == "sleeper":
            print("  Sleeper doesn't publish pending offers — run `trade --give ... --get ...` to evaluate one.")
        else:
            print("  No pending trades.")
        return
    for t in league.pending_trades:
        who = "You proposed" if t.proposed_by_me else "Offer received"
        print(f"  --- {who} (id {t.id}) ---")
        print_trade(evaluate_trade(league, t.give, t.get, t.other_team_id or None))


def cmd_pending(args):
    for league in _each(args):
        print_pending(league)


def cmd_find_trades(args):
    for league in _each(args):
        ideas = find_trades(league, max_results=args.limit)
        if not ideas:
            print("  No clearly win-win trades found right now.")
        for i in ideas:
            print(f"  With {i['partner']}: give {' + '.join(i['give'])}  for  {' + '.join(i['get'])}")
            print(f"      you {i['my_net']:+} (lineup {i['my_lineup_delta']:+}), them {i['their_net']:+}")


def print_waivers(league: League, limit: int):
    ideas = waiver_suggestions(league, limit=limit)
    if not ideas:
        print("  No free agent clearly beats your bench.")
    for i in ideas:
        drop = f"  drop {i['drop']['name']}" if i["drop"] else ""
        hot = " [trending]" if i["trending"] else ""
        print(f"  ADD {_fmt_player(i['add'])}{hot}{drop}  (lineup {i['lineup_gain']:+}, value {i['value_gain']:+})")


def cmd_waivers(args):
    for league in _each(args):
        print_waivers(league, args.limit)


def cmd_standings(args):
    for league in _each(args):
        for r in standings(league):
            star = " <- you" if r["is_me"] else ""
            print(f"  {r['rank']:>2}. {r['team']:<28}{r['record']:>7}  PF {r['points_for']:>7}{star}")


def cmd_report(args):
    """Weekly report for every league: overview, lineup, waivers, pending trades."""
    for league in _each(args):
        b = team_breakdown(league)
        opp = league.opponent()
        print(f"  {b['team']}  {b['record']}  power rank {b['power_rank']}/{b['num_teams']}"
              + (f"  vs {opp.name} this week" if opp else ""))
        if b["needs"]:
            print(f"  Needs: {', '.join(b['needs'])}   Surplus: {', '.join(b['surplus']) or '-'}")
        print("\n  LINEUP")
        print_lineup(league)
        print("\n  WAIVERS")
        print_waivers(league, 3)
        print("\n  PENDING TRADES")
        print_pending(league)


def cmd_ask(args):
    from .advisor import Advisor

    advisor = Advisor(_leagues(args), web_search=not args.no_web, effort=args.effort)

    def show(name, inp):
        print(f"  [checking {name} {inp.get('league', '')}]", file=sys.stderr)

    if args.question:
        print(advisor.ask(" ".join(args.question), on_tool=show))
        return
    print("Fantasy advisor ready. Ask anything (blank line or Ctrl-D to quit).")
    while True:
        try:
            q = input("\nyou> ").strip()
        except EOFError:
            break
        if not q:
            break
        print("\n" + advisor.ask(q, on_tool=show))


def main(argv=None):
    parser = argparse.ArgumentParser(prog="ffbot", description="Fantasy football decision bot")
    parser.add_argument("--config", help="Path to config.yaml")
    parser.add_argument("--league", help="Only this league (name substring)")
    parser.add_argument("--demo", action="store_true", help="Use a built-in fake league (no setup needed)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("leagues", help="List your leagues and teams").set_defaults(fn=cmd_leagues)
    sub.add_parser("report", help="Weekly report for every league").set_defaults(fn=cmd_report)
    sub.add_parser("lineup", help="Best start/sit lineup").set_defaults(fn=cmd_lineup)
    sub.add_parser("standings", help="League standings").set_defaults(fn=cmd_standings)
    sub.add_parser("pending", help="Evaluate pending trade offers (ESPN)").set_defaults(fn=cmd_pending)

    p = sub.add_parser("trade", help="Evaluate a trade: accept or decline?")
    p.add_argument("--give", required=True, help='Comma-separated, e.g. "Player A,Player B"')
    p.add_argument("--get", required=True, help="Comma-separated players you receive")
    p.set_defaults(fn=cmd_trade)

    p = sub.add_parser("find-trades", help="Suggest trades to propose")
    p.add_argument("--limit", type=int, default=8)
    p.set_defaults(fn=cmd_find_trades)

    p = sub.add_parser("waivers", help="Best free-agent pickups")
    p.add_argument("--limit", type=int, default=8)
    p.set_defaults(fn=cmd_waivers)

    p = sub.add_parser("ask", help="Ask the AI advisor (chat if no question given)")
    p.add_argument("question", nargs="*")
    p.add_argument("--no-web", action="store_true", help="Disable web search for news")
    p.add_argument("--effort", default="high", choices=["low", "medium", "high", "xhigh", "max"])
    p.set_defaults(fn=cmd_ask)

    args = parser.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
