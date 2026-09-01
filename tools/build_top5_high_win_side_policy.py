# -*- coding: utf-8 -*-
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd


ROOT = Path(r"D:\codex\outputs\football_odds_trader")
OUT_DIR = ROOT / "backtests" / "top5_tier_split"

LEAGUE_MAP: dict[str, tuple[str, str]] = {
    "英超": ("英格兰", "顶级"),
    "英冠": ("英格兰", "次级"),
    "英甲": ("英格兰", "次次级"),
    "英联杯": ("英格兰", "杯赛"),
    "英足总杯": ("英格兰", "杯赛"),
    "西甲": ("西班牙", "顶级"),
    "西乙": ("西班牙", "次级"),
    "西协甲": ("西班牙", "次次级"),
    "西班牙杯": ("西班牙", "杯赛"),
    "意甲": ("意大利", "顶级"),
    "意乙": ("意大利", "次级"),
    "意丙": ("意大利", "次次级"),
    "意大利杯": ("意大利", "杯赛"),
    "意杯": ("意大利", "杯赛"),
    "意丙杯": ("意大利", "杯赛"),
    "德甲": ("德国", "顶级"),
    "德乙": ("德国", "次级"),
    "德丙": ("德国", "次次级"),
    "德国杯": ("德国", "杯赛"),
    "德电信杯": ("德国", "杯赛"),
    "法甲": ("法国", "顶级"),
    "法乙": ("法国", "次级"),
    "法丙": ("法国", "次次级"),
    "法国杯": ("法国", "杯赛"),
    "法联杯": ("法国", "杯赛"),
}

SETTLED = {"赢", "赢半", "走", "输半", "输"}
COUNT_ORDER = ["赢", "赢半", "走", "输半", "输"]
FORWARD = "正向"
REVERSE = "反向"
NO_BET = "不下注"
LEAGUE_ALIASES = {
    "意杯": "意大利杯",
}


def latest_input_file() -> Path:
    files = sorted((ROOT / "ledger").glob("asian_intent_history_detail_*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        raise FileNotFoundError(f"No asian_intent_history_detail_*.csv under {ROOT / 'ledger'}")
    return files[0]


def extract_match_id(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    import re

    m = re.search(r"TITAN-(\d+)", text)
    return m.group(1) if m else text


def stable_time_sort(df: pd.DataFrame) -> pd.DataFrame:
    """Skill-required deterministic order; older ledgers may only have match id inside 模拟ID."""
    df = df.copy()
    if "开赛时间" not in df.columns:
        df["开赛时间"] = ""
    if "比赛ID" not in df.columns:
        source = df["模拟ID"] if "模拟ID" in df.columns else df.index.to_series().astype(str)
        df["比赛ID"] = source.map(extract_match_id)
    return df.sort_values(by=["日期", "开赛时间", "比赛ID"], ascending=[True, True, True]).reset_index(drop=True)


@dataclass(frozen=True)
class SideStats:
    sample: int
    red: int
    red_half: int
    push: int
    black_half: int
    black: int
    eff_win_rate: float | None
    hit_rate: float | None
    loss_rate: float | None
    pnl: float
    roi: float | None


@dataclass(frozen=True)
class Choice:
    side: str
    rate: float | None
    pnl: float
    sample: int
    reason: str


def parse_float(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    text = str(value).strip().replace("+", "").replace("u", "").replace("U", "")
    if not text:
        return None
    try:
        return round(float(text), 4)
    except ValueError:
        return None


def calc_pnl(settle: str, water: float | None, saved: object) -> float | None:
    existing = parse_float(saved)
    if existing is not None:
        return existing
    if settle == "赢":
        return round(water or 0.0, 4)
    if settle == "赢半":
        return round((water or 0.0) / 2.0, 4)
    if settle == "走":
        return 0.0
    if settle == "输半":
        return -0.5
    if settle == "输":
        return -1.0
    return None


def stat_from_settles(settles: pd.Series, pnls: pd.Series) -> SideStats:
    counts = {key: int((settles == key).sum()) for key in COUNT_ORDER}
    sample = sum(counts.values())
    non_push = sample - counts["走"]
    eff = hit = loss = None
    if non_push > 0:
        eff = round((counts["赢"] + 0.5 * counts["赢半"]) / non_push, 4)
        hit = round((counts["赢"] + counts["赢半"]) / non_push, 4)
        loss = round((counts["输"] + counts["输半"]) / non_push, 4)
    pnl = round(float(pnls.fillna(0).sum()), 4)
    roi = round(pnl / sample, 4) if sample else None
    return SideStats(
        sample=sample,
        red=counts["赢"],
        red_half=counts["赢半"],
        push=counts["走"],
        black_half=counts["输半"],
        black=counts["输"],
        eff_win_rate=eff,
        hit_rate=hit,
        loss_rate=loss,
        pnl=pnl,
        roi=roi,
    )


def side_stats(df: pd.DataFrame, side: str) -> SideStats:
    if side == FORWARD:
        return stat_from_settles(df["意图结算"], df["意图均注盈亏_数值"])
    if side == REVERSE:
        return stat_from_settles(df["反向结算"], df["反向均注盈亏_数值"])
    return SideStats(0, 0, 0, 0, 0, 0, None, None, None, 0.0, None)


def choose_higher_rate(df: pd.DataFrame, min_sample: int, reason: str) -> Choice:
    f = side_stats(df, FORWARD)
    r = side_stats(df, REVERSE)
    if f.sample < min_sample or r.sample < min_sample:
        return Choice(NO_BET, None, 0.0, min(f.sample, r.sample), f"样本不足<{min_sample}")
    fr = -1.0 if f.eff_win_rate is None else f.eff_win_rate
    rr = -1.0 if r.eff_win_rate is None else r.eff_win_rate
    if fr > rr:
        return Choice(FORWARD, f.eff_win_rate, f.pnl, f.sample, reason)
    if rr > fr:
        return Choice(REVERSE, r.eff_win_rate, r.pnl, r.sample, reason)
    if f.pnl > r.pnl:
        return Choice(FORWARD, f.eff_win_rate, f.pnl, f.sample, f"{reason};胜率相同按盈亏")
    if r.pnl > f.pnl:
        return Choice(REVERSE, r.eff_win_rate, r.pnl, r.sample, f"{reason};胜率相同按盈亏")
    return Choice(NO_BET, f.eff_win_rate, f.pnl, f.sample, "正反相同无优势")


def get_side_result(row: pd.Series, side: str) -> tuple[str, float]:
    if side == FORWARD:
        return str(row["意图结算"]), float(row["意图均注盈亏_数值"])
    if side == REVERSE:
        return str(row["反向结算"]), float(row["反向均注盈亏_数值"])
    return NO_BET, 0.0


def summarize_results(df: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for keys, g in df.groupby(group_cols, dropna=False, sort=True):
        if not isinstance(keys, tuple):
            keys = (keys,)
        active = g[g["选择方向"].isin([FORWARD, REVERSE])]
        s = stat_from_settles(active["选择结算"], active["选择盈亏"])
        row = {col: val for col, val in zip(group_cols, keys)}
        row.update(
            {
                "策略": g["策略"].iloc[0] if "策略" in g.columns and len(g) else "",
                "总场数": int(len(g)),
                "下注场数": int(s.sample),
                "跳过": int(len(g) - s.sample),
                "红": s.red,
                "红半": s.red_half,
                "走": s.push,
                "黑半": s.black_half,
                "黑": s.black,
                "红/红半/走/黑半/黑": f"{s.red}/{s.red_half}/{s.push}/{s.black_half}/{s.black}",
                "有效胜率": s.eff_win_rate,
                "红单命中率": s.hit_rate,
                "负率": s.loss_rate,
                "均注盈亏": s.pnl,
                "ROI": s.roi,
                "选正向": int((active["选择方向"] == FORWARD).sum()),
                "选反向": int((active["选择方向"] == REVERSE).sum()),
                "一致次数": int((active["一致性"] == "一致").sum()),
                "冲突次数": int((active["一致性"].astype(str).str.startswith("冲突")).sum()),
                "回退赛事级": int((active["一致性"] == "盘口样本不足-回退赛事级").sum()),
            }
        )
        rows.append(row)
    return pd.DataFrame(rows)


def fmt_rate(value: float | None) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    return f"{value * 100:.1f}%"


def fmt_unit(value: float | None) -> str:
    return "" if value is None else f"{value:+.4f}"


def prepare() -> tuple[pd.DataFrame, Path]:
    input_path = latest_input_file()
    df = pd.read_csv(input_path, encoding="utf-8-sig")
    df = stable_time_sort(df)
    df["赛事"] = df["赛事"].replace(LEAGUE_ALIASES)
    df = df[df["赛事"].isin(LEAGUE_MAP)].copy()
    df[["国家", "层级"]] = df["赛事"].map(LEAGUE_MAP).apply(pd.Series)
    df = df[df["意图结算"].isin(SETTLED) & df["反向结算"].isin(SETTLED)].copy()
    df["意图水位_数值"] = df["意图水位"].map(parse_float)
    df["反向水位_数值"] = df["反向水位"].map(parse_float)
    df["意图均注盈亏_数值"] = [
        calc_pnl(s, w, p) for s, w, p in zip(df["意图结算"], df["意图水位_数值"], df["意图均注盈亏"])
    ]
    df["反向均注盈亏_数值"] = [
        calc_pnl(s, w, p) for s, w, p in zip(df["反向结算"], df["反向水位_数值"], df["反向均注盈亏"])
    ]
    df = df[df["意图均注盈亏_数值"].notna() & df["反向均注盈亏_数值"].notna()].copy()
    return df.reset_index(drop=True), input_path


def build_choice_maps(df: pd.DataFrame, min_sample: int) -> tuple[dict[tuple, Choice], dict[tuple, Choice]]:
    league_map: dict[tuple, Choice] = {}
    line_map: dict[tuple, Choice] = {}
    for key, g in df.groupby(["国家", "层级", "赛事"], dropna=False, sort=False):
        league_map[key] = choose_higher_rate(g, min_sample, "赛事级胜率高方")
    for key, g in df.groupby(["国家", "层级", "赛事", "盘口档位", "候选标签"], dropna=False, sort=False):
        line_map[key] = choose_higher_rate(g, min_sample, "盘口档位+标签胜率高方")
    return league_map, line_map


def resolve_combined(league_choice: Choice, line_choice: Choice) -> tuple[str, str, str]:
    if league_choice.side == NO_BET and line_choice.side == NO_BET:
        return NO_BET, "两边样本不足", "无方向"
    if line_choice.side == NO_BET:
        return league_choice.side, "盘口样本不足-回退赛事级", league_choice.reason
    if league_choice.side == NO_BET:
        return line_choice.side, "赛事样本不足-用盘口倾向", line_choice.reason
    if league_choice.side == line_choice.side:
        return league_choice.side, "一致", "赛事级与盘口倾向同向"
    lr = -1.0 if league_choice.rate is None else league_choice.rate
    pr = -1.0 if line_choice.rate is None else line_choice.rate
    if pr > lr:
        return line_choice.side, "冲突-取盘口倾向胜率更高", f"盘口{fmt_rate(pr)} > 赛事{fmt_rate(lr)}"
    if lr > pr:
        return league_choice.side, "冲突-取赛事胜率更高", f"赛事{fmt_rate(lr)} > 盘口{fmt_rate(pr)}"
    if line_choice.pnl > league_choice.pnl:
        return line_choice.side, "冲突-胜率相同取盘口盈亏", "胜率相同"
    return league_choice.side, "冲突-胜率相同取赛事盈亏", "胜率相同"


def apply_full_sample_policy(df: pd.DataFrame, min_sample: int) -> pd.DataFrame:
    league_map, line_map = build_choice_maps(df, min_sample)
    rows: list[dict[str, object]] = []
    for _, row in df.iterrows():
        league_key = (row["国家"], row["层级"], row["赛事"])
        line_key = (row["国家"], row["层级"], row["赛事"], row["盘口档位"], row["候选标签"])
        league_choice = league_map.get(league_key, Choice(NO_BET, None, 0.0, 0, "无赛事样本"))
        line_choice = line_map.get(line_key, Choice(NO_BET, None, 0.0, 0, "无盘口样本"))
        for policy, choice_side, consistency, reason in [
            ("全样本事后体检-赛事级胜率高方", league_choice.side, "赛事级", league_choice.reason),
            ("全样本事后体检-赛事级+盘口倾向择高", *resolve_combined(league_choice, line_choice)),
        ]:
            settle, pnl = get_side_result(row, choice_side)
            item = row.to_dict()
            item.update(
                {
                    "策略": policy,
                    "选择方向": choice_side,
                    "选择结算": settle,
                    "选择盈亏": pnl,
                    "赛事级方向": league_choice.side,
                    "赛事级胜率": league_choice.rate,
                    "赛事级样本": league_choice.sample,
                    "盘口倾向方向": line_choice.side,
                    "盘口倾向胜率": line_choice.rate,
                    "盘口倾向样本": line_choice.sample,
                    "一致性": consistency,
                    "选择原因": reason,
                }
            )
            rows.append(item)
    return pd.DataFrame(rows)


def apply_walk_forward_policy(df: pd.DataFrame, min_sample: int) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for i, row in df.iterrows():
        hist = df.iloc[:i]
        league_key = (row["国家"], row["层级"], row["赛事"])
        line_key = (row["国家"], row["层级"], row["赛事"], row["盘口档位"], row["候选标签"])
        h_league = hist[
            (hist["国家"] == row["国家"]) & (hist["层级"] == row["层级"]) & (hist["赛事"] == row["赛事"])
        ]
        h_line = h_league[(h_league["盘口档位"] == row["盘口档位"]) & (h_league["候选标签"] == row["候选标签"])]
        league_choice = choose_higher_rate(h_league, min_sample, "赛前历史-赛事级胜率高方")
        line_choice = choose_higher_rate(h_line, min_sample, "赛前历史-盘口档位+标签胜率高方")
        for policy, choice_side, consistency, reason in [
            (f"顺序回测min{min_sample}-赛事级胜率高方", league_choice.side, "赛事级", league_choice.reason),
            (f"顺序回测min{min_sample}-赛事级+盘口倾向择高", *resolve_combined(league_choice, line_choice)),
        ]:
            settle, pnl = get_side_result(row, choice_side)
            item = row.to_dict()
            item.update(
                {
                    "策略": policy,
                    "选择方向": choice_side,
                    "选择结算": settle,
                    "选择盈亏": pnl,
                    "赛事级方向": league_choice.side,
                    "赛事级胜率": league_choice.rate,
                    "赛事级样本": league_choice.sample,
                    "盘口倾向方向": line_choice.side,
                    "盘口倾向胜率": line_choice.rate,
                    "盘口倾向样本": line_choice.sample,
                    "一致性": consistency,
                    "选择原因": reason,
                }
            )
            rows.append(item)
    return pd.DataFrame(rows)


def display_summary(summary: pd.DataFrame) -> pd.DataFrame:
    out = summary.copy()
    for col in ["有效胜率", "红单命中率", "负率", "ROI", "赛事级胜率", "盘口倾向胜率"]:
        if col in out.columns:
            out[col] = out[col].map(fmt_rate)
    if "均注盈亏" in out.columns:
        out["均注盈亏"] = out["均注盈亏"].map(fmt_unit)
    return out


def md_table(frame: pd.DataFrame, cols: list[str], limit: int | None = None) -> str:
    src = frame if limit is None else frame.head(limit)
    lines = ["| " + " | ".join(cols) + " |", "| " + " | ".join(["---"] * len(cols)) + " |"]
    for _, row in src.iterrows():
        lines.append("| " + " | ".join(str(row.get(c, "")) for c in cols) + " |")
    return "\n".join(lines)


def write_dashboard_compat(summary: pd.DataFrame, ts: str) -> None:
    compat = summary.copy()
    compat["口径"] = compat["国家"] + "-" + compat["层级"] + "-" + compat["赛事"]
    compat["方向"] = compat["策略"]
    compat = compat[
        [
            "口径",
            "方向",
            "下注场数",
            "红",
            "红半",
            "走",
            "黑半",
            "黑",
            "有效胜率",
            "负率",
            "均注盈亏",
            "ROI",
        ]
    ].rename(columns={"下注场数": "样本"})
    compat.to_csv(OUT_DIR / f"top5_tier_split_backtest_{ts}.csv", index=False, encoding="utf-8-sig")

    league = summary.copy()
    league.insert(0, "类型", "胜率高方择向")
    league["口径"] = league["国家"] + "-" + league["层级"]
    league["方向"] = league["策略"]
    league = league[
        [
            "类型",
            "国家",
            "层级",
            "赛事",
            "口径",
            "方向",
            "下注场数",
            "红",
            "红半",
            "走",
            "黑半",
            "黑",
            "红/红半/走/黑半/黑",
            "有效胜率",
            "均注盈亏",
            "ROI",
        ]
    ].rename(columns={"下注场数": "样本"})
    league.to_csv(OUT_DIR / f"top5_tier_split_by_league_{ts}.csv", index=False, encoding="utf-8-sig")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df, input_path = prepare()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    detail = pd.concat(
        [
            apply_full_sample_policy(df, min_sample=1),
            apply_walk_forward_policy(df, min_sample=1),
            apply_walk_forward_policy(df, min_sample=3),
        ],
        ignore_index=True,
    )
    overall = summarize_results(detail, ["策略"])
    by_league = summarize_results(detail, ["策略", "国家", "层级", "赛事"])
    by_tier = summarize_results(detail, ["策略", "国家", "层级"])

    detail_path = OUT_DIR / f"top5_high_win_side_policy_detail_{ts}.csv"
    overall_path = OUT_DIR / f"top5_high_win_side_policy_overall_{ts}.csv"
    league_path = OUT_DIR / f"top5_high_win_side_policy_by_league_{ts}.csv"
    tier_path = OUT_DIR / f"top5_high_win_side_policy_by_country_tier_{ts}.csv"
    report_path = OUT_DIR / f"top5_high_win_side_policy_{ts}.md"

    detail.to_csv(detail_path, index=False, encoding="utf-8-sig")
    show_overall_all = display_summary(overall)
    show_league_all = display_summary(by_league)
    show_tier_all = display_summary(by_tier)
    show_overall_all.to_csv(overall_path, index=False, encoding="utf-8-sig")
    show_league_all.to_csv(league_path, index=False, encoding="utf-8-sig")
    show_tier_all.to_csv(tier_path, index=False, encoding="utf-8-sig")

    dashboard_summary = by_league[by_league["策略"].isin(["顺序回测min3-赛事级胜率高方", "顺序回测min3-赛事级+盘口倾向择高"])].copy()
    write_dashboard_compat(dashboard_summary, ts)

    show_overall = display_summary(overall)
    show_league = display_summary(
        by_league[by_league["策略"].isin(["顺序回测min3-赛事级胜率高方", "顺序回测min3-赛事级+盘口倾向择高"])]
    )
    show_league = show_league.sort_values(["策略", "均注盈亏"], ascending=[True, False])
    report_path.write_text(
        "\n".join(
            [
                "# 五大地区：胜率高方择向统计",
                "",
                f"- 输入底稿：`{input_path}`",
                "- 正向=买当时盘口意图方向；反向=买当时盘口意图相反方向。",
                "- 赛事级胜率高方：在同一国家/层级/赛事内，谁的历史有效胜率高就买谁；胜率相同按均注盈亏。",
                "- 加盘口倾向：同时看同一赛事下的 `盘口档位+候选标签`；若赛事级方向与盘口倾向方向一致则买一致方向，若冲突则买历史有效胜率更高的一方，盘口样本不足时回退赛事级。",
                "- 顺序回测只用当前行之前的历史；`全样本事后体检` 读取了同组最终赛果，只能检查结构，不是赛前可交易胜率。",
                "- 前台/dashboard 只展示 `顺序回测min3`，低于 3 个历史样本的意乙/杯赛等必须显示跳过或样本不足。",
                "",
                "## 总体",
                md_table(
                    show_overall,
                    [
                        "策略",
                        "总场数",
                        "下注场数",
                        "跳过",
                        "红/红半/走/黑半/黑",
                        "有效胜率",
                        "均注盈亏",
                        "ROI",
                        "选正向",
                        "选反向",
                        "一致次数",
                        "冲突次数",
                        "回退赛事级",
                    ],
                ),
                "",
                "## 分联赛/杯赛：顺序回测min3",
                md_table(
                    show_league,
                    [
                        "策略",
                        "国家",
                        "层级",
                        "赛事",
                        "总场数",
                        "下注场数",
                        "红/红半/走/黑半/黑",
                        "有效胜率",
                        "均注盈亏",
                        "ROI",
                        "选正向",
                        "选反向",
                        "一致次数",
                        "冲突次数",
                        "回退赛事级",
                    ],
                ),
                "",
                "## 输出文件",
                f"- 总体：`{overall_path}`",
                f"- 分联赛/杯赛：`{league_path}`",
                f"- 分国家/层级：`{tier_path}`",
                f"- 逐场明细：`{detail_path}`",
            ]
        ),
        encoding="utf-8",
    )
    (OUT_DIR / f"top5_tier_split_backtest_{ts}_clean.md").write_text(report_path.read_text(encoding="utf-8"), encoding="utf-8")

    print(report_path)
    print(overall_path)
    print(league_path)
    print(tier_path)
    print(detail_path)
    print(show_overall.to_string(index=False))


if __name__ == "__main__":
    main()
