from ffbot.providers.espn import build_league as build_espn
from ffbot.providers.sleeper import build_league as build_sleeper


def sleeper_raw():
    return {
        "state": {"season": "2026", "week": 5},
        "week": 5,
        "my_user_id": "u1",
        "league": {
            "league_id": "L1",
            "name": "Sleeper Squad",
            "season": "2026",
            "scoring_settings": {"rec": 0.5},
            "roster_positions": ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "SUPER_FLEX", "K", "DEF", "BN", "BN", "IR"],
        },
        "users": [
            {"user_id": "u1", "display_name": "me", "metadata": {"team_name": "My Sleeper Team"}},
            {"user_id": "u2", "display_name": "rival"},
        ],
        "rosters": [
            {"roster_id": 1, "owner_id": "u1", "players": ["100", "200", "DET"], "starters": ["100", "0", "DET"],
             "settings": {"wins": 3, "losses": 1, "fpts": 450, "fpts_decimal": 50}},
            {"roster_id": 2, "owner_id": "u2", "players": ["300"], "starters": ["300"], "settings": {"wins": 1, "losses": 3}},
        ],
        "matchups": [{"roster_id": 1, "matchup_id": 1}, {"roster_id": 2, "matchup_id": 1}],
        "players": {
            "100": {"full_name": "Alpha QB", "position": "QB", "team": "BUF"},
            "200": {"full_name": "Bravo RB", "position": "RB", "team": "KC", "injury_status": "Questionable"},
            "300": {"full_name": "Charlie WR", "position": "WR", "team": "PHI"},
            "400": {"full_name": "Delta WR", "position": "WR", "team": "DAL"},
            "DET": {"first_name": "Detroit", "last_name": "Lions", "position": "DEF", "team": "DET"},
        },
        "projections": [
            {"player_id": "100", "stats": {"pts_half_ppr": 22.0}},
            {"player_id": "200", "stats": {"pts_half_ppr": 14.0}},
            {"player_id": "400", "stats": {"pts_half_ppr": 11.0}},
        ],
        "season_stats": [{"player_id": "100", "stats": {"pts_half_ppr": 80.0, "gp": 4}}],
        "trending": [{"player_id": "400", "count": 9000}],
    }


def test_sleeper_build_league():
    league = build_sleeper(sleeper_raw())
    assert league.scoring == "half_ppr"
    assert league.slots == {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1, "SUPER_FLEX": 1, "K": 1, "DEF": 1}
    me = league.my_team
    assert me.name == "My Sleeper Team"
    assert me.record == "3-1"
    assert me.points_for == 450.5
    assert me.starter_ids == ["100", "DET"]
    qb = me.player("100")
    assert qb.projected_points == 22.0 and qb.avg_points == 20.0
    assert me.player("200").injury_status == "Questionable"
    assert me.player("DET").name == "Detroit Lions" and me.player("DET").position == "DEF"
    assert league.opponent().name == "rival"
    assert [p.name for p in league.free_agents] == ["Delta WR"]
    assert [p.name for p in league.trending_adds] == ["Delta WR"]


def espn_player(pid, name, pos_id, team_id, proj, total=None, avg=None, injury="ACTIVE"):
    stats = [{"seasonId": 2026, "scoringPeriodId": 5, "statSourceId": 1, "statSplitTypeId": 1, "appliedTotal": proj}]
    if total is not None:
        stats.append({"seasonId": 2026, "scoringPeriodId": 0, "statSourceId": 0, "statSplitTypeId": 0,
                      "appliedTotal": total, "appliedAverage": avg})
    return {"id": pid, "fullName": name, "defaultPositionId": pos_id, "proTeamId": team_id,
            "injuryStatus": injury, "stats": stats}


def espn_raw():
    return {
        "league": {
            "id": 999,
            "seasonId": 2026,
            "scoringPeriodId": 5,
            "status": {"currentMatchupPeriod": 5},
            "settings": {
                "name": "Office League",
                "rosterSettings": {"lineupSlotCounts": {"0": 1, "2": 2, "4": 2, "6": 1, "23": 1, "16": 1, "17": 1, "20": 7, "21": 1}},
                "scoringSettings": {"scoringItems": [{"statId": 53, "points": 1.0}]},
            },
            "members": [{"id": "{ABC}", "displayName": "me"}, {"id": "{XYZ}", "displayName": "them"}],
            "teams": [
                {"id": 1, "name": "Espn Me", "primaryOwner": "{ABC}", "owners": ["{ABC}"],
                 "record": {"overall": {"wins": 2, "losses": 2, "pointsFor": 400.2}},
                 "roster": {"entries": [
                     {"playerId": 11, "lineupSlotId": 0, "playerPoolEntry": {"player": espn_player(11, "Echo QB", 1, 12, 20.5, 90, 22.5)}},
                     {"playerId": 12, "lineupSlotId": 20, "playerPoolEntry": {"player": espn_player(12, "Fox RB", 2, 2, 9.0, injury="OUT")}},
                 ]}},
                {"id": 2, "location": "Big", "nickname": "Dogs", "primaryOwner": "{XYZ}", "owners": ["{XYZ}"],
                 "record": {"overall": {"wins": 1, "losses": 3}},
                 "roster": {"entries": [
                     {"playerId": 21, "lineupSlotId": 4, "playerPoolEntry": {"player": espn_player(21, "Golf WR", 3, 25, 15.0)}},
                 ]}},
            ],
            "schedule": [{"matchupPeriodId": 5, "home": {"teamId": 1}, "away": {"teamId": 2}}],
        },
        "free_agents": [{"id": 31, "player": espn_player(31, "Hotel TE", 4, 8, 7.0)}],
        "pending": {"pendingTransactions": [
            {"id": "t1", "type": "TRADE_PROPOSAL", "status": "PENDING", "teamId": 2,
             "items": [{"playerId": 21, "fromTeamId": 2, "toTeamId": 1}, {"playerId": 11, "fromTeamId": 1, "toTeamId": 2}]},
        ]},
    }


def test_espn_build_league_detects_team_from_swid():
    league = build_espn(espn_raw(), swid="{abc}")
    assert league.my_team_id == "1"
    assert league.scoring == "ppr"
    assert league.slots == {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1, "DEF": 1, "K": 1}
    me = league.my_team
    assert me.starter_ids == ["11"]
    qb = me.player("11")
    assert (qb.position, qb.nfl_team, qb.projected_points, qb.games_played) == ("QB", "KC", 20.5, 4)
    rb = me.player("12")
    assert rb.injury_status == "Out" and rb.is_out
    assert league.team("2").name == "Big Dogs"
    assert league.opponent().name == "Big Dogs"
    assert league.free_agents[0].position == "TE"
    (offer,) = league.pending_trades
    assert [p.name for p in offer.give] == ["Echo QB"]
    assert [p.name for p in offer.get] == ["Golf WR"]
    assert offer.other_team_id == "2" and not offer.proposed_by_me


def test_espn_explicit_team_id():
    league = build_espn(espn_raw(), team_id="2")
    assert league.my_team.name == "Big Dogs"
