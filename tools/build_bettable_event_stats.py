from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path

import pandas as pd


ROOT = Path(r"D:\codex\outputs\football_odds_trader")
SEQ_DIR = ROOT / "backtests" / "sequential_asian"
LEDGER_DIR = ROOT / "ledger"


def newest(root: Path, pattern: str) -> Path:
    files = sorted(root.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        raise FileNotFoundError(f"No file matches {pattern} under {root}")
    return files[0]


COUNTRY_RULES: list[tuple[str, str]] = [
    ("中", "中国"),
    ("日", "日本"),
    ("韩", "韩国"),
    ("澳", "澳大利亚"),
    ("美", "美国"),
    ("加拿", "加拿大"),
    ("巴西", "巴西"),
    ("巴甲", "巴西"),
    ("巴乙", "巴西"),
    ("阿甲", "阿根廷"),
    ("阿乙", "阿根廷"),
    ("阿根廷", "阿根廷"),
    ("智利", "智利"),
    ("哥伦", "哥伦比亚"),
    ("乌拉", "乌拉圭"),
    ("厄瓜", "厄瓜多尔"),
    ("秘鲁", "秘鲁"),
    ("玻利", "玻利维亚"),
    ("英", "英格兰"),
    ("西甲", "西班牙"),
    ("西乙", "西班牙"),
    ("西协", "西班牙"),
    ("西班牙", "西班牙"),
    ("意", "意大利"),
    ("德", "德国"),
    ("法", "法国"),
    ("葡", "葡萄牙"),
    ("荷", "荷兰"),
    ("比", "比利时"),
    ("土", "土耳其"),
    ("瑞典", "瑞典"),
    ("瑞士", "瑞士"),
    ("挪", "挪威"),
    ("俄", "俄罗斯"),
    ("乌克", "乌克兰"),
    ("丹", "丹麦"),
    ("捷", "捷克"),
    ("克罗", "克罗地亚"),
    ("冰岛", "冰岛"),
    ("希腊", "希腊"),
    ("罗", "罗马尼亚"),
    ("波兰", "波兰"),
    ("保", "保加利亚"),
    ("科威特", "科威特"),
    ("卡", "卡塔尔"),
    ("沙特", "沙特"),
    ("阿联酋", "阿联酋"),
    ("哈萨", "哈萨克斯坦"),
    ("乌兹", "乌兹别克斯坦"),
    ("南非", "南非"),
]


def country_from_league(league: object) -> str:
    text = str(league or "")
    for needle, country in COUNTRY_RULES:
        if needle in text:
            return country
    return "未识别"


def tier_from_class(competition_class: object, league: object) -> str:
    klass = str(competition_class or "")
    league_text = str(league or "")
    text = f"{klass} {league_text}"
    if "国家队" in text:
        return "国家队正式赛"
    if "洲际" in text or "欧冠" in text or "欧联" in text or "亚冠" in text or "南球" in text or "解放者" in text:
        return "洲际杯赛"
    if "杯" in text or "国内杯赛" in text:
        return "杯赛"
    if "T1" in klass or "顶级" in klass:
        return "顶级联赛"
    if "T2" in klass or "T3" in klass or "次级" in klass or "次次级" in klass:
        return "非顶级联赛"
    return "未知分类"


def water_bucket(value: object) -> str:
    try:
        water = float(value)
    except Exception:
        return "缺水位"
    if water <= 0.70:
        return "<=0.70"
    if water <= 0.80:
        return "0.71-0.80"
    if water <= 0.90:
        return "0.81-0.90"
    if water <= 1.00:
        return "0.91-1.00"
    if water <= 1.10:
        return "1.01-1.10"
    return ">1.10"


def q4(value: float | int | None) -> str:
    if value is None or pd.isna(value):
        return ""
    return f"{float(value):.4f}"


def build_stats(detail_csv: Path, out_date: str) -> Path:
    df = pd.read_csv(detail_csv, encoding="utf-8-sig")
    bets = df[df["动作"].isin(["正向", "反向"])].copy()
    bets = bets[bets["已结算"].eq("是")].copy()
    bets["国家"] = bets["赛事"].map(country_from_league)
    bets["赛事层级"] = bets.apply(lambda r: tier_from_class(r.get("比赛分类"), r.get("赛事")), axis=1)
    bets["盘口"] = bets.get("盘口档位", "").fillna("").astype(str).str.strip().replace("", "缺盘口")
    bets["倾向意图"] = bets.get("盘口意图标签", "").fillna("").astype(str).str.strip().replace("", "缺倾向意图")
    bets["水位分层"] = bets["选中水位"].map(water_bucket)
    bets["选中水位数值"] = pd.to_numeric(bets["选中水位"], errors="coerce")
    bets["实际盈亏Unit数值"] = pd.to_numeric(bets["实际盈亏Unit"], errors="coerce").fillna(0.0)
    bets["实际盈亏金额数值"] = pd.to_numeric(bets["实际盈亏金额"], errors="coerce").fillna(0.0)
    bets["下注金额数值"] = pd.to_numeric(bets["下注金额"], errors="coerce").fillna(0.0)

    rows: list[dict[str, object]] = []
    group_cols = ["微观板块", "国家", "赛事层级", "盘口", "水位分层", "倾向意图"]
    for keys, group in bets.groupby(group_cols, dropna=False, sort=True):
        region, country, tier, line_bucket, bucket, intent_tag = keys
        labels = group["结算标签"].astype(str)
        red = int(labels.eq("红").sum())
        red_half = int(labels.eq("红半").sum())
        push = int(labels.eq("走水").sum())
        black_half = int(labels.eq("黑半").sum())
        black = int(labels.eq("黑").sum())
        wins = red + 0.5 * red_half
        losses = black + 0.5 * black_half
        denom = wins + losses
        pnl_unit = float(group["实际盈亏Unit数值"].sum())
        stake = float(group["下注金额数值"].sum())
        profit = float(group["实际盈亏金额数值"].sum())
        rows.append(
            {
                "统计日期": out_date,
                "数据源": str(detail_csv),
                "地区": region,
                "国家": country,
                "赛事层级": tier,
                "盘口": line_bucket,
                "水位分层": bucket,
                "倾向意图": intent_tag,
                "样本": int(len(group)),
                "红": red,
                "红半": red_half,
                "走水": push,
                "黑半": black_half,
                "黑": black,
                "有效胜率": wins / denom if denom else None,
                "负率": losses / denom if denom else None,
                "均注盈亏Unit": pnl_unit,
                "平均水位": float(group["选中水位数值"].mean()) if group["选中水位数值"].notna().any() else None,
                "ROI": profit / stake if stake else None,
                "备注": "仅含严格walk-forward漏斗通过且已结算的正向/反向亚盘投注行；按地区-国家-赛事层级-盘口-水位分层-倾向意图统计红黑",
            }
        )

    out = LEDGER_DIR / f"bettable_event_stats_{out_date}.csv"
    LEDGER_DIR.mkdir(parents=True, exist_ok=True)
    fields = [
        "统计日期",
        "数据源",
        "地区",
        "国家",
        "赛事层级",
        "盘口",
        "水位分层",
        "倾向意图",
        "样本",
        "红",
        "红半",
        "走水",
        "黑半",
        "黑",
        "有效胜率",
        "负率",
        "均注盈亏Unit",
        "平均水位",
        "ROI",
        "备注",
    ]
    result = pd.DataFrame(rows, columns=fields)
    for col in ["有效胜率", "负率", "均注盈亏Unit", "平均水位", "ROI"]:
        if col in result:
            result[col] = result[col].map(lambda x: q4(x) if x != "" else "")
    result.to_csv(out, index=False, encoding="utf-8-sig")
    return out


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build long-run bettable event stats from strict sequential detail.")
    parser.add_argument("--detail", type=Path, default=None, help="sequential_asian_backtest_*_detail.csv")
    parser.add_argument("--date", default=dt.date.today().isoformat(), help="stats date, e.g. 2026-09-01")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    detail = args.detail or newest(SEQ_DIR, "sequential_asian_backtest_*_detail.csv")
    out = build_stats(detail, args.date)
    df = pd.read_csv(out, encoding="utf-8-sig")
    print(out)
    print(f"rows={len(df)}")
    if not df.empty:
        print(df.sort_values(["均注盈亏Unit", "样本"], ascending=False).head(20).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
