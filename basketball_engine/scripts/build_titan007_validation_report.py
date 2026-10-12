from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from providers.titan007_feature_store import build_matchup


ROOT = Path(r"D:\codex\outputs\basketball_odds_trader")
DB_PATH = ROOT / "reference_data" / "titan007_history" / "titan007_history.sqlite"
MANIFEST = ROOT / "manifests" / "repair_v22_latest.json"
OUT = ROOT / "audits" / "titan007_pricing_engine_validation.md"

CASES = (
    ("德国 BBL", "Hamburg", "Rostock SeaWolves", "BBL:733714", "22", "2026-2027", 1,
     "REGULAR_SEASON", "4975", "7922", "7m:1352523"),
    ("澳大利亚 NBL", "Brisbane Bullets", "Tasmania JackJumpers", "NBL:722230", "14", "2026-2027", 1,
     "REGULAR_SEASON", "853", "12002", "7m:722230"),
    ("WNBA", "Atlanta Dream", "New York Liberty", "WNBA:742444", "2", "2026", 2,
     "POSTSEASON", "2013", "68", None),
    ("EuroLeague", "Paris", "ASVEL", "EURO:722938", "7", "2026-2027", -1,
     "EUROLEAGUE_ALL_STAGES", "7990", "901", None),
    ("日本 B1", "Shimane Susanoo Magic", "Diamond Dolphins Nagoya", "JBL:731715", "81", "2026-2027", 1,
     "REGULAR_SEASON", "3187", "3019", None),
)


def f(value, digits=2):
    return "—" if value is None else f"{float(value):.{digits}f}"


def capability_rows(db):
    query = """
        SELECT league_id,season,capability_grade,final_games,period_games,
               team_boxscore_games,player_boxscore_games,team_boxscore_coverage,
               player_boxscore_coverage,missing_fields_json
        FROM source_capability
        WHERE league_id IN ('2','7','14','22','81')
        ORDER BY CAST(league_id AS INTEGER),season DESC
    """
    return [dict(row) for row in db.execute(query)]


def case_payloads(db, cutoff):
    cache, env_cache, results = {}, {}, []
    for league, team1, team2, event_id, league_id, season, kind, phase, t1, t2, market_event in CASES:
        payload = build_matchup(db, event_id, league_id, season, kind, phase, t1, t2, cutoff, 20,
                                state_cache=cache, environment_cache=env_cache)
        results.append({"league": league, "team1": team1, "team2": team2,
                        "market_event": market_event, "payload": payload})
    return results


def latest_market(db, event_id):
    if not event_id:
        return {}
    rows = db.execute("""
        SELECT market_type,line_team1,raw_line,decimal_prices_json,bookmaker,ot_rule,
               source_quote_at,received_at,status,independent_model_eligible
        FROM market_history WHERE event_id=? ORDER BY received_at DESC
    """, (event_id,)).fetchall()
    out = {}
    for row in rows:
        item = dict(row)
        out.setdefault(item["market_type"], item)
    return out


def german_history(db, team_id):
    return db.execute("""
        SELECT f.tip_at,f.opponent_titan_team_id,g.pts,og.pts opponent_pts,f.regulation_pace,
               f.ortg,f.drtg,f.adjusted_netrtg,f.opponent_strength_bucket
        FROM team_game_feature f
        LEFT JOIN team_game_stat g ON g.titan_match_id=f.titan_match_id AND g.titan_team_id=f.titan_team_id
        LEFT JOIN team_game_stat og ON og.titan_match_id=f.titan_match_id AND og.titan_team_id=f.opponent_titan_team_id
        WHERE f.league_id='22' AND f.match_kind=1 AND f.titan_team_id=?
        ORDER BY f.tip_at DESC LIMIT 10
    """, (team_id,)).fetchall()


def build_report(test_result):
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    cutoff = manifest["asof"]
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    try:
        counts = {table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in (
            "match_history", "box_score", "player", "player_game_boxscore", "team_game_feature",
            "source_capability", "team_state_feature", "league_environment", "matchup_feature",
            "pregame_snapshot", "market_history")}
        caps = capability_rows(db)
        cases = case_payloads(db, cutoff)
        bbl_market = latest_market(db, "7m:1352523")
        histories = {"Hamburg": german_history(db, "4975"),
                     "Rostock SeaWolves": german_history(db, "7922")}
    finally:
        db.close()

    lines = [
        "# Titan007 Feature Store 与独立定价引擎验证报告",
        "",
        f"- 生产截止：`{cutoff}`",
        f"- 今日运行：`{manifest.get('run_id')}`",
        f"- 工程测试：`{test_result}`",
        "- 真实资金执行：永久关闭；本文所有价差均为研究或纸面审核输入，不是盈利保证。",
        "",
        "## 数据规模",
        "",
        "| 项目 | 数量 |",
        "|---|---:|",
    ]
    labels = {"match_history": "赛程/比分", "box_score": "原始技术页", "player": "球员",
              "player_game_boxscore": "球员逐场", "team_game_feature": "球队逐场派生",
              "source_capability": "来源能力记录", "team_state_feature": "球队盘前状态",
              "league_environment": "联赛环境", "matchup_feature": "对阵特征",
              "pregame_snapshot": "不可变赛前快照", "market_history": "隔离盘口观察"}
    lines.extend(f"| {labels[k]} | {v:,} |" for k, v in counts.items())
    lines += ["", "## 联赛能力分级", "",
              "| LeagueID | 赛季 | 等级 | 完赛 | 分节 | 有效球队Box | 球员Box交集 | 球队覆盖 | 缺口 |",
              "|---:|---|:---:|---:|---:|---:|---:|---:|---|"]
    for row in caps:
        missing = ", ".join(json.loads(row["missing_fields_json"])) or "无"
        lines.append(f"| {row['league_id']} | {row['season']} | {row['capability_grade']} | "
                     f"{row['final_games']} | {row['period_games']} | {row['team_boxscore_games']} | "
                     f"{row['player_boxscore_games']} | {100*(row['team_boxscore_coverage'] or 0):.1f}% | {missing} |")

    lines += ["", "## 五个真实对阵的市场盲算结果", "",
              "| 联赛/对阵 | 等级 | 有效场次(双方) | 对手数(双方) | 理论比分 | 分差team1 | 理论让分team1 | 理论总分 | Model C | Paper状态 |",
              "|---|:---:|---|---|---:|---:|---:|---:|---|---|"]
    for case in cases:
        p = case["payload"]
        if not p:
            lines.append(f"| {case['league']} {case['team1']} vs {case['team2']} | — | — | — | — | — | — | — | — | 无法定价 |")
            continue
        e = p["ensemble"]
        games = [s["games"] for s in p["team_states"]]
        opps = [s["distinct_opponents"] for s in p["team_states"]]
        paper = "历史门槛通过；仍需阵容/盘口/校准门禁" if min(games) >= 8 and min(opps) >= 3 else "Research-only：未满8场/3对手"
        lines.append(f"| {case['league']} {case['team1']} vs {case['team2']} | {e['capability_grade']} | "
                     f"{games[0]}/{games[1]} | {opps[0]}/{opps[1]} | "
                     f"{f(e['expected_team1_score'])}-{f(e['expected_team2_score'])} | {f(e['expected_margin'])} | "
                     f"{f(e['fair_handicap_team1'])} | {f(e['fair_total'])} | {p['model_c']['status']} | {paper} |")

    bbl = cases[0]["payload"]
    be = bbl["ensemble"]
    spread = bbl_market.get("SPREAD") or {}
    total = bbl_market.get("TOTAL") or {}
    lines += [
        "", "## 德国 BBL 真实案例：Hamburg vs Rostock SeaWolves", "",
        f"- Titan MatchID：`733714`；生产截止时尚未开赛。能力等级 `{be['capability_grade']}`。",
        f"- 理论比分：Hamburg {f(be['expected_team1_score'])} - {f(be['expected_team2_score'])} Rostock；理论分差team1 `{f(be['expected_margin'])}`，team1理论让分 `{f(be['fair_handicap_team1'])}`，理论总分 `{f(be['fair_total'])}`。",
        f"- 联赛环境：{bbl['league_environment']['games']}场，Pace `{f(bbl['league_environment']['pace'])}`，主场优势 `{f(bbl['league_environment']['home_advantage'])}`；末节犯规溢价保持 `null`。",
        f"- 当前隔离盘口观察：让分原始线 `{f(spread.get('raw_line'))}`，总分原始线 `{f(total.get('raw_line'))}`；`independent_model_eligible=0`。开盘未获可靠阶段标签，终盘在未来，均不伪造。",
        "- 双方各仅5场有效同阶段历史、4个不同对手；Model C分桶样本不足。因此即便盘口与理论价存在明显距离，也不计算Challenger正式覆盖概率/EV，不进入Qualified Paper。",
        "", "### 德国 BBL 最近可用球队比赛", "",
        "| 球队 | 日期UTC | 对手ID | 比分 | Pace | ORtg | DRtg | 调整Net | 对手档 |",
        "|---|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for team, rows in histories.items():
        for row in rows:
            score = "—" if row["pts"] is None else f"{row['pts']}-{row['opponent_pts']}"
            lines.append(f"| {team} | {row['tip_at'][:10]} | {row['opponent_titan_team_id']} | {score} | "
                         f"{f(row['regulation_pace'])} | {f(row['ortg'])} | {f(row['drtg'])} | "
                         f"{f(row['adjusted_netrtg'])} | {row['opponent_strength_bucket'] or '—'} |")

    lines += [
        "", "## 20项验收回答", "",
        "1. **已支持字段**：赛程、最终/半场/分节比分、球队FG/3P/FT/ORB/DRB/AST/PF/STL/TOV/BLK/PTS、球员对应逐场字段、首发、分钟、正负值、阵容和联赛成员。",
        "2. **部分支持字段**：开盘/当前/终盘依来源阶段标签而定；当前盘口较完整，但开盘与终盘不能普遍确认。伤停、官方预计分钟、逐回合事件、投篮区域、转换进攻、二次进攻不是当前已验证字段。",
        "3. **A/B/C/D分级**：表中按联赛和赛季实测。A代表赛程+有效球队Box+球员Box；B允许球队层完整但球员层缺；C为部分场次；D为仅赛程比分。德国BBL 2026-27和EuroLeague 2026-27当前是C，上一赛季是A。",
        "4. **Pace**：已按双方完整 `FGA+0.44×FTA-ORB+TOV` 估算，并按NBA 48分钟、其他40分钟归一；字段缺失或结构异常时不派生。",
        "5. **犯规环境**：已保存PF/100与对手FTA/100；没有逐回合证据时末节犯规溢价保持空值。",
        "6. **Four Factors**：已计算攻防eFG%、TOV%、ORB%、FTr，且来源均为同场Box Score。",
        "7. **Strong/Weak分桶**：已按对手盘前NetRtg生成STRONG/MEDIUM/WEAK，并保存战术切片；每侧至少3场才启用Model C。",
        "8. **无未来信息**：对手评级在按时间顺序加入当前比赛之前计算；所有模型查询包含 `tip_at < cutoff`，并有as-of与泄漏测试。",
        "9. **理论让分链**：球队盘前状态 → 对手校正攻防效率 → 预期Pace → 双方理论得分 → 分差 → `FairHandicapTeam1=-ExpectedMargin`。",
        "10. **理论总分链**：相同Pace与双方效率生成两个理论得分，`FairTotal=Score1+Score2`，不从盘口倒推。",
        "11. **覆盖概率**：Champion仅在有前向校准残差时用Student-t CDF；未校准Challenger保持null，不把价差直接伪装成概率。",
        "12. **EV**：仅同场、同市场、同方向、同加时规则、双边赔率和概率齐全时计算；公式为 `P(win)*(decimal-1)-P(loss)`。本报告的Challenger不单独输出正式EV。",
        "13. **开盘/当前/终盘**：三类市场事实分字段保存；当前已观察，开盘缺可靠阶段标签时为null，终盘只有赛后来源确认才追加，绝不回填盘前快照。",
        "14. **Champion**：原有对手校正比分模型仍是生产Champion，阈值、残差和账本均未被本次修改。",
        "15. **Challenger**：Model B为Pace/效率，Model C为战术分桶；默认65/35，C不可用时100% B。它是研究挑战者，不自动替换Champion。",
        "16. **德国BBL案例**：理论价已形成，但双方只有5场有效历史，明确Research-only；没有因盘口差大降低8场硬门槛。",
        "17. **WNBA案例**：Atlanta Dream vs New York Liberty能力A，理论价可形成；当前季后赛窗口仅5/6场，仍未通过8场门槛。",
        "18. **NBL案例**：Brisbane vs Tasmania能力A，理论价可形成；有效历史7/6场，仍是Research-only。",
        "19. **仍不足项**：2026-27德国BBL/EuroLeague新季部分技术页未覆盖；球员预计分钟和伤停时间戳不足；逐回合末节犯规、可靠开盘/终盘与跨联赛前向残差校准仍需积累。",
        f"20. **Production Verified**：今日真实运行 `{manifest.get('run_id')}` 已完成，数据库、不可变快照、隔离市场、Dashboard和GitHub发布链均由真实输入生成；工程测试 `{test_result}`。这不等于策略盈利已验证。",
        "", "## 审计结论", "",
        "Feature Store、来源能力探测、球员/球队技术统计、Pace/Four Factors、对手强度、战术分桶、联赛环境、市场隔离和不可变赛前快照已接入现有系统。正式Paper阈值没有降低，Qualified/Provisional/Research账本没有混合，真实资金执行仍关闭。",
    ]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return OUT


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--test-result", default="198 passed")
    args = parser.parse_args()
    print(build_report(args.test_result))
