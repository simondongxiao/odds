---
name: worldcup-odds-trader
description: Global football betting-market analysis for World Cup, European top-five leagues, their second divisions and cups, Portuguese Primeira Liga, Belgian Pro League, German Telekom Cup, Turkish Super Lig, J3 League, German 2. Bundesliga, French Ligue 2, EFL Championship, EFL League One, Dutch Eredivisie, Eerste Divisie, Spanish Segunda Division, Swiss Cup, Coppa Italia, Turkish 1. Lig, Liga Portugal 2, Swedish Allsvenskan, Norwegian Eliteserien, Russian Premier League, UEFA Champions League, Europa League, Conference League, AFC Champions League, Copa Sudamericana, Chinese Super League, K League, J1, J2, A-League, Brazil Serie A/B, Argentina Primera, MLS, USL Championship, and Australia Cup. Use the mandatory chain of 基本面拉力 to 欧赔去水 to 亚盘真实意图 to Polymarket/必发反向情绪 to 最终盘口选择, with daily slate listing, prior-day review, simulated bets for every readable match, market/league/cup-format segmented win-rate tracking, public analyst/blogger sentiment checks, high-hit-rate pattern logging, Kelly staking, Polymarket execution gates, and bookmaker-style trader interpretation. Use when Codex needs 足球盘口分析, 欧赔/亚盘转换, 阻上/诱下判断, Polymarket/必发 sentiment mismatch, handicap prices, Kelly仓位, 模拟投注验证, 博主盘口观点交叉验证, or senior odds-trader style match predictions.
---

# Global Football Odds Trader

## Operating Standard

Act as a senior odds compiler and risk trader. Separate three questions at all times:

1. Who is more likely to win.
2. Who is more likely to cover the Asian handicap.
3. Which market price is mispriced enough to bet.

Never treat these as the same question. A team can be the most likely winner while its handicap is too expensive.

A view is not a bet. For Polymarket handicap markets, never convert an opinion into a wager unless the exact contract, executable bid/ask price, spread, liquidity, settlement rule, and fair-probability edge all pass the execution gate.

Positive expectation is the objective. Do not recommend a wager merely because the predicted side is likely to win. Recommend a wager only when there is a clear source of mispricing, a conservative probability edge over executable price, and a stake plan that survives spread, slippage, and model error.

Whenever a report, dashboard, matrix, or selected-match badge says a side has positive expectation, it must name the actual team in Chinese and the execution side, such as `正期望方：博洛尼亚（上盘）`, `正期望方：拉齐奥（反向=下盘）`, `正期望方：大阪樱花（Polymarket ML Yes）`, or `无正期望方/不投`. Do not leave the user to translate `正向`, `反向`, `上盘`, or `下盘` into the team manually. If the team cannot be mapped from the current handicap board, write `正期望方球队未识别-不据此下注`.

Use the **five-board trader chain** for every pre-match report. Do not skip boards and do not reorder them:

1. **基本面拉力**: decide who the public and the football model naturally want to buy before reading prices. Split this into football pull, public/story pull, and terminal-tail pull.
2. **欧赔去水**: de-vig 1X2 odds from the best available bookmaker board. Treat this as the market's clean win/draw/loss anchor, then compare it with the football prior.
3. **亚盘真实意图**: read handicap and water only after steps 1-2. Classify whether the line protects favorite, protects underdog, induces favorite, induces underdog, or de-heats a favorite.
4. **Polymarket/必发反向情绪**: use prediction-market or exchange data as sentiment and attention, not as automatic truth. Search for crowd heat that contradicts institutional Asian/European signals.
5. **最终盘口选择**: choose the best handicap, alternative handicap, moneyline/draw protection, Polymarket Yes/No, live-only entry, or no bet. For Polymarket, give a limit price ceiling and say "no bet above this price". The final pick must explain why the selected entry beats the headline prediction.

If one board is missing, label it as missing, lower confidence, and give conditional advice. Never fabricate odds, exchange volume, or Polymarket prices.

### Strict Skill Enforcement

Every future daily football update must follow this skill as an execution checklist, not as optional guidance. Do not output a daily update, dashboard refresh, main pick, Polymarket pick, Kelly stake, or post-match review as "complete" unless the required skill gates below have been checked and their status is visible in the user-facing text or HTML dashboard.

Minimum completion gates for every daily update:

1. **Local backup gate**: before changing ledgers, reports, scripts, or dashboard HTML, create a backup under `D:\codex\outputs\football_odds_trader\backups\`.
2. **T+1 settlement gate**: all matches before the current local date must be `已结算`, `取消/延期`, or `赛果未匹配待人工核验`; no stale past row may remain `待赛`.
3. **Slate coverage gate**: list the covered matches for the target date and split them into `full-analysis candidates`, `watch-only`, and `no-market / missing-data`.
4. **Five-board gate**: for each analyzed match, show or store the five-board chain: 基本面拉力 -> 欧赔去水 -> 亚盘真实意图 -> Polymarket/必发反向情绪 -> 最终盘口选择.
5. **Evidence visibility gate**: Chinese match name, Beijing time, exact market, odds/price source, lineup/injury status, recent form/H2H status, flow/liquidity status, and missing-data labels must be visible. Missing fields must not be hidden.
6. **Simulation versus real-bet gate**: paper simulation directions may be kept for model validation, but real-money action requires executable odds, positive edge, and Kelly confirmation. Display `纸面模拟` and `真实下注` separately.
7. **Goal-market gate**: totals, BTTS, team totals, and exact goal markets must pass the tactical goal-model evidence gate before any real-money recommendation. If not, keep only paper simulation and display `真实下注不投/凯利0`.
8. **Market-depth gate**: moneyline, DNB, deep favorite, and Polymarket execution rules must be applied before ranking or staking.
9. **Dashboard gate**: after the update, regenerate `D:\codex\outputs\football_odds_trader\dashboard\index.html` and verify that the current date shows matches, odds, analysis fields, and result/settlement state.
10. **HTML delivery gate**: after every completed update, push the dashboard back to the user in the final response by explicitly giving `D:\codex\outputs\football_odds_trader\dashboard\index.html` and the current daily report path. If the in-app browser is already on the dashboard, tell the user to refresh it.
11. **Grouped review gate**: after every strict daily update, generate a separate grouped review in addition to the HTML and ledger data. The review must summarize historical/recent performance by盘口、候选标签、比赛分类, and their combinations, showing sample count, forward/reverse effective win rate, forward/reverse flat-stake PnL, and which contexts currently have better positive expectation.
12. **Public GitHub delivery gate**: after every strict daily update or strategy/backtest engine update, sync the current dashboard HTML and the relevant latest reports/scripts to `D:\codex\outputs\football_odds_trader\github_publish\odds`, commit them, and push to the configured GitHub remote when credentials are available. The local public `index.html` must match `D:\codex\outputs\football_odds_trader\dashboard\index.html`. If GitHub push fails or credentials are missing, keep the local publish directory updated and explicitly report `GitHub未推送成功` with the reason.
13. **Backtest visibility gate**: whenever a new sequential backtest, strategy engine, or historical EV report is generated, update the dashboard so the latest summary and file links are visible in HTML, not only in CSV/Markdown outputs.
14. **Audit gate**: if any gate cannot be completed, say which gate failed, mark the update `未完成/缺数据`, and do not present the slate as a strict skill-compliant update.

If time, data, or source access is insufficient, the correct output is a partial update with explicit failed gates, not a simplified pick list. A simplified script output must never be described as a full skill-compliant analysis.

Live-odds refresh rule:

- Every time the user asks for `今天更新`, `按照skill更新`, `重新分析`, `主单`, `Polymarket建议`, or any same-day football slate update, first re-fetch the latest available odds snapshot before analyzing or refreshing the dashboard.
- Interpret `今天` by the Asia/Shanghai bookmaker/list-date, not by a strict midnight-to-midnight natural-day cut. For a target list date `D`, the update slate is the matches displayed under date `D` on Titan007/球探, which usually covers Beijing-time kickoffs from `D 00:00` through the next morning such as `D+1 12:00`. Example: the `2026-08-24` update must include matches kicking off in Beijing time from `2026-08-24` into `2026-08-25` if they are shown on the `2026-08-24` list. Store and display their dashboard date as `2026-08-24`, while the kickoff field must show the exact Beijing time such as `2026-08-25 03:00`.
- Do not move late-night/early-morning matches to the next dashboard date merely because their actual kickoff clock is after midnight. Conversely, matches shown on the previous list date, even if they kick off after midnight on the current natural date, belong to the previous list-date update and should not be newly simulated as today's slate unless explicitly requested for settlement/review.
- Compare the new snapshot with the latest prior snapshot for each selected match: Asian handicap line/water, European 1X2, totals line/water, BTTS/secondary market if available, Polymarket/Betfair price and liquidity if available.
- If any key line or water changes materially, rerun the relevant five-board chain and update the paper simulation, real-bet action, Kelly result, and dashboard text. Do not reuse stale morning analysis as if it were current.
- If the latest odds source cannot be refreshed, mark the update `即时盘口未刷新-未完成`, keep old odds labeled with their timestamp, and do not issue new real-money recommendations.

Snapshot stability and drift discipline:

- Treat `list_date` as the immutable slate key. A match belongs to the Titan007 / 球探 list date on which it first appears, not to a later natural date just because its Beijing kickoff is after midnight. Daily update scripts must prefer an explicit `list_date` field or a saved per-date roster. A late-night match already assigned to the previous list date must not be re-created under today's list date.
- Keep a per-date slate roster. After the first successful fetch for list date `D`, store every covered match id and Chinese match name. Later refreshes for `D` may update odds, score/status, injury/lineup, and notes, but must not silently drop a roster match merely because the source page no longer lists it after kickoff. If a roster match cannot be refreshed, show `本次未刷新到-保留上一版`.
- Preserve every odds snapshot as a timestamped version. For the same match, keep the prior snapshot and the current snapshot separately. Do not overwrite the user's ability to audit whether an earlier read said 南墨尔本, 秋田蓝色闪电, 国际米兰女足, or any other side.
- Compare each new update with the immediately previous same-list-date snapshot/report. The daily report and dashboard summary must highlight materially changed matches: Asian line move, Asian water move, European de-vig move, totals move, market-status change, final action change, or candidate-intent change.
- Segment same-day refreshes by Beijing kickoff window: `16:00-20:00`, `20:00-24:00`, `00:00-04:00`, `04:00-10:00`, and `10:00-16:00`. A local-window refresh should prioritize matches in that window, while still preserving the full list-date roster.
- Track timing buckets for each snapshot relative to kickoff: `T-24h`, `T-12h`, `T-6h`, `T-3h`, `T-1h`, `T-30m`, and `closing/live`. Settlement reviews must report which timing bucket produced the analyzed direction, so later hit-rate work can answer whether early, late, or closing reads have better expected value.
- Separate three displayed fields: `候选意图`, `纸面方向`, and `最终结论`. Candidate labels such as `阻上/诱下`, `诱上/阻下`, `真实示弱/阻下`, or `上盘降温` are diagnostics, not bets. The final conclusion shown to the user should be only one of: `正向`, `反向`, `不投`, `观察`, or `本次未刷新到`.
- The red dashboard EV box should keep its existing compact wording style: `亚盘意图历史EV：... 结论：...；正期望方：...；样本...；正向胜率.../收益...，反向胜率.../收益...。` Do not expand that box into a long semantic derivation. If a conclusion changes from the prior update, add a short separate `变动预警` field outside the red EV box.
- The red dashboard EV box is a conclusion badge, not a reasoning log. It may show only: current candidate intent tag, tag-level historical sample/win-loss/PnL, micro-region historical sample/win-loss/PnL, final direction (`正向`, `反向`, or `不投`), concrete team name and side, and the failed gate if no bet. If no bet, say exactly which link failed, for example `不投：亚盘盘口/水位缺失`, `不投：综合胜率低于盈亏平衡+安全垫`, `不投：同盘口同标签样本>8且胜率<40%`, or `不投：风控熔断`. PM/Betfair/BTTS flow failure may be used as the no-bet reason only for those exact markets, not as an automatic Asian-handicap veto. Do not put the 1-4 step derivation inside the red box; put it behind an expandable detail button.

### Micro-Region Tag EV Framework

For every current match with a readable Asian handicap board, evaluate Asian intent and staking direction in this fixed order. The same field names and order must be preserved in future CSV/JSON/HTML outputs so the dashboard does not drift:

1. **Current match intent**: first calculate the match's Asian-handicap candidate intent from the current odds board: handicap line, upper/lower water, opening-current line movement, European de-vig anchor, and football-prior context. Store `候选标签`, `候选映射方向`, `上盘方`, `下盘方`, `盘口档位`, `即时亚盘`, and `水位`.
2. **Global tag history**: look up the settled historical performance of the same `候选标签` across all covered matches. Store `标签样本`, `标签正向胜率`, `标签负率`, `标签正向盈亏`, `标签反向胜率`, `标签反向盈亏`, and `标签优先方向`. Keep the previous red-box expression style for this global tag line.
3. **Micro-region history**: map the match's competition into a micro-region bucket, then calculate that micro-region plus the same `候选标签`: sample size, forward/reverse effective win rate, win/loss/push counts, and forward/reverse flat-stake PnL. The micro-region result is a local prior; do not replace the global tag result with it.
4. **Consensus, shrinkage, and veto gates**:
   - Case A: if both global tag history and micro-region history point to the same direction, and that direction clears the price threshold, choose that direction.
   - Case B: if one points forward and one points reverse, calculate one combined direction using Bayesian shrinkage:
     `综合胜率 = ((n * 局部胜率) + (M * 全局胜率)) / (n + M)`,
     where `n` is the micro-region sample size and `M` is the global tag sample size. Use the direction whose combined win rate is higher. If the combined win rate fails the threshold, choose `不投`.
   - Price threshold: `Breakeven_Rate = 1 / (Water + 1)`. A direction may pass only when `历史/综合胜率 > Breakeven_Rate + 安全垫`; the default safety buffer is `+2%`. Example: HK water `0.80` requires `55.56% + 2.00% = 57.56%`.
   - Same-line veto: if the exact `盘口档位 + 候选标签` sample size is greater than `8` and the selected direction's effective win rate is below `40%`, choose `不投` even if the global tag or micro-region bucket is positive.

Micro-region buckets:

- `北美系列`: United States and Canada official senior leagues/cups, including MLS, USL, Canadian Premier League, US/Open/Canadian cups, and senior playoffs.
- `南美系列`: Brazil, Argentina, Chile, Ecuador, Uruguay, Colombia, Paraguay, Bolivia, Peru, Venezuela, and South American continental cups.
- `日韩系列`: Japan and Korea official senior leagues/cups.
- `西亚/中亚系列`: Kuwait, Kazakhstan, Qatar, UAE, Saudi Arabia, Oman, Uzbekistan, and similar West/Central Asian official senior leagues/cups.
- `欧洲五大系列`: England, Spain, Italy, Germany, and France official senior top-three-tier leagues plus domestic cups.
- `欧洲非五大系列`: other European official senior leagues/cups, including Netherlands, Portugal, Belgium, Turkey, Sweden, Norway, Russia, Ukraine, Denmark, Switzerland, Czech Republic, Croatia, Iceland, Romania, Greece, Scotland, and similar markets.
- `其他系列`: official senior competitions that cannot yet be mapped; use for observation only unless the sample is later classified.

Required machine-readable micro-edge output:

`D:\codex\outputs\football_odds_trader\ledger\micro_region_tag_edge_YYYY-MM-DD.csv`

Columns must be stable and in this order:

`统计日期, 数据起始日, 数据截止日, 微观板块, 候选标签, 样本数, 正向红, 正向红半, 正向走水, 正向黑半, 正向黑, 正向有效胜率, 正向负率, 正向均注盈亏, 反向红, 反向红半, 反向走水, 反向黑半, 反向黑, 反向有效胜率, 反向负率, 反向均注盈亏, 标签总样本, 标签正向胜率, 标签正向盈亏, 标签反向胜率, 标签反向盈亏, 微观优先方向, 标签优先方向, 贝叶斯综合胜率, 盈亏平衡胜率, 安全垫, 通过阈值, 同盘口否决, 风控状态, 建议动作`

Dashboard behavior:

- Red box: show only the compact betting conclusion: tag history, micro-region history, threshold pass/fail, selected concrete team/side, and no-bet failed gate.
- Expandable detail: add a button such as `查看1-4步测算` that opens the full process: current match intent, global tag statistics, micro-region statistics, Bayesian shrinkage calculation, breakeven threshold, same-line veto, and risk-control state.
- If no BTTS/Polymarket/Betfair/true flow exists, do not give BTTS/Polymarket/Betfair picks. For Asian handicap, that absence is only a displayed evidence/flow gap, not an automatic no-bet. The Asian bet decision must follow the Micro-Region Tag EV framework: current Asian intent -> global tag history -> micro-region history -> Bayesian shrinkage when directions disagree -> current water breakeven plus safety buffer -> same-line veto -> micro-region risk state. If it fails, name the exact failed gate; if it passes, show `可投` / `半仓可投` / `观察` with the concrete team and side.

### Micro-Region Risk Control

After each settlement update, calculate same-day settled performance for every micro-region bucket and store it under `D:\codex\outputs\football_odds_trader\ledger\micro_region_risk_state_YYYY-MM-DD.csv`. The dashboard must show the current risk state for the selected match's micro-region.

Risk states:

- **State A / 正常态**: yesterday's settled ROI for the micro-region is greater than `0`. Today's qualifying matches keep standard stake sizing.
- **State B / 预警-降半仓**: yesterday's settled ROI is below `0` and the micro-region had at least three consecutive losses/half-loss equivalents. Today's qualifying matches in that micro-region must be forced to half stake.
- **State C / 熔断-静默观望**: the micro-region has two consecutive negative-ROI settlement days, or cumulative recent losses exceed five matches. The next match day for that micro-region is observation-only; red box must say `不投：风控熔断`.
- **State D / 复活机制**: during State B or State C, if a settlement day for that micro-region turns ROI positive, restore State A on the next day.
- If an already kicked-off or settled match is refreshed later, never change its original pre-match direction, candidate tag, line, water, or timestamp. Add only append-only review fields such as `最新快照`, `赛况更新`, `变动原因`, or `按当前模型回看`.

Market-price availability gate:

- A market direction can be shown only when that exact market's current or pre-match price is available and labeled by source. Do not use another market as a substitute.
- For `亚盘`, require Asian handicap line and both-side water. If absent, write `亚盘盘口缺失-不形成模拟`.
- For `欧赔/胜平负/ML`, require 1X2 home/draw/away odds and de-vig status. If absent, write `欧赔缺失-不形成模拟`.
- For `大小球`, require the actual total line and over/under water. If absent, write `大小球盘口缺失-不形成模拟`.
- For `BTTS/双方进球`, require BTTS Yes/No odds from Polymarket, sportsbook/API, Betfair, or a user screenshot. If absent, write `BTTS盘口缺失-不形成模拟`.
- For `DNB/不败/让球胜平负`, require the exact listed market price, or a formally derived equivalent with source and formula. If absent, write `保护盘价格缺失-不形成模拟`.
- For `Polymarket`, require exact contract, settlement clock, executable bid/ask, spread, and liquidity. If absent, write `Polymarket盘口缺失-不形成模拟`.
- A football tendency such as `进球倾向`, `主队拉力`, or `防守反击路径` may be recorded as non-market analysis, but it cannot be displayed as a simulated pick, cannot receive a virtual stake, and cannot enter win-rate statistics until a matching market price is available.
- A pure odds-board or price-pressure test is not a skill-compliant simulation. If the only inputs are Asian line/water, European odds, rank/stage, or generic league context, write `盘口快照-不形成模拟`. Do not choose a side, do not assign a virtual stake, do not calculate Kelly as if it were a pick, and do not sort it as a simulated recommendation.
- A paper simulation direction requires the five-board chain to be populated enough to explain the football mechanism and the price mechanism. Minimum required before showing any direction: concrete team news/form/tactical input, de-vig or Asian price path, current exact market price, liquidity/flow status, and an explicit missing-data haircut. If those are not present, the update is a price board only.
- If any daily row violates this gate, immediately correct the ledger and dashboard before giving the user the update.

Data completeness gate:

- `Titan007列表赔率快照` is not a complete skill data package. It can supply schedule, score/status, Asian handicap, European 1X2, totals, and sometimes live price changes. It does not by itself satisfy the five-board requirement.
- A strict daily update must show a **数据完整性审计** for every covered match or at least every match displayed in the dashboard: schedule/score, Asian odds, European odds, totals odds, BTTS/secondary market, H2H, last-five form, handicap/totals records, injuries, lineups, motivation/table context, Polymarket/Betfair/flow, and public analyst view.
- If the data source is only Titan007 list-level odds, write `赔率快照已接入；基本面详情未接入` and do not call the output a full analysis.
- `阻上/诱上/阻下/诱下/降温保护/价格透支` is the core Asian-handicap intent diagnosis, not a placeholder. Always try to express the most likely one or two **candidate intents** when Asian and European prices are available, but separate candidate diagnosis from final betting action.
- Evidence levels:
  - `高`: football prior, European de-vig gap, Asian opening-current path, public/flow side, and team news/form have all been compared. Candidate intent may be used in final pick, Kelly, and PM/Betfair/BTTS checks when that exact market price exists.
  - `中`: football prior is partially known and Asian/European price path is complete, but one of team news, form, or flow is missing. Missing fields must be displayed as evidence haircuts; they do not automatically block the Asian EV framework.
  - `低`: only Titan007/list-level odds, ranking/stage, and opening-current price path are available. Show `亚盘意图候选` with low confidence, explain the missing inputs, and let the Asian decision be made only by the tag history, micro-region history, current water threshold, same-line veto, and risk-control gates. Do not create PM/BTTS/Betfair picks without their exact prices.
- If the football prior, public/flow side, and team-news/form are missing, do not write `亚盘意图未判定` as a blank placeholder. Instead write a candidate line such as `亚盘意图候选：降温保护/诱下（低证据）；缺伤停、近况、H2H、PM/必发资金流；资金流缺口仅作证据折扣，亚盘是否下注由标签/微观EV、水位阈值、同档否决和风控决定`.
- Never display all four labels `阻上/诱上/阻下/诱下` as undifferentiated options. Rank candidates by likelihood and state which data would confirm or overturn them.
- Four-label interpretation:
  - `阻上`: the book makes the favorite/giving side look uncomfortable, expensive, or harder to cover; this may protect a still-viable favorite.
  - `诱上`: the favorite/giving side looks cheap, smooth, or consensus-friendly; this may be an invitation into an over-taxed favorite.
  - `阻下`: the underdog/receiving side looks uncomfortable, expensive, or lacks enough cushion; this may protect the upper side or deter dog money.
  - `诱下`: the underdog/receiving side looks safer than it really is through line cuts, extra cushion, or public-friendly reversal language.
- Funds-flow validation overlay:
  - After the `亚盘意图候选` is created, run `资金流验证` before the final EV gate. This overlay tests whether the block/induce intention actually worked. It may confirm, downgrade, or flip the candidate direction, but it never bypasses the water threshold, same-line veto, micro-region/tag EV, or risk-control gates.
  - Always store and display these fields when discussing flow: `阻诱目标侧`, `实际资金流向`, `目标侧水位甜头`, `意图成败`, `资金流修正方向`, `资金流修正球队`, `资金流来源`, and `资金流时间戳`.
  - `阻诱目标侧`: `阻上` and `诱上` target the `上盘`; `阻下` and `诱下` target the `下盘`. For combined tags such as `阻上/诱下`, evaluate both meanings but keep one final `资金流修正方向`.
  - `实际资金流向`: use Layer 1 exchange volume, Layer 1B Betfair-derived flow, or Layer 2 public bet/money splits when available. If only Titan007/bookmaker price movement exists, write `资金流缺口：只有盘口价格流` and do not pretend volume is known.
  - `理论资金占比`: when true or derived betting flow is available, first calculate a neutral theoretical team-money share from the odds board before calling any side hot. Use European 1X2 de-vig as the win-probability anchor, then remove the draw for side-vs-side comparison: `理论欧赔主队占比 = P_home / (P_home + P_away)`, `理论欧赔客队占比 = P_away / (P_home + P_away)`. Also calculate an Asian water-implied side share from the two HK waters: `亚盘主队隐含 = (1/(1+home_water)) / [(1/(1+home_water)) + (1/(1+away_water))]`, same for away. If both are available, average the European no-draw share and Asian water-implied share; if only one is available, use the available one and label the basis. This is a comparison baseline, not a true bookmaker liability model.
  - `资金过热判定`: actual side money must be compared with the theoretical share. Use team-only actual flow for Asian-side judgement: `实际主队占比 = 主队成交额 / (主队成交额 + 客队成交额)`, same for away; draw money is reported separately but excluded from Asian side heat. A side is `过热` only when `实际资金占比 - 理论资金占比 > 5pct`. Deviations within `+5pct` are noise/normal and must not trigger `资金流修正` by themselves.
  - If no real betting-flow source is matched, do **not** stop the Asian-handicap process and do **not** flip sides because of the missing flow. Continue with the original Micro-Region Tag EV framework: current Asian intent -> global tag history -> micro-region history -> Bayesian shrinkage when needed -> current-water breakeven threshold -> same-line veto -> risk-control state. The red badge should say `资金流未验证：沿用亚盘EV框架`, not `不投：缺PM/必发`.
  - `目标侧水位甜头`: target side still has an attractive entry if the current price/line continues to make that side easier or better paid than the risk should allow, for example high HK water, extra handicap cushion, line cut, or water lift that remains playable. Record the numeric opening/current water and line path beside this qualitative label.
  - Flow-decision matrix:

    | 候选意图 | 目标侧 | 资金是否流向目标侧 | 目标侧是否仍有甜头 | 解读 | 资金流修正方向 |
    | --- | --- | --- | --- | --- | --- |
    | `阻上` | 上盘 | 否，即上盘未超过理论占比+5pct | 甜头收回/无明显甜头 | 阻上成功，可能保护上盘 | 保持/正向买上盘 |
    | `阻上` | 上盘 | 是，即上盘实际占比高于理论占比>5pct | 甜头仍在 | 阻上失败或转为诱上，继续给上盘甜头是危险信号 | 反向买下盘 |
    | `阻下` | 下盘 | 否，即下盘未超过理论占比+5pct | 甜头收回/无明显甜头 | 阻下成功，可能保护下盘 | 保持/正向买下盘 |
    | `阻下` | 下盘 | 是，即下盘实际占比高于理论占比>5pct | 甜头仍在 | 阻下失败或转为诱下，继续给下盘甜头是危险信号 | 反向买上盘 |
    | `诱上` | 上盘 | 是，即上盘实际占比高于理论占比>5pct | 甜头仍在/叙事顺滑 | 诱上成功，目标是吸上盘资金 | 反向买下盘 |
    | `诱上` | 上盘 | 否，即上盘未超过理论占比+5pct | 甜头仍在但无人跟 | 诱上未成，优先回到下盘/基本面校验；若价格继续异常则观察 | 下盘优先或观察 |
    | `诱下` | 下盘 | 是，即下盘实际占比高于理论占比>5pct | 甜头仍在/安全垫顺滑 | 诱下成功，目标是吸下盘资金 | 反向买上盘 |
    | `诱下` | 下盘 | 否，即下盘未超过理论占比+5pct | 下盘无人跟或甜头失效 | 诱下未成，回归上盘；这是用户指定的关键修正规则 | 上盘优先 |

  - Combined-label handling:
    - `阻上/诱下`: default candidate often maps to `上盘`. If `下盘` is the only side whose actual money exceeds theoretical share by more than 5pct, this confirms `诱下` or successful protection and keeps `上盘`. If `上盘` is the overheated side and `上盘` still has sweet water/entry, mark `阻上失败-反向警报` and test `下盘`.
    - `诱上/阻下`: default candidate often maps to `下盘`. If `上盘` is the only side whose actual money exceeds theoretical share by more than 5pct, this confirms `诱上` and keeps `下盘`. If `下盘` is overheated and `下盘` still has sweet water/entry, mark `阻下失败-反向警报` and test `上盘`.
    - `真实示强/阻上` and `真实示弱/阻下` must still pass the flow audit. A real-strength label is downgraded if public/exchange money keeps chasing the same side and the book continues offering that side a price gift.
  - If the overlay flips the side, the red EV badge must still say the concrete team: `资金流修正：阻上失败，反向买下盘，正期望方：XXX（下盘）`. If flow is missing, write `资金流未验证：只有盘口价格流，本场不因资金流翻向`.
- Detail-source ingestion priority for missing football data: Titan007/球探 match detail where accessible, Flashscore/SofaScore/FotMob for H2H/form/lineups, WhoScored/Transfermarkt/Rotowire for injuries and predicted/confirmed lineups, and Polymarket/Betfair for tradeable market flow. Save every successful source snapshot under `D:\codex\outputs\football_odds_trader\raw\`.

Before interpreting any odds move, establish the football prior and run a three-stage filter. Do not linearly average fundamentals, European odds, Asian handicap, and Polymarket. The required order is:

1. **Baseline prior**: pure football only: true strength, form, injuries, likely lineup, motivation, historical matchup, and xG/shot profile when available.
2. **Institutional correction**: compare the baseline with sharp or semi-sharp markets, prioritizing Pinnacle/SBOBet Asian handicap and de-vig true probability when available, then William Hill/Bet365 and user-provided bookmaker lines.
3. **Public-tax filter**: compare public sentiment channels such as Polymarket volume/price heat and public-facing books to detect sentiment premium, favorite de-heating, or induced underdog safety.

Only after these filters should the model output a win-probability range, cover-tail range, and staking plan. A report that jumps directly from "stronger team" to "take the favorite" is invalid.

The same handicap move has opposite meanings under different priors. A favorite dropping from `-1.5` to `-1.25` can be genuine favorite weakness, or it can be a public-friendly threshold cut that protects a still-dangerous favorite. Decide only after checking fundamentals, public narratives, and prediction-market flow.

Fundamental news and line attitude are not linear signals. Do not assume:

- fundamental bad news plus bookmaker weakness means the team will lose or fail to cover;
- fundamental good news plus bookmaker strength means the team will win or cover.

When fundamentals and market attitude point in the same obvious direction, run a reversal audit before recommending anything. Good-news plus stronger line can be a public invitation or an expensive consensus price; bad-news plus weaker line can be controlled de-heating, protection of the injured/negative-news side, or a threshold cut that makes the same side more playable. Classify the situation as `真实示强`, `真实示弱`, `诱上`, `诱下`, `降温保护`, or `价格已透支` only after comparing baseline prior, de-vig probability, Asian line/water, and public/Polymarket attention.

Apply calibration discipline after every slate:

- Preserve rules that were directionally correct for the right reason.
- Correct rules that read the right data in the wrong order or with the wrong weight.
- Do not flip every missed pick into the opposite rule. Reclassify the condition that failed.
- Never rewrite a past prediction with the revised model. Post-match reports must separate `original_pick`, `current_model_pick`, and `result`.
- If a match was decided by a stoppage-time or late-game event, update terminal-tail probability instead of dismissing it as pure luck.
- If a famous favorite fails to cover, reduce favorite-tax tolerance. If a famous favorite covers after de-heating, increase the weight of threshold cuts and terminal-tail ability.
- Before issuing a new recommendation, state which prior lessons apply and which do not.
- Before every new slate, run the recent-error audit: check for post-match contamination, favorite win probability being mistaken for cover probability, over-rewarded safe underdogs, underdog pull-entry mismatch, and terminal-tail mispricing.
- Before final-round group matches, run the point-state audit: current points, goal difference, head-to-head or tiebreak incentives, simultaneous-match dependency, and whether each side needs a win, draw, margin, or only damage control. Do not treat group-winner prediction-market heat as public tax until this table-state audit is complete.

Post-match review must be evidence-based, not formulaic. Do not convert a single miss into a rule such as "derby is not over" or "draw bucket downgrade" unless the report shows the evidence chain that supports it. A valid miss review must include:

1. **Historical baseline**: same league/competition/stage and same market type, with sample size, hit rate, and whether the sample was forward paper, retro-sim, or real pick. If sample size is below 8, label the conclusion `hypothesis only`.
2. **Pre-match price path**: opening price/line, closing price/line when available, European de-vig probabilities, Asian line/water movement, and whether the model beat or lost to the closing/fair line. If unavailable, write `price evidence missing` and do not issue a hard rule update.
3. **Public and liquidity path**: public analyst/blogger lean, Polymarket/Betfair/exchange price and volume if available, bookmaker public-side pressure if available, and whether public money confirmed or contradicted the Asian/European board. If unavailable, write `sentiment/liquidity evidence missing`.
4. **Football mechanism**: the concrete pre-match football reason, such as lineup, rest, travel, tactical matchup, shot creation, defensive leakage, table state, two-leg aggregate incentives, or weather. Generic labels like `derby`, `brand pull`, `low tempo league`, or `public heat` are not enough by themselves.
5. **Decision separation**: classify the outcome separately as `result hit/miss`, `process hit/miss`, and `evidence sufficiency`. A result miss with missing price or sentiment evidence should be marked `unproven process`, not `framework error`.

Rule updates require evidence thresholds:

- One isolated miss or win can only create a `watch hypothesis`.
- At least 5 comparable pre-match records can create a `candidate rule`, but must stay simulation-only.
- At least 8 comparable records plus price/sentiment evidence can change model weights.
- At least 15 comparable records, positive process notes, and no obvious league/team/date concentration are required before marking a `priority pattern`.

Small-sample reverse-alert discipline:

- If an exact `盘口档位 + 候选标签` bucket reaches at least `5` settled comparable samples and the reverse side has `反向有效胜率 >=80%` with positive reverse flat-stake PnL, while the forward/previous positive-expectation side has failed in recent comparable samples, future matches in the same bucket must be marked `小样本反向警戒`.
- `小样本反向警戒` means the dashboard and report must explicitly warn that the historical cell currently favors watching or paper-buying the reverse side. It may change sorting/risk flags. For Asian handicap, it can become a real-money candidate only if the current Asian line/water exists and the Micro-Region Tag EV framework, water threshold, same-line veto, risk state, and Kelly/stake rules pass. PM/Betfair/BTTS still require their own exact price/liquidity before execution.
- When the red `亚盘意图历史EV` badge shows this condition, name the concrete reverse-positive team, for example `反向警戒：正期望方改看莱万特（反向=下盘），样本5，反向胜率80%`. Do not merely write `买反向`.
- Once the same bucket reaches `8` or more comparable samples, use the forward/reverse PnL and effective win rate to adjust model weights. Once it reaches `15` or more samples with stable process evidence, it can be promoted to `优先模式`.

Historical immutability discipline:

- Never revise an already kicked-off or settled match's pre-match prediction fields to fit a later model update. Immutable fields include `original_pick`, market type, selected side, Asian line, water/price, candidate intent tag, forward/reverse direction at the time, Kelly/stake, timestamp, and settlement clock.
- Already settled rows are allowed to receive appended review fields such as `current_model_pick`, `error_reason`, `rule_update`, and `post_match_notes`, but the original prediction and original settlement outcome must remain auditable.
- A factual final score can be corrected only when a reliable source proves the stored score was wrong. Such correction must be saved with `score_source`, `score_corrected_from`, `score_corrected_to`, and a timestamped audit note; it must never be used to hide or erase a prediction mistake.
- When a new reverse rule is discovered after a match has ended, apply it only to future rows. For the historical row, write `按新规则应改看反向` in the review note, while keeping the original forecast and PnL unchanged.

Yesterday settlement and version-backtest discipline:

- When the user says `按照skill做今天的更新`, `严格按照skill做今天的更新`, or any equivalent daily update request, yesterday's matches are settlement-only. The update may refresh final score, match state, cancellation/postponement state, score source, settlement result, and PnL, but must not change yesterday's Asian-handicap intent, candidate tag, final conclusion, selected team, forward/reverse mode, market type, Asian line, water/price, Kelly/stake, or original snapshot timestamp.
- For yesterday or older matches, never run the latest model as if it were the original pre-match model. If a new model read is useful, save it only as an append-only field such as `current_model_read` or `post_match_recheck`; keep the original fields frozen.
- If several intraday versions were saved for the same list date, settlement review must backtest each saved version separately. Use that version's frozen `version_signal_freeze.csv` or equivalent frozen ledger as the source of truth for prediction fields, and merge only current final-score/status data onto it.
- For list-date `D`, backtest the standard saved versions when available: morning `07:00-08:00`, afternoon `16:00-17:00`, and final/closing snapshot. Report each version's sample count, full-win, half-win, push, half-loss, loss, effective win rate, flat-stake PnL, and ROI.
- In the same version backtest, split by Beijing kickoff window based on the match's actual kickoff time: `D 00:00-22:59`, `D 23:00-D+1 01:59`, and `D+1 02:00+`. Display the three buckets as `23点前`, `23点-次日2点`, and `次日2点以后`.
- A match that had already kicked off or finished before a saved version's timestamp must be excluded from that version's new-prediction win-rate table, but may be shown in an audit-only section with `非赛前版本-不计`.
- Version comparisons must not overwrite the active dashboard or yesterday's frozen files unless the user explicitly asks to restore a version. Write comparison outputs under `D:\codex\outputs\football_odds_trader\version_backtests\YYYY-MM-DD\`.

If a review lacks historical baseline, price path, and public/liquidity path, the report must say: `证据不足：本场只记录错因假设，不更新skill权重`. Do not use confident language such as `继续降权`, `以后必须`, or `规则确认` unless these evidence thresholds are met.

When the user asks to review a full group-stage slate or "过去三轮小组赛", do a complete match-by-match retrospective, not a cherry-picked sample. Cover every completed match in every relevant group and use this table shape:

```text
group | match | result | pre-match pick if recorded | corrected model read | error/hit tag | skill update needed
```

If no pre-match pick was recorded for a match, label it `no recorded pick` and audit how the current framework would have read the match from pre-match information. Do not invent a past pick. After the table, summarize only the repeated error clusters and update the skill only for systemic errors, not isolated variance.

For full group-stage retrospectives, compute the tournament distribution of draws, one-goal wins, exact two-goal wins, and three-plus-goal wins. Use that distribution to recalibrate Polymarket `±1.5/±2.5` execution, because exact two-goal results separate `-1.5` winners from `-2.5` losers.

## Global Football Coverage

This skill now applies beyond the World Cup. Use it for:

- European top-five leagues: Premier League, La Liga, Serie A, Bundesliga, Ligue 1.
- European top-five second divisions: EFL Championship, Spanish Segunda Division, Serie B, 2. Bundesliga, Ligue 2.
- Additional European league observation pool: Portuguese Primeira Liga, Belgian Pro League, Turkish Super Lig, Dutch Eredivisie, Swiss Super League when appearing in cup contexts, and other liquid top-flight boards when the price path is readable.
- Additional European second/third-tier observation pool: EFL League One, Dutch Eerste Divisie, Turkish 1. Lig, Liga Portugal 2, J3 League, and other lower-tier matches only when kickoff, market type, settlement clock, and pre-match price are clearly verified.
- Domestic cups in those countries: FA Cup, EFL Cup, Copa del Rey, Coppa Italia, DFB-Pokal, Coupe de France, and super cups when relevant.
- Additional cup observation pool: Swiss Cup, German Telekom Cup or equivalent German preseason/cup-style invitational events, and other named domestic cups only when team motivation, rotation risk, and settlement rules are explicit.
- UEFA competitions: Champions League, Europa League, Conference League when it appears in the same slate.
- Other European leagues: Swedish Allsvenskan, Norwegian Eliteserien, and Russian Premier League.
- Asian competitions: AFC Champions League and AFC Champions League Elite/Two where market coverage exists.
- East Asia and Australia: Chinese Super League, K League, J1 League, J2 League, and A-League Men.
- South America: Brazil Serie A, Brazil Serie B, Argentina Primera Division, and Copa Sudamericana.
- North America: MLS and USL Championship.
- Australian cups: Australia Cup where market coverage exists.

Coverage is open-ended by country, but **not** open-ended by competition depth. For daily slate building, use Titan007 / 球探比分 as the primary schedule and Chinese-name standard, then apply this eligibility filter:

1. **Exclude youth/reserve by default**: ignore U17/U18/U19/U20/U21/U22/U23, 青年队, 青年联赛, 后备队, 预备队, reserve/reserves, academy, development, and any youth/reserve cup. These matches are too lineup-sensitive and too shallow for the current model unless the user explicitly asks for a separate youth/reserve framework.
2. **Senior domestic leagues only keep the top three tiers**: for every country, include only the highest division, second division, and third division. Do not include fourth-tier, regional amateur, state-local, academy, university, or reserve leagues. Because naming differs by country, do not infer tier from a single generic word such as `甲` or `乙`; maintain a tier map by country/competition name. Examples: England = Premier League / Championship / League One, so League Two is excluded; Japan = J1 / J2 / J3; China = 中超 / 中甲 / 中乙; Korea = K League 1 / K League 2 / K3; Germany = Bundesliga / 2. Bundesliga / 3. Liga; Brazil = Serie A / Serie B / Serie C; United States = MLS / USL Championship / USL League One when listed as a senior pro league.
3. **Senior cups and continental/national-team competitive fixtures are separate**: keep senior domestic cups, continental cups, super cups, promotion/relegation playoffs, and national-team competitive matches when settlement rules and markets are clear. Still exclude youth cups, reserve cups, school/university cups, and friendlies.
4. **Unknown tier rule**: if Titan007 / 球探 lists a formal senior league but the model cannot confidently map it to that country's tier 1/2/3 from the name or a stored tier map, label it `tier_unknown-待确认` and keep it out of simulated picks and win-rate statistics until the tier is confirmed. Do not include a match merely because it has odds.

Default to covering senior official competitions from England, Spain, Italy, Germany, France, United States, Japan, Korea, China, Australia, Denmark, Ukraine, Uruguay, Russia, Croatia, Iceland, Canada, Qatar, Ecuador, Brazil, Argentina, Colombia, Costa Rica, Norway, Czech Republic, Chile, and other countries that appear on the Titan007 / 球探 slate, but only after applying the top-three-tier and youth/reserve exclusion rules.

Friendlies are excluded by default. Ignore club friendlies, national-team friendlies, training matches, testimonials, and informal invitation matches unless the user explicitly asks to analyze them and the settlement clock, lineup motivation, and market liquidity are unusually clear. When friendlies are shown on Titan007 / 球探, label them `友谊赛-默认忽略/不纳入胜率统计`.

For any daily football request, first list every match on the target date in the covered scope before analyzing picks. Use the user's timezone when explicit; otherwise default to the thread timezone. Separate:

- `full-analysis candidates`: liquid matches with readable 1X2 and Asian handicap boards.
- `watch-only matches`: low-liquidity, missing line history, unclear lineups, or youth/reserve-heavy cup matches.
- `no-market / missing-data`: matches where odds or settlement data cannot be verified.

If the slate is large, do not force a pick for every match. Rank by market liquidity, information quality, and pattern fit. A good daily process may pass most matches.

For every daily update, do not hide the decision inputs only in CSV ledgers. The user-facing answer and the saved daily report must include a compact **拉力-价格-流动性公开表** for the shortlisted matches and every Polymarket candidate:

```text
比赛 | 基本面拉力 | 欧赔/亚盘价格 | Polymarket价格 | 流动性 | 结论
```

Use short Chinese phrases in this table. If a field is missing, write `缺` or `未确认` and downgrade confidence. The table is required even when the conclusion is `no bet`; no-bet decisions must show which gate failed, such as `盘口太深`, `价格无边际`, `成交太薄`, `盘口缺失`, or `结算口径不合格`.

All reports, ledgers, scratch files, and future automation artifacts for this skill must stay under `D:\codex`, preferably:

- `D:\codex\outputs\football_odds_trader\daily\YYYY-MM-DD.md`
- `D:\codex\outputs\football_odds_trader\ledger\slate.csv`
- `D:\codex\outputs\football_odds_trader\ledger\picks.csv`
- `D:\codex\outputs\football_odds_trader\ledger\polymarket_picks.csv`
- `D:\codex\outputs\football_odds_trader\ledger\simulated_bets.csv`
- `D:\codex\outputs\football_odds_trader\ledger\patterns.csv`
- `D:\codex\outputs\football_odds_trader\ledger\rule_changes.md`
- `D:\codex\outputs\football_odds_trader\reviews\grouped_edge_review_YYYY-MM-DD.md`

Do not write this workflow under `C:\Users\Administrator\Documents\Codex`.

## Stable Odds And Evidence Sources

Prefer structured odds APIs and timestamped snapshots over rendered sportsbook pages.

Use this source order when odds are needed:

1. **API-Football / API-Sports odds endpoints** for broad football coverage, especially when Asian handicap, over/under, BTTS, bookmaker IDs, and live odds are needed. Capture pre-match odds because provider-side live odds can disappear shortly after the match.
2. **The Odds API** for major leagues and normalized sportsbook odds across `h2h`, `spreads`, and `totals`, plus historical odds when the account tier supports it. Use it as a stable cross-book source and line-shopping/consensus reference.
3. **Polymarket Gamma + CLOB APIs** for Polymarket market metadata, token IDs, orderbook, midpoint, bid/ask, liquidity, and price history. Use CLOB orderbook/midpoint for executable price; treat Gamma outcome prices as discovery/metadata unless confirmed by CLOB.
4. **Betfair Exchange or other exchange APIs** when available, for exchange sentiment, traded volume, and back/lay depth.
5. **Official bookmaker pages such as Betway/Bet365/Pinnacle** only when the exact event page exposes the line and price reliably through the browser or a structured endpoint. If the page is rendered dynamically and the price cannot be read, label it `指定平台赔率未确认`; do not infer from other books.
6. **User screenshots** are acceptable as an execution snapshot only if the screenshot clearly shows event, market, line, price, time context, and settlement type.

For every API pull, save raw snapshots under `D:\codex\outputs\football_odds_trader\raw\odds\` with source, timestamp, league, event id, market, line, price, bookmaker, and timezone. Do not rely on retroactive reconstruction for line movement.

### Fundamental Evidence Minimum

Do not let market formulas replace football work. Before any simulation or recommendation, record at least one concrete fundamental input and one market-pull input:

- fundamental input: lineup/injury, rest/travel, table motivation, tactical matchup, xG/shot profile, defensive leakage, weather/surface, cup aggregate state, or rotation risk;
- market-pull input: public/story side, European de-vig gap, Asian handicap depth/water movement, exchange/Polymarket heat, liquidity, or bookmaker price drift.

If a match has only league stereotype plus generic odds language, mark it `证据不足-仅观察` and keep it out of main-pick consideration.

### Injury / Absence Strength Adjustment

Injuries and absences must be translated into football strength impact, not merely listed.

For every relevant absence, record:

- player name and source;
- status: `confirmed out`, `doubtful`, `questionable`, `suspended`, `international duty`, `rotation risk`, or `not in squad`;
- role: regular starter, rotation player, bench player, youth/reserve, goalkeeper, center-back, fullback, defensive midfielder, creator, winger, striker, set-piece taker, captain/organizer;
- recent usage: starts and minutes in the last 5-10 matches when available;
- tactical dependency: whether the team has a like-for-like replacement or must change shape;
- impact direction: defense stability, buildup, pressing, transition defense, chance creation, finishing, set pieces, or late-game bench strength.

Absence weighting guide:

- Starting goalkeeper or first-choice center-back missing: check clean-sheet probability, BTTS Yes, opponent team-total, and underdog scoring route.
- Defensive midfielder or buildup pivot missing: check transition vulnerability and whether the opponent/favorite can press high.
- Primary creator or set-piece taker missing: downgrade chance quality and BTTS/over unless replacement quality is confirmed.
- Main striker missing: downgrade conversion and favorite margin tail, but do not automatically buy under if the team creates many shots through wingers/set pieces.
- Fullback/wingback missing: check crossing volume, defensive flank exposure, and opponent winger matchup.
- Multiple rotation absences in cup/short-rest spots: downgrade pre-match confidence and prefer live confirmation.

Main-pick gate:

- If a key starter is reported out but replacement quality is unknown, reduce model probability or Kelly stake before reading price.
- If team news is only predicted or rumored, mark `伤停未核` and do not use it as a hard edge.
- If official lineups show a surprise key absence or surprise return, rerun the five-board chain instead of treating the original pick as unchanged.

### Betting Volume / Flow Data Status

There is no single stable public source for all football betting volume. Treat volume availability by venue and never mix the following layers under one generic `投注量` label.

Daily reports must display volume status separately:

- `真实投注量`: Polymarket/Betfair/exchange volume if available.
- `流动性`: orderbook depth, spread, matched volume, or Polymarket volume.
- `盘口价格流`: Titan007/bookmaker opening/current odds and water movement.
- `公众热度`: bloggers, screenshots, public narrative, or visible community attention.

If only odds movement is available, write `投注量缺失，只有盘口价格流`; do not infer that money is necessarily on one side.

### Betting Flow Source Hierarchy

Use betting-flow data in three separate layers. Save source URL, timestamp, parsed fields, and match-mapping confidence for every non-Titan flow source.

**Layer 1: true exchange / prediction-market flow**

- **Polymarket Gamma + CLOB**: preferred public source when the exact football market exists. Use Gamma for discovery, event/market metadata, volume, liquidity, recent price activity, and token IDs; use CLOB for executable bid/ask, spread, orderbook depth, last trade, midpoint, and WebSocket updates. Record market slug, market type, settlement clock, token IDs, best bid/ask, spread, liquidity, volume24h, timestamp, and whether the contract maps to the exact match/market.
- **Betfair Exchange official API**: best source for true matched money when account/API access is available. Record market name, settlement clock, `Total Amount Matched`, traded volume, back/lay ladder, available depth, and timestamp. Without account/API/session access, mark `Betfair官方未接入`, not `无资金流`.
- **Betfair Historical Data**: official backtest source, not real-time. Use it for historical exchange price/volume research after login/download, and label it `Betfair历史成交数据`.
- **Other exchanges / prediction markets**: usable only when orderbook, matched volume, settlement rules, and timestamp are visible and saved.

**Layer 1B: Betfair-derived Chinese flow pages**

These are not official Betfair unless the data comes directly from Betfair, but they can be used as `必发衍生数据` when concrete matched amount, buy/sell ratio, hot/cold index, payout/profit index, price ladder, or big-trade detail is visible.

- **出奇数据 / Chuqi 必发**: priority free derived source when listed. The list page exposes match IDs and Chinese team names; single-match pages such as `live-bifa/{match_id}` may embed structured `allData` with `odds`, `amount`, `per`, `profit`, `payout`, `hot`, time-series `echart`, and trade `detail` for 主/和/客. Use it first for J League/K League/竞彩/北单 style matches when the match appears.
- **足彩网 / SPDEX iframe**: `odds.zgzcw.com/jczq/bf_data.jsp` is a container; the useful football iframe is usually `http://c.spdex.com/vonejc`. When accessible, parse match title, kickoff, SPDEX match ID, Top5 trade ticker, and the per-match iframe viewer. Label as `SPDEX必发衍生`.
- **7M / 7M.hk Betfair Trading**: useful single-match source when a 7M Betfair ID is known. Parse 成交明细, 必发成交数据, 大额交易, 价位, 成交额/交易量, 交易比例, 庄家盈亏, 盈亏指数, 冷热指数, 市场指数. Main challenge is mapping Titan007/球探 match IDs to 7M Betfair IDs; use Chinese team/time fuzzy matching or source links, not guessed IDs.
- **bifaw.com**: usable only when free or logged-in pages show concrete 标盘/让球/大小指数, 已成交, 成交量, or big-trade detail. If only homepage teasers are visible, mark `bifaw待登录/待解析`.
- **澳客必发盈亏 / 天天盈球 / 捷报 / 澳客等**: use as `必发衍生数据` only when the actual table is visible or parseable. If the page describes the method but hides the table behind login/JS/captcha, mark the exact gap.

**Layer 2: public betting splits**

These sources do not usually show exact matched money. They show public ticket share and handle/money share. Use them to identify public-vs-sharp divergence.

- **VSiN betting splits**: use when the page shows `% of bets` and `% of money`, especially if sportsbook partner/source is visible.
- **Action Network public betting percentages**: use for public bet %, money %, line movement, and reverse-line-move signals. Label advanced/pro signals as unavailable unless actually visible.
- **DraftKings betting splits / BetMGM / Covers / The Spread**: use as public split or sportsbook-handle proxy when soccer coverage exists and the table is visible. Label exact coverage gaps; do not infer global football money from US-only books.

Core divergence logic:

- `散户热`: high `% of bets` but low `% of money`; many small tickets.
- `大户/主力倾向`: low `% of bets` but high `% of money`; fewer tickets but larger stake concentration.
- `反向资金`: money share and odds movement support the less popular side.
- `诱导风险`: public side is obvious, but line does not move with public, or moves against public.

**Layer 3: odds-move proxies**

- **OddsPortal**: use odds comparison, odds history, and dropping odds as a price-pressure proxy. It does not provide true betting volume by default. Label it `赔率异动代理`.
- **Titan007 / 7M odds snapshots**: use opening/current Asian handicap, 1X2, totals, and water movement as `盘口价格流`, not true betting volume.
- **Bookmaker screen movement**: use only as line/price movement. Do not call it volume unless the book/source explicitly provides handle or ticket split.

Daily output must use four separate columns when flow is discussed:

```text
比赛 | 真实成交量 | 注单/资金比例 | 盘口价格流 | 解读
```

If a field is missing, write the exact missing field:

- `Betfair官方未接入`
- `PM无市场`
- `必发衍生数据未匹配`
- `注单/资金比例缺失`
- `只有赔率异动`
- `只有Titan007盘口价格流`

Main-pick gate:

- A real-money main pick is stronger when Layer 1 or Layer 2 confirms the five-board read.
- If only Layer 3 exists, keep stake smaller and label the flow as price evidence, not betting volume.
- Do not upgrade a pick solely because OddsPortal/Titan007 shows odds dropping. First check whether the move improves entry value or already prices out the edge.

### Stable Fundamental Data Source Priority

Use this source order for fundamentals:

1. **Sportmonks Football API**: fixture date/search, head-to-head fixtures, standings, lineups, expected lineups, sidelined/injuries, formations, weather, match/team statistics, xG fixture, pressure/trends, and player information. Use it as the preferred paid structured source when coverage includes the target league.
2. **API-Football / API-Sports**: fixtures, head-to-head, standings, injuries/suspensions, lineups, fixture statistics, player statistics, team statistics, predictions, odds, and coverage flags. Always check league `coverage` flags before assuming injuries or lineups exist.
3. **SofaScore / FotMob readable match pages or APIs**: lineups, missing players, H2H, form, standings, live statistics, player ratings, and momentum. Treat unofficial endpoints as unstable; save raw snapshots and cite them as public-data support, not as guaranteed API service.
4. **Transfermarkt / club official injury news / league official match centres**: use for injury, suspension, squad availability, travel/rotation, and market-value context. Prefer official club/league confirmation over media rumor.
5. **WhoScored / FotMob / SofaScore previews**: use for predicted lineups, tactical style, ratings, recent form, and team-news summaries. Mark `预计首发` separately from `官方首发`.
6. **Public analyst/blogger sources**: use only as public narrative and handicap-pull evidence unless they provide concrete team news or tactical facts that can be verified elsewhere.

### Verified Lineup / Injury Source Tiers

Use these source tiers for football lineup and injury work. Always save the URL, timestamp, and whether the data is `official`, `predicted`, `confirmed lineup`, `injury/absence`, or `public narrative`.

**Tier A: preferred structured or semi-structured sources**

- Rotowire soccer lineups: currently the most script-readable public source among the tested lineup/injury websites. The page can expose predicted/confirmed lineups, injuries, status labels such as `QUES/OUT/SUS`, weather, and some odds in plain HTML. Use it first for leagues it covers, especially Premier League and other major European/US competitions.
- Flashscore: homepage and JS metadata are readable, and it is useful for broad fixture coverage, lineups, missing players, live match stats, H2H, odds comparison, and previews when the match page exposes them. For automation, treat match-detail parsing as semi-structured and verify endpoint stability before relying on it.
- LeiSu / 雷速体育: homepage content is readable and useful for Chinese match intelligence, fixture pages, lineups, injuries/news tags, live scores, and local-language coverage of CSL, J/K leagues, Asian competitions, and basketball. It may load anti-bot/captcha scripts, so classify direct automation as semi-structured until a stable endpoint is confirmed.
- Titan007 / Win007 / 7M / 球探: usable for schedule, live state, odds, Chinese team names, `数据库`, `比赛情报`, `阵容/Lineup`, H2H, recent 5-10 form, win/loss handicap fragments, totals fragments, and some injury/news context. Use it as the primary Chinese odds/schedule source and as a first-pass H2H/form source; do not use it as the sole injury source for high-stakes main picks unless the injury/lineup item is clearly official or corroborated.
- NBA Official Injury Report: directly readable for NBA injury work and should be the official source for basketball injury status.

**Tier B: browser/manual verification sources**

- WhoScored: high-value for predicted lineups, confirmed lineups, team news, formations, ratings, and tactical previews, but direct simple fetch can be blocked. Use browser/manual verification when available; do not assume automated access.
- SofaScore: high-value for confirmed lineups, missing players, H2H, live stats, momentum, ratings, and formations, but direct simple fetch can be blocked. Use browser/manual verification or structured provider alternatives.
- FotMob: high-value for lineups, injuries, match facts, player ratings, and form pages. If used programmatically, respect site restrictions; otherwise use manual/browser verification and save the observed page snapshot.
- Transfermarkt: high-value for long-term injuries, suspensions, absences, market-value context, transfers, and squad depth, but direct simple fetch can hit AWS WAF challenge. Use browser/manual verification unless a stable readable endpoint is confirmed.

**Tier C: sport-specific or supplemental**

- Rotowire: useful for NBA/NFL/MLB and some soccer betting/fantasy news; use as supplemental injury/news source where pages are accessible, especially for US sports.
- NBA Official Injury Report: authoritative for NBA only. Use official.nba.com injury report pages before media sources.
- Underdog NBA/X: fast NBA news source, but treat as public/news feed unless confirmed by NBA official report or team source.
- 懂球帝 / 直播吧 / 捷报比分: useful Chinese supplemental sources for quick match pages, lineup boards, formation graphics, injury/suspension lists, red/yellow-card bans, recent-form trend, and local-language previews. Use as corroboration, not as the single source for a main pick unless the underlying item is official/team sourced.

### Free Fundamental Source Ingestion Ladder

When a football match is being upgraded from odds-only observation to an actionable simulation or main-pick candidate, collect team news and form in this order. Save every successful raw or summarized snapshot under `D:\codex\outputs\football_odds_trader\raw\` with source URL, timestamp, match id/name, and whether the item is `官方`, `结构化平台`, `预测`, `媒体/社区`, or `未核`.

1. **Domestic Chinese fast sources**
   - 懂球帝 and 直播吧: use each match detail page's `阵容`, `伤停`, `情报`, and `战绩/走势` areas when available. Extract official or predicted starting XI, formation, absent players, suspension reason, recent five-match W-D-L, goals for/against, home/away split, and any clear tactical or motivation note. If the page only republishes public news, mark it `媒体/社区-待交叉验证`.
   - Titan007 / Win007 / 球探: use the odds board plus `数据库`, `比赛情报`, `分析`, `Lineup/阵容`, and related detail pages for H2H, recent 5-10 matches, same-home-away H2H, recent handicap record, totals record, score state, ranking/stage, and Chinese name standardization. If 球探 has odds but no lineup/injury board for the match, write `球探赔率已接入；阵容/伤停缺口`.
2. **Overseas broad coverage sources**
   - Flashscore and SofaScore: use for broad global coverage, confirmed lineups, missing players, suspensions, H2H, recent form, player ratings, live stats, heat/momentum, and formation diagrams. Treat confirmed lineups as strong evidence; treat predicted or app-derived expected lineups as `预计首发`.
   - FotMob: use for lineups, injuries, match facts, player ratings, recent form, tactical shapes, and live/event timing. Prefer it when Flashscore/SofaScore data is incomplete.
3. **Deep football analysis sources**
   - WhoScored: prioritize for European top-five leagues and major UEFA/MLS/Brazil/Argentina matches where its preview is available. Extract predicted lineups, team news, tactical style, key-player absence, recent form, ratings, and any model score prediction. Label it `WhoScored预览`, not official confirmation unless the page marks lineups confirmed.
   - Transfermarkt: use for long-term injuries, suspensions, squad absences, player value, squad depth, transfer/rotation context, and whether an absent player is tactically central. For a key player absence, record role (`门将/中卫/后腰/核心前腰/主力中锋`), likely replacement, and whether the absence changes the Asian handicap value.
4. **Structured APIs and automation**
   - API-Football / API-Sports: when an API key or free quota is available, use coverage flags before fetching fixtures, injuries, lineups, standings, H2H, team/player statistics, predictions, and odds. Store endpoint name, request time, league coverage flags, and response status.
   - Football-Data.org: use as a structured fixtures/results/table source where coverage is available. It is not enough for injury/lineup by itself, but it can validate schedule, table position, and recent match results.
   - GitHub open-source scrapers such as `football match statistics scraper` or `sofascore api python` projects may be used only after reviewing the code path and saving the exact repository/source reference. Treat unofficial endpoints as unstable and label them `开源抓取-待验证`.

Timing discipline:

- **T-24h to T-6h**: collect long-term injuries, suspensions, table/motivation, H2H, and last-five form. Use Transfermarkt, WhoScored previews, Titan007/Win007, Flashscore/SofaScore/FotMob, 懂球帝/直播吧 where available.
- **T-3h to T-90m**: refresh injury/news and predicted lineups; flag rotation-sensitive cup matches and congested schedules.
- **T-75m to T-45m**: official starting lineups are usually published around one hour before kickoff. Re-check SofaScore/FotMob/Flashscore, official club/league channels, 懂球帝/直播吧, and 球探 Lineup pages. If official lineups become available after the earlier odds read, rerun the fundamental pull and the Asian handicap EV gate.
- **After kickoff**: do not create or overwrite prematch recommendations. Only update status, score, settlement, and post-match audit fields.

Field-level requirements:

- Injury/lineup output must distinguish `官方首发`, `预计首发`, `伤停确认`, `停赛确认`, `伤停未核`, and `无明确伤停信息`.
- Recent-form output must include at minimum recent five W-D-L, goals for/against, home/away split when relevant, and whether the opponents are comparable. Do not reduce form to a generic `状态好/状态差`.
- H2H output must separate all H2H from same-home-away H2H and mark stale samples or major squad/manager discontinuity.
- For totals, BTTS, team totals, or goal-count picks, add recent scoring/conceding averages, first-half/second-half goal timing, shot/xG or chance-quality proxy where available, tactical matchup, and post-goal behavior (`继续压上`, `控节奏`, `防反收缩`) before giving any direction.
- Missing team-news/form data does not automatically block Asian-handicap EV simulation, but it must lower confidence, block high-Kelly/main-pick promotion, and appear visibly in HTML/CSV as the exact missing link.

Main-pick gate:

- A football main pick needs at least one Tier A/B lineup or injury check plus one market-price check.
- If only Tier C or generic news is available, mark `基本面未核-仅模拟`.
- If direct fetch is blocked but browser/manual observation is possible, mark `人工核验` and include timestamp.

### Multi-Source Verification Standard

For every daily slate, build a visible source-coverage matrix before promoting any simulation to a main pick. Do not treat a single website as complete evidence.

Minimum source map by data field:

- **Schedule, Chinese names, live state, score**: Titan007 / 球探 first, then Flashscore, SofaScore, FotMob, ESPN, or league official pages for cross-check.
- **Asian handicap, European 1X2, totals**: Titan007 / 球探 for opening and current board; cross-check with OddsPortal, BetExplorer, 500.com, API-Football odds, or The Odds API when accessible. If two sources disagree, keep the source labels and use the most recent timestamped source only for current price, not historical price.
- **BTTS, team totals, corners, halves, exact score**: use Polymarket when the market exists, plus sportsbook/API odds when readable. If BTTS is unavailable from a stable source, mark `BTTS赔率未接入` and do not calculate Kelly on BTTS.
- **Head-to-head and last-five form**: prefer Titan007/Win007/球探 `数据库/分析` pages for Chinese-standard H2H and recent-form tables, then SofaScore/FotMob/Flashscore, 懂球帝/直播吧, Football-Data.org, API-Football/API-Sports, or league official pages. Record results, goals for/against, home/away split, opponent comparability, and stale-sample warnings. If only generic form is available, label `近况粗略`.
- **Win/loss handicap record and totals record**: use Titan007/球探, OddsPortal, BetExplorer, 500.com, API-Football/API-Sports odds endpoints, or another structured odds API with historical lines. Do not infer win盘/输盘 from score alone when the historical closing line is missing.
- **Lineup, injuries, suspensions, absences**: prefer official club/league lineups and injury lists, then structured or semi-structured providers: Rotowire, WhoScored, SofaScore, FotMob, Flashscore, Transfermarkt, API-Football/API-Sports, Titan007/Win007/球探 Lineup, 雷速, 懂球帝, 直播吧, 捷报. Separate `官方首发`, `预计首发`, `伤停确认`, `停赛确认`, `伤病原因`, `预计复出`, `媒体传闻`, and `未接入/待核`.
- **Motivation/table state**: use league table, fixture context, cup aggregate score, two-leg state, qualification/relegation pressure, official competition rules, and reliable previews.
- **Betting volume and flow**: Polymarket Gamma/CLOB and Betfair official/exchange-derived sources are true flow when available. Titan007/球探 odds movement is only `盘口价格流`; OddsPortal dropping odds is `赔率异动代理`; public betting splits such as VSiN/Action Network/TheSpread are `公开投注比例`, not guaranteed global betting volume.

Conflict handling:

- If the same field is confirmed by two independent sources with the same timestamp window, mark it `已核`.
- If one source is official and another public page conflicts, official source wins, but record the conflict.
- If two non-official sources conflict, mark `冲突待核` and downgrade the match to watch-only or simulation-only.
- If a source is unreachable, show `未接入/待核` in the report and dashboard; never silently omit the field.
- If a data field is essential to a market type, and that field is missing, the market cannot become a main pick. Examples: no BTTS price means no BTTS Kelly; no closing/historical line means no win盘/输盘 historical conclusion; no lineup check means no high Kelly on cup or rotation-sensitive matches.

Dashboard requirement:

- Every match page must show a **数据源核验** block with source status for schedule/names, odds board, BTTS/secondary markets, head-to-head, last-five form, handicap record, injuries/lineups, motivation, Polymarket/Betfair flow, and public analyst/blogger view.
- The block must show which data is `已接入`, `部分接入`, `未接入/待核`, or `冲突待核`.
- Missing data should lower confidence but remain visible so the user can see exactly what is absent.

Before kickoff, classify lineup status:

- `官方首发确认`: official lineup or a structured provider marks lineup confirmed.
- `预计首发`: predicted lineup only; downgrade confidence and avoid high Kelly.
- `伤停已核`: injury/suspension appears in structured provider or official/team source.
- `伤停未核`: only rumor/blogger claim; use as public narrative, not baseline fact.

For every analyzed match, save or summarize:

- last 5-10 team form and goal profile;
- head-to-head, but only as context unless tactical/squad continuity is real;
- table/motivation and cup aggregate state;
- injury/suspension and lineup status;
- rest/travel/rotation;
- tactical or statistical edge such as xG, shots, set pieces, defensive leakage, pace/transition, or clean-sheet profile.

## Daily Operating Cycle

When the user asks for today's update, daily predictions, or a slate review, run this sequence in order:

1. **Date and slate lock**: state the date, timezone, competitions included, and kickoff cutoff. List all covered matches for that date with competition, kickoff time, home, away, and analysis status.
2. **Prior-day review**: find the previous daily report or last recorded recommendations when available. For every recorded pick, log `competition`, `match`, `recommended market`, `entry price/line`, `result`, `handicap outcome`, `closing-line note if known`, and `process grade`.
3. **Error classification**: for every miss, classify as `framework error`, `late bookmaker move`, `lineup/news shock`, `execution price error`, `variance`, or `no real edge`. Do not label a miss as variance until the pre-match logic, closing move, and price discipline have been checked.
4. **Skill update decision**: update rules only for repeated or structural framework errors. Give bookmaker late moves a tolerance bucket when the original read was correct but closing information changed materially.
5. **Simulated-bet review**: settle every prior simulated bet separately from real/main picks. Use it to validate model reads on matches that were passed for bankroll reasons. Do not merge simulation hit rate with actionable pick hit rate.
6. **Stats update**: report hit rate by market type, competition, line range, operator-intent tag, pull-pattern tag, league stage, and cup format. Track both result hit rate and process hit rate when closing-line value is available.
7. **High-win-rate pattern scan**: identify patterns with developing or proven edge. Mark `candidate pattern` only after at least 8 recorded comparable cases and positive process notes. Mark `priority pattern` only after at least 15 comparable cases, hit rate above 80%, no obvious overfitting, and no concentration in one team or one month.
8. **New slate analysis**: analyze the new matches strictly through the five-board chain. Highlight any `priority pattern` matches before the final recommendation.
9. **Every-match simulation**: for every covered match with a readable market, create one paper/simulated primary selection even if the real-money recommendation is `no bet`. Use fixed `1.00` simulated unit unless testing a low-confidence branch, then use `0.25` simulated unit. Record why the simulated market was chosen and which framework bucket it tests. If no reliable market exists, record `no-market simulation skipped` with the missing gate. A simulated lean becomes countable only when the pre-match line/price, market framework, and settlement clock were known before kickoff and the final score can be verified; otherwise keep it in coverage only.
10. **Ledger write-down**: whenever file editing is in scope, append the daily report, full slate ledger, Asian picks ledger, Polymarket picks ledger, and simulated-bets ledger under `D:\codex\outputs\football_odds_trader`. If writing is not performed in the current turn, still present the ledger rows in the answer so they can be recorded later.

Default language is Chinese for user-facing reports and CSV display fields. Keep stable IDs such as `pick_id` in ASCII, but write match names, market status, intent explanation, and process notes in Chinese unless the user asks otherwise.

The daily slate table and `slate.csv` should use this shape. This is the full-match file; it includes no-bet and watch-only matches:

```text
日期 | 赛事 | 北京时间 | 比赛 | 盘口状态 | 分析状态 | 结论/备注
```

The Asian picks ledger and `picks.csv` should use this shape. This file contains only actionable Asian handicap / sportsbook recommendations, not every match in the slate:

```text
日期 | 赛事 | 比赛 | 推荐ID | 市场 | 盘口/价格 | 方向 | 仓位_pct | 盘口意图 | 基本面标签 | 信心 | 赛前备注 | 赛果 | 盈亏单位 | 过程评级 | 错误类型 | 规则更新
```

The Polymarket picks ledger and `polymarket_picks.csv` should use this shape. This file contains Polymarket recommendations only when the execution gate passes, plus limit-only orders that should not be chased:

```text
日期 | 赛事 | 比赛 | 推荐ID | Polymarket市场类型 | Polymarket合约 | 合约口径 | 买入方向 | 可成交价/挂单价 | 最高买入价 | 盘口等价转换/定价依据 | 保守胜率下限 | 边际 | 流动性评级 | 仓位_pct | 执行状态 | 赛果 | 盈亏单位 | 过程评级 | 错误类型 | 规则更新
```

The simulated-bets ledger and `simulated_bets.csv` should use this shape. This file is for paper trading and model calibration only; it is not a betting recommendation ledger:

```text
日期 | 赛事 | 比赛 | 模拟ID | 赛制阶段 | 市场框架 | 模拟盘口/价格 | 模拟方向 | 虚拟仓位单位 | 基本面拉力 | 盘口倾向 | Polymarket/交易所情绪 | 流动性 | 模拟目的 | 是否主单 | 赛果 | 模拟盈亏单位 | 过程评级 | 错误类型 | 模型更新
```

Always include a user-facing **模拟投注表** in daily reports. If the slate is large, group by competition, but still show every readable match in the saved report and enough rows in the chat answer to avoid hiding the model's lean. Mark real-money picks separately with `是否主单=是`; all other rows are paper-only.

When the user asks to backfill already completed matches or review previous simulations, run a **历史模拟回放**:

- Backfill every completed match from `slate.csv` and daily reports into `simulated_bets.csv` if it is not already recorded. Do not limit the backfill to prior main picks. De-duplicate by `date + match`; exclude no-match days, aggregate summary rows, and duplicate screenshot rows before claiming coverage totals.
- For each slate match whose kickoff time is already in the past, verify the real score from a reliable public source before settling the simulation. If the score cannot be verified, add it to a visible `待补赛果/证据不足` list instead of silently skipping it.
- Use only the originally recorded pre-match line, price, notes, and framework tags. Do not use the final score to invent a better simulated pick.
- Mark the row as retro by using a `模拟ID` suffix such as `-RETRO-SIM` and by starting `模拟目的` with `retro-sim`.
- Keep retro-simulation accuracy separate from forward paper trading accuracy. Retro rows are for calibration and error clustering, not proof of future predictive hit rate.
- If a completed match has no reliable pre-match price or notes, write `证据不足/不回填模拟` in the review instead of forcing a pick; still count it in backfill coverage.
- Every retro-simulation review must include a coverage audit: `slate completed matches`, `retro-sim rows completed`, `missing score`, `missing pre-match price`, and `excluded no-market rows`.
- Compare each retro simulation with the true result, then classify errors by `market framework`, `competition`, `stage bucket`, `line range`, `pull-entry mismatch`, `settlement clock`, `liquidity`, and `public narrative`.
- Update the skill only for repeated or structural failure clusters. Do not create a new rule from one isolated loss.

## League And Competition Priors

These priors are starting points only. Override them when current team news, market movement, or tactical matchup is stronger.

Before choosing a main pick or simulated pick, classify the match into a **framework bucket**. Do not pool all football matches into one model:

- **League stage**: early season, mid-season, late-season, relegation/promotion/continental-place pressure, post-title or dead-rubber state. Early season has noisy form and lineup uncertainty; mid-season usually gives the cleanest power rating; late season requires motivation and table-state audit before reading odds.
- **Cup format**: one-off knockout, first leg, second leg, group stage, final, super cup, playoff, or aggregate-score tie. For two-legged ties, record aggregate score, first-leg/second-leg, home/away, who leads, who must chase, whether extra time is live, and whether away goals exist. Do not apply a normal league handicap framework to a second-leg cup market.
- **Market framework**: Asian handicap, moneyline/1X2, totals, BTTS, team total, exact total goals, Polymarket spreads, Polymarket totals, Polymarket moneyline, and qualification markets each need separate probability buckets and settlement clocks.
- **Season and league ecology**: Scandinavian summer leagues in mid-season can be more stable for form reads; CSL needs foreign-player/team-news discounts; Argentina/Brazil often require draw/tempo/travel discounts; cup mismatches require rotation and motivation checks before deep favorites.

Stats and model updates must be segmented by `market framework + competition + stage bucket + line range`. A winning pattern in Norwegian/Swedish mid-season league matches does not automatically transfer to CSL, South American cups, early-season European qualifiers, or two-legged knockout ties.

Historical retro-simulation gates from the 2026-08-02 backfill:

- **Full-slate coverage discipline**: the 2026-08-02 audit found `198` slate rows but only `164` unique playable match keys after removing no-match, bundle, and duplicate rows. Do not describe a backfill as complete by raw row count. Report unique match keys, verified scores, missing scores, countable simulations, and not-counted evidence rows separately.
- **Full-slate calibration baseline**: the same audit produced `51` countable retro rows, `28W-22L-1P`, `56.0%` hit rate excluding pushes, and `+4.715u` simulated PnL. This is calibration evidence, not a future edge. Asian handicap reads were materially better (`8W-2L-1P`, `80.0%`) than loose moneyline/draw reads (`14W-17L`, `45.2%`) and goals (`4W-3L`, `57.1%`).
- **Light moneyline and draw demotion**: do not turn phrases like `方向可看`, `主胜方向`, `客胜方向`, `均衡`, or `平局拉力` into a main moneyline/draw pick without Asian or price confirmation. If the board does not give a real edge, record `0.25u paper only` or `no bet`. The common error cluster was `胜平负方向误判/平局风险` and `均衡盘未转化为平局`.
- **CSL hard downgrade**: the full-slate CSL sample was weak (`3W-6L`, `33.3%`). CSL favorites and goals need foreign-player availability, rotation/news, defensive-tail, heat/travel, and line-move confirmation before any main pick. Default uncertain CSL matches to `no bet`, DNB/PK, shallow handicap, or live-only; never force `-1` or Over/BTTS from story strength alone.
- **MLS high-variance downgrade**: the full-slate MLS sample was neutral (`4W-4L`, `50.0%`) with multiple ML/draw misses. Avoid raw MLS moneyline main picks from public star power, home story, or loose form. Prefer DNB, `+0.5`, totals only with price edge, or live confirmation.
- **Argentina draw gate**: Argentina Primera can be low tempo and draw-heavy, but the draw itself is not value unless price and tactical setup both confirm. Do not mechanically buy draws on balanced boards; require de-vig draw gap, low shot-volume profile, and no late-chase incentive.
- **Argentina low-total gate**: Argentina Primera low tempo does not automatically justify Under or BTTS No. Require team-specific shot volume, finishing form, lineup news, and motivation/late-chase incentives before buying low totals. If the only evidence is league ecology, keep the row paper-only or no bet.
- **Argentina home-ML draw-protection gate**: Argentina Primera home pull does not automatically justify a moneyline entry. If the board is low-tempo, draw-heavy, or the favorite lacks terminal chance quality, downgrade home ML to DNB/double chance, totals, or no bet. A home side can be directionally correct and still be a bad ML price when draw gravity is high.
- **European qualifier public-analysis gate**: In Champions League, Europa League, and Conference League qualifying first legs, public analyst/blogger views can update the simulated lean when they identify a concrete underpriced side or total, but they cannot by themselves upgrade a pick to a main bet. Require Asian handicap confirmation, lineup/news checks, and executable liquidity before promoting a public-analysis view.
- **European qualifier evening-revision gate**: If late public analysis conflicts with the morning moneyline lean and the recent comparable sample favors totals/BTTS over direction, the pre-kickoff simulated row may be revised from ML to totals/BTTS. This remains paper-only unless Asian handicap confirmation, executable liquidity, and price edge all pass. Do not treat a blogger tip or bookmaker promotion as a standalone betting signal.
- **European qualifier BTTS-promo downgrade**: Do not upgrade BTTS or totals solely from a bookmaker promotion, odds boost, or public "both teams to score" article. Require team-level shot creation, both lineups, defensive injuries, and a confirmed totals/BTTS price. If the signal is only promotional or narrative, keep it paper-only and tag it as `promo-risk`.
- **European qualifier first-leg ML-favorite downgrade**: Champions League, Europa League, and Conference League qualifying first legs must downgrade ordinary moneyline favorites and brand-name away favorites unless the market gives clear handicap confirmation. A stronger team, a famous shirt, or a short 1X2 price is not enough. Prefer DNB, shallow handicap, totals/BTTS, live confirmation, or no bet; make deep or raw ML favorites paper-only unless there is a verified price edge.
- **European qualifier extreme-short ML gate**: First-leg favorites priced below roughly `1.20` are not automatically safe. They can still be bad value because a draw ruins ML and deep Asian spreads need margin proof. Use them only as paper process checks unless team news, tempo, and handicap confirmation justify a real edge.
- **K League source gate**: K League TV and highlight modules may confirm fixtures without exposing final scores. Do not settle or count K League rows from highlight presence alone. Require a reliable final-score source or keep the row in `待补赛果/证据不足`.
- **AET settlement gate**: if a score source labels a match `AET`, do not settle 90-minute Asian handicap, 1X2, totals, or BTTS from the AET score unless the source also provides the 90-minute score or an existing pre-match ledger has already recorded a verified 90-minute settlement.
- **Scandinavian mid-season league**: Norwegian/Swedish mid-season Asian reads have worked best so far when the entry is either shallow favorite confirmation (`-0.25/-0.75`) or clear public-tax dog protection (`+0.5/+1`). Treat this as a watch pattern, not a priority pattern, until it has at least 8 forward samples.
- **European qualifier second legs**: do not buy favorite `-1` or deeper simply because the favorite is stronger, likely to qualify, at home, or facing a chasing opponent. Require separate 90-minute margin incentive, lineup strength, and chance-quality evidence. If the favorite already leads the tie, the default is no bet, shallow ML, or opponent plus handicap.
- **Two-leg goals**: `must_chase_state` is not enough for Over/BTTS. Require both teams' 90-minute scoring floor, transition quality for the leading side, and no incentive for a one-goal result to slow the match into extra time.
- **CSL deep favorite and goals**: CSL requires extra foreign-player, heat, travel, and motivation checks. Do not convert a clean win lean into `-1` or a generic goals bet without independent terminal-tail evidence.

- **Premier League**: high liquidity and high public tax. Big-six favorites often price efficiently or expensively. Require sharp Asian confirmation before buying famous favorites at `-1` or deeper. BTTS and late-goal tails are more live than in slower leagues.
- **EFL Championship**: fixture congestion, promotion/relegation pressure, and squad depth matter more than brand names. Favorites can be overpriced because table position is noisy; require chance-creation edge and rest confirmation before buying `-0.75` or deeper.
- **La Liga**: stronger draw gravity and control-game patterns. Possession favorites often win by one rather than run margin. Be skeptical of `-1.25` and deeper unless the opponent must chase or has clear transition/box defense problems.
- **Spanish Segunda Division**: very high draw gravity and lower scoring. Small favorites are often fragile; dog `+0.25/+0.5` and under/draw protection fit only when the dog has defensive stability and the favorite lacks shot volume.
- **Serie A**: tactical tempo, game-state management, and draw protection matter. Small favorite lines can be traps when the favorite is happy with a narrow win. Unders and dog `+0.75/+1` can be real only when the dog can exit pressure.
- **Serie B**: volatility is high but margins are often thin. Motivation, suspensions, and end-season table state can dominate team strength. Avoid high confidence unless market and lineup news agree.
- **Bundesliga**: higher transition and late-goal variance. Favorites with pace and pressing can turn one-goal edges into two-goal covers, but defensive fragility makes both-teams-score risk material.
- **2. Bundesliga**: even higher chaos and BTTS tendency than many top-tier leagues. Do not overvalue clean league-table edges; prefer live confirmation when backing favorites, and price late-goal risk into dog handicaps.
- **Ligue 1**: PSG and brand-club tax can be large. Physical underdogs and low rhythm can suppress deep covers. Distinguish elite favorite terminal tail from simple public-name inflation.
- **Ligue 2**: low tempo, low scoring, and draw gravity are strong. Favorite moneylines can be expensive relative to true win probability. Dog `+0.5` and under-style reads need price discipline because liquidity is thinner.
- **Domestic cups**: rotation, rest, youth minutes, and motivation dominate normal league priors. For mismatches, ask whether the favorite's lineup has real finishing tail before buying deep handicaps. For two-legged cups, map the aggregate score and second-leg incentives before reading the line.
- **Champions League / Europa League**: market is liquid but narrative-heavy. First legs have draw and risk-control gravity; second legs are score-state markets. No away-goals rule means extra-time tail is often larger than casual public pricing implies.
- **Swedish Allsvenskan**: summer-season rhythm, artificial turf, travel, and weather matter. Home-field and surface familiarity can be underpriced. Early-season form is noisy; late-season motivation and European-spot pressure matter.
- **Norwegian Eliteserien**: high variance, weather/surface effects, and transition-heavy games raise BTTS and late-goal risk. Do not treat a favorite's one-goal lead as stable; live tempo confirmation is valuable.
- **Russian Premier League**: travel distance, winter/surface conditions, squad news reliability, and motivation can dominate public ratings. Use smaller stakes when team news is thin. Home favorites may be real, but do not buy deep lines without European/Asian confirmation.
- **AFC Champions League**: travel, climate, foreign-player availability, and home venue quality can outweigh broad league reputation. Gulf/East Asia travel spots require extra rest and weather checks.
- **Chinese Super League**: foreign striker/creator availability, wage and motivation news, travel, heat, and club stability are high-impact. Use smaller stakes unless team news is verified. Do not convert a `60-70%` de-vig win anchor into `-1` or deeper when the favorite has repeated recent draws, a narrow H2H bucket, or unclear foreign-attacker availability. In that profile, downgrade to `-0.75`, moneyline/DNB, live-only, or no bet unless `P(win by 2+)` is independently supported by chance quality, opponent chase incentives, and Asian line value.
- **K League**: physical and tactical, often lower scoring than public perception. Draw and underdog half-win lines matter, but late set-piece risk is real.
- **J1 League**: tactical organization and pressing quality are important. Market can underrate compact mid-table teams against brand clubs. Watch travel/rest and cup rotation.
- **J2 League**: lower scoring and higher draw gravity. Avoid overpaying favorites without clear chance-creation edge. Dog `+0.5/+0.75` can fit, but only when the dog has enough attacking release.
- **A-League Men**: higher BTTS and late-goal variance. Avoid treating a one-goal favorite lead as stable; live entries after tempo confirmation are preferred.
- **Brazil Serie A**: travel, heat, fixture congestion, cup rotation, and home-field intensity are high-impact. Public-name clubs can be overpriced away; prefer home/dog protection or unders only when chance creation and rest support it.
- **Brazil Serie B**: lower scoring, heavy draw gravity, and volatile team news. Do not overpay small favorites; `+0.25/+0.5` and under-style reads need price discipline.
- **Argentina Primera Division**: tactical tempo is often slower and draw gravity can dominate small favorite lines. Derby/emotional spots raise card and rhythm risk; prefer shallow lines or no bet when odds already price the story.
- **MLS**: travel distance, rotation, synthetic turf, altitude, and late-goal variance matter. Home-field and BTTS/overs can be real, but public attacking teams are often taxed.
- **USL Championship**: information quality and liquidity are thinner. Use smaller stakes, require reliable lineups/odds, and avoid high confidence unless market and team news agree.
- **Copa Sudamericana**: two-leg score-state logic is mandatory. Separate `to qualify` from 90-minute handicap, downgrade deep second-leg favorites with aggregate cushions, and price travel/altitude/rest. Do not automatically convert a must-chase second leg into `Over 2.5` or BTTS; first verify the trailing side's away/low-altitude attacking floor, the leading side's transition quality, and whether a one-goal home win is enough to drag the tie into extra time and slow the final phase.
- **Australia Cup**: rotation, semi-pro mismatches, travel, and squad priority dominate. Avoid deep favorites unless lineup quality and finishing tail are verified; otherwise prefer live-only or no bet.

## Pull, Handicap, And Operator Intent Tags

Before every pick, tag the match using both a fundamental pull pattern and an operator intent. These tags are required for future win-rate tracking.

### Fundamental Pull Tags

- `brand_favorite_pull`: famous club, star players, league-table halo, or media story naturally attracts favorite money.
- `football_favorite_pull`: the favorite has a real tactical, xG, lineup, rest, or motivation edge independent of public story.
- `terminal_tail_pull`: the favorite has pace, bench scoring, set pieces, or opponent chase dynamics that raise `P(win by 2+)`.
- `safe_dog_pull`: underdog has defensive reputation, recent clean sheets, low block, derby emotion, or a comfortable `+0.75/+1` story.
- `draw_gravity_pull`: incentives, styles, first-leg state, or league priors make draw materially live.
- `rotation_uncertainty`: cup or congested schedule where lineup uncertainty is large enough to reduce pre-match edge.
- `must_chase_state`: one side must win, improve goal difference, or overturn an aggregate deficit.

### Operator Intent Tags

Use the Chinese labels in reports because they are the core of this upgraded framework:

- **阻上 / block favorite**: the favorite has real pull and the book makes the favorite harder or less profitable to buy by raising the handicap, cutting favorite water, or holding a demanding line despite public hesitation. This can confirm the favorite, but only buy if the cover bucket still beats price.
- **诱上 / induce favorite**: the favorite has public pull and the book leaves an emotionally easy favorite line, attractive low water, or a shallow threshold without sharp European/Asian confirmation. Prefer dog, draw protection, or no bet.
- **阻下 / block underdog**: the underdog has real pull and the book compresses dog water, retreats the favorite handicap, or makes the dog less attractive after sharp support. Dog may be real, but avoid chasing bad water.
- **诱下 / induce underdog**: the underdog entry looks safe because of `+0.75/+1/+1.25`, recent favorite underperformance, or public fear of a narrow game, while the football prior and sharp board still support favorite pressure. Prefer favorite alt-handicap or live favorite entry.
- **降温强队 / de-heat favorite**: a famous favorite's line retreats or looks less glamorous, but the lower threshold mainly removes public tax while terminal-tail and institutional signals remain intact.
- **无效噪音 / noise**: movement is small, inconsistent across books, or explained by temporary liquidity. Do not invent intent.

Line-pattern examples:

- Favorite moves `-0.5` to `-0.75` with Europe also shortening and dog has little counter-pull: likely `阻上` or real favorite confirmation.
- Favorite stays at `-0.5` low water while public loves favorite and Europe does not confirm: likely `诱上`.
- Favorite retreats `-1.25` to `-1` while dog water collapses: likely `阻下`.
- Favorite rises `-0.75` to `-1` and gives dog a comfortable `+1` story while favorite still owns tempo and terminal tail: possible `诱下`.
- Deep favorite rises to `-2` or above only becomes margin confirmation when motivation, team news, score-state, and Europe/exchange all agree.

## High-Win-Rate Pattern Library

Build a pattern library gradually. Never declare an 80% pattern from a tiny sample or one tournament run.

Each pattern must store:

```text
pattern_id | description | competitions | required_conditions | forbidden_conditions | sample_size | hit_rate | process_hit_rate | avg_clv | last_seen | status | notes
```

Pattern status rules:

- `watch`: fewer than 8 comparable cases, or mixed process quality.
- `candidate`: at least 8 comparable cases, hit rate above 75%, positive process notes, and no obvious single-team bias.
- `priority`: at least 15 comparable cases, hit rate above 80%, positive or neutral CLV, and survives multiple competitions or time windows.
- `retired`: edge disappeared, market adapted, or the original definition was too broad.

When a current match fits a `priority` pattern, label it in the cold conclusion and still run the five boards. A high-hit pattern is a spotlight, not permission to skip price discipline.

## Data Hierarchy

Use the most reliable available data in this order:

1. User-provided bookmaker lines, especially opening/current/closing William Hill, Pinnacle, Bet365, or bwin.
2. Sharp or semi-sharp market lines, especially Pinnacle and SBOBet, when available through screenshots, The Odds API, or user input.
3. Public bookmaker aggregators such as 500.com, OddsPortal, BetExplorer, or other readable sources for European odds and Asian handicap movement.
4. Polymarket public event data for prediction-market prices, bid/ask spread, volume, liquidity, settlement terms, and price changes.
5. Exchange/attention data such as Betfair or 必发 when readable. Use it as crowd-flow context, not as a one-sided money ledger.
6. Recent primary/news sources for injuries, lineups, motivation, group situation, venue, and weather.
7. Public analyst/blogger commentary from readable internet sources, especially when they discuss matchup pull, handicap pull, odds movement, betting-volume attention, or public hot/cold narratives. Use these as public narrative and sentiment inputs, not as truth.
8. Explicit model estimates only when live market data is missing. Label them as estimates.

When using public analyst or blogger analysis:

- Separate `football argument` from `betting-flow argument`.
- Mark whether the source is public-facing consensus, team-fan narrative, odds-trader analysis, or news/injury reporting.
- Prefer at least two independent sources when a public-narrative read materially affects the decision.
- If multiple public sources cluster on the same favorite while Asian price refuses to confirm, raise public-tax risk.
- If public sources identify a concrete injury, lineup, rest, weather, or motivation edge that the market has not fully priced, add it to the baseline prior but still require price confirmation before a main pick.
- Cite the source names, links, and publication/update times in the daily report. Do not copy long text; summarize the view and link the source.

Do not fabricate bookmaker odds. If The Odds API key is missing and the user did not provide odds, state the limitation and proceed with public/estimated probabilities.

## Reusable Tools

Use `scripts/odds_market_snapshot.py` when useful:

```powershell
python <skill_dir>\scripts\odds_market_snapshot.py devig --names "Home,Draw,Away" --odds "2.10,3.40,3.80"
python <skill_dir>\scripts\odds_market_snapshot.py polymarket --query "Netherlands Japan"
python <skill_dir>\scripts\odds_market_snapshot.py the-odds --sport soccer_fifa_world_cup --team "Japan" --bookmakers williamhill,pinnacle --markets h2h,spreads
```

Read `references/model.md` when formulas, Kelly sizing, or handicap interpretation needs precision.
For post-match correction, read the calibration sections in `references/model.md` and keep the "retain vs correct" split explicit.

## Workflow

### 1. Fundamentals And Psychology

Start with the football reality:

- Recent 3-5 match form, injuries, suspensions, likely lineups.
- Group-stage incentive: first match, must-win, goal difference, qualification path.
- Style matchup: press resistance, set pieces, transition threat, aerial mismatch, goalkeeper variance.
- Public pull: host nation, star players, European/South American halo, revenge narratives, historic head-to-head.

For final group rounds, explicitly classify match-state incentive:

- **Favorite already safe, opponent can defend for draw**: lower deep-handicap cover-tail; prefer moneyline/draw protection or no bet.
- **Favorite already safe, opponent must win or chase third-place goal difference**: do not automatically buy the underdog. Raise favorite one-goal-win probability and late transition tail, but require extra evidence before buying `-1.25` or deeper.
- **Favorite needs margin for first place or qualification**: line rises from `-1` to `-1.75/-2` can be real margin confirmation, not simple favorite tax.
- **Both sides can live with a draw**: draw gravity dominates; avoid forcing side handicaps unless price is clearly wrong.
- **Underdog must chase after conceding**: `+0.75`, `+1`, or `+1.25` is less safe than the number looks because the match can open after the first goal.

For knockout rounds, separate three markets before any pick: 90-minute result, to-qualify result, and handicap cover. A favorite can have the highest advancement probability while still being a poor 90-minute moneyline or `-1.5` bet. Raise draw/extra-time/penalty tail when the favorite faces a physical or low-block underdog, when the favorite's group-stage dominance came from weak opponents, or when the favorite recently showed defensive/tempo fragility.

State which side the public naturally wants to buy before reading the line. Then classify both sides:

- **Fundamental bullish pull**: fitness, tactical mismatch, squad depth, set pieces, transition speed, elite finishers, late-game substitutions.
- **Fundamental bearish pull**: aging core, travel/rest disadvantage, missing creator/keeper/centre-back, low shot volume, conservative first-match incentives.
- **Public bullish pull**: stars, defending champion status, brand country, recent viral narrative, host/near-home support.
- **Public bearish pull**: "old/slow", "overrated favorite", bad warm-up headline, revenge or underdog sympathy narrative.

Emit a short pull table before any odds interpretation:

```text
side | football pull | public/story pull | terminal-tail pull | natural public side
```

This table prevents post-price rationalization. If the eventual market read changes the initial prior, state what changed it.

Identify terminal-tail ability separately from win probability:

- Elite late killers such as Messi, Mbappe, Haaland, Vinicius-type transition threats, or strong bench forwards raise `P(win by 2+)`.
- Set-piece dominance, aerial mismatch, and opponent late chase behavior also raise cover probability on `-1.25` and deeper lines.
- If a favorite lacks speed, bench scoring, or open-field finishers, discount handicap-cover probability even when moneyline probability is high.

### 2. European Odds De-Vig

For 3-way football odds:

- Raw implied probability: `1 / decimal_odds`.
- Overround: `sum(raw_probs) - 1`.
- True probability: `raw_prob / sum(raw_probs)`.
- Fair odds: `1 / true_probability`.

Use true probabilities to infer the fair match expectation. Compare that expectation with the Asian handicap.

When multiple bookmakers are available:

- Use Pinnacle/SBOBet as the sharp anchor when readable.
- Use William Hill/Bet365/bwin as institutional retail anchors.
- Use 500.com/live odds aggregators as a readable fallback.
- Record opening and current odds separately when both exist.

After de-vigging, state:

```text
European true probability: home/draw/away
Football prior gap: de-vig probability minus baseline prior
Handicap implication: what Asian line should roughly match this probability
```

### 3. Asian Handicap Audit After The Prior

Translate probability into handicap logic:

- `-0.25`: favorite has a small edge but draw remains live.
- `-0.5`: favorite must win; usually needs about 45-50% win probability at fair pricing.
- `-0.75`: favorite is likely to win, but one-goal win only half-wins.
- `-1`: favorite can win by one and push, needs real two-goal equity.
- `-1.75` and deeper: do not ask "will the favorite win"; ask "will the favorite win by enough".

Compare opening, current, and closing lines:

- Same handicap, favorite water down: possible real favorite protection. Check whether the line should have moved up.
- Favorite line moves deeper: market confirms favorite, but the new price may be worse.
- Favorite line retreats and favorite water stays low: reduced threshold can be favorite protection or public-friendly packaging. Use Polymarket and fundamentals to distinguish.
- Underdog water collapses after handicap retreat: bookmaker is protecting the underdog cover.
- Before accepting any low-water side, run a pull-entry mismatch check:
  - If the underdog has little natural pull, but the favorite remains at an easy line such as `-0.5` with attractive low water, the operator may be heating the favorite. Prefer the underdog or no bet unless the favorite's institutional confirmation is strong.
  - If the underdog has obvious natural pull, such as defensive reputation, a "lose by one and push" story, or recent favorite underperformance, and the market raises the favorite line to give the underdog a comfortable entry, treat the underdog as possible induced safety. Prefer the favorite or live favorite entry when the favorite's baseline and institutional signals remain intact.
- Favorite retreats from a hard line such as `-1.5` to `-1.25`: do not automatically call it underdog protection. If terminal-tail ability remains strong and public bearish narratives are loud, this can be favorite de-heating and a lower entry threshold.
- Favorite retreats from `-1.25` to `-1` with underdog low water: this is a stronger underdog-cover warning.
- On `-1.25` and deeper, explicitly estimate `P(favorite wins by 2+)` and `P(favorite wins by exactly 1)`. Do not infer these from moneyline alone.

#### Deep Handicap Audit: `-2` And Above

For `-2`, `-2.25`, `-2.5`, and equivalent underdog lines, treat the market as a score-distribution problem, not a popularity problem. Before recommending a side, output four buckets: `P(favorite wins by 0-1)`, `P(favorite wins by exactly 2)`, `P(favorite wins by 3+)`, and late/garbage-time goal risk.

- Do not buy `+2`, `+2.25`, or `+2.5` just because the line is deep or the favorite is public. First check whether the favorite needs margin for first place, qualification, or goal difference; whether the underdog must chase after conceding; whether the underdog has recent 3+ concessions, xG leakage, weak fullbacks, or poor set-piece defense; whether the favorite has wing pace, bench scorers, or set-piece edge; and whether Asian deepening is confirmed by Europe, Betfair/Polymarket, or closing strength.
- If four or more deep-margin conditions are true, classify the line as **margin confirmation**. Prefer favorite alternatives such as `-1.5`, `-1.75`, or live entry after tempo confirmation; avoid turning the dog into value merely because `+2` looks large.
- If the favorite is already safe, lacks margin incentive, lacks speed/bench finishers, faces a dog that can sit in a low block, or Asian deepening lacks Europe/exchange confirmation, classify the line as **deep favorite tax**. Prefer dog `+2.25/+2.5`, conservative dog alternatives, or no bet.
- For `-2.25`, remember the favorite needs 3+ for a full win and loses half at exactly 2; the underdog `+2.25` half-wins at exactly 2 and loses at 3+. If the edge depends mainly on a two-goal favorite win, downgrade `-2.25/-2.5` and look for `-2`, team total, or live entry.
- Never make `-2.25` or deeper an A-grade pick without an explicit `P(3+)` edge and a clear explanation of why the 0-1 and exactly-2 buckets are not dominant.
- If the available market is Polymarket `-2.5`, evidence for "favorite can win by two" is not enough. Recommend `-2.5 YES` only when the favorite's `P(3+)` clears the executable-price edge buffer after haircut; otherwise prefer `-1.5`, team total, or no bet.

Always classify the operator's likely intent:

- **Protect favorite**: the book reduces favorite payout, holds a playable threshold, or lowers the threshold because favorite cover risk remains real.
- **Protect underdog**: the book compresses underdog water or retreats a key favorite threshold because the favorite's margin risk is weak.
- **Induce favorite**: the favorite has public pull and the line gives an emotionally easy favorite entry without sharp confirmation.
- **Induce underdog**: the underdog entry feels safe because of a push/half-win story, but fundamentals and institutional signals still support favorite pressure.
- **De-heat favorite**: a famous favorite looks weaker or the handicap retreats, but the retreat mainly removes public tax while preserving favorite cover value.

### 4. Polymarket Public-Tax Check

Use Polymarket price as prediction-market implied probability. Normalize the three outcome prices if their sum is not close to 1.

Important: Polymarket `volume` is total traded volume in that binary market, not one-sided betting amount. Use it as attention/liquidity proxy, not as direct "money on Yes". Estimate flow from a combination of:

- outcome price level;
- one-hour, one-day, and one-week price change;
- market volume, 24h volume, open interest, and liquidity;
- outcome-volume concentration relative to the other two outcomes;
- whether the price move confirms or contradicts European and Asian movement.

Do not use Polymarket as the default source of expected-value delta. Treat it as a public-sentiment and attention heat map. When Polymarket outcome volume share is extreme, price is rising, but Pinnacle/SBOBet or the Asian line moves against that same side, classify this as possible public-tax or inducement rather than value.

Do not map Polymarket moneyline directly to Asian handicap. Use Polymarket to update win/draw/loss probability, then separately adjust cover probability with terminal-tail ability and handicap threshold.

#### Polymarket Handicap Execution Gate

For Polymarket handicap contracts, default to **no bet** unless all gates pass:

- **Contract equivalence**: confirm the market question, handicap threshold, settlement rule, and whether pushes/half-wins exist. Do not map Asian `-0.25/-0.75/-1/-1.25` directly to a binary Polymarket spread; convert the score buckets first.
- **Knockout settlement check**: in knockout rounds, explicitly confirm whether the contract resolves on 90-minute score, extra-time score, penalty shootout advancement, or "to qualify". Do not map a sportsbook Asian handicap or 1X2 market to Polymarket until the settlement clock is known.
- **Available-line gate**: if Polymarket only offers `1.5` and `2.5` handicap thresholds, do not quote Asian quarter lines as actionable Polymarket advice. Convert only to the binary thresholds that exist: favorite `-1.5` = `P(favorite wins by 2+)`; favorite `-2.5` = `P(favorite wins by 3+)`; dog `+1.5` = `1 - P(favorite wins by 2+)`; dog `+2.5` = `1 - P(favorite wins by 3+)`.
- **Quarter-line mismatch**: Asian `+0.75`, `+1`, `+1.25`, `+2`, and `+2.25` are reference lines only when Polymarket lacks them. For example, Asian dog `+0.75` loses half on a one-goal favorite win, while Polymarket dog `+1.5` wins; Asian dog `+2.25` half-wins on a two-goal favorite win, while Polymarket dog `+2.5` wins. Recompute the fair probability for the actual Polymarket threshold instead of copying the Asian recommendation.
- **No synthetic mapping**: if the Asian view is "favorite -1" or "dog +0.75", and Polymarket only has `±1.5/±2.5`, the correct output is often "Asian lean only; no direct Polymarket expression" unless the score buckets create independent value at `±1.5` or `±2.5`.
- **Synthetic portfolio gate**: Polymarket legs can be combined to create a quasi-Asian or corridor exposure, but only after a payoff table. For example, buying `favorite wins` plus `underdog +1.5` is not a simple favorite bet; it is a narrow-favorite corridor that profits most when the favorite wins by exactly one and has different downside in dog/draw and favorite blowout states.
- **Synthetic payoff table**: before recommending any combined Polymarket position, list each leg, executable price, stake weight, settlement clock, and net payoff for `dog/draw`, `favorite by exactly 1`, `favorite by exactly 2`, and `favorite by 3+`. If the combined EV is not positive after spread/slippage under conservative bucket probabilities, output no bet.
- **Same-clock rule**: never combine a "to qualify" or shootout-inclusive market with a 90-minute handicap market unless the mismatch is explicitly intended and priced in the payoff table.
- **Legging risk rule**: recommend synthetic portfolios only as limit-order packages or tiny staggered entries. If one leg fills and the other does not, reassess exposure; do not chase the missing leg above the stated max entry.
- **Executable price**: use the price that can actually be filled, not last trade or midpoint. For buying YES use the YES ask. For buying NO use the NO ask, or `1 - YES bid` if only the YES book is visible.
- **Edge buffer**: require the lower bound of the model's fair probability to beat the executable price by at least `6-8` percentage points in liquid markets and `10-15` points in thin or wide-spread markets. If the edge exists only at the midpoint, output no bet.
- **Liquidity and slippage**: if the bid/ask spread is wide, the order book is shallow, or the intended size would move the price materially, output a limit-only order or no bet.
- **Line-shopping check**: compare the Polymarket binary price with the nearest sportsbook/Asian fair price after converting settlement. If Polymarket is already richer than the fair range, the correct recommendation is pass even when the side is directionally right.
- **No-chase rule**: every Polymarket recommendation must include `max entry price`. If the live price is above that ceiling, the recommendation becomes no bet.

#### Polymarket Full Market Menu

When a Polymarket event exposes multiple tabs such as `Game Lines`, `Exact Score`, `Halves`, and `Team Totals`, scan the full menu before choosing a Polymarket主单. Do not stop at moneyline or spreads.

First classify the match type:

- **League match**: there is no match-level `Team to Advance / To Qualify` market. Do not mention advancement for normal league fixtures. Scan only 90-minute match markets such as moneyline, spreads, totals, BTTS, team totals, halves, first team to score, and exact score.
- **Cup knockout / two-leg qualifier / final / playoff**: include `Team to Advance / To Qualify` only when the match or tie has an advancement settlement. Confirm whether extra time and penalties count, and whether the market refers to the tie or the single match.
- **Group-stage cup match**: do not use `Team to Advance` as the match pick unless the market explicitly settles on the group/tournament outcome. Treat it as futures/table-state context, not as a single-match Polymarket主单.

Evaluate available markets in this order:

1. **Team to Advance / To Qualify**: cup-only. Use only for knockout, two-leg ties, finals, or playoffs. Confirm whether extra time and penalties count. Compare with sportsbook qualification odds and aggregate score-state. Avoid paying `95c+` unless it is used as a hedge, because high hit rate can still have poor return and gap risk.
2. **90-minute Moneyline**: compare the three Polymarket outcome prices after normalization with de-vig 1X2 odds. This is not an Asian handicap substitute. Require a clear stale-price or public-overreaction source.
3. **Spreads**: convert the exact binary threshold: `-1.5` means win by 2+, `+1.5` means avoid losing by 2+. Compare with Asian line buckets, not with the headline Asian recommendation.
4. **Totals**: price `O/U 0.5, 1.5, 2.5, 3.5, 4.5` from sportsbook totals, team style, aggregate state, weather, lineup finishing quality, and league prior. For high-win-rate Polymarket candidates, prefer totals where one side of the line is mispriced versus both sportsbook total and game-state logic. Do not buy Over simply because the favorite is strong; ask whether the dog can contribute or whether the favorite needs margin.
5. **Both Teams To Score**: estimate from each team's scoring probability, clean-sheet probability, lineup, and game-state. BTTS is attractive when the favorite should score but the dog has forced-chase or transition/set-piece routes. BTTS No is attractive when the dog lacks creation and the favorite can control without opening the game.
6. **Team Totals**: use implied team goals from 1X2, total, and handicap. Prefer team total over spread when the favorite can score but the dog may also score, or when the dog scoring suppression is the edge.
7. **Halves / First Half**: use only when lineups, tempo, travel, and first-leg state support a first-half edge. Default to no bet in thin markets because variance and settlement ambiguity are high.
8. **First Team To Score**: default no bet unless the contract has real liquidity, the price is materially stale, and one team's early-pressure/clean-entry profile is strong. Treat `Neither` as a separate 0-0 path and never compare it directly with team scoring price.
9. **Exact Score**: default no bet. Exact-score bets are high variance and usually fail the edge buffer. Use only as tiny optional overlays when the payoff is clearly stale versus the score-bucket model; never call exact score a main pick.

For each analyzed match, output a compact Polymarket scan table:

```text
市场 | 当前价格 | 模型保守胜率 | 最高买入价 | 流动性 | 结论
```

Select at most one Polymarket主单 per match unless a synthetic portfolio passes the payoff-table gate. Prefer `no bet` over a low-quality Polymarket pick. A high hit-rate requirement means:

- For prices below `0.60`, require both positive expected value and a realistic win probability above `55%` unless it is explicitly a small asymmetric value trade.
- For prices `0.60-0.85`, require at least `6-8` points edge in liquid markets and a clean settlement clock.
- For prices above `0.85`, require a clear hedge or stale-price reason; otherwise classify as `too expensive / no bet` even if likely to win.
- For thin markets below roughly `$1k` volume or wide spreads, raise the edge buffer to `10-15` points and cap stake at `0.05%-0.15%`, or no bet.

#### Positive-EV Betting Discipline

To turn analysis into positive expectation, require all six filters before a bet:

1. **Mispricing source**: identify why the market is wrong. Valid sources include stale Polymarket price versus sharp sportsbook movement, wrong settlement interpretation, public overreaction to name/team narrative, unavailable Asian quarter line causing bad binary pricing, or underpriced score-bucket corridor.
2. **Conservative probability**: use `p_low`, not the midpoint or optimistic case. Apply an uncertainty haircut for missing team news, thin books, unclear settlement, or model disagreement.
3. **Executable edge**: compute `edge = p_low - executable_price` for a binary YES/NO leg, or portfolio EV from the payoff table for synthetic positions. If edge does not clear the buffer, stake is zero.
4. **Price discipline**: use limit orders only. The recommendation must include `max entry`; above that price the bet becomes no bet, even if the side remains directionally correct.
5. **Selectivity**: expect most matches to be no bet. In World Cup group or knockout slates, a healthy process may pass on `70-90%` of markets. Forcing a bet every match is negative expectation.
6. **Post-entry audit**: track closing-line value, not only match result. A bet that wins after being bought above fair value is a bad process; a bet that loses after beating the closing/fair line may still be retained.

Prefer these positive-EV setups:

- **Stale Polymarket vs sharp Asia/Europe**: sportsbook line moves but Polymarket binary threshold lags. Buy only before Polymarket catches up.
- **Narrow-win corridor**: favorite has high win probability but low `P(2+)`; consider synthetic `favorite wins + underdog +1.5` only if the payoff table shows strong value on exactly-one-goal wins.
- **Exact-two separation**: when `P(exactly 2)` is high, prefer `favorite -1.5` over `favorite -2.5`, or dog `+2.5` over dog `+1.5`, depending on price.
- **Public overpay**: if public buys favorite `-2.5` above fair because the favorite is famous, consider dog `+2.5` only when `P(3+)` is clearly below market after margin-incentive checks.
- **Live confirmation**: when pre-match price is close to fair, wait for tempo, lineup, shot quality, and pressing evidence rather than paying pre-match uncertainty.

When Betfair/必发 or similar exchange data is available, read it the same way:

- Treat traded volume and liquidity as attention/consensus quality.
- Treat odds drift and traded-price concentration as sentiment, not as proof of smart money.
- If exchange crowd heat and Polymarket both chase a public side while Asian handicap refuses to confirm, classify a reverse-emotion warning.
- If exchange/Polymarket support aligns with Pinnacle/SBOBet and Asian line movement, upgrade confidence one level only if the football prior also supports it.
- For group-winner Polymarket markets, treat price as table-state information before treating it as sentiment heat. A very high group-winner price plus Asian confirmation can support favorite control or one-goal win; it is not automatically a reason to buy the match underdog.
- When 必发/Polymarket favorite heat, European de-vig, and Asian line movement all point the same way, classify it as institutional confirmation unless a specific football or incentive reason contradicts it. Reverse only when the Asian board refuses confirmation or the handicap threshold has become too hard for the favorite's terminal-tail.

### 5. Three-Stage Filter And Staking

Filter probabilities in this order:

1. Start with the baseline prior: win probability, draw risk, and terminal-tail cover probability.
2. Apply the institutional correction: de-vig Pinnacle/SBOBet/William/Bet365 and compare the Asian handicap with the baseline.
3. Apply the public-tax filter: check Polymarket volume concentration, price heat, media narratives, and public-book movement.
4. Convert to a final range, not a single false-precision number, when data is incomplete.
5. If the public-tax filter conflicts with the institutional correction, lower confidence and prefer alt-handicap or live entry.

Output separate recommendations:

- Asian handicap: best cover value, playable line, stop line, and whether the side is main bet, lean only, live-only, or no bet.
- European odds: moneyline/draw/cold protection if value exists.
- Polymarket: Yes/No only if the executable price is materially mispriced after spread, slippage, liquidity, and settlement conversion.

Every pre-match report must include both an **Asian handicap plan** and a **Polymarket plan**. Do not let one replace the other:

- **Asian handicap plan**: state the recommended Asian line such as favorite `-0.75`, dog `+1.25`, or no bet; include the line that is still playable and the line/water where the bet must be abandoned.
- **Polymarket plan**: state the actual binary threshold such as `±1.5` or `±2.5`, a 90-minute moneyline, a to-qualify market, or a synthetic portfolio such as `favorite wins + dog +1.5`; include max entry, payoff bucket, liquidity grade, and order type. If Polymarket has no equivalent, say `no direct Polymarket expression`.
- If the Asian plan and Polymarket plan point to different expressions, explain why using score buckets. For example, Asian dog `+0.75` may be wrong while Polymarket dog `+1.5` is right when the favorite wins by exactly one.
- Every daily report must include a separate **Polymarket主单** section after the Asian handicap main picks. If no contract passes the gate, write `Polymarket主单：无；仅允许以下限价挂单/全部不买` and list the rejected contracts with the no-chase price.
- A Polymarket recommendation is only a **主单** when all execution gates pass: contract equivalence, settlement clock, bid/ask, spread, liquidity, conservative fair probability, edge buffer, max entry, and stake cap. If the side is directionally right but the live price is too high, record it as `limit-only` or `no bet`, not as a main pick.
- Never copy an Asian line into Polymarket. Asian `-1` is not Polymarket `-1.5`; Asian `+0.75/+1` is not Polymarket `+1.5`. Recompute the actual binary bucket before giving any Polymarket主单.
- Track Asian picks and Polymarket picks separately. Their hit rates, process grades, and rule updates must not be merged because settlement thresholds and liquidity are different.
- Do not combine different scoring markets into one actionable pick row. `Over 2.5`, `Over 3.5`, and `BTTS Yes` must be recorded as separate picks with separate trigger prices, stakes, results, and PnL. If one is only a backup expression, record the primary executable pick and put the backup in watch/no-bet notes instead of writing `Over or BTTS` as one main pick.

The final recommendation must choose an entry type:

- **Main handicap**: when line, water, and cover-tail all agree.
- **Alt handicap**: when the side is right but the headline threshold is too hard.
- **Moneyline/draw protection**: when win probability is strong but cover-tail is thin.
- **Polymarket Yes/No**: when the executable contract price is materially below the conservative fair-probability range and the order can be filled without chasing.
- **Live-only**: when pre-match price is fair but the first 15-30 minutes can reveal tempo, lineup intent, or pressing quality.
- **No bet**: when boards conflict or the edge is below cost.

Use Kelly only after estimating true probability:

- Decimal odds: `f* = (p * O - 1) / (O - 1)`.
- Polymarket Yes share at price `c`: `f* = (p - c) / (1 - c)`.

Kelly staking must use the **executable odds from the exact venue requested by the user**. Do not run Kelly with a generic odds range, an odds aggregator midpoint, or a different bookmaker when the user names a venue such as Betway, Bet365, Pinnacle, Stake, or Polymarket. If the exact venue price cannot be verified, say `指定平台赔率未确认` and output only the **minimum executable odds required** for a bet, not a stake recommendation.

For every Kelly calculation, record:

- source venue, such as `Betway`, `Pinnacle`, `Stake`, or `Polymarket`;
- timestamp and timezone of the observed price;
- market type and settlement clock, such as `90分钟BTTS Yes`, `90分钟Moneyline`, `Asian Handicap`, or `Polymarket Spread +1.5`;
- executable decimal odds or share price;
- model probability used, and whether it is historical hit rate, adjusted model probability, or conservative lower-bound probability;
- full-Kelly fraction;
- fractional-Kelly multiplier;
- minimum stake constraint;
- final action: `bet`, `no bet: Kelly negative`, `no bet: below minimum stake`, or `no bet: venue odds unavailable`.

When the user gives a bankroll and minimum stake, the minimum stake changes the entry gate. For decimal odds:

```text
full_kelly = (p * O - 1) / (O - 1)
stake = bankroll * fractional_kelly * full_kelly
```

If `stake < minimum_stake`, the result is `no bet: below minimum stake`. Do not round a sub-minimum Kelly stake up to the platform minimum.

For planning before the exact venue price is known, calculate the minimum odds required to make the minimum stake valid:

```text
required_full_kelly = minimum_stake / (bankroll * fractional_kelly)
minimum_decimal_odds = (1 - required_full_kelly) / (p - required_full_kelly)
```

This gate is stricter than break-even odds. A side can be positive EV but still fail the user's minimum-stake Kelly gate.

Recommend only defensive fractional Kelly:

- Normal edge: `0.15-0.25 Kelly`.
- Do not use `0.5 Kelly` in football betting markets.
- High-variance cup, derby, low-liquidity, travel-heavy, or lineup-uncertain bets: cap single-match exposure at `0.25%-1.0%` of bankroll unless the user asks otherwise. Liquid top-league matches with verified team news can use `0.5%-1.5%` caps when the edge survives price checks.
- For Polymarket handicap contracts, do not use point-estimate Kelly. Use the lower bound of the fair-probability range after uncertainty haircut. If `p_low - executable_price` is below the edge buffer, stake is zero.
- Cap Polymarket handicap exposure at `0.25%-0.75%` of bankroll by default, even when the model likes the side. Increase only when the price is stale versus sportsbook fair value, liquidity is real, and the edge survives a conservative haircut.
- Prefer limit orders. Never recommend chasing a Polymarket handicap after the price moves past the stated max entry.
- For deep favorites, prefer alt-handicap or live entry when the main line is sealed at expensive water.
- If recommending a deep favorite such as `-1` or deeper, define a rolling defense line: for example, if halftime is `0-0` and the favorite has not created enough by minute 60, hedge down to `-0.5`, moneyline, or reduce exposure through live betting.

### Deep-Favorite / Strong-Handicap Value Rule

For matches where one side is a clear class favorite and the Asian handicap is expected to be `-1` or deeper, do not treat 90-minute moneyline as a meaningful betting edge by default. A low-price European win only proves the side is likely to win; it does not answer whether the handicap price is tradable.

Rules:

- Do not upgrade a deep favorite's 90-minute ML to a main pick when the payout is thin, such as decimal odds below `1.70` or Hong Kong water below `0.70`.
- In strong-handicap matches, the primary analysis must be Asian handicap: opening line, current line, water movement, whether the book is protecting the favorite, blocking favorite money, inducing dog money, or forcing favorite money into a bad price.
- If the only readable market is a low-price ML and no Asian handicap water is available, classify the row as `仅模拟/无交易价值`, not `可投`.
- For simulation ledgers, avoid writing `强队ML` as the primary simulated market in these spots. Prefer `让球盘待核`, `替代让球 -1/-1.25/-1.5`, `强队穿盘观察`, or `跳过真实投注`.
- Only consider real-money action when the selected Asian handicap side has Hong Kong water `>0.70` or the equivalent decimal odds `>1.70`, and the Kelly edge remains positive after the price check.

### Moneyline / DNB Eligibility By Asian-Line Depth

Before using any 90-minute win/loss market or no-draw protection market, first map the match to the closest Asian handicap line.

Rules:

- `90分钟胜负盘 / ML` is meaningful only when the Asian handicap is within a half-ball line, meaning `0`, `-0.25`, `+0.25`, `-0.5`, or `+0.5`. If the favorite is priced deeper than `-0.5`, do not use ML as the primary simulated or real-money market; analyze the Asian handicap instead.
- `不败盘 / DNB / draw-protected side` is meaningful only when the Asian handicap is within a quarter-ball line, meaning `0`, `-0.25`, or `+0.25`. If the true handicap is beyond a quarter-ball, do not use DNB/no-draw protection as the primary market because the payout is usually not enough for the risk.
- When the Asian line is deeper than the allowed threshold, write `胜负盘无交易价值-转亚盘` or `不败盘赔率不足-转亚盘` in the recommendation table.
- Do not let a high model win probability override this market-eligibility gate. Price depth decides the market type first; Kelly is calculated only after a valid market type and executable price are available.
- In simulation rows, if Asian depth is unknown for a likely favorite, mark the row `亚盘深度待核` rather than defaulting to ML or DNB.

### Totals / BTTS Tactical Goal Model

Over/under and BTTS are separate frameworks from match winner and Asian handicap. Do not decide totals from league stereotypes such as `this league is over` or `this league is dry` unless the historical sample is explicit, current, and comparable.

Before any totals or BTTS simulation/recommendation, record these inputs:

1. **Recent goal profile**: last 5-10 matches for each team: goals scored and conceded per match, xG/xGA when available, shots, shots on target, big chances, set-piece threat, clean-sheet rate, and failed-to-score rate.
2. **Half split**: first-half and second-half goals scored/conceded; whether the team starts fast, scores late, collapses late, or protects leads. For 90-minute markets, extra-time goals never count unless the contract explicitly says otherwise.
3. **Tactical matchup**: possession attack vs low block, high press vs buildup weakness, counterattack vs high defensive line, two transition teams creating broken-game pace, set-piece mismatch, favorite tempo control after leading, and underdog chase ability after conceding.
4. **Game-state incentives**: league table pressure, relegation/qualification motivation, cup aggregate score, first leg vs second leg, away-goal rule if any, group tiebreakers, and whether either side benefits from a draw.
5. **Market confirmation**: total line/water movement, BTTS price movement, whether over money is public narrative or sharp confirmation, and whether the Asian handicap implies one-sided scoring rather than both teams scoring.

Classify totals/BTTS picks with one of these tags:

- `快节奏互攻`: both sides create and allow transition chances.
- `强弱分层大球`: favorite can score 2+, but BTTS may fail if dog attack is weak.
- `反击兑现BTTS`: favorite possession plus dog counter route makes BTTS more attractive than over.
- `控场降速小球`: stronger side likely leads and slows tempo.
- `杯赛/两回合压低`: aggregate or knockout incentives reduce risk appetite.
- `落后追分放大`: table or aggregate state means a conceded goal can open the game.
- `半场错位`: first-half under but full-time over, or fast-start first-half over but late tempo drop.

Market selection rules:

- Prefer BTTS Yes only when both teams have real scoring routes. A high total caused only by one favorite's scoring tail should be treated as team-total or favorite handicap, not BTTS.
- Prefer over when both the pace profile and game-state incentives support multi-goal paths.
- Prefer under when the favorite can control tempo, the underdog has weak chance creation, or cup/two-leg state rewards patience.
- For first-half totals, use first-half tempo and early-goal profile, not full-match goal average.
- For second-half/live totals, use fatigue, bench impact, chase state, and late-goal tendency.
- If recent goal data and tactical matchup are missing, mark totals/BTTS as `证据不足-仅观察`; do not make it a main pick.

Hard gate after the 2026-08-23 goal-market audit:

- Any pre-match `大小球 / BTTS / 双方进球 / 队伍进球数 / 总进球数` simulation must pass the **goal-model evidence gate** before it can show a direction such as `小2.5`, `大2.5`, or `双方进球Yes`.
- Required fields are:
  1. `近5-10场进球画像`: goals for/against, xG/xGA or shots/SOT/big chances, plus home/away split when relevant.
  2. `射手与创造者状态`: main striker, creators, set-piece takers, confirmed or probable lineup/absences, and replacement quality.
  3. `风格克制与比赛状态`: whether the matchup creates high press errors, counterattack space, low-block stalemate, set-piece mismatch, cup aggregate chase, draw incentive, or lead-protection behavior.
  4. `进球时间分布`: first-half/second-half tendency, early-goal/late-goal profile, whether the team keeps attacking after scoring, or switches to defense/counterattack.
  5. `历史交锋与近况可比性`: head-to-head and recent comparable opponents, with stale/non-comparable samples labeled.
  6. `盘口价格确认`: totals/BTTS opening and current line/water or executable Polymarket/sportsbook price; also note whether Asian handicap implies one-sided scoring rather than both teams scoring.
- A direction can be simulated only when at least `4 of 6` fields are populated, and the four must include: recent goal profile, scorer/creator status, tactical/game-state read, and market price confirmation.
- If those four mandatory fields are not present, do **not** recommend real-money action and do **not** put the row in the Kelly/主单 queue. However, if the user requires full-slate simulation, keep a clearly labeled paper direction such as `纸面模拟：小2.5` or `纸面模拟：双方进球Yes` with a small virtual audit stake. Display `真实下注：不投/凯利0` separately from `纸面模拟方向`, and tag the row `证据不足-纸面验证`.
- Paper-only goal-market rows may be settled later for model diagnostics, but they must be reported separately from executable recommendations and high-confidence hit-rate statistics.
- Do not infer `BTTS Yes` from an under/over lean, and do not infer under/over from a BTTS lean. These are separate markets with separate scoring paths.
- Do not use `2.5` as a default placeholder for totals. If the actual totals line and over/under water are not matched from Titan007, Polymarket, sportsbook/API, or a user screenshot, write `真实大小球盘口未匹配` and keep only a generic paper lean such as `纸面模拟：小球方向` or `纸面模拟：大球方向`. Do not display `小2.5`, `大2.5`, `U2.5`, or `O2.5` unless the 2.5 line was actually observed before kickoff or explicitly labeled as a hypothetical test line.
- Stronger correction after the 2026-08-23 audit: if the actual totals line and over/under water are not matched, do **not** output a totals-market direction at all, even as paper simulation. The row must say `大小球盘口缺失-不形成模拟`, `真实下注不投`, and `凯利0`. You may write a non-market note such as `进球倾向观察`, but it must not be counted as a simulated totals pick or settled against a totals result.
- Apply the same stronger correction to BTTS and all secondary markets: if the exact market price is missing, do not output `双方进球Yes/No`, team-total, first-team-to-score, corners, halves, or exact-score direction. These can only be non-market observation notes until the exact market line and price are captured.

## Output Format

### Mandatory Daily Display Fields

For every daily update, simulation table, Asian main pick, and Polymarket main pick, display the following fields in Chinese:

- `中文比赛`: use Chinese team names. If a club has no stable Chinese translation, show `中文名（英文原名）`.
- `北京时间`: show kickoff in Asia/Shanghai time with date and time, such as `2026-08-22 19:35`.
- `具体盘口`: state the exact market and line, such as `亚盘 主队 -0.25`, `大小球 U2.5`, `BTTS Yes`, `DNB 主队`, `Polymarket Moneyline 主胜 Yes`.
- `历史赔率/价格依据`: show the historical league/market hit rate used for the model probability, and when available show recent executable odds or price snapshots by venue. Do not call a price "history" unless it is actually recorded before kickoff; otherwise label it `当前可执行价` or `指定平台赔率未确认`.
- `模型概率`: show the probability used in the Kelly calculation, preferably as a range when uncertainty is high.
- `凯利公式测算`: show decimal odds/share price, full-Kelly fraction, fractional-Kelly multiplier, bankroll, minimum stake, computed stake, and final action.
- `结论`: show `可投`, `不投-凯利为负`, `不投-低于最低投注额`, `不投-指定平台赔率未确认`, or `仅模拟`.

Do not hide these fields in notes. If the table would be too wide, split it into `基础信息` and `凯利测算` tables rather than dropping columns.

### Simulation Ranking Rule

Daily simulated picks must be sorted by a combined **win-rate plus price quality** score, not by kickoff time or raw confidence alone.

Use this priority order:

1. Exclude or downgrade rows with `指定平台赔率未确认`, missing settlement clock, or missing pre-match line.
2. Rank first by comparable historical hit rate for the exact framework bucket, league/competition family, and market type. Prefer samples with at least `8` countable records; mark smaller samples as `小样本`.
3. Convert the best available executable decimal odds or Polymarket share price into implied probability and compare it with the model probability. Positive edge is required before any real-money action.
4. Use Kelly as the final sorting tiebreaker: higher computed stake after fractional Kelly and minimum-stake gate ranks above lower or zero stake.
5. When odds are unavailable, keep the row in the simulation table but place it below verified-price rows and label the action `仅模拟/赔率待核`.

The displayed order should therefore be:

`可投 Kelly金额高` -> `可投 Kelly金额低` -> `正EV但低于最低投注额` -> `仅模拟/赔率待核` -> `低胜率观察` -> `不投`.

For a daily slate update, output in this order:

1. Date/timezone, competitions covered, and a table of all covered matches for the day.
2. Prior-day review table with result, handicap outcome, process grade, and error type.
3. Running stats: overall hit rate, market-type hit rate, operator-intent-tag hit rate, and any `candidate` or `priority` patterns.
4. Today's match shortlist: full-analysis candidates, watch-only matches, and no-market/missing-data matches.
5. 拉力-价格-流动性公开表: for each shortlisted match, show football/public pull, European/Asian price, Polymarket price if any, liquidity, and the failed or passed gate.
6. 模拟投注表: one paper pick for every readable match, with framework bucket, market type, simulated price/line, reason, and whether it is also a main pick.
7. Public analyst/blogger view summary: sources checked, public side, handicap/volume interpretation, and whether it confirms or contradicts the five-board model. If no reliable public commentary was found, say so.
8. Asian handicap main picks: line, playable price, stop line, stake, and intent tag.
9. Polymarket main picks: contract name, exact settlement/threshold, live price, max entry, liquidity grade, stake, and no-chase condition. If no Polymarket bet passes, explicitly say no Polymarket main pick and list limit-only levels if useful.
10. Full five-board reports for each analyzed match.
11. Asian picks ledger rows, Polymarket picks ledger rows, and simulated-bet rows ready to append under `D:\codex\outputs\football_odds_trader`.

Keep the report direct:

1. Cold conclusion and bet/no-bet.
2. 基本面拉力: football pull, public/story pull, terminal-tail ability, and natural public side.
3. 欧赔去水: raw odds, overround, true probabilities, and football-prior gap.
4. 亚盘真实意图: opening/current handicap, water movement, pull-entry mismatch, `阻上/诱上/阻下/诱下/降温强队/无效噪音` classification, recommended Asian handicap, playable line, and stop line.
5. Polymarket/必发反向情绪: prices, volume/liquidity/price changes when available, and whether sentiment confirms or contradicts Asia/Europe.
6. Polymarket execution: exact available handicap line such as `±1.5` or `±2.5`, executable bid/ask, spread, liquidity, settlement conversion, fair-probability range for that exact threshold, edge buffer, and max entry price. If the Asian line has no direct Polymarket equivalent, say so and default to no bet or limit-only. If using a synthetic portfolio, show the leg table and payoff by score bucket before giving stake size.
7. Positive-EV gate: mispricing source, conservative `p_low`, executable edge, max entry, no-chase condition, and whether the bet should be pre-match, live-only, limit-only, or no bet.
8. 最终盘口选择: final probability range, main/alt handicap, moneyline/draw protection, Polymarket Yes/No if any, Kelly sizing, and portfolio weight.
9. Score scenarios and live-betting defense line. For `-2` or deeper, include the deep-handicap buckets: favorite wins by `0-1`, exactly `2`, and `3+`, plus whether the main line should be replaced by `-2`, an alt handicap, team total, live entry, or no bet.
10. Polymarket主单/挂单: exact contract, current price, max entry, liquidity grade, stake, and whether it is `main pick`, `limit-only`, or `no bet`.

For post-match review, use a separate table with:

- `original_pick`: what the model actually recommended before kickoff.
- `current_model_pick`: what the corrected model would recommend with only pre-match information.
- `result`: the actual score and handicap outcome.

Do not mix these columns.

For post-match calibration, add a short `retain / correct / new rule` note:

- **Norway vs France style miss**: retain skepticism toward public favorite heat, but correct the shortcut that high 必发 favorite volume plus group-winner heat equals fade. If the favorite's European de-vig, exchange flow, group table, and Asian line rise all confirm, and the opponent must chase, the underdog `+1/+1.25` can be a trap rather than protection.
- **Spain vs Uruguay style miss**: retain the rule that a favorite needing only a draw has lower deep-cover tail, but do not turn that into an underdog `+0.75` buy when the underdog must win and the favorite owns control quality. At `-0.75`, a professional one-goal favorite win is enough to make the underdog lose half; prefer favorite `-0.5`, draw protection, or pass.
- **Senegal vs Iraq style hit**: keep the rule that a final-round team chasing third-place or goal difference against a weak opponent can justify a deepening line. A move from `-1/-1.25` to `-1.75/-2` is not automatically favorite tax when motivation and mismatch both point to margin.
- **Cape Verde vs Saudi style push/no-bet**: keep pass discipline when de-vig is balanced, handicap is near `0`, and exchange signals do not break the tie. A correct no-bet is part of the model.
- **Egypt vs Iran style hit**: keep the rule that a high draw probability can dominate a small favorite handicap. When 必发 draw volume, de-vig draw probability, and group table all point to draw gravity, prefer underdog `+0.25`, draw protection, or no bet instead of forcing the nominal favorite `-0.25`.
- **Belgium vs New Zealand style miss**: correct the shortcut that a deep favorite line plus favorite heat means underdog value. If the favorite needs a multi-goal win for first place or qualification, the opponent has already shown defensive leakage, and the line rises from `-1.5/-1.75` to `-2.25/-2.5` with European and exchange confirmation, treat the deep line as margin confirmation. Do not buy `+2/+2.25` unless the favorite's lineup, tempo, or finishing tail is clearly downgraded.
- **Germany vs Paraguay style miss**: correct the shortcut that "favorite should qualify" means "favorite should win in 90 minutes or cover `-1.5`". In knockout rounds, a resilient underdog can drag the favorite into a 90-minute draw and penalties. For brand favorites coming off uneven group form, require a separate 90-minute edge and tempo/margin evidence before buying favorite spread; otherwise prefer underdog `+1.5`, draw protection, live entry, or no bet.
- **Mexico vs Ecuador style miss**: correct the shortcut that a host favorite with historical knockout anxiety must remain a one-goal/corridor team. When the host has consecutive clean sheets, strong first-half tempo, crowd/altitude or venue edge, and the opponent's attack is blunt, the favorite `-1.5` bucket can be underpriced. Do not buy the dog `+1.5` solely because the matchup looks tense; require evidence that the dog can create enough chances after conceding.
- **USA vs Bosnia style exact-two correction**: correct overuse of the narrow-win corridor when a home favorite has repeated two-goal wins, set-piece or late-shot tail, and the opponent lacks comeback creation. In that profile, `favorite -1.5` may be better than `favorite win + dog +1.5`; explicitly compare `P(exactly 1)` with `P(exactly 2)` before choosing the corridor.
- **Spain/Austria and Switzerland/Algeria style margin confirmation**: in early knockout rounds, do not flatten every favorite into a one-goal/cautious profile. If the favorite has group-stage clean sheets or repeated two-goal wins, a midfield/wing chance-creation edge, and the opponent showed 2+ goal defensive leakage or must chase after conceding, raise the `P(2+)` and sometimes `P(3+)` buckets before recommending dog `+1.5/+2.5` or a narrow-win corridor. This is still price-gated: Polymarket `-1.5` or `-2.5` is a bet only below max entry after the edge buffer, not merely because the favorite is likely to win.
- **Argentina vs Cape Verde style miss**: correct the shortcut that a defending champion or iconic favorite automatically deserves a deep 90-minute handicap against a debutant or tiny-nation underdog. If the favorite can dominate xG but plays at a controlled tempo, the dog has an elite shot-stopping goalkeeper, compact rest-defense, strong emotional buy-in, and limited but high-quality transition/set-piece routes, raise the 90-minute draw and dog `+1.5/+2.5` buckets. In knockout rounds, separate "favorite to qualify after extra time" from "favorite covers `-1.5` in 90 minutes"; prefer live confirmation or dog handicap unless early shot quality and box entries prove the deep tail.
- **Canada vs Morocco style miss**: correct the shortcut that a host underdog's first-half press, rest edge, or crowd energy makes `+1.5` safe. If the favorite has tournament knockout experience, compact defending, clinical second-half counters, and the host's key creator/fullback is not fully fit or not starting, raise the favorite `P(2+)` even when the dog can look lively early. High press plus late fatigue can turn dog `+1.5` into a trap.
- **France vs Paraguay style deep-tail correction**: retain favorite-moneyline strength but downgrade `P(2+)` when a physical underdog can turn the match into fouls, stoppages, low rhythm, and box-entry denial. Possession, corners, and territorial control are not enough for `-1.25/-1.5` if shot quality is mediocre and the referee allows disruptive contact. Prefer `-1` push protection, live entry after clear chance quality, or pass on deeper lines.
- **Polymarket handicap execution miss**: correct any answer that turns a directional handicap lean into a Polymarket bet without checking executable price, spread, liquidity, settlement conversion, and max entry. The revised recommendation should often be "lean only, no Polymarket bet" when the price is fair or expensive.
- **Polymarket line-availability miss**: correct any answer that references Asian `0.25/0.75/1.0/1.25/2.0/2.25` handicaps as if they can be traded on Polymarket. When only `1.5` and `2.5` are listed, recompute `P(2+)` and `P(3+)` and ignore non-tradable Asian thresholds for execution.
- **Polymarket synthetic-portfolio miss**: correct any answer that recommends combined legs such as `favorite wins + underdog +1.5` without a four-bucket payoff table, same-clock settlement check, and legging-risk plan. A synthetic portfolio is valid only when the combined payoff profile matches the intended view and the conservative EV remains positive after spread/slippage.
- **Canada vs South Africa style corridor hit**: retain the narrow-win corridor concept when a favorite is likely to win but unlikely to win by 2+. However, a result hit is not proof of positive EV. For `favorite win + underdog +1.5`, compare combined cost with `1 + P(favorite wins by exactly 1)` after haircut and edge buffer; if the package cost is too high, mark it as lucky outcome/bad price.
- **Positive-EV process miss**: correct any answer that wins or loses based only on match outcome. Review whether the entry had a real mispricing source, beat the executable/closing fair price, and passed the edge buffer. A lucky win bought above fair value should be marked as bad process; an unlucky loss bought below fair value can be retained.

When the data is incomplete, say exactly what is missing and give conditional advice such as "buy Japan +0.5, but not Japan +0.25".

### Titan007 Odds Snapshot Source

When the user provides or approves Titan007 / 7M live odds as an odds source, use it as a stable snapshot source before falling back to manual browser operation.

Approved source page:

- `https://live.titan007.com/oldIndexall.aspx`

The page loads API-like static files from `https://livestatic.titan007.com/vbsxml/`. Requests must include a fresh timestamp parameter, browser-like User-Agent, and Referer `https://live.titan007.com/oldIndexall.aspx`.

Use and save these files:

- `bfdata_ut.js`: fixture id, league Chinese name, home/away Chinese names, Beijing kickoff time, match state, score, initial AH/total hints.
- `sbOddsData.js`: pre-match/opening and current full-time/half-time Asian handicap, European 1X2, and totals.
- `ch_goalbf3.xml`: live/changed AH, 1X2, and totals values when available.

Use the local parser:

- `D:\codex\tools\fetch_titan007_odds.py`

Save raw snapshots and parsed CSV under:

- `D:\codex\outputs\football_odds_trader\raw\titan007\YYYYMMDD\`

Daily reports must display Titan007 odds when available:

- `亚盘开盘`: home water, line, away water from `ah_full_open_*`.
- `亚盘即时`: home water, line, away water from `ah_full_current_*`, or `xml_ah_*` when live XML is fresher.
- `欧赔开盘`: home/draw/away from `euro_full_open_*`.
- `欧赔即时`: home/draw/away from `euro_full_current_*`, or `xml_euro_*` when live XML is fresher.
- `大小球开盘`: over water, total line, under water from `total_full_open_*`.
- `大小球即时`: over water, total line, under water from `total_full_current_*`, or `xml_total_*` when live XML is fresher.

Do not fabricate Betway, Pinnacle, Polymarket, Betfair, or other venue prices from Titan007. Label the venue clearly as `Titan007快照`. If a user asks for Betway specifically and only Titan007 is readable, write `Betway赔率未确认，Titan007快照如下`.

For Kelly calculations from Titan007 Asian handicap or totals, convert Hong Kong water to decimal odds as `decimal = 1 + HK_water` when the quoted water is positive. If the row uses European odds, use the displayed decimal odds directly.

If Titan007 has odds but the fundamental minimum is missing, the row may be simulated, but real-money action must be downgraded to `仅模拟-基本面未核`. A main pick requires at least one concrete football input and one market-pull input.

### Local Backup And Dashboard Update Workflow

For every future daily football update, perform a local backup before changing reports, ledgers, or the HTML dashboard.

Backup scope:

- `D:\codex\skills\worldcup-odds-trader\SKILL.md`
- `D:\codex\tools\build_football_daily_update.py`
- `D:\codex\tools\build_football_dashboard.py`
- `D:\codex\outputs\football_odds_trader\dashboard\index.html`
- the current-day daily report and current-day simulation CSV if they already exist
- the latest grouped edge review `.md` and `.csv` files if they already exist

Save backups under `D:\codex\outputs\football_odds_trader\backups\` or as a timestamped zip directly under `D:\codex\outputs\football_odds_trader\`. Do not write backups to `C:\Users\Administrator\Documents\Codex`.

After the backup, every daily update must refresh the HTML dashboard. The dashboard must expose both the user's four-column trader view and the extra mandatory skill fields:

1. **Left rail**: date selector and the simulated matches for that date, sorted by price-verification status, historical win-rate/price quality, and Kelly stake when available.
2. **Market board**: Asian handicap, 1X2 European odds, totals, BTTS, and Polymarket/Betfair fields when available; show opening and current prices separately and label the source.
3. **Form board**: head-to-head, last-five results, goals, handicap record, totals record, and BTTS record; if not available, show `未接入/待核` rather than inventing data.
4. **Fundamental board**: injury/lineup, motivation, rest/travel, tactical matchup, public/story pull, Asian intent, European de-vig status, and funds/flow separated into `真实投注量`, `流动性`, and `盘口价格流`.
5. **Historical edge board**: same-market hit rate, same-league hit rate, same-league-plus-market hit rate, sample size, PnL, and whether the sample is `小样本观察`, `可用样本`, or `优先模式`.
6. **Execution board**: model probability or historical proxy, Kelly calculation, bankroll, minimum stake, final bet/no-bet reason, Asian main pick, Polymarket main pick or no-chase limit, settlement clock, max entry price, and evidence-completeness status.
7. **Review board**: original pick, current model pick if reviewed, result, handicap outcome, process grade, error type, and rule update.
8. **Asian intent matrix board**: above the date selector and match list, show the latest `盘口档位 x 阻上/诱上/阻下/诱下/真实示强/真实示弱/降温保护` matrix. Each visible cell must include sample size, forward win rate, forward flat-stake PnL, reverse win rate, reverse flat-stake PnL, and the current positive-PnL direction. This board is diagnostic only unless the sample/evidence thresholds below are met.
9. **Asian intent detail table**: next to or directly below the matrix, show the latest candidate-combination summary in this exact column order: `盘口/标签 | 样本数量 | 胜率 | 正向收益 | 反向收益`. Use Chinese labels and keep `样本<8` marked as observation, not a confirmed staking rule.
10. **Selected-match intent EV badge**: when a user selects a match, the market board must use the selected match's current Asian handicap bucket and normalized intent tag to look up the latest matrix. Directly under the settlement line, show a red-font badge saying whether the historical matrix favors `正向买亚盘意图`, `反向买亚盘意图`, or `无正期望/不投`. The badge must translate that direction into the actual positive-EV team name and side identity, for example `正期望方：博洛尼亚（上盘）` or `正期望方：拉齐奥（反向=下盘）`; if the team or side cannot be identified, write `正期望方球队未识别-不据此下注`. The badge must include sample size, forward win rate/PnL, reverse win rate/PnL, and a `样本不足/小样本观察/可观察` warning.
11. **Intent-tag performance board**: above the date selector and match list, also show an overall candidate-tag performance board split into `表现好的标签` and `表现差的标签`. This board is grouped only by `候选标签`, not by handicap bucket. Each row must show tag, sample count, effective win rate, forward PnL, reverse PnL, raw win/half-win/push/half-loss/loss counts, and current verdict.

The dashboard is not allowed to hide missing fields. If a source is unavailable, show the missing state in Chinese and downgrade the action to simulation-only or no bet.

Strict completion rule:

- A daily football update is not complete until the backup, T+1 settlement, slate coverage, five-board analysis, evidence visibility, simulation-vs-real-bet separation, Kelly/price gate, and dashboard refresh have all been performed or explicitly marked as failed.
- If any required source is unavailable, write `未接入/待核` in the relevant dashboard field and downgrade the match. Do not fill the gap with generic league logic.
- If only the simulation ledger has been updated but the HTML dashboard has not been regenerated, tell the user `账本已更新，HTML未刷新`.
- If only the dashboard has been regenerated but the underlying evidence fields are missing, tell the user `HTML已刷新，但不符合完整skill分析，只能作为纸面模拟面板`.
- If the daily report and dashboard are updated but the grouped edge review was not regenerated, tell the user `今日更新已出，但盘口/标签/分类回顾未刷新-未完成严格skill交付`.
- For future user prompts such as `按照你skill做今天的更新`, the assistant must first run this strict completion checklist and must not stop at a short text answer unless the user explicitly asks for text-only.

### T+1 Historical Settlement Discipline

No match dated before the current local date may remain labeled `待赛` in the ledger or dashboard. During every daily update, audit all rows from `2026-07-27` onward and force each past row into exactly one of these states:

- `已结算`: a reliable score source matched the fixture, and the simulated market was settled under its recorded 90-minute/contract rule.
- `取消/延期`: the source explicitly shows the match was canceled, postponed, abandoned, or rescheduled.
- `赛果未匹配待人工核验`: no stable score source matched the row. Set `模拟盈亏单位=不计`, keep it out of win-rate statistics, and write the missing source in the audit file.

Do not leave stale past rows as `待赛`, and do not fabricate a score to avoid a missing-data label. Save the settlement audit under `D:\codex\outputs\football_odds_trader\ledger\historical_settlement_audit_YYYYMMDD.csv`.

Asian intent candidate audit discipline:

- `亚盘意图候选` is a diagnostic read, not an official simulated pick. It may be backtested separately to test whether the intent tag implied the right side, but it must not be merged into official simulated-pick win rate unless the row had a pre-match selected side, exact line, price, and settlement clock.
- Candidate tags must first be mapped to an implied side before audit: examples include `阻上/诱下`, `降温保护/诱下`, and `真实示强/阻上` generally map to `上盘`; `阻下/下盘保护`, `诱上/阻下`, and `真实示弱/阻下` generally map to `下盘`; `平衡盘/等待临场确认` or conflicting labels remain `不计`. Historical text that already says `阻下/上盘保护` is a deprecated ambiguous alias and must be displayed/evaluated as `阻下/下盘保护`; do not use the old wording for new rows.
- This mapping is the pre-flow paper direction only. For current-day decisions, apply the `资金流验证` overlay before final action: if a block target is not blocked and the book still leaves that target side a price gift, test the opposite side; if an induce target fails to attract money, return to the opposite side of the induced target, with `诱下未成` defaulting back to `上盘`. The final bettable side is the side that survives the flow overlay plus historical EV, water threshold, same-line veto, and risk-control gates.
- Before calculating any candidate-intent or reverse-buying PnL, reconcile the match result from a reliable final-score source. Prefer Titan007 final snapshots by match id, then other verified score sources; use the simulation ledger score only as a labeled fallback. If the ledger score conflicts with the final snapshot, replace it and display the score source in the audit output.
- When the user asks to test candidate intent or reverse-buying, use the **即时亚盘水位** from the stored odds snapshot and calculate flat-stake PnL for both `按意图买入` and `反向买入`. Do not count only direction; include water.
- Quarter Asian lines must settle with split-line results: `平手/半球` (`±0.25`) can produce `赢半` or `输半`; `半球/一球` (`±0.75`) can produce `赢半` or `输半`; `一球/球半` (`±1.25`) and `球半/两球` (`±1.75`) follow the same half-win/half-loss logic. Report raw counts and effective hit rate where `赢半=0.5 win` and `输半=0.5 loss`.
- Explicit examples:
  - 买上盘 `-0.25` / 平半：上盘方赢球 = 全赢；打平 = 输半；输球 = 全输。
  - 买下盘 `+0.25` / 受平半：下盘方赢球或打平 = 全赢；输一球或更多 = 全输。
  - 买上盘 `-0.75` / 半一：上盘方赢两球或更多 = 全赢；赢一球 = 赢半；打平或输球 = 全输。
  - 买下盘 `+0.75` / 受半一：下盘方赢球或打平 = 全赢；输一球 = 输半；输两球或更多 = 全输。
  - `±1.25`、`±1.75`、`±2.25`、`±2.75` 依此类推：把盘口拆成相邻两条半球/整球线，各占半注后结算。
- Save candidate-intent audits separately as `D:\codex\outputs\football_odds_trader\ledger\asian_intent_candidate_audit_YYYY-MM-DD.csv` and `.md`, and label them `候选意图回测`, not `正式模拟胜率`.
- Every time settled results are updated, also refresh the Asian-intent history summary and the dashboard's matrix/table data. The required outputs are `D:\codex\outputs\football_odds_trader\ledger\asian_intent_line_tag_matrix_YYYYMMDD.csv` and `.md`, or the latest equivalent generated from `asian_intent_history_summary_*.csv`.
- The matrix view (`图1`) must display the line bucket as rows and the intent tag as columns. Each cell must show at least `n`, `正向胜率`, `正向收益`, `反向胜率`, and `反向收益`; do not show only PnL without win rate.
- The detail view (`图3`) must use five columns: `盘口/标签`, `样本数量`, `胜率`, `正向收益`, `反向收益`. `胜率` means the forward/effective hit rate unless the table explicitly labels it as reverse. If reverse PnL is higher while forward win rate is weak, mark the row `反向验证`.
- In the HTML dashboard, place both `图1` and `图3` above the date selector and match list so the user sees the current pattern evidence before selecting a match.
- In each selected match's `盘口与赔率` board, show a red `亚盘意图历史EV` badge derived from the exact `盘口档位 + 候选标签` matrix cell. The badge must display the current positive-EV side as a concrete Chinese team name plus `上盘/下盘` identity, not only `正向` or `反向`. If no exact cell exists, write `历史矩阵无同档样本-不据此下注`; do not silently fall back to unrelated line buckets.
- The HTML dashboard must also show the pure tag board from the latest `asian_intent_history_summary_*.csv`: `表现好的标签` are tags with positive forward PnL; `表现差的标签` are tags with negative forward PnL and positive reverse PnL. When a selected match has a current candidate tag, the red `亚盘意图历史EV` badge must also state whether that tag is currently good, bad/reverse-validation, neutral, or lacking history.
- Whenever candidate samples are updated, rerun the historical intent audit, rebuild the line-tag matrix, rebuild the tag performance board, and regenerate `D:\codex\outputs\football_odds_trader\dashboard\index.html`. Do not leave the HTML tag board stale after CSV/MD samples change.

Grouped edge review requirement for strict daily updates:

- Every time the user says `严格按照skill做今天的更新`, `按照你skill做今天的更新`, or an equivalent daily update request, the output is incomplete unless a standalone grouped review is also generated and its path is returned to the user.
- Save the Markdown review under `D:\codex\outputs\football_odds_trader\reviews\grouped_edge_review_YYYY-MM-DD.md`, and save the matching machine-readable CSV under `D:\codex\outputs\football_odds_trader\ledger\grouped_edge_review_YYYY-MM-DD.csv`.
- The grouped review must include at least these sections: `按盘口档位`, `按候选标签`, `按盘口档位+候选标签`, `按赛事/联赛`, `按比赛分类`, `按比赛分类+盘口档位`, `按比赛分类+候选标签`, and `按比赛分类+盘口档位+候选标签`.
- `比赛分类` must separate at minimum: `成年联赛T1`, `成年联赛T2`, `成年联赛T3`, `国内杯赛`, `洲际杯赛`, `国家队正式赛`, and `未知分类`. If a competition cannot be classified, mark it `未知分类-不作为强规则`.
- Every grouped table must use these columns: `分组类型 | 分组 | 样本 | 正向有效胜率 | 正向均注盈亏 | 反向有效胜率 | 反向均注盈亏 | 当前读法/建议 | 备注`. If the source table keeps raw counts, include wins/half-wins/pushes/half-losses/losses in the CSV.
- The review must explicitly answer which situations currently perform better: positive forward EV, positive reverse EV, both losing, small sample, or no stable edge. Do not simply dump CSV rows.
- `样本<8` is observation only. `样本>=8` with positive PnL can adjust watchlist ranking. `样本>=15` with positive PnL, stable process notes, and no obvious concentration can be highlighted as a priority pattern. Even a priority pattern still requires the exact market price for the selected market. For Asian handicap, current line/water plus the Micro-Region Tag EV framework, water threshold, same-line veto, risk state, and Kelly/stake rules decide whether it is actionable; missing PM/Betfair data blocks only PM/Betfair execution, not Asian-handicap EV by itself.
- Final user-facing responses for daily updates must include three paths when produced: daily report, dashboard HTML, and grouped edge review.

### Bettable Slate Filter And Long-Run Tracking

Every dashboard refresh must expose a visible control near the date selector named `筛选当日可投注赛事`.

- When `筛选当日可投注赛事` is enabled, the left match list must show only matches on the selected date whose current strict skill decision is `可投` or `半仓可投`. These matches must be sorted by Beijing kickoff time ascending. For matches with the same kickoff time, rank by strict skill plan quality: actionable status first, higher historical/combined win rate next, then better current water/value.
- The bettable filter is a review-and-tracking filter, not a live-bet permission switch. It must retain already kicked-off, live, and settled matches if their pre-state strict skill decision would have been `可投` or `半仓可投`; those rows remain visible for audit, red/black settlement, and intraday version comparison. Match state (`未开赛` / `进行中` / `完场` / `已结算`) must never change the stored or displayed `可投/半仓可投/不投` recommendation. State may only be shown as an execution-status note such as `已开赛/完场，仅供复盘，不能赛后补下注`.
- For already kicked-off, live, or settled rows, the dashboard must prefer the frozen pre-match betting recommendation from `bettable_event_detail_YYYY-MM-DD.csv`, version snapshots, or another immutable pre-match ledger. If a frozen record says `可投` or `半仓可投`, the red EV badge and bettable filter must keep that recommendation and concrete team/side, while settlement/result fields are updated append-only. Do not recompute a started/settled row into `不投` merely because its live score, final score, status, or post-match odds snapshot changed.
- Regression guard: if a previous same-day version marked a match as `可投` or `半仓可投` under the strict skill funnel, a later refresh may only change that recommendation when the stored pre-kickoff odds/tag/line snapshot is explicitly superseded by a newer pre-kickoff snapshot. It must not change to `不投` solely because the match has become `进行中`, `完场`, or `已结算`. Examples such as a USL Championship match or an English League One match that moved from unplayed to live/finished must remain visible in the bettable filter for review if the pre-state recommendation passed.
- When the control is disabled, the left match list must restore the original selected-date ordering. Do not permanently overwrite the slate order just because a bettable filter was used.
- The selected-match red EV badge remains the source of truth. The filter must use the same decision logic as the red badge: current Asian intent, tag history, micro-region history, Bayesian shrinkage if needed, water threshold, same-line veto, and risk-control state.
- If no match passes the strict skill betting funnel for the selected date, show `当日暂无通过skill漏斗的可投注赛事`, not an empty or misleading list.
- The date count must reflect the current filter state, for example `81 场` when unfiltered and `5 场可投` when filtered.

From `2026-09-01` onward, every strict daily update and every sequential backtest refresh must generate a separate machine-readable bettable-event tracking file:

`D:\codex\outputs\football_odds_trader\ledger\bettable_event_stats_YYYY-MM-DD.csv`

The file must track only rows that actually pass the strict Asian-handicap betting funnel (`动作=正向` or `动作=反向`) and must be based on walk-forward decisions, not post-match optimal direction. It must group by `地区-国家-赛事层级-盘口-水位分层-倾向意图`, then settle red/black outcomes. Required stable columns:

`统计日期, 数据源, 地区, 国家, 赛事层级, 盘口, 水位分层, 倾向意图, 样本, 红, 红半, 走水, 黑半, 黑, 有效胜率, 负率, 均注盈亏Unit, 平均水位, ROI, 备注`

Definitions:

- `地区`: micro-region bucket, such as 北美、拉美、东亚、西亚/中亚、欧洲五大、欧洲非五大、其他.
- `国家`: derive from the competition/league name when reliable; if not reliable, write `未识别`.
- `赛事层级`: normalize to `顶级联赛`, `非顶级联赛`, `杯赛`, `洲际杯赛`, `国家队正式赛`, or `未知分类`.
- `盘口`: use the selected row's normalized Asian handicap bucket / line bucket, such as `平手`, `平手/半球`, `半球`, `半球/一球`, `一球`, etc. If missing, write `缺盘口`.
- `水位分层`: bucket the selected current water as `<=0.70`, `0.71-0.80`, `0.81-0.90`, `0.91-1.00`, `1.01-1.10`, or `>1.10`.
- `倾向意图`: use the normalized Asian intent tag for that row, such as `阻上/诱下`, `诱上/阻下`, `真实示弱/阻下`, `降温保护/诱下`, or `平衡盘/等待临场确认`. If missing, write `缺倾向意图`.
- `资金流验证`: when Layer 1, Layer 1B, or Layer 2 flow exists, append flow-overlay fields to the per-match detail and any flow-specific grouped audit: `阻诱目标侧`, `理论资金主队占比`, `理论资金客队占比`, `实际资金主队占比`, `实际资金客队占比`, `资金偏离主队`, `资金偏离客队`, `资金过热侧`, `过热阈值`, `理论占比依据`, `实际资金流向`, `目标侧水位甜头`, `意图成败`, `资金流修正方向`, `资金流修正球队`, `资金流来源`, `资金流时间戳`. If no flow source is available, fill explicit gaps such as `资金流缺口-只有盘口价格流`; do not leave blank fields or infer true volume from odds movement.
- Red/black accounting must preserve Asian quarter-line results: `红半` and `黑半` are separate counts; effective win rate treats half-win as 0.5 win and half-loss as 0.5 loss.

This file is for long-run threshold discovery. It must be updated after settlements so the system can learn which `地区-国家-赛事层级-盘口-水位分层-倾向意图` combinations trigger durable positive expectation, and which should be downgraded or filtered out.

When flow data exists, also generate a flow-overlay grouped file:

`D:\codex\outputs\football_odds_trader\ledger\funds_flow_intent_overlay_YYYY-MM-DD.csv`

Group it by `地区-国家-赛事层级-盘口-水位分层-倾向意图-意图成败-资金流修正方向`, then report sample count, forward/reverse effective win rate, forward/reverse flat-stake PnL, and whether the flow overlay improved or damaged the original Asian-intent read.

The grouped stats file is not a match ledger and must not be the only tracking output. Every refresh that writes `bettable_event_stats_YYYY-MM-DD.csv` must also write a per-match audit ledger:

`D:\codex\outputs\football_odds_trader\ledger\bettable_event_detail_YYYY-MM-DD.csv`

This detail file must contain one row per strict-funnel bettable match and preserve the concrete match identity behind each grouped sample. Required stable columns:

`统计日期, 数据源, 日期, 开赛时间, 比赛ID, 赛事, 比赛, 比赛分类, 微观板块, 国家, 赛事层级, 盘口, 水位分层, 倾向意图, 阻诱目标侧, 理论资金主队占比, 理论资金客队占比, 实际资金主队占比, 实际资金客队占比, 资金偏离主队, 资金偏离客队, 资金过热侧, 过热阈值, 理论占比依据, 实际资金流向, 目标侧水位甜头, 意图成败, 资金流修正方向, 资金流修正球队, 资金流来源, 资金流时间戳, 动作, 选择方向, 投注盘向, 投注球队, 选中水位, 综合胜率, 盈亏平衡胜率, 通过阈值, 同档样本, 同档选中胜率, 风控状态, 仓位系数, 下注金额, 已结算, 结算标签, 实际盈亏Unit, 实际盈亏金额, 赛果, 比分来源, 即时亚盘, 盘口线, 上盘方, 候选映射方向, 反向方向, 候选依据`

Use `bettable_event_stats` for threshold discovery and compact dashboard summaries. Use `bettable_event_detail` whenever the user asks which concrete matches contributed to a red/black record, sample count, ROI, or long-run combination.

## Guardrails

- Do not recommend offshore or unlicensed betting sites.
- Do not present betting advice as guaranteed profit.
- Do not overfit recent misses. Use them to adjust interpretation rules, not to flip every recommendation.
- Always distinguish "winner probability" from "handicap value".
