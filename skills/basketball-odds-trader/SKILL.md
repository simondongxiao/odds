---
name: basketball-odds-trader
description: Basketball betting-market prediction and dashboard workflow for NBA, WNBA, CBA, NBA G League/development league, NCAAB, EuroLeague, FIBA national-team games, Olympic/World Cup/Asia Cup qualifiers, B.League, KBL, NBL, and other readable basketball slates. Use when Codex needs 篮球盘口分析, NBA/CBA/WNBA/G联赛/国家队比赛预测, moneyline/spread/totals/team-total analysis, 比分赛程抓取, 初盘-即时-终盘 line movement, 让分/大小分变盘解释, injury/rest/pace-based priors, public-flow checks, positive-EV gates, Kelly staking, simulated-pick ledgers, or an HTML basketball odds dashboard.
---

# Basketball Odds Trader

## Operating Standard

Act as a senior basketball odds compiler and risk trader. Separate four questions at all times:

1. Which team is more likely to win.
2. Which team is more likely to cover the spread.
3. Whether the game total or team total is mispriced.
4. Whether the executable price is good enough to bet.

A view is not a bet. Do not recommend a side merely because it is more likely to win or because the model leans over/under. Recommend a wager only when the data chain identifies a mispricing source, the conservative probability beats the executable price after spread/slippage/model error, and the stake plan is defensive.

Basketball is a late-news and closing-line sport. For spread and totals, always store and interpret **opening, current/latest, and closing** lines separately. If closing is not known before tipoff, label it `终盘待回填`; after settlement, update closing line value before judging process quality.

## Basketball Quantitative Trading Hard Gate

This section is mandatory for every local run, report, ledger row, and HTML dashboard row. The target pool is NBA and major basketball-league **spread** and **total** markets. Moneyline is normally a context market unless the user supplies an exact executable ML or binary contract.

Mathematical floor:

- Standard decimal odds around `1.91` have breakeven near `52.38%`.
- A wager is allowed only when conservative `p_low >= 55.0%`.
- Minimum EV gate: `p_low * decimal_odds > 1.025` (EV greater than 2.5%).
- If either floor fails, set `Kelly=0`, `stake=0`, and `bet_status=不可投` or `临场观察`.

Probability and threshold gate:

- Output a probability range, not only one point estimate: `p_low | p_mid | p_high`.
- Use residual sigma `sigma_spread = 11-13` points for full-game spread unless league data says otherwise.
- Use residual sigma `sigma_total = 15-18` points for full-game totals unless league data says otherwise.
- Calculate the model/market gap before action. Let `Pred` be projected margin or projected total and `Line` be the live market threshold. Only allow a candidate into the build queue when `abs(Line - Pred) >= K`, with `K=2.5-4.0` points. Noise inside K is no-action.
- For spread, compute the gap on cover direction, not win direction. Moneyline win probability must never be reused as spread-cover probability.

Time lock, volatility fuse, and steam check:

- Line-move based entries are valid only inside the final 2 hours before tipoff.
- Moves more than 5 hours before tipoff are treated as institutional probing and ignored for entry.
- If the line range moves more than 5 points inside the final hour, mark the game `SKIP/不可投` unless a verified injury/lineup source explains it and the user explicitly asks for live monitoring.
- Final steam direction must agree with the model side. If the model side is home/favorite/over but the final sharp move attacks the opposite side, abandon the pre-game bet regardless of `p_mid`.

Kelly and staking:

- Use binary Kelly for decimal odds: `f* = (p * (b + 1) - 1) / b`, where `b = decimal_odds - 1`.
- Use `p_low`, not `p_mid`, for Kelly.
- Real staking uses strict quarter Kelly: `stake = 0.25 * max(f*, 0)`, then apply league/liquidity caps.
- Any missing hard gate, stale injury data, bad price, or steam mismatch forces `Kelly=0`.

Basketball-specific quant checks:

- Spread shallow/deep logic must inspect injuries and **minutes projection**: weak-team scorer absence/minutes cap versus favorite core minutes; favorite blowout protection or rest risk versus underdog backdoor.
- Deep spread trigger: road favorite `-10.5+` or home favorite `-12+` requires motivation, no rest, and no garbage-time red flag; otherwise default to dog/pass.
- Schedule/travel tags are required: cross-conference long-travel back-to-back, 3-in-4, 4+ game circus trip, and penultimate road-trip fatigue.
- Totals must start from `Pace_expected = (Pace_1 + Pace_2) / 2`, then adjust for ORtg/DRtg, shot profile, defensive-anchor status, whistle/foul rate, and late-game foul/bench behavior.
- Add garbage-time and fourth-quarter filters: last-quarter net-rating tendency, bench stability, late-foul discipline, and free-throw reliability. Teams that often give up backdoor covers or collapse late require a haircut to `p_low`.

Every recommendation or dashboard row must store or visibly encode these extra quant fields:

```text
pred_margin_or_total | sigma | p_low | p_mid | p_high | breakeven | ev_multiplier | edge |
K | line_pred_gap | time_lock_status | volatility_fuse | steam_alignment |
minutes_projection_status | travel_fatigue_tag | garbage_time_guard |
quarter_kelly | stake_cap | final_zero_action_reason
```

If the HTML template does not have dedicated columns, encode the same fields in `pass_fail_gates`, `execution`, `spreadAudit`, `totalAudit`, or the top no-bet reason. Do not hide a failed quant gate in lower commentary.

Use the prediction discipline from `worldcup-odds-trader`, but adapt it to basketball market reality. The model must not linearly average fundamentals, odds, and public heat. It must run this three-stage filter in order:

1. **Baseline prior**: basketball-only view before price: rotation, usage, rim protection, ballhandling, rest/travel, pace, shot profile, matchup, motivation, and likely public/story pull.
2. **Institutional correction**: compare the prior with de-vig moneyline, spread, total, and the opening-current-closing path. For liquid NBA/WNBA/NCAAB, give more weight to multi-book and sharper lines. For CBA, FIBA, summer league, and lower-liquidity leagues, treat single-book movement as fragile until confirmed.
3. **Public-tax and execution filter**: use tickets/money, exchange or prediction-market heat, media narratives, and public-facing book movement only after the institutional check. Public heat is not automatically a fade; it is a tax or confirmation signal depending on whether the spread/ML/total board agrees.

Output probabilities as ranges when injury, opening line, closing line, or liquidity is incomplete. Convert to a bet only after the executable price clears the conservative lower-bound probability and the no-chase price. Most slates should produce many `不投/观察` rows.

## Coverage And Score Source

Cover all readable basketball slates by default, not only NBA and CBA. The minimum same-day league screen is:

- NBA.
- WNBA.
- CBA and other China/Asia professional leagues when visible.
- NBA G League / development league.
- FIBA and national-team competitions, including World Cup, Olympic, continental cup, Asia Cup, EuroBasket, AmeriCup, AfroBasket, qualifiers, and youth national-team events when visible.
- NCAAB, EuroLeague, B.League, KBL, NBL, and other leagues when a reliable scoreboard and market board are available.

Use **SofaScore basketball scheduled events** as the broad default scoreboard source because it returns cross-league basketball events with tournament/category/team/status fields. If direct SofaScore HTTP is blocked, use browser capture or **TheSportsDB eventsday basketball** as the public fallback discovery source. For NBA-family games, cross-check with **NBA Stats** when possible:

- `LeagueID=00`: NBA.
- `LeagueID=10`: WNBA.
- `LeagueID=15`: NBA Summer League.
- `LeagueID=20`: NBA G League.

For official national-team context, cross-check SofaScore slates with FIBA's games/results pages when the match is FIBA-sanctioned. If one source misses a league, label the miss and try the next source; do not silently drop WNBA, G League, CBA, or national-team games from the slate.

### Date And Timezone Discipline

The user usually means the Asia/Shanghai basketball day. For a target Beijing date `D`, build the slate by querying enough source dates to catch cross-day US games:

- Query broad sources for `D`.
- For NBA/WNBA/G League/US college, also query source dates `D-1` and `D+1` when necessary because ESPN/NBA Stats may use US local game dates while kickoff appears on the next Beijing morning.
- Convert every event to `bj_time`, then filter the final dashboard slate by Beijing kickoff time.
- Keep source date and Beijing time separately. If two sources disagree, dedupe by team names, UTC time, and official game ID where available.
- Do not mix a completed prior-day UTC event into today's Beijing slate unless its `bj_time` falls inside the target display window.
- Preserve historical dashboard rows. A daily update must append or merge the new Beijing-date slate into the existing dashboard history instead of replacing `DATA.matches` wholesale. Past dates must remain selectable unless the user explicitly asks to archive or delete them.
- When querying `D-1`, `D`, and `D+1`, dedupe by stable source game ID when available; otherwise use normalized league + home + away + Beijing start time. If a game already exists from yesterday's run, update its status/score/closing line rather than creating a second row or treating it as a new today's-game candidate.
- Store each event's `bj_date`/dashboard `date` from converted Beijing time. Source-date rows that convert outside the target Beijing day can be shown only as adjacent-date preview rows, not counted as today's slate.
- Adjacent-date preview rows within the next 36 hours are market work, not just schedule work. For NBA, WNBA, G League, NCAAB, and other book-listed leagues, after finding a `D+1` or cross-day game, run the same odds-source pass before writing the dashboard: Action Network exact game page, Covers odds/matchup page, OddsPortal/odds comparison source, The Odds API if keyed, then readable exchange/consensus fallback. Record opening, current, total, moneyline, public percentages, and injury status when they are available. If no market is readable, write `盘口源未发现` plus the exact attempted sources/search terms; do not leave a generic `下一日预告，赛前盘口未抓`.
- If a direct HTTP/script fetch of a market page returns an empty shell, WAF block, or no odds table, use search-result snippets or browser capture as the next step and save the raw/source note. Do not downgrade to `未获取` until at least two independent market-source attempts have failed or the game is not yet listed by a market board.

### Team And Score Order Discipline

Do not infer basketball score order from a visual card, crawler order, or `away @ home` convention when the source does not explicitly say so.

- Store canonical teams as `home_team` and `away_team` when the official source has home/away fields.
- Display dashboard rows as `home_team vs away_team` and label final score as `比分顺序：主队-客队`.
- Store settled scores as `home_score-away_score`; calculate spread and totals from those canonical fields only.
- For neutral FIBA/national-team, summer-league, tournament, or source-first listings where home/away is ambiguous, store `official_order_team_1`, `official_order_team_2`, `score_1`, `score_2`, and `score_order=official_source_order`. Do not display these as `away @ home`.
- Do not settle a spread, total, CLV, or hit-rate row while team order or score order is ambiguous. Mark it `赛果未匹配待人工核验` until repaired from an official box score.
- When importing historical rows, do not flip teams to fit a pick result. Keep the first recorded team/order fields and append a correction note if a source-order bug is discovered.

## Mandatory Six-Board Chain

Use this order for every pre-game report. Do not skip boards unless the data is unavailable; if unavailable, label it and lower confidence.

1. **篮球基本面拉力**: team quality, rotation, injuries, rest/travel, pace, matchup, motivation, and natural public side before reading prices.
2. **ML 去水与隐含分差**: de-vig moneyline, compare with the baseline win-probability prior, and infer whether the spread is broadly coherent. Do not use moneyline probability as spread-cover probability; deep favorites can be correct on ML and still expensive on spread.
3. **让分初盘-即时-终盘审计**: compare opening/current/closing spread and both-side prices. Classify intent as true favorite strength, true favorite weakness, protect favorite, protect underdog, induce favorite, induce underdog, injury de-heat, stale line, or price exhausted. Include a pull-entry mismatch check: which side felt easy before price, and whether the book made that side cheaper or harder.
4. **大小分初盘-即时-终盘审计**: compare opening/current/closing total and over/under prices. Reconcile the move with pace, shot profile, injury, whistle, travel, and schedule effects. Never assume star out automatically means under, and never let a spread lean substitute for a total bet.
5. **公众/流动性反向情绪**: use Polymarket/Kalshi/Betfair when exact basketball markets exist, plus public-ticket, money-split, analyst/blogger, or community data when readable. Treat volume as attention, not one-sided truth. Public favorites and overs are sometimes taxes and sometimes real confirmation; decide only after the institutional line check.
6. **最终盘口选择**: choose main spread, alt spread, total, team total, moneyline, live-only, limit-only, paper-only, or no bet. Give playable line, stop line, max entry price, edge buffer, and Kelly stake. Explain why the selected entry beats the headline prediction.

If the line path is missing, output `盘口路径缺失-不形成强推荐`. A pure current-price snapshot may support a watchlist, but it cannot be called a full skill-compliant prediction.

### Basketball Market Reality And Prediction Tiers

Basketball is less forgiving than football for stale information because one guard scratch, minutes restriction, rest decision, or garbage-time rotation can swing spread and total markets. Classify every recommendation into one tier before writing it:

```text
tier | allowed label | minimum evidence | allowed statistics treatment
```

- **Tier A - executable real bet**: at least one trusted executable price, preferably two independent market checks; opening/current/closing-pending path stored; injury/lineup status fresh enough for the league; mispricing source identified; conservative `p_low` beats breakeven by the required buffer; Kelly > 0 after caps. Count only in `real_money` if actually triggered.
- **Tier B - first-write paper simulation**: exact pre-tip side, line, price, timestamp, and trigger condition are recorded, but at least one major board is incomplete. Count only in `first_write_paper`; never call it real win rate.
- **Tier C - watchlist / live-only**: team or total lean exists, but price is missing, stale, single-source, or outside the playable line. Do not count as a pick unless a later pre-tip update records a concrete Tier A or Tier B entry.
- **Tier D - scoreboard / post-match coverage**: game is completed, live at first capture, postponed, or has no verified market. Record score/status only. Never backfill into a pick.

Default real-bet stance by league:

- **NBA/WNBA/NCAAB regular markets**: real bets are possible only with current price, injury freshness, and line-move context. Late injury windows can downgrade an otherwise valid bet to live-only.
- **FIBA and national-team events**: require roster confirmation and at least a usable current market. If the market differs materially across books, use the worse executable line for EV or output no bet.
- **CBA, CBA summer league, Asian domestic leagues, G League, and preseason/summer events**: default to Tier B/C unless a trusted board supplies executable line, price, and enough roster/news context. Single-source current odds can justify observation, not a full recommendation.

Real-bet edge buffers:

- Liquid NBA/WNBA sides: `p_low - breakeven >= 2-3 percentage points`.
- Liquid NBA/WNBA totals or team totals: `>= 3-4 percentage points` because injury/pace/whistle error is larger.
- NCAAB/FIBA/CBA regular markets: `>= 4-6 percentage points`.
- Summer league, preseason, youth, or thin international markets: `>= 8-12 percentage points`; otherwise `Kelly=0`.

No-chase rule: if the current executable line is worse than the playable line or the price is above the max entry, the recommendation becomes `不投` even if the directional read remains correct.

### Bettable / No-Bet Screening Gate

Borrow the final-selection discipline from `worldcup-odds-trader`: every analyzed market must pass a bettable screen after the six-board chain and before it appears as a recommendation. A strong basketball view is still only a view until the executable market clears the gate.

Assign exactly one `bet_status` to each candidate:

```text
bet_status | meaning | allowed action | statistics bucket
可投-主单 | Tier A, all hard gates pass, edge survives p_low and no-chase | executable main recommendation with defensive Kelly | real_money only if actually triggered
可投-小仓限价 | Tier A but edge/liquidity/news risk is thin; playable only at max_entry or better | limit-only, capped stake, auto-cancel above max_entry | real_money only if trigger fires before tipoff
纸面模拟 | Tier B, exact pre-tip side/line/price/timestamp exists but evidence is incomplete | model audit only, not a real recommendation | first_write_paper
临场观察 | Tier C, thesis exists but needs lineup, price, pace, or live trigger | watchlist/live-only, no pre-game pick | no-action
不可投 | Tier C/D or any hard blocker fails | no bet, coverage or review only | no-action/coverage
```

Hard blockers that force `不可投` unless explicitly repaired before tipoff:

- No exact executable line and price for the selected market.
- First capture is already live, completed, postponed, or after the relevant market closed.
- Team order, home/away identity, official listing order, or score order is unresolved.
- Only a scoreboard source exists; no market source confirms spread, total, moneyline, or exchange price.
- CBA, CBA summer league, G League, preseason/summer, youth, or thin international market is supported only by one current snippet without opening path, timestamp, and roster context.
- NBA/WNBA/NCAAB/FIBA injury, lineup, rotation, rest, or roster status is stale or missing for a late-news-sensitive game.
- Spread or total recommendation lacks opening-current-closing/`终盘待回填` path.
- Conservative `p_low` does not beat breakeven by the required league/market buffer.
- Current price is worse than the playable line, above `max_entry`, or requires chasing after the edge has been consumed.
- Public/exchange heat conflicts with institutional line movement and the report cannot explain the mismatch.
- Prediction-market or exchange contract has unclear settlement, threshold, overtime treatment, bid/ask, or liquidity.
- Source is stale, off-date, wrong-season, ambiguous, or not tied to the exact game.

For every slate, include a `可投/不可投汇总`: count rows in each `bet_status`, list the main no-bet reasons, and explain why any selected bet beats merely predicting the winner. Most basketball slates should have few or zero `可投` rows.

Every recommendation table or dashboard row must store:

```text
match | market | selection | line_price | tier | bet_status | pass_fail_gates | p_low | breakeven | edge | min_buffer | max_entry | kelly | stake_cap | count_bucket | reason
```

The first visible dashboard panel for a game should show only the simulated/execution summary: `bet_status`, selected market, line/price, stake/trigger, count bucket, and no-bet reason. Keep long market-intent, EV, and reverse-matrix explanation in lower detail sections, not in the top recommendation panel.

## Basketball-Specific Priors

Build the baseline prior before reading the odds board:

- **Rotation and injuries**: confirmed starters, usage redistribution, rim protection, primary ballhandler availability, bench depth, minute limits, back-to-back rest, and late scratches.
- **Pace and shot diet**: possessions, transition rate, three-point attempt rate, free-throw rate, offensive rebounding, turnover pressure, and opponent scheme.
- **Schedule and venue**: back-to-back, 3-in-4, travel distance, altitude, early local start, home/away splits, tournament/cup format, and motivation.
- **Spread mechanics**: late-foul game, two-possession/three-possession thresholds, blowout risk, bench gap, garbage-time backdoor risk, and favorite tendency to coast.
- **Totals mechanics**: pace ceiling, half-court efficiency, whistle/foul environment, opponent transition defense, defensive anchor availability, and whether injuries reduce offense, defense, or tempo.
- **League profile**: NBA and WNBA are late-news sensitive; NCAAB has bigger home-court and foul variance; CBA/Asian leagues may have import-player and foreigner-minute rules; EuroLeague often has lower possession counts and more half-court defense.
- **Public/story pull**: popular NBA teams, defending champions, USA national teams, host teams, star-player narratives, recent blowouts, and "must win" stories can create tax. They are not automatic fades if institutional prices confirm the same side.
- **Margin buckets**: for spread choices, estimate cover-tail buckets around the available line, not just one projected margin. At minimum classify `close game 0-3`, `two-possession 4-6`, `three-possession 7-9`, `double-digit 10-14`, and `blowout 15+` for ordinary spreads. For FIBA/development deep spreads, also estimate `favorite wins by 20+` and `garbage-time backdoor`.

Do not merge these priors into one score. Keep separate estimates for moneyline probability, spread-cover probability, total probability, and team-total probability.

## Data Matrix By Dimension

Use different source stacks for different questions. Do not treat a scoreboard source as a market-flow source or an odds page as an injury source.

### 1. Odds And Schedule

Primary use: same-day global slate, score status, spread/total/ML board, opening-current-closing path.

- **OddsPortal**: use as the global odds and historical line-movement anchor for NBA, WNBA when listed, EuroLeague, ACB, NBL, CBA, KBL, B.League, FIBA/national-team, and other leagues. Prefer it for bookmaker comparison, opening line, current line, closing line, and market count.
- **Action Network**: use as the US-market odds monitor for NBA, WNBA, NCAA, and major international games when listed. Use alerts, best odds, line movement, and public betting tabs when readable.
- **Flashscore / SofaScore**: use as broad live-score and lower-tier league discovery sources. Use them for match list, status, form/H2H, and basic odds only; cross-check important markets elsewhere.

### 2. Public Betting And Money Splits

Primary use: public pull, ticket concentration, handle concentration, reverse-line-move and steam checks.

- **Action Network Betting Splits**: prioritize `Bets%`, `Money%`, `Diff`, best odds, and line movement. Money% far above Bets% may indicate larger/stabler money; Bets% without Money% is only public heat.
- **SportsInsights / Action Network Pro**: use for steam moves and RLM when accessible. Label as unavailable if not subscribed.
- **Pregame / Covers / Wunderdog / OddsCrowd / Wiseguy-style pages**: use as public consensus fallback. Record whether percentages are contests, tickets, money, or model community picks; do not mix them.

Do not equate public splits with sharp truth. In basketball, public attention often clusters on favorites, overs, star-player overs, and national-brand teams. A money split confirms only if it aligns with a credible line move and injury/rotation context. If public money chases a side while the spread refuses to move, classify a public-tax warning. If public heat and sharper line movement both support the same side, upgrade confidence only one level and still require executable edge.

### 3. Lineups, Injuries, Rotation, Matchups

Primary use: spread and totals adjustment before price interpretation.

- **Rotowire / Underdog NBA / official injury reports**: fastest NBA/WNBA injury and starting-lineup sources. Use status, timestamp, probable starters, and minutes-limit notes.
- **Eurohoops / BasketNews**: preferred EuroLeague/EuroCup/European domestic injury, rotation, and team-news sources.
- **Swish Analytics**: use for rotation, player matchup, and injury impact value when accessible; label unavailable if paywalled.
- **Team official/beat reports**: use to confirm late scratches, rest decisions, G League call-ups/send-downs, national-team roster availability, import-player availability, and coach rotation comments.

### 4. Pace And Advanced Analytics

Primary use: totals, team totals, matchup quality, and non-box-score team strength.

- **NBA Stats**: pace, offensive/defensive rating, lineup net rating, player impact, shot profile, turnovers, rebounding, and play-by-play for NBA-family games.
- **Cleaning The Glass**: NBA clean data with garbage time removed; prefer it for true pace, transition frequency, half-court efficiency, and lineup quality when accessible.
- **KenPom / BartTorvik**: NCAA men's basketball adjusted efficiency, pace, projected score, and win probability.
- **Basketball-Reference / RealGM**: historical schedules, team/player stats, international leagues, G League, FIBA, and non-NBA data.

## Scenario Tool Combos

Use these combinations by research task:

- **Totals / 大小分**: KenPom or NBA Stats/CTG + OddsPortal line path + injury/rotation source. Core indicators: pace, possessions, shot mix, free-throw rate, transition, defensive-anchor availability, and total open/current/close.
- **Spread / 对位**: Rotowire or Eurohoops/BasketNews + Swish/CTG/NBA Stats + OddsPortal/Action line path. Core indicators: injury impact, NetRtg, rotation depth, rest/travel, matchup edge, and spread open/current/close.
- **Market flow / 诱盘与资金**: Action Network Pro or public betting + OddsPortal + Covers/Pregame/OddsCrowd fallback. Core indicators: ticket%, money%, RLM, steam moves, stale line, and line move versus public side.
- **Global non-NBA slates**: Flashscore/SofaScore/TheSportsDB + OddsPortal + RealGM/Basketball-Reference + league/club official news. Core indicators: schedule reliability, opening/closing odds, roster availability, and league-specific pace.

If a recommended tool is paywalled or blocked, say so and continue with the best verified fallback. Missing `Money%`, injury timestamp, or closing line must downgrade action to `观察/不投`.

### CBA-Specific Coverage Gate

CBA must not be covered only by a broad basketball fallback. For every daily update, run and record at least one CBA-specific schedule source even when the result is no game. This includes regular season, playoffs, preseason, summer league, CBA Cup, regional summer stops, and official club warm-up tournaments when they are listed by CBA/Chinese basketball sources:

```text
CBA official or China Basketball Association calendar | Sina/Tencent/Flashscore/Titan007/7M cross-check | TheSportsDB Chinese CBA/eventsday fallback | market-board check if a game exists
```

If broad sources return empty but the CBA-specific source is not checked, the CBA coverage gate is incomplete. If the target date is outside the published preseason, regular-season, playoff, or cup window, record the calendar reason and do not create fake CBA match rows.

## Dashboard Slate Discipline

Keep the left match list clean. It must contain only real games or upcoming tradable events with teams, league, Beijing time, and status. Do **not** place coverage buckets such as `官方源 @ NBA`, `覆盖桶 @ CBA`, or `国家队 @ 覆盖桶` in the match list.

Show league-source coverage separately in the gates, source table, or a dedicated coverage-status table. Each coverage bucket can say `已获取`, `当日无赛程`, `公开源未发现`, or `源不可用`, but it is not a match and must not receive a fake home/away team.

Display team names in Chinese in user-facing HTML and reports. Keep English names, abbreviations, source IDs, or original team names only inside source notes when useful for audit. If a Chinese translation is uncertain, use a conservative transliteration and optionally add the English name in parentheses once.

Never use placeholder data. If a field is unknown, write `未获取`, `源不可用`, `待临场`, or `终盘待回填` with the reason. Do not fill spread, total, injury, public-money, sample size, win rate, or PnL with guessed numbers.

## Spread Intent And Forward-Reverse Matrix

Basketball spread analysis must include the Asian-handicap style intent labels used in football, adapted to spread markets:

Before interpreting any spread, emit or store a pull table:

```text
side | basketball pull | public/story pull | spread-cover tail | natural public side
```

This table must be written before the odds interpretation in the analysis record. If the eventual market read overrides the pre-price prior, state exactly what changed it.

- `阻上`: the favorite/giving side is made harder or more expensive to buy; if fundamentals, ML, and injury context confirm, the intended side can still be the upper/favorite side.
- `诱上`: the favorite/giving side looks emotionally easy, cheap, or public-friendly without enough confirmation; default audit is to fade the upper/favorite side or pass.
- `阻下`: the underdog/receiving side is made uncomfortable, expensive, or receives less usable cushion. Map only after checking whether the book is protecting the dog or protecting the favorite.
- `诱下`: the underdog/receiving side looks too safe despite mismatch, weak rotation, or market resistance; default audit is to fade the lower/underdog side or pass.
- `降温保护`: bad news or public fear lowers the threshold for a side that may remain live.
- `真实示强` / `真实示弱`: line, ML, fundamentals, and injury/rest information point cleanly in the same direction.
- `价格已透支`: the read may be right but current spread/price has already consumed the edge.

Always translate the tag into an actual side:

```text
intent_tag | implied_side | forward_team | reverse_team | line_bucket | source
```

`正向` means buying the side implied by the current intent diagnosis. `反向` means buying the opposite side. Never show only `正向` or `反向`; write the concrete team and side, for example `正向=买下盘 Golden State +分，反向=买上盘 Minnesota -分`.

After settlement, update the intent matrix for both directions:

```text
match | market | line_bucket | intent_tag | forward_team | forward_line | forward_result | forward_pnl | reverse_team | reverse_line | reverse_result | reverse_pnl | close_line | CLV | notes
```

Use flat-stake settlement including pushes and half-wins where the market supports them. In dashboard cells and selected-match badges, show sample size, forward hit rate/PnL, reverse hit rate/PnL, and current better direction only when a real historical ledger exists. If there is only a single live/recent case, write `本场复盘` or `历史样本库未建立`; do not convert it into a statistical matrix. Treat sample sizes below the configured threshold as observation only; do not use them for real-bet staking.

For deep basketball spreads, explicitly estimate the distribution around the traded threshold:

```text
favorite by 0-3 | favorite by 4-6 | favorite by 7-9 | favorite by 10-14 | favorite by 15+ | garbage-time backdoor risk
```

For national-team, youth, preseason, or summer-league mismatches with spreads of `-20` or deeper, add `favorite by 20+`, `favorite by 30+`, and `bench-minute uncertainty`. Evidence that the favorite is far better is not enough; the question is whether the favorite clears the actual number at the executable price.

## Spread Path Discipline

For every analyzed spread, record:

```text
source | open_spread | open_price | current_spread | current_price | close_spread | close_price | timestamp
```

Use the home-team spread sign convention when storing data: home favorite is negative, home underdog is positive. State the selected side clearly in Chinese, for example `正期望方：湖人（让分上盘 -4.5）` or `正期望方：勇士（受让下盘 +6.5）`.

Material movement thresholds:

- NBA/WNBA: spread move of `1.5+` points is material; `2.5+` usually requires injury, lineup, rest, or sharp confirmation.
- NCAAB/CBA/low-liquidity leagues: spread move of `2+` points is material; large late moves are easier to overreact to and require source confirmation.
- Price-only movement of `10+` American cents or `0.08+` HK water can be material near a key number.

Interpret common spread paths:

- Favorite from `-3.5` to `-5.5` with ML confirmation and lineup support: likely real favorite strength; entry may still be worse after the move.
- Favorite from `-6.5` to `-4.5` after star questionable news: classify as injury de-heat first; only buy favorite if minutes/status evidence supports it.
- Favorite line deeper while favorite price remains cheap: possible favorite protection or public chase; compare with public-ticket side and totals.
- Underdog receives more points but underdog price gets worse: possible dog protection or sharp dog resistance.
- Easy public favorite at a short line with no ML/lineup confirmation: possible induce favorite; prefer pass or live confirmation.
- Large dog looks safe but has pace mismatch, turnover risk, and weak bench: beware induced underdog and backdoor-cover illusion.

For spread recommendations, always include:

- Entry line and price.
- Playable line.
- Stop line.
- What closing line would prove good process.
- Live defense plan if early pace, foul trouble, or rotation news breaks the prior.

## Totals Path Discipline

For every total, record:

```text
source | open_total | open_over_price | open_under_price | current_total | current_over_price | current_under_price | close_total | close_prices | timestamp
```

Material movement thresholds:

- NBA/WNBA: total move of `2.5+` points is material; `4+` points requires a concrete pace/injury/news explanation.
- NCAAB/CBA/European leagues: total move of `3+` points is material; adjust for lower liquidity and venue uncertainty.
- A total that rises while over price stays attractive can be true over protection or public over chase. Decide only after the pace/injury/whistle audit.

Totals rules:

- Star out can create under, over, or no effect. A high-usage star missing can reduce half-court efficiency, but can also increase pace, bench threes, opponent rim pressure, or defensive leakage.
- Defensive-anchor out often matters more for totals than secondary scorer out.
- Back-to-back fatigue can lower shooting legs but increase transition defense mistakes and foul rate.
- A spread blowout profile can hurt full-game over through fourth-quarter bench tempo, or help over if both benches play fast and defend poorly.
- If the main total has moved too far, compare first-half total, team total, or live entry after first-six-minute pace confirmation.

Do not recommend a total without a separate total-market price. A spread opinion cannot substitute for over/under odds.

## Data Hierarchy

Use the most reliable available data in this order:

1. Broad scoreboard source: SofaScore basketball scheduled events for full-day league discovery across NBA, WNBA, CBA, G League, FIBA/national teams, and international leagues.
2. Public fallback discovery: TheSportsDB basketball `eventsday` when SofaScore direct access is blocked, with source quality labeled as lower than official feeds.
3. Official scoreboard cross-check: NBA Stats for NBA/WNBA/Summer/G League; ESPN for NBA/WNBA/NCAAB/G League pages when readable; FIBA official games/results for national-team competitions.
4. User-provided lines or screenshots with opening/current/closing spread, totals, and prices.
5. Sharp or semi-sharp sportsbook/API lines such as Pinnacle/SBOBet or The Odds API when available.
6. Public line-movement pages such as Covers, ScoresAndOdds, VegasInsider, OddsPortal, BetExplorer, Titan007/7M basketball, Flashscore, or SofaScore odds when readable.
7. Primary basketball data: NBA Stats, ESPN summary, Basketball-Reference, official league reports, and official injury reports when available.
8. Injury/lineup specialists such as RotoWire, Underdog NBA, SportsDataIO, Sportradar, or user screenshots.
9. Prediction/exchange markets such as Polymarket, Kalshi, or Betfair only when the exact basketball market, settlement, bid/ask, spread, and liquidity are visible.
10. Explicit model estimates only when live market data is missing; label them as estimates.

Source-role discipline:

- A scoreboard source can prove game existence, time, status, and score; it cannot prove spread, total, public money, or executable price.
- A sportsbook snippet can support a Tier B paper observation only when it includes side, line, price, timestamp/capture context, and the game has not tipped. If any of these are missing, downgrade to Tier C.
- A single low-liquidity or offshore-looking book is not enough for a real bet. Use it only as a line clue unless the user explicitly supplies executable access and the price passes all legal/safety guardrails.
- A prediction-market price is a separate contract with its own settlement rule. Do not map a moneyline probability to spread, total, or team-total execution.
- User screenshots from a trusted board outrank public snippets, but still require timestamp, market type, and whether the shown price is open/current/close.

### Prediction-Market And Exchange Execution

When Polymarket, Kalshi, Betfair, 必发, or another exchange-like source is visible, handle it as an execution market only if the exact contract can be audited:

- Confirm market question, league/game, settlement clock, overtime treatment, cancellation rule, and whether the contract is moneyline, spread, total, team total, or series/tournament.
- Use executable bid/ask, not last trade or midpoint. For buying YES, use the YES ask. For buying NO, use the NO ask or the inverse of the visible bid when necessary.
- Record liquidity, bid/ask spread, and whether the intended size would move the book. Wide or shallow markets are limit-only or no-bet by default.
- Convert fair probability for that exact contract. Do not use sportsbook spread value to buy a moneyline contract, and do not use a moneyline price to justify a spread.
- Require an edge buffer of at least `6-8` percentage points for liquid binary markets and `10-15` points for thin basketball markets. If the edge exists only at midpoint, output no bet.
- Every binary-market recommendation must include `max entry price`. Above that price, the recommendation automatically becomes `不投`.

Read `references/data_sources.md` when choosing fetch sources. Read `references/model.md` for formulas, settlement, Kelly, CLV, spread-sign conventions, and total projection rules.

## Reusable Tool

Use `scripts/basketball_market_snapshot.py` for common calculations and lightweight public fetches:

```powershell
python D:\codex\skills\basketball-odds-trader\scripts\basketball_market_snapshot.py devig --names "Home,Away" --odds "1.91,1.95"
python D:\codex\skills\basketball-odds-trader\scripts\basketball_market_snapshot.py line-audit --market spread --selection home --entry-line -4.5 --open-line -3.5 --current-line -5.0 --close-line -5.5
python D:\codex\skills\basketball-odds-trader\scripts\basketball_market_snapshot.py line-audit --market total --selection over --entry-line 226.5 --open-line 224.0 --current-line 227.5 --close-line 228.0
python D:\codex\skills\basketball-odds-trader\scripts\basketball_market_snapshot.py estimate-cover --projected-margin 6.0 --spread -4.5 --sigma 12.0
python D:\codex\skills\basketball-odds-trader\scripts\basketball_market_snapshot.py quant-gate --market spread --selection home --prob-low 0.56 --odds 1.91 --pred 8.5 --line -4.5 --k-points 3.0 --hours-to-tip 1.5 --steam-aligned yes
python D:\codex\skills\basketball-odds-trader\scripts\basketball_market_snapshot.py quant-gate --market total --selection under --prob-low 0.555 --odds 1.91 --pred 218.0 --line 224.5 --k-points 3.5 --hours-to-tip 1.0 --volatility-last-hour 2.0 --steam-aligned yes
python D:\codex\skills\basketball-odds-trader\scripts\basketball_market_snapshot.py the-odds --sport basketball_nba --markets h2h,spreads,totals
python D:\codex\skills\basketball-odds-trader\scripts\basketball_market_snapshot.py espn-scoreboard --league nba --date 20260824
python D:\codex\skills\basketball-odds-trader\scripts\basketball_market_snapshot.py sofascore-scoreboard --date 2026-08-25 --include "NBA,WNBA,CBA,G League,FIBA,World Cup,Asia Cup,Olympic"
python D:\codex\skills\basketball-odds-trader\scripts\basketball_market_snapshot.py thesportsdb-scoreboard --date 2026-08-25 --include "WNBA,NBA,CBA,FIBA"
python D:\codex\skills\basketball-odds-trader\scripts\basketball_market_snapshot.py nba-stats-scoreboard --league wnba --date 2026-08-25
python D:\codex\skills\basketball-odds-trader\scripts\basketball_market_snapshot.py nba-stats-scoreboard --league gleague --date 2026-08-25
```

The script can compute without network for devig, Kelly, line audit, probability estimates, and the hard `quant-gate`. Network subcommands require the relevant source to be reachable and may need API keys.

## Local Output Workflow

For daily basketball updates, use this local structure:

- Skill: `D:\codex\skills\basketball-odds-trader\`
- Dashboard: `D:\codex\outputs\basketball_odds_trader\dashboard\index.html`
- Raw source snapshots: `D:\codex\outputs\basketball_odds_trader\raw\`
- Ledger and audits: `D:\codex\outputs\basketball_odds_trader\ledger\`
- Backups: `D:\codex\outputs\basketball_odds_trader\backups\`

Before changing ledgers, reports, scripts, or dashboard HTML, create a timestamped backup under the basketball backups directory. After an update, refresh the HTML dashboard and give the user the dashboard path.

Use `assets/dashboard_template.html` as the standalone dashboard template when no generated dashboard exists. The template must show missing fields rather than hiding them.

## Daily Update Gates

Do not mark a daily basketball update complete unless these gates are checked:

1. **Backup gate**: current skill/script/dashboard/ledger files are backed up before edits.
2. **Recent-error audit gate**: before new picks, check post-match contamination, favorite win probability mistaken for cover probability, over-rewarded safe underdogs, public favorite/over tax, current-only odds snapshots, injury freshness, and whether any prior row was wrongly counted as real money.
3. **Coverage gate**: NBA, WNBA, CBA, G League/development league, and FIBA/national-team slates have each been queried or explicitly marked `当日无赛程/源不可用`.
4. **Timezone gate**: source dates and `bj_time` are both stored; the dashboard slate is filtered by Beijing time after dedupe.
5. **Slate gate**: target-date games are listed with league, Beijing time, teams, status, and source.
6. **Market path gate**: spread and totals show opening/current/closing or explicit `终盘待回填`.
7. **Injury/rest gate**: injuries, probable starters, rest, travel, and back-to-back status are visible or marked `未接入/待核`.
8. **Six-board gate**: the mandatory chain is stored or visible for every analyzed match.
9. **Prediction-tier gate**: every row is labeled Tier A/B/C/D. Only Tier A can become real money, Tier B is paper-only, Tier C is watch/live-only, and Tier D is coverage-only.
10. **Bettable-screen gate**: every analyzed market is labeled `可投-主单`, `可投-小仓限价`, `纸面模拟`, `临场观察`, or `不可投`, with `pass_fail_gates`, `count_bucket`, and no-bet reason stored.
11. **Team/score-order gate**: home/away or official source order is recorded before settlement. Ambiguous order is `赛果未匹配待人工核验`, not a win/loss.
12. **Intent-matrix gate**: analyzed spread rows include `阻上/诱上/阻下/诱下/真实示强/真实示弱/降温保护/价格已透支`, the implied forward side, reverse side, and post-settlement forward/reverse result when available.
13. **Price gate**: exact market price exists for every simulated pick; no matching price means no simulated pick.
14. **Quant-gate**: run or manually reproduce the hard model gate for each candidate: `p_low >= 55%`, `p_low * odds > 1.025`, `abs(Line-Pred) >= K`, time-lock/fuse pass, steam aligned, quarter Kelly > 0 after caps. Any fail is Zero Action.
15. **Edge-buffer gate**: `p_low` must beat breakeven by the league-specific buffer before any Kelly > 0. Directional conviction without buffer is `观察/不投`.
16. **Real-bet gate**: real-money action requires executable price, positive edge, conservative Kelly, stop line, and no-chase max entry. Otherwise display `纸面模拟`, `临场观察`, or `不可投`.
17. **T+1 settlement gate**: past games are `已结算`, `取消/延期`, or `赛果未匹配待人工核验`.
18. **CLV gate**: post-match review records entry line, closing line, result, spread/total outcome, and process grade.
19. **Dashboard gate**: `index.html` is regenerated or explicitly marked stale.

If a source fails, keep the update partial and display the failed gate. Do not fill a missing injury report, closing line, exchange price, or total line with invented data.

## Output Format

For a pre-game report, use this order:

1. Cold conclusion: one of `可投-主单`, `可投-小仓限价`, `纸面模拟`, `临场观察`, or `不可投`; include the exact bet/no-bet reason first.
2. Bettable screen table: `match | market | selection | line_price | tier | bet_status | pass_fail_gates | pred_margin_or_total | sigma | p_low | p_mid | p_high | breakeven | ev_multiplier | edge | min_buffer | K | line_pred_gap | time_lock_status | volatility_fuse | steam_alignment | max_entry | quarter_kelly | stake_cap | count_bucket | reason`.
3. Prediction tier: Tier A/B/C/D, plus whether it can count as `real_money`, `first_write_paper`, or coverage-only.
4. Data completeness audit: market path, injury/rest, box-score/form, public/flow, exact price source, team/score order, and missing fields.
5. Basketball baseline pull table: `side | basketball pull | public/story pull | spread-cover tail | natural public side`.
6. ML de-vig and implied margin: raw odds, no-vig probability, prior gap, and why this does or does not translate into spread value.
7. Spread path: open/current/closing spread, price movement, pull-entry mismatch, intent tag, entry/playable/stop line.
8. Intent matrix: `阻上/诱上/阻下/诱下` candidate, `正向=具体队伍+上盘/下盘`, `反向=具体队伍+上盘/下盘`, sample size, forward/reverse hit rate and flat-stake PnL.
9. Margin buckets: close-game, two-possession, three-possession, double-digit, blowout, and garbage-time backdoor risk when the spread is meaningful.
10. Totals path: open/current/closing total, over/under price movement, pace/injury/whistle explanation, and why it is independent from the spread view.
11. Public/flow: Polymarket/Kalshi/Betfair/public-ticket/analyst view when available, with contract/settlement/liquidity limits.
12. Quant and Positive-EV gate: mispricing source, conservative `p_low`, breakeven, EV multiplier, edge buffer, K gap, time lock, volatility fuse, steam alignment, quarter Kelly, stake cap, and no-chase condition.
13. Final execution: main/alt spread, moneyline, total/team total, live defense line, and `不投` conditions. Do not label a side as recommended when `bet_status=不可投`.
14. Score and pace scenarios: projected margin range, projected total range, late-foul/backdoor risk, garbage-time risk.
15. Slate summary: count `可投-主单/可投-小仓限价/纸面模拟/临场观察/不可投` and list the dominant no-bet blockers.

For post-match review, keep these columns separate:

```text
match | original_pick | entry_line | close_line | result | market_outcome | team_score_order_status | CLV | process_grade | retain/correct/new_rule
```

Never rewrite a past pick using final information. A losing pick with positive CLV can be retained; a winning pick bought at a bad price must be marked as poor process.

### Immutable First-Write Settlement

For hit-rate statistics, use only the first pre-game record for a match and market. Store these fields before tipoff when available:

```text
first_recorded_at | source_update_file | match_id | market | original_side | original_line | original_price | trigger_condition | gate_status | bet_status | count_bucket | real_bet_flag | kelly | result | settlement_line | settlement_status
```

Later updates may append `settlement_result`, `closing_line`, `CLV`, `post_match_revision`, and `process_grade`, but must not replace `original_side`, `original_line`, `trigger_condition`, `real_bet_flag`, or `kelly` for statistical purposes.

Rows labeled `Intent corrected`, `retain/correct/new_rule`, or any post-match revision are review rows. They can explain process learning, but they cannot be counted as historical pre-game wins. If the original record says `no bet`, `wait for re-audit`, `trigger not met`, `limit-only`, or `Kelly=0`, classify it as `no-action` for real-money statistics. Track such rows only in a separate `first_write_paper` bucket when explicitly auditing paper theses.

Dashboard and ledger statistics must keep three buckets separate:

```text
real_money | first_write_paper | post_match_revision
```

Only `real_money` can be called the real win rate. `first_write_paper` is a model-audit rate, and `post_match_revision` is not a predictive hit-rate statistic.

## Guardrails

- Do not recommend offshore or unlicensed betting sites.
- Do not present betting advice as guaranteed profit.
- Do not overfit one late injury, buzzer-beater, overtime, or garbage-time cover into a permanent rule.
- Always distinguish winner probability, spread value, total value, team-total value, and executable price.
