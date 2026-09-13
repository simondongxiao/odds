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
    """Skill-required deterministic order; use stable surrogates when older ledgers lack kickoff columns."""
    df = df.copy()
    if "开赛时间" not in df.columns:
        df["开赛时间"] = ""
    if "比赛ID" not in df.columns:
        source = df["模拟ID"] if "模拟ID" in df.columns else df.index.to_series().astype(str)
        df["比赛ID"] = source.map(extract_match_id)
    return df.sort_values(by=["日期", "开赛时间", "比赛ID"], ascending=[True, True, True]).reset_index(drop=True)


@dataclass
class Stat:
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


def parse_float(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    text = str(value).strip()
    if not text:
        return None
    text = text.replace("+", "").replace("u", "").replace("U", "")
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


def settlement_stat(df: pd.DataFrame, settle_col: str, pnl_col: str) -> Stat:
    counts = {key: int((df[settle_col] == key).sum()) for key in COUNT_ORDER}
    sample = sum(counts.values())
    non_push = sample - counts["走"]
    eff = None
    hit = None
    loss = None
    if non_push > 0:
        eff = round((counts["赢"] + 0.5 * counts["赢半"]) / non_push, 4)
        hit = round((counts["赢"] + counts["赢半"]) / non_push, 4)
        loss = round((counts["输"] + counts["输半"]) / non_push, 4)
    pnl = round(float(df[pnl_col].fillna(0).sum()), 4)
    roi = round(pnl / sample, 4) if sample else None
    return Stat(
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


def fmt_rate(v: float | None) -> str:
    return "" if v is None else f"{v * 100:.1f}%"


def fmt_unit(v: float) -> str:
    return f"{v:+.4f}"


def pct_text_to_decimal(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if text.endswith("%"):
        return f"{float(text[:-1]) / 100.0:.4f}"
    return text


def stat_fields(prefix: str, stat: Stat) -> dict[str, object]:
    return {
        f"{prefix}样本": stat.sample,
        f"{prefix}红": stat.red,
        f"{prefix}红半": stat.red_half,
        f"{prefix}走水": stat.push,
        f"{prefix}黑半": stat.black_half,
        f"{prefix}黑": stat.black,
        f"{prefix}红/红半/走/黑半/黑": f"{stat.red}/{stat.red_half}/{stat.push}/{stat.black_half}/{stat.black}",
        f"{prefix}红半折算胜率": fmt_rate(stat.eff_win_rate),
        f"{prefix}红单命中率": fmt_rate(stat.hit_rate),
        f"{prefix}负率": fmt_rate(stat.loss_rate),
        f"{prefix}均注盈亏": fmt_unit(stat.pnl),
        f"{prefix}ROI": fmt_rate(stat.roi),
    }


def summarize_group(df: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for keys, g in df.groupby(group_cols, dropna=False, sort=True):
        if not isinstance(keys, tuple):
            keys = (keys,)
        forward = settlement_stat(g, "意图结算", "意图均注盈亏_数值")
        reverse = settlement_stat(g, "反向结算", "反向均注盈亏_数值")
        edge = "正向" if forward.pnl > reverse.pnl else "反向" if reverse.pnl > forward.pnl else "接近"
        row = {col: val for col, val in zip(group_cols, keys)}
        row.update(
            {
                "比赛数": int(len(g)),
                "当时意图优势": edge,
                "正向减反向盈亏差": fmt_unit(round(forward.pnl - reverse.pnl, 4)),
            }
        )
        row.update(stat_fields("当时意图正向_", forward))
        row.update(stat_fields("当时意图反向_", reverse))
        rows.append(row)
    return pd.DataFrame(rows)


def long_summary(df: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for keys, g in df.groupby(group_cols, dropna=False, sort=True):
        if not isinstance(keys, tuple):
            keys = (keys,)
        base = {col: val for col, val in zip(group_cols, keys)}
        for direction, settle_col, pnl_col in [
            ("当时意图正向", "意图结算", "意图均注盈亏_数值"),
            ("当时意图反向", "反向结算", "反向均注盈亏_数值"),
        ]:
            s = settlement_stat(g, settle_col, pnl_col)
            row = dict(base)
            row.update(
                {
                    "方向": direction,
                    "样本": s.sample,
                    "红": s.red,
                    "红半": s.red_half,
                    "走水": s.push,
                    "黑半": s.black_half,
                    "黑": s.black,
                    "红/红半/走/黑半/黑": f"{s.red}/{s.red_half}/{s.push}/{s.black_half}/{s.black}",
                    "红半折算胜率": fmt_rate(s.eff_win_rate),
                    "红单命中率": fmt_rate(s.hit_rate),
                    "负率": fmt_rate(s.loss_rate),
                    "均注盈亏": fmt_unit(s.pnl),
                    "ROI": fmt_rate(s.roi),
                }
            )
            rows.append(row)
    return pd.DataFrame(rows)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
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

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    country = summarize_group(df, ["国家", "层级"])
    country_total = summarize_group(df.assign(层级="合计"), ["国家", "层级"])
    country_out = pd.concat([country, country_total], ignore_index=True)
    country_out = country_out.sort_values(["国家", "层级"]).reset_index(drop=True)

    league_out = summarize_group(df, ["国家", "层级", "赛事"])
    line_tag_out = summarize_group(df, ["国家", "层级", "赛事", "盘口档位", "候选标签"])
    detail_cols = [
        "日期",
        "国家",
        "层级",
        "赛事",
        "比赛",
        "赛果",
        "即时亚盘",
        "盘口线",
        "盘口档位",
        "上盘方",
        "候选标签",
        "候选映射方向",
        "意图水位",
        "意图结算",
        "意图均注盈亏_数值",
        "反向方向",
        "反向水位",
        "反向结算",
        "反向均注盈亏_数值",
        "模拟ID",
    ]
    detail = df[detail_cols].copy()
    detail = detail.rename(
        columns={
            "意图均注盈亏_数值": "意图均注盈亏",
            "反向均注盈亏_数值": "反向均注盈亏",
        }
    )

    corrected_country = OUT_DIR / f"top5_country_intent_split_{ts}.csv"
    corrected_league = OUT_DIR / f"top5_league_intent_split_{ts}.csv"
    corrected_detail = OUT_DIR / f"top5_country_league_walkforward_{ts}.csv"
    corrected_line_tag = OUT_DIR / f"top5_line_tag_intent_split_{ts}.csv"
    country_out.to_csv(corrected_country, index=False, encoding="utf-8-sig")
    league_out.to_csv(corrected_league, index=False, encoding="utf-8-sig")
    detail.to_csv(corrected_detail, index=False, encoding="utf-8-sig")
    line_tag_out.to_csv(corrected_line_tag, index=False, encoding="utf-8-sig")

    # Rewrite the exact previously shared tables so reopening them shows the corrected logic.
    country_out.to_csv(OUT_DIR / "top5_country_intent_split_20260901_211340.csv", index=False, encoding="utf-8-sig")
    league_out.to_csv(OUT_DIR / "top5_league_intent_split_20260901_211340.csv", index=False, encoding="utf-8-sig")
    detail.to_csv(OUT_DIR / "top5_country_league_walkforward_20260901_211340.csv", index=False, encoding="utf-8-sig")

    tier_summary = long_summary(df, ["国家", "层级"])
    tier_summary.insert(0, "口径", tier_summary["国家"] + "-" + tier_summary["层级"])
    tier_compat = tier_summary[
        [
            "口径",
            "方向",
            "样本",
            "红",
            "红半",
            "走水",
            "黑半",
            "黑",
            "红半折算胜率",
            "均注盈亏",
            "ROI",
            "国家",
            "层级",
        ]
    ].rename(columns={"走水": "走", "红半折算胜率": "有效胜率"})
    tier_compat["有效胜率"] = tier_compat["有效胜率"].map(pct_text_to_decimal)
    tier_compat["ROI"] = tier_compat["ROI"].map(pct_text_to_decimal)
    tier_compat.to_csv(OUT_DIR / f"top5_tier_split_backtest_{ts}.csv", index=False, encoding="utf-8-sig")

    league_long = long_summary(df, ["国家", "层级", "赛事"])
    league_long.insert(0, "类型", "当时盘口意图")
    league_long.insert(3, "口径", league_long["国家"] + "-" + league_long["层级"])
    league_compat = league_long[
        [
            "类型",
            "国家",
            "层级",
            "赛事",
            "口径",
            "方向",
            "样本",
            "红",
            "红半",
            "走水",
            "黑半",
            "黑",
            "红/红半/走/黑半/黑",
            "红半折算胜率",
            "均注盈亏",
            "ROI",
        ]
    ].rename(columns={"走水": "走", "红半折算胜率": "有效胜率"})
    league_compat["有效胜率"] = league_compat["有效胜率"].map(pct_text_to_decimal)
    league_compat["ROI"] = league_compat["ROI"].map(pct_text_to_decimal)
    league_compat.to_csv(OUT_DIR / f"top5_tier_split_by_league_{ts}.csv", index=False, encoding="utf-8-sig")

    report = OUT_DIR / f"top5_country_tier_intent_recalc_{ts}.md"
    top_country_lines = country_out[country_out["层级"] == "合计"].copy()
    top_country_lines["正向盈亏数"] = top_country_lines["当时意图正向_均注盈亏"].str.replace("+", "", regex=False).astype(float)
    top_country_lines = top_country_lines.sort_values("正向盈亏数", ascending=False)
    league_rank = league_out.copy()
    league_rank["正向盈亏数"] = league_rank["当时意图正向_均注盈亏"].str.replace("+", "", regex=False).astype(float)
    league_rank = league_rank.sort_values("正向盈亏数", ascending=False)
    line_tag_rank = line_tag_out.copy()
    line_tag_rank["正向盈亏数"] = line_tag_rank["当时意图正向_均注盈亏"].str.replace("+", "", regex=False).astype(float)
    line_tag_rank = line_tag_rank.sort_values("正向盈亏数", ascending=False)

    def md_table(frame: pd.DataFrame, cols: list[str], limit: int | None = None) -> str:
        if limit is not None:
            frame = frame.head(limit)
        lines = ["| " + " | ".join(cols) + " |", "| " + " | ".join(["---"] * len(cols)) + " |"]
        for _, r in frame.iterrows():
            lines.append("| " + " | ".join(str(r.get(c, "")) for c in cols) + " |")
        return "\n".join(lines)

    report.write_text(
        "\n".join(
            [
                "# 五大地区按国家/层级重算：当时盘口意图模拟",
                "",
                f"- 输入底稿：`{input_path}`",
                "- 口径：只使用每场当时已记录的候选标签、候选映射方向、即时亚盘、盘口档位、水位和赛后真实结算。",
                "- 正向：买当时盘口意图方向；反向：买当时盘口意图相反方向。",
                "- 有效胜率：红=1、红半=0.5、走水剔除、黑半/黑=0；盈亏使用当时水位均注结算。",
                "- 本表不再使用全样本事后择优方向，因此不会把结构诊断胜率误当成赛前可交易胜率。",
                "",
                "## 国家合计",
                md_table(
                    top_country_lines,
                    [
                        "国家",
                        "比赛数",
                        "当时意图优势",
                        "正向减反向盈亏差",
                        "当时意图正向_红/红半/走/黑半/黑",
                        "当时意图正向_红半折算胜率",
                        "当时意图正向_均注盈亏",
                        "当时意图反向_红/红半/走/黑半/黑",
                        "当时意图反向_红半折算胜率",
                        "当时意图反向_均注盈亏",
                    ],
                ),
                "",
                "## 赛事正向盈亏排序",
                md_table(
                    league_rank,
                    [
                        "国家",
                        "层级",
                        "赛事",
                        "比赛数",
                        "当时意图优势",
                        "正向减反向盈亏差",
                        "当时意图正向_红/红半/走/黑半/黑",
                        "当时意图正向_红半折算胜率",
                        "当时意图正向_均注盈亏",
                        "当时意图反向_红/红半/走/黑半/黑",
                        "当时意图反向_红半折算胜率",
                        "当时意图反向_均注盈亏",
                    ],
                ),
                "",
                "## 盘口档位+标签正向盈亏前二十",
                md_table(
                    line_tag_rank,
                    [
                        "国家",
                        "层级",
                        "赛事",
                        "盘口档位",
                        "候选标签",
                        "比赛数",
                        "当时意图优势",
                        "正向减反向盈亏差",
                        "当时意图正向_红/红半/走/黑半/黑",
                        "当时意图正向_红半折算胜率",
                        "当时意图正向_均注盈亏",
                        "当时意图反向_红/红半/走/黑半/黑",
                        "当时意图反向_红半折算胜率",
                        "当时意图反向_均注盈亏",
                    ],
                    limit=20,
                ),
                "",
                "## 输出文件",
                f"- 国家/层级：`{corrected_country}`",
                f"- 赛事拆分：`{corrected_league}`",
                f"- 逐场明细：`{corrected_detail}`",
                f"- 盘口档位+标签：`{corrected_line_tag}`",
            ]
        ),
        encoding="utf-8",
    )
    (OUT_DIR / f"top5_tier_split_backtest_{ts}_clean.md").write_text(report.read_text(encoding="utf-8"), encoding="utf-8")

    print(corrected_country)
    print(corrected_league)
    print(corrected_detail)
    print(corrected_line_tag)
    print(report)
    print(country_out[country_out["层级"] == "合计"].to_string(index=False))
    print(league_rank.to_string(index=False))


if __name__ == "__main__":
    main()
