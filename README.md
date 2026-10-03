# ffbot — Fantasy Football Decision Bot

A personal assistant for managing several fantasy football teams across **Sleeper** and **ESPN**.
It pulls your live league data, does the math (start/sit, trade value, waiver pickups), and adds an
**AI advisor (Claude)** that you can chat with. The advisor checks real data and searches the web for injury news.

| What you want | Command |
|---|---|
| One weekly report for all of your teams | `ffbot report` |
| Who to start and who to sit | `ffbot lineup` |
| Should I accept or decline this trade? | `ffbot trade --league "ESPN" --give "Player A" --get "Player B,Player C"` |
| Trade offers waiting for me (ESPN) | `ffbot pending` |
| Trades I should propose | `ffbot find-trades` |
| Best waiver pickups and who to drop | `ffbot waivers` |
| Standings | `ffbot standings` |
| Ask the AI anything | `ffbot ask "Should I trade my RB1 for two WR2s in my Sleeper league?"` |
| Chat with the AI | `ffbot ask` |

Add `--league "<part of the name>"` to any command to focus on one league.

---

## 1. Install (one time)

You need Python 3.10 or newer.

```bash
git clone https://github.com/AnthonyLMorales/fantasyfootball.git
cd fantasyfootball
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

Try it right away with a fake league (no setup needed):

```bash
ffbot --demo report
ffbot --demo find-trades
```

## 2. Connect your leagues

```bash
cp config.example.yaml config.yaml
```

Then edit `config.yaml`:

**Sleeper**
- `league_id`: open the league at sleeper.com. It's the long number in the URL (`/leagues/<league_id>/...`).
- `username`: your Sleeper username. It's how the bot finds your team.
- You don't need a password. Sleeper's API is public and read-only.

**ESPN**
- `league_id`: the `leagueId=` number in your ESPN league URL.
- `team_id`: the `teamId=` number when you view your own team.
- **Private leagues** (most are) also need two browser cookies:
  1. Log in at fantasy.espn.com on a computer.
  2. Open developer tools (F12), go to **Application → Cookies → https://fantasy.espn.com**.
  3. Copy the values of `espn_s2` and `SWID` (the SWID includes the `{ }` braces).
  4. Put them in environment variables instead of the file:
     ```bash
     export ESPN_S2="AEB...long value..."
     export ESPN_SWID="{XXXXXXXX-XXXX-...}"
     ```
  These cookies act like a login to your ESPN account, so keep them private. `config.yaml` is git-ignored.

Check that everything connects:

```bash
ffbot leagues
```

## 3. Turn on the AI advisor

The advisor uses Claude through the Anthropic API.

1. Create an API key at https://console.anthropic.com.
2. `export ANTHROPIC_API_KEY="sk-ant-..."`
3. `ffbot ask`

Example questions:
- "Give me my start/sit for all three teams and tell me which close calls I should watch on Sunday morning."
- "I got offered Player X for Player Y in my ESPN league. Accept or decline? If decline, what's a fair counter?"
- "Which of my teams is most likely to miss the playoffs, and what trade would fix it?"
- "Who are the best waiver pickups this week in each league, and how much FAAB should I bid?"

How it works: Claude has tools wired to the same analysis the CLI uses (rosters, standings, lineup
optimizer, trade evaluator, trade finder, waivers). It also has web search for injury and depth-chart
news. It has to call those tools before it gives you numbers, so it can't make up rosters or projections.

Options: `--no-web` turns off web search, and `--effort low|medium|high|xhigh|max` trades speed and cost for depth.
The model defaults to `claude-opus-5-5`. You can override it with the `FFBOT_MODEL` environment variable.

---

## How the decisions are made

- **Player score**: 60% this week's projection plus 40% season average. Injured players marked Out or IR don't start.
- **Value over replacement**: a player's score minus the score of the best player your league would
  leave on waivers at that position. A 15-point TE is worth more than a 15-point WR.
- **Trade verdict** (ACCEPT / LEAN ACCEPT / LEAN DECLINE / DECLINE) combines two things:
  1. how many points your **best possible starting lineup** gains or loses this week, and
  2. how much **value over replacement** you gain or lose. If you'd get more players than you send,
     the bot also counts the bench player you'd have to drop.
  It also flags injured players coming in and positions left without depth. When the deal is bad, it
  proposes a **counter-offer**: the smallest add or removal that makes the deal good for you.
- **Trade finder** tries 1-for-1 and 2-for-1 deals with every team. It keeps only deals that help you
  **and** don't hurt the other manager, because those are the ones that actually get accepted.
- **Waivers** rank free agents (plus Sleeper's trending adds) by how much they improve your lineup and roster value.

## What it can and can't do

- **Accepting or declining trades is up to you.** The bot tells you what to do, and you tap Accept or Decline
  in the app. Sleeper's API is read-only, and ESPN's write endpoints are private. Letting a bot act
  on your account would risk your account and your league's trust.
- **Pending offers**: ESPN pending trades are read on a best-effort basis (ESPN's API is unofficial).
  Sleeper doesn't publish pending offers. Run `ffbot trade --give ... --get ...` with the players in the offer.
- **Projections** come from each platform's own projections (Sleeper's app endpoints and ESPN's player stats).
  These endpoints are unofficial and could change. If a projection is missing, the bot falls back to season averages.
- Supports standard, superflex, and RB/WR or WR/TE flex lineups. IDP is not modeled yet.

## Project layout

```
ffbot/
  models.py            Player / Team / League / TradeOffer shared by everything
  providers/sleeper.py Sleeper API -> League
  providers/espn.py    ESPN API   -> League
  analysis/lineup.py   optimal lineup (start/sit)
  analysis/value.py    replacement levels, value over replacement
  analysis/trades.py   trade evaluation, counters, trade finder
  analysis/waivers.py  waiver pickups, team strengths, standings, player search
  advisor.py           Claude tool-use agent over the analysis
  cli.py               `ffbot` command line
  demo.py              fake league for testing
tests/                 pytest suite (runs offline)
```

Run the tests with `pytest`.

## Ideas for next steps

- Run `ffbot report` automatically every Tuesday (waivers) and Sunday morning (inactives), for example with a cron job or a scheduled GitHub Action, and send it to your phone.
- Add Yahoo or NFL.com as another provider. Write a `providers/<name>.py` that returns a `League`.
- Track the bot's advice against actual results to tune the trade thresholds.
