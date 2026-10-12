# Basketball Data Sources

Use this reference when selecting basketball data sources. Treat access status as conditional: pages and APIs can change, so verify on the day of use and save raw snapshots under `D:\codex\outputs\basketball_odds_trader\raw\`.

## Best Practical Source Stack

1. **User screenshots / exported odds**: best for opening-current-closing lines when the user has a trusted board.
2. **SofaScore basketball scheduled events**: broad default scoreboard source for NBA, WNBA, CBA, NBA G League, national-team/FIBA, and international basketball discovery. Use it first to avoid silently missing leagues outside the NBA ecosystem.
3. **TheSportsDB basketball eventsday**: public fallback discovery source when SofaScore direct HTTP is blocked. It can return date-level Basketball events and was reachable in local testing, but it is lower-quality than official feeds.
4. **NBA Stats / stats.nba.com**: official NBA-family cross-check for NBA, WNBA, Summer League, and NBA G League via LeagueID. Use it for scoreboard, box score, pace, team/player stats, and play-by-play where available.
5. **ESPN public scoreboard endpoints**: useful no-key cross-check for schedule, scores, status, teams, and links for NBA/WNBA/NCAAB and G League pages when readable. Endpoint pattern: `https://site.api.espn.com/apis/site/v2/sports/basketball/{league}/scoreboard?dates=YYYYMMDD`.
6. **FIBA official games/results**: official national-team event calendar and match results. Use it to validate FIBA World Cup, Olympic, continental cup, qualifier, youth, and women's national-team slates.
7. **The Odds API**: structured odds for basketball sports such as NBA, WNBA, NCAAB, and other leagues depending on plan. Use for `h2h`, `spreads`, and `totals`; historical/closing snapshots depend on API plan, so poll and save snapshots if closing lines are needed.
8. **iSportsAPI or similar paid live-data providers**: production-grade option for global basketball schedule/results and match-modify records when an API key/plan is available.
9. **Line-movement web pages**: Covers, ScoresAndOdds, VegasInsider, OddsPortal, BetExplorer, Titan007/7M basketball, Flashscore, and SofaScore can expose opening/current odds, line movement, scores, and sometimes team/news data. Use as readable fallbacks and label the exact source.
10. **Injury and lineup sources**: official NBA injury reports, NBA.com game previews, RotoWire, Underdog NBA, SportsDataIO, Sportradar, team beat reports, and user screenshots. Late scratches are decisive in basketball, so timestamp every injury status.
11. **Prediction/exchange markets**: Polymarket, Kalshi, Betfair, or other public exchange-like boards only when the exact market is visible with settlement, bid/ask, spread, and liquidity. Use them as sentiment/price checks, not automatic truth.

## Basketball Market Reality Notes

Use the `worldcup-odds-trader` execution logic as the template, but adjust for basketball:

- **Scoreboard completeness is not market completeness**: CBA, FIBA, summer league, youth, and lower-tier leagues can have reliable scores but missing or thin betting markets. Write the game, but downgrade the betting tier.
- **Current-only odds are fragile**: a visible current spread without opening, price path, and close can support a watchlist or first-write paper observation, not a full real-money recommendation.
- **Low-liquidity movement is noisy**: for CBA summer league, preseason, G League, youth national teams, and obscure international boards, a one-book move can be stale inventory, trader adjustment, or tiny-limit action. Require larger edge buffers and smaller Kelly caps.
- **Late basketball news matters more than headline strength**: one primary ballhandler, rim protector, import player, or minutes restriction can move both spread and total. Timestamp injury/lineup status; stale injury data downgrades real-bet eligibility.
- **Public heat is asymmetric**: popular favorites, USA national teams, celebrity NBA teams, overs, and star-player overs attract casual money. Fade only when institutional prices refuse to confirm; do not fade public heat automatically.
- **Totals are independent**: a side lean does not justify over/under. Always require a separate total price, pace/shot/whistle logic, and blowout or garbage-time analysis.
- **Prediction markets are separate contracts**: Polymarket/Kalshi/Betfair moneyline, spread, series, or tournament contracts need their own settlement clock, bid/ask, liquidity, and max entry. Do not map a sportsbook spread lean into a binary bet unless the exact threshold is tradable and mispriced.

## Coverage Requirement

Every same-day update must query or explicitly mark the status of these buckets:

```text
NBA | WNBA | CBA | NBA G League/development league | FIBA/national teams | other visible pro/college leagues
```

Do not call a slate complete until each bucket is labeled `已获取`, `当日无赛程`, or `源不可用`. If SofaScore returns a full basketball slate, use tournament/category filters to split it into these buckets. If a bucket has no bookmaker market, keep it as score/watch-only rather than dropping it.

## Date And Timezone Rules

Use Asia/Shanghai as the final dashboard date unless the user asks otherwise.

- Query source date `D` for broad global sources.
- For US leagues such as NBA, WNBA, NBA G League, and NCAAB, query `D-1`, `D`, and sometimes `D+1`, then convert UTC/source time to Beijing time and filter the final slate.
- ESPN returns UTC timestamps and the scoreboard date may represent US local game date.
- NBA Stats `GameDate` is an NBA-family game-date input and should be cross-checked with ESPN UTC timestamps when building Beijing-date slates.
- TheSportsDB can return Basketball events by date, but may include prior completed events under a different source-date convention. Always rely on `bj_time` for the final display window.
- Store both `source_date` and `bj_time`; never overwrite one with the other.
- Daily dashboard updates must preserve prior `DATA.matches` rows and merge the new slate by stable game ID or normalized league/team/Beijing-time key. Do not replace the whole match list with only the newest date.
- Cross-day US source queries are discovery inputs only. After conversion to Beijing time, exclude events outside the target day from today's count unless they are deliberately stored as adjacent-date preview rows. If yesterday's already-stored game appears again from a source-date query, update that existing row instead of creating a duplicate.
- Adjacent-date preview rows within the next 36 hours must trigger odds collection before the dashboard is written. For NBA-family and US college games, search Action Network exact game pages, Covers matchup/odds pages, OddsPortal or another odds-comparison page, The Odds API if keyed, and exchange/consensus fallbacks when readable. Save the result as opening/current/closing-pending, total, moneyline, public percentages, and injury status. If no market is listed, record `盘口源未发现` and the attempted sources/search terms; do not use the vague label `下一日预告，赛前盘口未抓`.
- If a market page returns a blank shell to direct HTTP, use web search snippets or browser capture before giving up. This is required because Action/Covers pages may expose odds to the browser/search index while script fetches show an empty odds table.

## Industry Matrix By Data Dimension

Use the source that matches the question being answered. A score feed can prove that a game exists, but it cannot prove betting pressure; an odds board can show line movement, but it cannot replace injury and rotation work.

### Odds And Schedule

- **OddsPortal**: global odds and historical movement anchor. Use for NBA, WNBA when listed, EuroLeague, ACB, NBL, CBA, KBL, B.League, FIBA/national-team events, and other pro leagues. Record bookmaker count, opening line, latest line, closing line, spread, total, and moneyline separately.
- **Action Network**: preferred US-market monitor for NBA, WNBA, NCAA, and major international games when available. Use its live odds, line movement, alerts, best odds, and betting splits tabs.
- **Flashscore / SofaScore**: broad global basketball schedule and score discovery. Use for lower-tier and international leagues, live status, form, H2H, and basic odds, then cross-check meaningful markets elsewhere.

### Public Betting And Money Splits

- **Action Network Betting Splits**: first choice for `Bets%`, `Money%`, `Diff`, best odds, and line movement. Money% far above Bets% may signal larger money; Bets% alone is only public pull.
- **SportsInsights / Action Network Pro**: preferred source for steam moves and RLM when the account can read it. If not subscribed, mark it unavailable.
- **Pregame / Covers / Wunderdog / OddsCrowd**: public-consensus fallback. Record whether the percentage represents tickets, money, contest picks, model picks, or forum/community picks.

### Lineups, Injuries, Rotation, Matchups

- **RotoWire / Underdog NBA / official reports**: fastest practical NBA/WNBA injury and starting-lineup stack. Capture status, timestamp, probable starters, and minutes-limit notes.
- **Eurohoops / BasketNews**: priority sources for EuroLeague, EuroCup, and European domestic league injuries, travel, rotation, and pre-game context.
- **Swish Analytics**: matchup, rotation, and injury-impact source when accessible. If paywalled, mark it unavailable rather than estimating its output.
- **Team official and beat reports**: late scratches, rest decisions, G League call-ups/send-downs, national-team roster availability, import-player status, and coach rotation comments.

### Pace And Advanced Analytics

- **NBA Stats**: NBA-family pace, offensive rating, defensive rating, lineup net rating, shot profile, turnovers, rebounds, and play-by-play.
- **Cleaning The Glass**: NBA clean data with garbage time removed. Use for true pace, half-court efficiency, transition rate, and lineup quality when readable.
- **KenPom / BartTorvik**: NCAA men's basketball adjusted efficiency, tempo, projected score, and win probability.
- **Basketball-Reference / RealGM**: historical schedules, team/player stats, G League, international leagues, and non-NBA player/team lookup.

### Recommended Tool Combos

- **Totals / 大小分**: KenPom or NBA Stats/CTG + OddsPortal line path + injury/rotation source. Core checks: pace, possessions, shot mix, free-throw rate, transition, defensive-anchor availability, and total open/current/close.
- **Spread / 对位**: RotoWire or Eurohoops/BasketNews + Swish/CTG/NBA Stats + OddsPortal/Action line path. Core checks: injury impact, NetRtg, rotation depth, rest/travel, matchup edge, and spread open/current/close.
- **Market flow / 诱盘与资金**: Action Network Pro or public betting + OddsPortal + Covers/Pregame/OddsCrowd fallback. Core checks: Ticket%, Money%, RLM, steam moves, stale line, and line movement against the public side.
- **Global non-NBA slates**: Flashscore/SofaScore/TheSportsDB + OddsPortal + RealGM/Basketball-Reference + league/club official news. Core checks: schedule reliability, opening/closing odds, roster availability, and league-specific pace.

## Source Notes

### The Odds API

- Use when an API key is available in `THE_ODDS_API_KEY` or provided by the user.
- Common sports keys include `basketball_nba`, `basketball_wnba`, `basketball_ncaab`, and international basketball keys when supported by the account.
- Request `markets=h2h,spreads,totals` and decimal odds.
- For opening and closing, poll repeatedly and save snapshots. If historical/event odds are available under the plan, still label timestamps because "closing" must be the last stable pre-tip price.

### ESPN Scoreboard

- Good for schedule, scores, clock/status, home/away teams, and event IDs.
- Useful league path examples:
  - NBA: `basketball/nba`
  - WNBA: `basketball/wnba`
  - NBA G League page exists on ESPN, but its API slug should be verified before automation; use NBA Stats LeagueID `20` as the first official G League programmatic check.
  - Men's college basketball: `basketball/mens-college-basketball`
  - Women's college basketball: `basketball/womens-college-basketball`
- ESPN odds fields, when present, are not a complete line-movement history. Treat them as current display odds unless a timestamped path is stored locally.

### NBA Stats

- Use for NBA box scores, team/player season stats, lineup context, pace, offensive rating, defensive rating, rebounds, turnovers, and play-by-play.
- Scoreboard league IDs:
  - `00`: NBA.
  - `10`: WNBA.
  - `15`: NBA Summer League.
  - `20`: NBA G League.
- Requests usually need browser-like headers: `User-Agent`, `Referer: https://www.nba.com/`, `Origin: https://www.nba.com`, and `x-nba-stats-origin: stats`.
- If blocked, use ESPN, NBA.com pages, Basketball-Reference, or a browser session as fallback.

### SofaScore Scoreboard

- Use endpoint pattern: `https://api.sofascore.com/api/v1/sport/basketball/scheduled-events/YYYY-MM-DD`.
- Use it to discover all basketball events on a date, then filter by `tournament.name`, `uniqueTournament.name`, `category.name`, team names, and status.
- Expected useful fields: event ID, start timestamp, tournament/category, home/away team, current score, period scores, and match status.
- SofaScore is broad and practical, but not official. For NBA-family and FIBA/national-team games, cross-check against NBA Stats/ESPN/FIBA when possible.
- If direct HTTP returns WAF/403, try browser capture, Chrome-like headers, or `curl_cffi`; mark source `SofaScore源不可用` if not readable.

### TheSportsDB Scoreboard

- Use endpoint pattern: `https://www.thesportsdb.com/api/v1/json/3/eventsday.php?d=YYYY-MM-DD&s=Basketball`.
- Use it as an accessible fallback for date-level event discovery when SofaScore direct access returns 403.
- In local testing on `2026-08-25`, the endpoint returned HTTP 200 and WNBA events.
- Treat it as secondary: verify important games with NBA Stats, ESPN, FIBA, league official pages, or another source before settlement.

### FIBA Official

- Use FIBA games/results pages for national-team and FIBA-sanctioned competitions.
- It is the official context source for tournament name, group/round, venue, standings, and national-team schedules.
- Public pages may be easier to read than an open JSON API. Save HTML/screenshot snapshots if no stable API endpoint is found.

### Paid Production Source: iSportsAPI

- Candidate endpoint: `/sport/basketball/schedule`.
- Use when an API key and Live Data plan are available; it returns basketball schedule/results by date, league ID, or match ID and includes match modify records for sync.
- Treat it as the production fallback when public sources are blocked or incomplete.

### Titan007 / 7M / Chinese Basketball Boards

- Football Titan007 endpoints are already used locally; basketball pages may use different `lq`/basketball paths and should be re-verified before automation.
- Treat Titan007/7M basketball as a candidate source for Chinese names, live scores, Asian-style spread, total, and opening/current line hints.
- If only page-level data is readable, capture HTML/browser snapshots and label `Titan007/7M篮球页面快照`. Do not pretend it is Pinnacle, Bet365, or a sharp source.

### Covers / ScoresAndOdds / VegasInsider

- Good for NBA/NCAAB line movement and public market context when readable.
- They often show open/current consensus lines, spread, moneyline, and total. Closing must be captured near tipoff or after final if the page preserves it.
- Web layouts can change. Use structured selectors only after inspecting the page; otherwise keep a raw HTML/screenshot snapshot for audit.

### SofaScore / Flashscore / OddsPortal / BetExplorer

- Useful for international basketball, lower leagues, live status, form, H2H, and odds comparison.
- These sites can be JavaScript-heavy or protected. Prefer browser capture or API-like endpoints only when verified.
- For odds history, distinguish bookmaker-specific line movement from aggregated consensus.

### Injury / Lineup Sources

- NBA late injury news changes spread and totals more than most football news. Timestamp every status:
  - confirmed out / doubtful / questionable / probable;
  - starting lineup confirmed;
  - minutes restriction;
  - back-to-back rest candidate;
  - trade or tanking rotation risk.
- If injury status is not current within 60-90 minutes of tipoff, mark real-bet action `不投/等待临场`.

## Minimum Fields By Market

### Spread

```text
league, game_id, Beijing_time, home, away, source, open_home_spread, open_home_price,
current_home_spread, current_home_price, close_home_spread, close_home_price,
away_price, timestamp, selected_side, playable_line, stop_line
```

### Total

```text
league, game_id, Beijing_time, home, away, source, open_total, open_over_price,
open_under_price, current_total, current_over_price, current_under_price,
close_total, close_over_price, close_under_price, timestamp, selected_side,
playable_total, stop_total
```

### Fundamentals

```text
injuries, starters, questionable_players, rest_days, back_to_back, travel,
pace_rank, offensive_rating, defensive_rating, 3pa_rate, free_throw_rate,
rebound_edge, turnover_edge, public_side, source_timestamp
```

## Opening / Current / Closing Rules

- `open`: earliest available market line after the game is posted. If multiple books differ, store source-specific opens.
- `current`: latest refreshed line at analysis time.
- `close`: last stable pre-tip line from the same source or the sharpest available source. Do not use a post-tip live line as closing.
- If the source cannot preserve historical opens, poll and save snapshots at least morning, T-6h, T-2h, T-30m, and T-5m for NBA/WNBA.
- For lower-liquidity leagues, add a final snapshot as close to tipoff as practical because late steam is often concentrated.

## Example Scoreboard Commands

```powershell
python D:\codex\skills\basketball-odds-trader\scripts\basketball_market_snapshot.py sofascore-scoreboard --date 2026-08-25 --include "NBA,WNBA,CBA,G League,FIBA,World Cup,Asia Cup,Olympic"
python D:\codex\skills\basketball-odds-trader\scripts\basketball_market_snapshot.py thesportsdb-scoreboard --date 2026-08-25 --include "WNBA,NBA,CBA,FIBA"
python D:\codex\skills\basketball-odds-trader\scripts\basketball_market_snapshot.py nba-stats-scoreboard --league nba --date 2026-08-25
python D:\codex\skills\basketball-odds-trader\scripts\basketball_market_snapshot.py nba-stats-scoreboard --league wnba --date 2026-08-25
python D:\codex\skills\basketball-odds-trader\scripts\basketball_market_snapshot.py nba-stats-scoreboard --league gleague --date 2026-08-25
python D:\codex\skills\basketball-odds-trader\scripts\basketball_market_snapshot.py espn-scoreboard --league wnba --date 20260825
```

## Links To Verify Before Use

- The Odds API docs: https://the-odds-api.com/liveapi/guides/v4/
- ESPN NBA scoreboard example: https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard
- NBA Stats homepage: https://www.nba.com/stats
- NBA API community docs: https://github.com/swar/nba_api
- SofaScore basketball scheduled-events docs: https://github.com/pseudo-r/Public-Sofascore-API/blob/main/docs/sports/basketball.md
- TheSportsDB API: https://www.thesportsdb.com/api.php
- FIBA games/results: https://www.fiba.basketball/en/games
- FIBA events calendar: https://www.fiba.basketball/en/events/
- iSportsAPI basketball schedule docs: https://www.isportsapi.com/en/docs.html?id=26
- balldontlie API docs: https://docs.balldontlie.io/
- Covers NBA odds: https://www.covers.com/sport/basketball/nba/odds
- ScoresAndOdds NBA odds: https://www.scoresandodds.com/nba
- VegasInsider NBA odds: https://www.vegasinsider.com/nba/odds/las-vegas/
- SofaScore basketball: https://www.sofascore.com/basketball
- Flashscore basketball: https://www.flashscore.com/basketball/
- OddsPortal basketball: https://www.oddsportal.com/basketball/
