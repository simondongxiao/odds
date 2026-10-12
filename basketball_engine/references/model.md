# Basketball Odds Model Reference

Use this file for formulas and settlement details. Keep probability outputs as ranges when injury or closing-line data is incomplete.

## Mandatory Quant Gate

Run this gate before any real or simulated recommendation for spread or total markets. A model lean is not enough.

```text
standard_price = 1.91
standard_breakeven = 1 / 1.91 = 52.36%  # practical shorthand: 52.38%
minimum_true_probability = 55.0%
minimum_ev_multiplier = 1.025
K = 2.5-4.0 points
```

Action is allowed only if all are true:

```text
p_low >= 0.55
p_low * decimal_odds > 1.025
directional Line-Pred gap >= K
time_lock_status passes
volatility_fuse is not tripped
steam_alignment is yes
quarter_kelly > 0 after caps
```

Otherwise:

```text
bet_status = 临场观察 or 不可投
kelly = 0
stake = 0
count_bucket = no-action
```

For spreads, compare projected margin with the spread threshold in the selected side's direction:

```text
home_spread = -4.5
market_home_threshold = -home_spread = 4.5
home_side_gap = projected_home_margin - market_home_threshold
away_side_gap = market_home_threshold - projected_home_margin
```

For totals:

```text
over_gap = projected_total - market_total
under_gap = market_total - projected_total
```

Only the selected side's positive gap can pass the K rule. Do not use `abs(gap)` to justify the wrong side.

## Probability Ranges And Sigma

Always output probability ranges:

```text
p_low | p_mid | p_high
```

Default residual standard deviations:

```text
sigma_spread = 11-13 points
sigma_total = 15-18 points
```

Use wider sigmas or a lower `p_low` when injuries, minutes, roster, line history, or liquidity are incomplete. Basketball is late-news sensitive; missing news is a probability haircut, not a reason to fill with neutral estimates.

## Time Lock, Volatility Fuse, And Steam

Line movement can be used as an entry trigger only close to tipoff:

```text
hours_to_tip < 0: live/post-tip, no pre-game action
line_move_trigger and hours_to_tip > 5: ignore as institutional probing
line_move_trigger and hours_to_tip > 2: wait, no pre-game build
line_move_trigger and 0 <= hours_to_tip <= 2: eligible
```

Volatility fuse:

```text
if volatility_points_last_hour > 5:
    bet_status = 不可投
    reason = SKIP: final-hour swing exceeds 5 points
```

Steam alignment:

```text
steam_alignment = yes: may continue
steam_alignment = no: abandon
steam_alignment = unknown: no real bet; paper only if every other Tier B field is exact
```

If final sharp movement attacks the model side, set `Kelly=0` even when `p_mid` looks attractive.

## Fundamentals And Efficiency Matrix

Spread checks:

- Shallow favorite line: verify favorite core minutes and defense versus underdog scorer absence/minutes restriction. If favorite minutes are real and underdog shot creation is impaired, favorite cover can survive. If favorite blowout protection or rest is likely, downgrade to dog/pass.
- Deep spread: road favorite `-10.5+` or home favorite `-12+` requires high motivation, no rest, no key GTD, and manageable backdoor risk. Public chase plus late downshift plus favorite GTD is a strong dog/pass signal.
- Travel fatigue tags are mandatory: cross-conference long-travel back-to-back, 3-in-4, 4+ road circus trip, and penultimate road-trip fatigue.

Totals checks:

```text
Pace_expected = (Pace_1 + Pace_2) / 2
```

Adjust for ORtg/DRtg, shot profile, transition rate, free-throw rate, offensive rebounding, turnover pressure, defensive anchor status, travel, altitude, whistle tendency, and bench pace.

Value patterns:

- Under: expected pace is league-bottom slow, but the market total is inflated by a one-game high-score narrative.
- Over: both defenses are bottom-tier and pace is high, while a star absence depresses the line even though the team style still creates fast possessions and defensive leakage.

Garbage-time guard:

- For favorites, check fourth-quarter net margin, bench defensive quality, late-foul discipline, and free-throw reliability.
- For totals, check whether blowout bench time kills full-game pace or creates loose, high-turnover scoring.
- Haircut `p_low` for teams that routinely concede backdoor covers or collapse late.

## Odds Conversion

Decimal implied probability:

```text
raw_prob = 1 / decimal_odds
```

American to decimal:

```text
if american > 0: decimal = 1 + american / 100
if american < 0: decimal = 1 + 100 / abs(american)
```

Hong Kong water to decimal:

```text
decimal = 1 + hk_water
```

No-vig two-way probability:

```text
p_a_raw = 1 / odds_a
p_b_raw = 1 / odds_b
p_a_true = p_a_raw / (p_a_raw + p_b_raw)
p_b_true = p_b_raw / (p_a_raw + p_b_raw)
```

## Kelly

Decimal odds:

```text
kelly = (p * decimal_odds - 1) / (decimal_odds - 1)
```

Binary market at price `c`:

```text
kelly = (p - c) / (1 - c)
```

Use defensive fractional Kelly:

- Normal basketball edge: `0.15-0.25 Kelly`.
- Late-news uncertain NBA/WNBA: cap single pre-game exposure at `0.5%-1.0%` bankroll.
- Lower-liquidity leagues or unclear injury status: cap at `0.25%-0.75%`.
- If conservative lower-bound probability does not beat price after edge buffer, stake is zero.

## Positive-EV Gate And Edge Buffers

Borrow the execution discipline from `worldcup-odds-trader`: a correct direction is not a bet until the conservative lower-bound probability beats the executable price by enough to pay for model error, line movement, slippage, and liquidity.

For decimal odds:

```text
breakeven = 1 / decimal_odds
edge = p_low - breakeven
```

For a binary prediction-market contract at executable cost `c`:

```text
edge = p_low - c
```

Before calculating binary EV, confirm:

```text
contract_question | game_id | settlement_clock | overtime_included | market_type | threshold | yes_ask | no_ask | liquidity | cancellation_rule
```

Mapping rules:

- Moneyline contracts require win probability for the exact settlement clock, including whether overtime counts.
- Spread contracts require cover probability at the exact listed threshold.
- Total contracts require over/under probability at the exact listed number.
- Series, tournament, or group/result contracts cannot be used as single-game spread evidence except as public-attention context.
- Do not synthesize a portfolio unless every leg has the same settlement clock and a payoff table by score/margin bucket.

Minimum edge buffers before any Kelly > 0:

```text
market_context | minimum_edge_buffer
liquid NBA/WNBA spread or moneyline | 0.02-0.03
liquid NBA/WNBA total or team total | 0.03-0.04
NCAAB/FIBA/CBA regular market | 0.04-0.06
preseason/summer/youth/thin international | 0.08-0.12
binary exchange/prediction market, liquid | 0.06-0.08
binary exchange/prediction market, thin/wide | 0.10-0.15
```

If `edge < minimum_edge_buffer`, set `kelly = 0` even when the midpoint projection likes the side. If the available line is worse than the playable line or above the stated max entry, set `kelly = 0`.

Use `p_low`, not the midpoint. Apply haircuts for:

- missing current injury/lineup status;
- single-book or snippet-only odds;
- no opening or closing line;
- low-liquidity league;
- wide binary bid/ask spread;
- conflicting public roster/news reports;
- high garbage-time or overtime sensitivity.

## Prediction Tiers

Every pre-game or daily-dashboard row must have a tier:

```text
Tier A: executable real bet
Tier B: first-write paper simulation
Tier C: watchlist / live-only
Tier D: scoreboard / post-match coverage
```

Settlement treatment:

- Tier A can count in `real_money` only if the trigger fired before tipoff, the exact executable line and price were recorded, and Kelly was greater than zero.
- Tier B can count only in `first_write_paper` when the original side, line, price, timestamp, and trigger condition were recorded before tipoff.
- Tier C does not count as a pick unless a later pre-tip update promotes it to Tier A or Tier B with exact price fields.
- Tier D never counts as a prediction. It is coverage, score, or post-match review.

Do not promote a lower tier after the game starts or after the result is known.

## Bettable Status Mapping

Use `tier` to describe data quality and `bet_status` to describe actionability. They are related but not identical.

```text
bet_status | allowed tier | count_bucket | action rule
可投-主单 | Tier A only | real_money only if trigger fires | all hard gates pass and defensive Kelly > 0
可投-小仓限价 | Tier A only | real_money only if limit trigger fires | edge exists but price/liquidity/news risk requires max_entry discipline and capped stake
纸面模拟 | Tier B only | first_write_paper | exact pre-tip side, line, price, timestamp, and trigger are stored, but evidence is incomplete
临场观察 | Tier C only | no-action | wait for lineup, price, live pace, or line-back trigger
不可投 | Tier C/D or failed gate | no-action/coverage | any hard blocker fails or edge is below buffer
```

Hard blockers set Kelly to zero and force `不可投` unless fixed before tipoff: no exact line/price, game already live at first capture, ambiguous team or score order, scoreboard-only source, stale/off-date odds, missing late-news injury/lineup context, missing opening-current-closing/`终盘待回填` path, `p_low` edge below buffer, price worse than `max_entry`, unclear exchange settlement, or low-liquidity single-snippet CBA/summer/preseason evidence.

Dashboard and ledger rows should carry:

```text
match | market | selection | line_price | tier | bet_status | pass_fail_gates | p_low | breakeven | edge | min_buffer | max_entry | kelly | stake_cap | count_bucket | reason
```

## Spread Sign Convention

Store spread as the home-team spread:

- Home favorite by 4.5: `home_spread = -4.5`.
- Home underdog by 6.5: `home_spread = +6.5`.

Expected home margin is approximately:

```text
expected_home_margin = -home_spread
```

For CLV:

```text
home_spread_pick_clv = entry_home_spread - closing_home_spread
away_spread_pick_clv = closing_home_spread - entry_home_spread
over_clv = closing_total - entry_total
under_clv = entry_total - closing_total
```

Positive CLV means the pick beat the close. Example: bought home `-4.5`, close is home `-5.5`, CLV is `+1.0`.

## Spread Settlement

Let `margin = home_score - away_score`.

Home spread settlement:

```text
adjusted = margin + home_spread
home covers if adjusted > 0
push if adjusted == 0
home loses if adjusted < 0
```

Away spread settlement is the opposite side of the same adjusted margin.

Basketball spreads usually use half-points, but whole-number spreads can push. Do not ignore push probability when the line is an integer.

## Total Settlement

Let `points = home_score + away_score`.

```text
over wins if points > total
under wins if points < total
push if points == total
```

Team-total settlement follows the same rule using one team's score.

## Probability Approximation

When only a projected margin and market spread are available, approximate cover probability with a normal margin distribution:

```text
cover_prob_home = 1 - CDF((spread_threshold - projected_margin) / sigma)
```

Simpler implementation with home spread:

```text
home_covers if margin + home_spread > 0
z = (-home_spread - projected_margin) / sigma
P(home_cover) = 1 - CDF(z)
```

Default full-game margin sigma ranges:

- NBA: `11-13`.
- WNBA: `10-12`.
- NCAAB: `12-15`.
- CBA/EuroLeague/other: start `11-14`, then calibrate by league.

Totals sigma default ranges:

- NBA/WNBA: `15-18`.
- NCAAB: `16-22`.
- Lower-liquidity leagues: use wider ranges until calibrated.

This is an approximation, not a replacement for injury, pace, and market-path analysis.

## Basketball Margin Buckets

For every meaningful spread, describe the cover distribution around the traded line. Do not use moneyline probability as cover probability.

Standard buckets:

```text
favorite by 0-3
favorite by 4-6
favorite by 7-9
favorite by 10-14
favorite by 15+
garbage-time backdoor
```

For deep FIBA, youth, preseason, summer league, or heavy-mismatch games:

```text
favorite by 0-9
favorite by 10-19
favorite by 20-29
favorite by 30+
bench-minute uncertainty
favorite-coasting risk
underdog late-foul/backdoor risk
```

Guidelines:

- A huge ML edge supports winner probability, not necessarily `-20` or deeper cover value.
- If the favorite has tournament margin incentive, defensive pressure, bench scoring, and the underdog must chase, raise blowout buckets.
- If the favorite can win while managing minutes, or if the underdog can score late against bench units, raise backdoor buckets.
- If the exact traded threshold sits between two buckets, prefer the market with better protection or pass.

## Basketball Total Projection

A quick full-game total prior can be framed as:

```text
projected_possessions = blend(team_a_pace, team_b_pace, league_average, matchup_adjustments)
team_a_points = projected_possessions * adjusted_team_a_points_per_possession
team_b_points = projected_possessions * adjusted_team_b_points_per_possession
projected_total = team_a_points + team_b_points
```

Adjust for:

- Injury impact on usage, spacing, rim pressure, ballhandling, defense, and pace.
- Back-to-back fatigue, travel, and altitude.
- Foul/whistle and free-throw profile.
- Offensive rebounding and transition defense.
- Blowout and garbage-time pace.
- Tournament motivation and playoff rotation tightening.

If the projected total is close to market, prefer live confirmation rather than forcing a pre-game total.

## Line Movement Interpretation

Classify every spread and total move with both magnitude and story:

```text
line_delta = current_line - opening_line
close_delta = closing_line - opening_line
price_delta = current_price - opening_price
```

For home spreads, a move from `-4.5` to `-6.0` is a `-1.5` line change but a `+1.5` move toward the home team in expected margin. Use both labels to avoid sign mistakes.

Minimum basketball interpretation labels:

- `真实示强`: line, ML, injury/rest, and matchup confirm one side.
- `真实示弱`: line and fundamentals both downgrade one side.
- `降温保护`: bad news or public fear lowers threshold but the side remains live.
- `诱上`: favorite/giving side looks too easy without confirmation.
- `诱下`: dog/receiving side looks too safe despite mismatch or market resistance.
- `价格已透支`: direction is right but current line has consumed the edge.
- `等待临场`: injury, lineup, or closing-line uncertainty is too large.

## Intent Direction Settlement

Use this layer to answer whether the market-intent read should be followed (`正向`) or faded (`反向`).

Definitions:

- `上盘`: the favorite/giving side on the spread.
- `下盘`: the underdog/receiving side on the spread.
- `正向`: buy the side implied by the current intent diagnosis.
- `反向`: buy the opposite side.

Intent labels are not automatic bets. Map every label to a team and side before settlement:

```text
match | spread_line | upper_team | lower_team | intent_tag | forward_team | reverse_team
```

Common starting mappings:

- `诱上`: forward side is usually `下盘`; the favorite is too easy/public-friendly.
- `诱下`: forward side is usually `上盘`; the dog looks too safe despite weak evidence.
- `阻上`: forward side is often `上盘` when ML/fundamentals confirm; otherwise pass.
- `阻下`: forward side depends on context. If paired with `诱上`, it often points to `下盘`; if paired with `上盘保护`, it points to `上盘`.
- `降温保护`: forward side is the cooled side only if lineup and ML confirm that the threshold cut improved entry.
- `价格已透支`: no forward bet unless the line moves back into the playable zone.

For each settled spread, calculate both paths with the same stake and line:

```text
forward_result = settle(forward_team, forward_line, final_score)
reverse_result = settle(reverse_team, reverse_line, final_score)
forward_pnl = flat_stake_pnl(forward_result, price)
reverse_pnl = flat_stake_pnl(reverse_result, reverse_price)
```

Dashboard summaries must show:

```text
line_bucket | intent_tag | n | forward_hit_rate | forward_pnl | reverse_hit_rate | reverse_pnl | current_better_direction
```

Show these columns only from a verified historical ledger. If no historical ledger exists, write `历史样本库未建立` and store only case-level settlement such as `本场复盘：正向命中/反向未命中`. Do not display fake sample sizes, hit rates, or unit PnL. If sample size is below the configured threshold, mark the row as `观察样本`. If reverse PnL is better than forward PnL with enough sample size, mark the tag as `反向验证`; if forward PnL is better, mark `正向有效`. If no exact line bucket exists, do not borrow another bucket.

### Immutable First-Write Ledger

Hit-rate math must be based on the first pre-game record for each `match_id + market`. Do not recompute an original side from later scores, closing lines, or `Intent corrected` notes.

Required buckets:

```text
real_money: rows with executable price, triggered entry, positive edge, and kelly > 0
first_write_paper: first pre-game paper/observation thesis rows with a concrete original side and line
post_match_revision: settlement or correction rows written after the result or after new information
```

Only `real_money` is a real win rate. If a first-write row has `no bet`, `wait for re-audit`, `trigger not met`, `limit-only`, or `Kelly=0`, it is `no-action` for real-money settlement. It may be counted in `first_write_paper` only when the audit explicitly states that paper theses are being measured separately.

## Post-Match Process Grade

Grade process separately from result:

- `A`: beat closing line, evidence chain was complete, result path matched scenario or variance was acceptable.
- `B`: beat or matched closing line, one evidence field was weak, no structural error.
- `C`: result may hit, but entry price was fair/expensive or evidence incomplete.
- `D`: lost to closing line, missed obvious injury/rest/news, or forced a pick without market price.
- `No grade`: canceled/postponed/no verified score/no verified closing line.

Use `retain / correct / new rule` after each review. Do not create a new rule from one noisy overtime, buzzer-beater, or garbage-time cover.
