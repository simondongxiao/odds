from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pandas as pd


ROOT = Path(r"D:\codex\outputs\football_odds_trader")
LEDGER = ROOT / "ledger"
OUT_ROOT = ROOT / "backtests" / "sequential_asian"

TAG_ALIASES = {
    "阻下/上盘保护": "阻下/下盘保护",
}


def canonical_tag(tag: object) -> str:
    text = str(tag or "").replace(" ", "").strip()
    return TAG_ALIASES.get(text, text)


FORWARD = "正向"
REVERSE = "反向"
NO_BET = "不投"

SETTLED_SKIP = {"", "待赛", "未开赛", "进行中", "取消", "取消/延期", "延期", "腰斩", "赛果未匹配待人工核验"}
NO_COUNT_PREFIXES = ("不计", "无方向", "平衡")
BALANCED_TAG = "平衡盘/等待临场确认"


def q4(value: float | None) -> float | None:
    if value is None:
        return None
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return round(float(value), 4)


def f4(value: float | None) -> str:
    value = q4(value)
    return "" if value is None else f"{value:.4f}"


def parse_float(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    text = str(value).strip()
    if not text:
        return None
    text = text.replace(",", "").replace("u", "").replace("U", "").replace("+", "")
    is_pct = text.endswith("%")
    if is_pct:
        text = text[:-1]
    try:
        num = float(text)
    except ValueError:
        return None
    if is_pct:
        num /= 100.0
    return q4(num)


def first_existing(row: dict[str, object], names: Iterable[str], default: object = "") -> object:
    for name in names:
        if name in row and str(row.get(name, "")).strip() != "":
            return row.get(name)
    return default


def normalize_date(value: object) -> str:
    if value is None or str(value).strip() == "":
        return "1900-01-01"
    try:
        return pd.to_datetime(value).date().isoformat()
    except Exception:
        text = str(value).strip()
        m = re.search(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", text)
        if m:
            y, mo, d = map(int, m.groups())
            return dt.date(y, mo, d).isoformat()
    return str(value).strip()


def normalize_kickoff(value: object, date_text: str) -> str:
    text = "" if value is None else str(value).strip()
    if not text:
        return f"{date_text} 00:00:00"
    text = text.replace("北京时间", "").replace("（东8区）", "").strip()
    parsed = None
    try:
        parsed = pd.to_datetime(text)
    except Exception:
        parsed = None
    if parsed is not None and not pd.isna(parsed):
        if getattr(parsed, "year", 1900) != 1900:
            return parsed.strftime("%Y-%m-%d %H:%M:%S")

    md = re.search(r"(\d{1,2})[-/](\d{1,2})\s+(\d{1,2}):(\d{2})", text)
    if md:
        y = int(date_text[:4]) if re.match(r"\d{4}-", date_text) else 1900
        mo, d, hh, mm = map(int, md.groups())
        return dt.datetime(y, mo, d, hh, mm).strftime("%Y-%m-%d %H:%M:%S")

    hm = re.search(r"(\d{1,2}):(\d{2})", text)
    if hm:
        hh, mm = map(int, hm.groups())
        return f"{date_text} {hh:02d}:{mm:02d}:00"

    return text


def latest_history_file() -> Path:
    files = sorted(
        LEDGER.glob("asian_intent_history_detail_*.csv"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not files:
        raise FileNotFoundError(f"No asian_intent_history_detail_*.csv found under {LEDGER}")
    return files[0]


def load_table(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix in {".xlsx", ".xls"}:
        df = pd.read_excel(path)
    elif suffix in {".csv", ".txt"}:
        df = pd.read_csv(path, encoding="utf-8-sig")
    else:
        raise ValueError(f"Unsupported input type: {path.suffix}")
    return df


def coalesce_series(df: pd.DataFrame, names: list[str], default: str = "") -> pd.Series:
    out = pd.Series([default] * len(df), index=df.index, dtype="object")
    for name in names:
        if name not in df.columns:
            continue
        series = df[name].fillna("").astype(str)
        out = out.where(out.astype(str).str.strip() != "", series)
    return out


def normalize_region(raw_region: object, league: object) -> str:
    text = str(raw_region or "").strip()
    mapping = {
        "北美系列": "北美",
        "南美系列": "拉美",
        "日韩系列": "东亚",
        "西亚/中亚系列": "海湾",
        "欧洲五大系列": "欧洲五大",
        "欧洲非五大系列": "欧洲非五大",
    }
    if text in mapping:
        return mapping[text]
    if text in {"北美", "拉美", "东亚", "海湾", "欧洲五大", "欧洲非五大", "其他"}:
        return text

    league_text = str(league or "")
    if re.search(r"美职|美冠|美甲|美乙|美国|加拿大|MLS|USL|Canada|USA", league_text, re.I):
        return "北美"
    if re.search(r"巴西|阿甲|阿乙|阿根廷|智利|厄瓜|乌拉|哥伦|巴拉|玻利|秘鲁|委内|南美|解放者|Brazil|Argentina|Chile|Ecuador|Uruguay|Colombia", league_text, re.I):
        return "拉美"
    if re.search(r"日职|日皇|日联|日本|韩K|韩国|韩足|中超|中协|中国|J[123]|K联|Korea|Japan|China", league_text, re.I):
        return "东亚"
    if re.search(r"科威|哈萨克|卡塔|阿联|沙特|阿曼|乌兹|亚冠|西亚|中亚|Kuwait|Qatar|Saudi|UAE|Uzbek|Kazakh", league_text, re.I):
        return "海湾"
    if re.match(r"^(英|西|意|德|法)", league_text) or re.search(r"England|Spain|Italy|Germany|France", league_text, re.I):
        return "欧洲五大"
    if re.search(r"欧|荷|葡|比|土|瑞典|挪|俄|乌克|丹麦|瑞士|捷|克亚|冰岛|罗|希腊|苏|波兰|立陶|保乙|Netherlands|Portugal|Belgium|Turkey|Sweden|Norway|Russia|Ukraine|Denmark|Swiss|Poland", league_text, re.I):
        return "欧洲非五大"
    return "其他"


def prepare_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    source_rows = df.to_dict("records")

    dates = []
    kickoffs = []
    match_ids = []
    regions = []
    tags = []
    line_buckets = []
    leagues = []
    matches = []

    for idx, row in enumerate(source_rows):
        date_text = normalize_date(first_existing(row, ["日期", "list_date", "date", "比赛日期"], "1900-01-01"))
        kickoff = normalize_kickoff(first_existing(row, ["开赛时间", "北京时间", "bj_time", "time", "比赛时间"], ""), date_text)
        match_id = str(first_existing(row, ["比赛ID", "match_id", "模拟ID", "id"], f"row-{idx:08d}")).strip()
        league = str(first_existing(row, ["赛事", "联赛", "league", "league_cn"], "")).strip()
        match = str(first_existing(row, ["比赛", "对阵", "match", "match_name"], match_id)).strip()
        region = normalize_region(first_existing(row, ["微观板块", "micro_region", "region"], ""), league)
        tag = canonical_tag(first_existing(row, ["盘口意图标签", "意图标签", "候选标签", "tag"], ""))
        line_bucket = str(first_existing(row, ["盘口档位", "盘口线", "line_bucket", "handicap_bucket"], "")).strip()

        dates.append(date_text)
        kickoffs.append(kickoff)
        match_ids.append(match_id)
        regions.append(region)
        tags.append(tag)
        line_buckets.append(line_bucket)
        leagues.append(league)
        matches.append(match)

    df["日期"] = dates
    df["开赛时间"] = kickoffs
    df["比赛ID"] = match_ids
    df["微观板块"] = regions
    df["盘口意图标签"] = tags
    df["盘口档位"] = line_buckets
    df["赛事"] = leagues
    df["比赛"] = matches

    # Required deterministic time alignment. Keep this exact sort before any walk-forward loop.
    df = df.sort_values(by=["日期", "开赛时间", "比赛ID"], ascending=[True, True, True]).reset_index(drop=True)
    return df


def derive_flat(unit: float | None, water: float | None) -> float | None:
    if unit is None:
        return None
    if unit > 0:
        return q4(unit * water) if water is not None else None
    if unit < 0:
        return q4(unit)
    return 0.0


@dataclass
class MatchRow:
    seq: int
    date: str
    date_obj: dt.date
    kickoff: str
    match_id: str
    league: str
    match: str
    competition_class: str
    region: str
    tag: str
    line_bucket: str
    forward_water: float | None
    reverse_water: float | None
    forward_unit: float | None
    reverse_unit: float | None
    forward_flat: float | None
    reverse_flat: float | None
    settled: bool


def is_no_count_tag(tag: str) -> bool:
    if not tag or tag == BALANCED_TAG:
        return True
    return any(tag.startswith(prefix) for prefix in NO_COUNT_PREFIXES)


def row_from_record(seq: int, record: dict[str, object]) -> MatchRow:
    date_text = str(record.get("日期", "1900-01-01"))
    try:
        date_obj = dt.date.fromisoformat(date_text[:10])
    except ValueError:
        date_obj = dt.date(1900, 1, 1)

    fw = parse_float(first_existing(record, ["正向水位", "意图水位", "即时水位", "Water", "water"], None))
    rw = parse_float(first_existing(record, ["反向水位", "reverse_water", "ReverseWater"], None))
    fu = parse_float(first_existing(record, ["正向盈亏单位", "意图盈亏单位", "forward_pnl_unit"], None))
    ru = parse_float(first_existing(record, ["反向盈亏单位", "reverse_pnl_unit"], None))
    ff = parse_float(first_existing(record, ["正向均注盈亏", "意图均注盈亏", "forward_flat_pnl"], None))
    rf = parse_float(first_existing(record, ["反向均注盈亏", "reverse_flat_pnl"], None))
    if ff is None:
        ff = derive_flat(fu, fw)
    if rf is None:
        rf = derive_flat(ru, rw)

    result_text = str(record.get("赛果", "")).strip()
    settled = (
        result_text not in SETTLED_SKIP
        and not is_no_count_tag(str(record.get("盘口意图标签", "")).strip())
        and fu is not None
        and ru is not None
        and ff is not None
        and rf is not None
    )

    return MatchRow(
        seq=seq,
        date=date_text,
        date_obj=date_obj,
        kickoff=str(record.get("开赛时间", "")),
        match_id=str(record.get("比赛ID", "")),
        league=str(record.get("赛事", "")),
        match=str(record.get("比赛", "")),
        competition_class=str(first_existing(record, ["比赛分类", "赛制阶段", "competition_class"], "")),
        region=str(record.get("微观板块", "")),
        tag=canonical_tag(record.get("盘口意图标签", "")),
        line_bucket=str(record.get("盘口档位", "")).strip(),
        forward_water=fw,
        reverse_water=rw,
        forward_unit=fu,
        reverse_unit=ru,
        forward_flat=ff,
        reverse_flat=rf,
        settled=settled,
    )


@dataclass
class SideStats:
    sample: int
    red: int
    red_half: int
    push: int
    black_half: int
    black: int
    win_rate: float | None
    loss_rate: float | None
    flat_pnl: float

    @property
    def effective_sample(self) -> int:
        return self.red + self.red_half + self.black_half + self.black


def result_label(unit: float | None) -> str:
    if unit is None:
        return ""
    if unit >= 1:
        return "红"
    if 0 < unit < 1:
        return "红半"
    if unit == 0:
        return "走水"
    if -1 < unit < 0:
        return "黑半"
    return "黑"


def calc_side_stats(rows: list[MatchRow], direction: str) -> SideStats:
    red = red_half = push = black_half = black = 0
    flat_pnl = 0.0
    count = 0
    for row in rows:
        unit = row.forward_unit if direction == FORWARD else row.reverse_unit
        flat = row.forward_flat if direction == FORWARD else row.reverse_flat
        if unit is None or flat is None:
            continue
        count += 1
        flat_pnl += flat
        label = result_label(unit)
        if label == "红":
            red += 1
        elif label == "红半":
            red_half += 1
        elif label == "走水":
            push += 1
        elif label == "黑半":
            black_half += 1
        elif label == "黑":
            black += 1
    wins = red + red_half
    losses = black + black_half
    denom = wins + losses
    win_rate = wins / denom if denom else None
    loss_rate = losses / denom if denom else None
    return SideStats(
        sample=count,
        red=red,
        red_half=red_half,
        push=push,
        black_half=black_half,
        black=black,
        win_rate=q4(win_rate),
        loss_rate=q4(loss_rate),
        flat_pnl=q4(flat_pnl) or 0.0,
    )


def preferred_direction(forward: SideStats, reverse: SideStats) -> str | None:
    if forward.sample == 0 and reverse.sample == 0:
        return None
    fw = forward.win_rate if forward.win_rate is not None else -1.0
    rv = reverse.win_rate if reverse.win_rate is not None else -1.0
    if fw > rv:
        return FORWARD
    if rv > fw:
        return REVERSE
    if forward.flat_pnl > 0 and reverse.flat_pnl <= 0:
        return FORWARD
    if reverse.flat_pnl > 0 and forward.flat_pnl <= 0:
        return REVERSE
    return FORWARD if forward.flat_pnl >= reverse.flat_pnl else REVERSE


def bayes_rate(local_rate: float | None, local_n: int, global_rate: float | None, global_m: int) -> float | None:
    if local_rate is None and global_rate is None:
        return None
    if local_rate is None or local_n <= 0:
        return q4(global_rate)
    if global_rate is None or global_m <= 0:
        return q4(local_rate)
    return q4(((local_n * local_rate) + (global_m * global_rate)) / (local_n + global_m))


def breakeven_threshold(water: float | None, safety_buffer: float) -> tuple[float | None, float | None]:
    if water is None or water <= -1:
        return None, None
    breakeven = 1.0 / (water + 1.0)
    return q4(breakeven), q4(breakeven + safety_buffer)


@dataclass
class RiskState:
    state: str
    stake_factor: float
    reason: str
    yesterday_roi: float
    negative_roi_days: int
    recent_loss_count: int


def turnover_roi(rows: list[dict[str, object]]) -> float:
    turnover = sum(float(r.get("stake_amount", 0.0)) for r in rows)
    if turnover <= 0:
        return 0.0
    profit = sum(float(r.get("profit_amount", 0.0)) for r in rows)
    return q4(profit / turnover) or 0.0


def risk_state_for(region: str, current_date: dt.date, strategy_history: list[dict[str, object]], severe_loss_count: int) -> RiskState:
    past = [r for r in strategy_history if r["region"] == region and r["date_obj"] < current_date]
    yday = current_date - dt.timedelta(days=1)
    yday_rows = [r for r in past if r["date_obj"] == yday]
    yday_roi = turnover_roi(yday_rows)

    by_day: dict[dt.date, list[dict[str, object]]] = defaultdict(list)
    for row in past:
        by_day[row["date_obj"]].append(row)

    negative_roi_days = 0
    for day in sorted(by_day.keys(), reverse=True):
        if day >= current_date:
            continue
        roi = turnover_roi(by_day[day])
        if roi < 0:
            negative_roi_days += 1
        else:
            break

    recent_loss_count = 0
    for row in sorted(past, key=lambda r: (r["date_obj"], r["kickoff"], r["match_id"]), reverse=True):
        pnl_unit = float(row.get("pnl_unit", 0.0))
        if pnl_unit < 0:
            recent_loss_count += 1
        elif pnl_unit > 0:
            break

    if negative_roi_days >= 2 or recent_loss_count > severe_loss_count:
        return RiskState("状态C-熔断/静默观望", 0.0, "连续两天负ROI或近期严重亏损", yday_roi, negative_roi_days, recent_loss_count)
    if yday_roi < 0:
        return RiskState("状态B-预警/降半仓", 0.5, "昨日ROI为负，今日该板块半仓", yday_roi, negative_roi_days, recent_loss_count)
    return RiskState("状态A-正常态", 1.0, "昨日ROI非负，标准仓位", yday_roi, negative_roi_days, recent_loss_count)


@dataclass
class Config:
    safety_buffer: float = 0.02
    same_line_min_sample: int = 8
    same_line_veto_rate: float = 0.40
    rolling_window: int = 15
    rolling_min_sample: int = 15
    rolling_min_win_rate: float = 0.40
    rolling_min_flat_pnl: float = -3.0
    severe_loss_count: int = 5
    min_tag_sample: int = 8
    min_micro_sample: int = 8
    intent_only: bool = True
    starting_bankroll: float = 100.0
    standard_stake_rate: float = 0.05


def blocked(row: MatchRow, stage: str, reason: str, risk: RiskState | None = None) -> dict[str, object]:
    return {
        "动作": NO_BET,
        "拦截阶段": stage,
        "拦截原因": reason,
        "风控状态": risk.state if risk else "",
        "仓位系数": risk.stake_factor if risk else 0.0,
        "昨日ROI": risk.yesterday_roi if risk else None,
        "连续负ROI天数": risk.negative_roi_days if risk else None,
        "近期连续亏损场": risk.recent_loss_count if risk else None,
    }


def decide_match(
    row: MatchRow,
    settled_history: list[MatchRow],
    strategy_history: list[dict[str, object]],
    config: Config,
) -> dict[str, object]:
    if is_no_count_tag(row.tag):
        return blocked(row, "1-历史样本", "盘口意图标签为空/平衡盘，不形成投注")

    tag_hist = [r for r in settled_history if r.tag == row.tag]
    M = len(tag_hist)
    if M < config.min_tag_sample:
        return blocked(row, "1-历史样本", f"标签历史样本不足：M={M}")

    micro_hist = [r for r in tag_hist if r.region == row.region]
    n = len(micro_hist)
    if n < config.min_micro_sample:
        return blocked(row, "1-历史样本", f"微观板块同标签样本不足：n={n}")
    line_tag_hist = [r for r in tag_hist if r.line_bucket == row.line_bucket]
    rolling_hist = tag_hist[-config.rolling_window :]

    g_forward = calc_side_stats(tag_hist, FORWARD)
    g_reverse = calc_side_stats(tag_hist, REVERSE)
    m_forward = calc_side_stats(micro_hist, FORWARD)
    m_reverse = calc_side_stats(micro_hist, REVERSE)
    l_forward = calc_side_stats(line_tag_hist, FORWARD)
    l_reverse = calc_side_stats(line_tag_hist, REVERSE)
    r_forward = calc_side_stats(rolling_hist, FORWARD)
    r_reverse = calc_side_stats(rolling_hist, REVERSE)

    global_pref = preferred_direction(g_forward, g_reverse)
    micro_pref = preferred_direction(m_forward, m_reverse)

    combined_forward = bayes_rate(m_forward.win_rate, n, g_forward.win_rate, M)
    combined_reverse = bayes_rate(m_reverse.win_rate, n, g_reverse.win_rate, M)
    if combined_forward is None and combined_reverse is None:
        return blocked(row, "2-意图与微观对齐", "正反向历史胜率均不可计算")
    if (combined_forward or -1.0) >= (combined_reverse or -1.0):
        selected = FORWARD
        selected_rate = combined_forward
    else:
        selected = REVERSE
        selected_rate = combined_reverse

    selected_water = row.forward_water if selected == FORWARD else row.reverse_water
    breakeven, threshold = breakeven_threshold(selected_water, config.safety_buffer)
    if threshold is None or selected_rate is None:
        return blocked(row, "3-动态水位阈值", "选中方向水位缺失，无法计算盈亏平衡")
    if selected_rate < threshold:
        out = blocked(row, "3-动态水位阈值", "性价比不足，不投")
        out.update({"综合胜率": selected_rate, "选中水位": selected_water, "盈亏平衡胜率": breakeven, "通过阈值": threshold})
        return out

    selected_line_stats = l_forward if selected == FORWARD else l_reverse
    if len(line_tag_hist) > config.same_line_min_sample and selected_line_stats.win_rate is not None:
        if selected_line_stats.win_rate < config.same_line_veto_rate:
            out = blocked(row, "4-同盘口档位风控", "同档胜率过低，不投")
            out.update({"同档样本": len(line_tag_hist), "同档选中胜率": selected_line_stats.win_rate})
            return out

    selected_roll = r_forward if selected == FORWARD else r_reverse
    if len(rolling_hist) >= config.rolling_min_sample:
        if (selected_roll.win_rate is not None and selected_roll.win_rate < config.rolling_min_win_rate) or selected_roll.flat_pnl <= config.rolling_min_flat_pnl:
            out = blocked(row, "5-近期15场滚动熔断", "近期滚动回测熔断，不投")
            out.update({"近15样本": len(rolling_hist), "近15选中胜率": selected_roll.win_rate, "近15选中盈亏": selected_roll.flat_pnl})
            return out

    risk = risk_state_for(row.region, row.date_obj, strategy_history, config.severe_loss_count)
    if risk.stake_factor == 0:
        return blocked(row, "6-按日阶梯风控", "风控熔断，只观察不投注", risk)

    return {
        "动作": selected,
        "拦截阶段": "7-通过/结算",
        "拦截原因": "通过",
        "M": M,
        "n": n,
        "标签正向胜率": g_forward.win_rate,
        "标签反向胜率": g_reverse.win_rate,
        "标签正向盈亏": g_forward.flat_pnl,
        "标签反向盈亏": g_reverse.flat_pnl,
        "微观正向胜率": m_forward.win_rate,
        "微观反向胜率": m_reverse.win_rate,
        "微观正向盈亏": m_forward.flat_pnl,
        "微观反向盈亏": m_reverse.flat_pnl,
        "近15样本": len(rolling_hist),
        "近15正向胜率": r_forward.win_rate,
        "近15反向胜率": r_reverse.win_rate,
        "近15正向盈亏": r_forward.flat_pnl,
        "近15反向盈亏": r_reverse.flat_pnl,
        "全局优先方向": global_pref or "",
        "微观优先方向": micro_pref or "",
        "选择方向": selected,
        "综合胜率": selected_rate,
        "选中水位": selected_water,
        "盈亏平衡胜率": breakeven,
        "通过阈值": threshold,
        "同档样本": len(line_tag_hist),
        "同档选中胜率": selected_line_stats.win_rate,
        "风控状态": risk.state,
        "仓位系数": risk.stake_factor,
        "昨日ROI": risk.yesterday_roi,
        "连续负ROI天数": risk.negative_roi_days,
        "近期连续亏损场": risk.recent_loss_count,
    }


DETAIL_FIELDS = [
    "序号",
    "日期",
    "开赛时间",
    "比赛ID",
    "赛事",
    "比赛",
    "比赛分类",
    "微观板块",
    "盘口意图标签",
    "盘口档位",
    "M",
    "n",
    "标签正向胜率",
    "标签反向胜率",
    "标签正向盈亏",
    "标签反向盈亏",
    "微观正向胜率",
    "微观反向胜率",
    "微观正向盈亏",
    "微观反向盈亏",
    "近15样本",
    "近15正向胜率",
    "近15反向胜率",
    "近15正向盈亏",
    "近15反向盈亏",
    "全局优先方向",
    "微观优先方向",
    "选择方向",
    "综合胜率",
    "选中水位",
    "盈亏平衡胜率",
    "通过阈值",
    "同档样本",
    "同档选中胜率",
    "风控状态",
    "昨日ROI",
    "连续负ROI天数",
    "近期连续亏损场",
    "仓位系数",
    "标准仓位比例",
    "实际仓位比例",
    "下注金额",
    "动作",
    "拦截阶段",
    "拦截原因",
    "已结算",
    "结算标签",
    "实际盈亏Unit",
    "实际盈亏金额",
    "资金流水ROI贡献",
]


def selected_flat_and_unit(row: MatchRow, action: str) -> tuple[float | None, float | None]:
    if action == FORWARD:
        return row.forward_flat, row.forward_unit
    if action == REVERSE:
        return row.reverse_flat, row.reverse_unit
    return None, None


def make_detail_row(
    row: MatchRow,
    decision: dict[str, object],
    day_start_bankroll: float,
    config: Config,
) -> tuple[dict[str, object], dict[str, object] | None]:
    action = str(decision.get("动作", NO_BET))
    stake_factor = float(decision.get("仓位系数", 0.0) or 0.0)
    stake_rate = config.standard_stake_rate * stake_factor if action in {FORWARD, REVERSE} else 0.0
    stake_amount = day_start_bankroll * stake_rate
    flat, unit = selected_flat_and_unit(row, action)
    settled = row.settled and action in {FORWARD, REVERSE} and flat is not None and unit is not None
    pnl_unit = q4(flat * stake_factor) if settled else 0.0
    profit_amount = q4(stake_amount * flat) if settled else 0.0
    turnover_roi_contribution = q4(profit_amount / stake_amount) if settled and stake_amount else None
    settle = result_label(unit) if settled else ("未结算" if action in {FORWARD, REVERSE} else "不投")

    detail = {
        "序号": row.seq,
        "日期": row.date,
        "开赛时间": row.kickoff,
        "比赛ID": row.match_id,
        "赛事": row.league,
        "比赛": row.match,
        "比赛分类": row.competition_class,
        "微观板块": row.region,
        "盘口意图标签": row.tag,
        "盘口档位": row.line_bucket,
        "标准仓位比例": q4(config.standard_stake_rate),
        "实际仓位比例": q4(stake_rate),
        "下注金额": q4(stake_amount),
        "动作": action,
        "拦截阶段": decision.get("拦截阶段", ""),
        "拦截原因": decision.get("拦截原因", ""),
        "已结算": "是" if row.settled else "否",
        "结算标签": settle,
        "实际盈亏Unit": pnl_unit,
        "实际盈亏金额": profit_amount,
        "资金流水ROI贡献": turnover_roi_contribution,
    }
    for field in DETAIL_FIELDS:
        if field not in detail:
            detail[field] = decision.get(field, "")

    strategy_record = None
    if settled:
        strategy_record = {
            "date": row.date,
            "date_obj": row.date_obj,
            "kickoff": row.kickoff,
            "match_id": row.match_id,
            "region": row.region,
            "tag": row.tag,
            "action": action,
            "stake_amount": float(stake_amount),
            "profit_amount": float(profit_amount or 0.0),
            "pnl_unit": float(pnl_unit or 0.0),
            "settlement": settle,
        }
    return detail, strategy_record


def summarize_rows(rows: list[dict[str, object]]) -> dict[str, object]:
    bets = [r for r in rows if r["动作"] in {FORWARD, REVERSE}]
    settled_bets = [r for r in bets if r["已结算"] == "是"]
    labels = Counter(str(r["结算标签"]) for r in settled_bets)
    wins = labels["红"] + labels["红半"]
    losses = labels["黑"] + labels["黑半"]
    effective = wins + losses
    total_profit = sum(float(r.get("实际盈亏金额") or 0.0) for r in settled_bets)
    total_stake = sum(float(r.get("下注金额") or 0.0) for r in settled_bets)
    total_unit = sum(float(r.get("实际盈亏Unit") or 0.0) for r in settled_bets)
    return {
        "完整测算比赛数": len(rows),
        "符合投注条件数": len(bets),
        "已结算数": sum(1 for r in rows if r["已结算"] == "是"),
        "投注已结算数": len(settled_bets),
        "不投数": sum(1 for r in rows if r["动作"] == NO_BET),
        "熔断拦截数": sum(1 for r in rows if "熔断" in str(r.get("拦截阶段", "")) or "熔断" in str(r.get("拦截原因", ""))),
        "红": labels["红"],
        "红半": labels["红半"],
        "走水": labels["走水"],
        "黑半": labels["黑半"],
        "黑": labels["黑"],
        "实际总胜率": q4(wins / effective) if effective else None,
        "实际总负率": q4(losses / effective) if effective else None,
        "实际总盈亏Unit": q4(total_unit),
        "实际总盈亏金额": q4(total_profit),
        "总投注流水": q4(total_stake),
        "整体资金流水ROI": q4(total_profit / total_stake) if total_stake else 0.0,
    }


def grouped_summary(rows: list[dict[str, object]], key: str) -> list[dict[str, object]]:
    groups: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        if row["动作"] in {FORWARD, REVERSE} and row["已结算"] == "是":
            groups[str(row.get(key, ""))].append(row)

    out = []
    for name, group in groups.items():
        stat = summarize_rows(group)
        out.append(
            {
                key: name,
                "已结算投注数": stat["投注已结算数"],
                "胜率": stat["实际总胜率"],
                "负率": stat["实际总负率"],
                "盈亏Unit": stat["实际总盈亏Unit"],
                "ROI": stat["整体资金流水ROI"],
                "红": stat["红"],
                "红半": stat["红半"],
                "走水": stat["走水"],
                "黑半": stat["黑半"],
                "黑": stat["黑"],
            }
        )
    return sorted(out, key=lambda r: (float(r.get("盈亏Unit") or 0.0), float(r.get("胜率") or 0.0)), reverse=True)


def grouped_type_summary(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    specs = [
        ("微观板块", ["微观板块"]),
        ("盘口意图标签", ["盘口意图标签"]),
        ("盘口档位", ["盘口档位"]),
        ("赛事", ["赛事"]),
        ("比赛分类", ["比赛分类"]),
        ("微观板块+标签", ["微观板块", "盘口意图标签"]),
        ("盘口档位+标签", ["盘口档位", "盘口意图标签"]),
        ("赛事+标签", ["赛事", "盘口意图标签"]),
        ("比赛分类+标签", ["比赛分类", "盘口意图标签"]),
        ("微观板块+盘口档位+标签", ["微观板块", "盘口档位", "盘口意图标签"]),
    ]
    out: list[dict[str, object]] = []
    for group_type, fields in specs:
        groups: dict[str, list[dict[str, object]]] = defaultdict(list)
        for row in rows:
            if row["动作"] not in {FORWARD, REVERSE} or row["已结算"] != "是":
                continue
            key = " / ".join(str(row.get(field, "") or "未分类") for field in fields)
            groups[key].append(row)
        for key, group in groups.items():
            stat = summarize_rows(group)
            out.append(
                {
                    "分组类型": group_type,
                    "分组": key,
                    "已结算投注数": stat["投注已结算数"],
                    "胜率": stat["实际总胜率"],
                    "负率": stat["实际总负率"],
                    "盈亏Unit": stat["实际总盈亏Unit"],
                    "ROI": stat["整体资金流水ROI"],
                    "红": stat["红"],
                    "红半": stat["红半"],
                    "走水": stat["走水"],
                    "黑半": stat["黑半"],
                    "黑": stat["黑"],
                }
            )
    return sorted(
        out,
        key=lambda r: (
            int(r.get("已结算投注数") or 0) >= 8,
            float(r.get("盈亏Unit") or 0.0),
            float(r.get("胜率") or 0.0),
            int(r.get("已结算投注数") or 0),
        ),
        reverse=True,
    )


def csv_value(value: object) -> object:
    if isinstance(value, float):
        return f"{q4(value):.4f}"
    return "" if value is None else value


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: csv_value(row.get(field, "")) for field in fields})


def table_lines(rows: list[dict[str, object]], key: str) -> list[str]:
    lines = [
        f"| {key} | 已结算投注数 | 胜率 | 负率 | 盈亏Unit | ROI | 红 | 红半 | 走水 | 黑半 | 黑 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            "| {name} | {bets} | {wr} | {lr} | {pnl} | {roi} | {red} | {rh} | {push} | {bh} | {black} |".format(
                name=row[key],
                bets=row["已结算投注数"],
                wr=f4(row["胜率"]),
                lr=f4(row["负率"]),
                pnl=f4(row["盈亏Unit"]),
                roi=f4(row["ROI"]),
                red=row["红"],
                rh=row["红半"],
                push=row["走水"],
                bh=row["黑半"],
                black=row["黑"],
            )
        )
    return lines


def type_table_lines(rows: list[dict[str, object]], limit: int = 30, min_sample: int = 3) -> list[str]:
    shown = [r for r in rows if int(r.get("已结算投注数") or 0) >= min_sample][:limit]
    lines = [
        "| 分组类型 | 分组 | 已结算投注数 | 胜率 | 负率 | 盈亏Unit | ROI | 红/红半/走/黑半/黑 |",
        "|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for row in shown:
        lines.append(
            "| {gt} | {g} | {bets} | {wr} | {lr} | {pnl} | {roi} | {w}/{wh}/{p}/{lh}/{l} |".format(
                gt=row["分组类型"],
                g=row["分组"],
                bets=row["已结算投注数"],
                wr=f4(row["胜率"]),
                lr=f4(row["负率"]),
                pnl=f4(row["盈亏Unit"]),
                roi=f4(row["ROI"]),
                w=row["红"],
                wh=row["红半"],
                p=row["走水"],
                lh=row["黑半"],
                l=row["黑"],
            )
        )
    return lines


def write_report(
    path: Path,
    source: Path,
    detail_csv: Path,
    intent_csv: Path,
    type_csv: Path,
    summary: dict[str, object],
    by_region: list[dict[str, object]],
    by_tag: list[dict[str, object]],
    by_type: list[dict[str, object]],
    block_counts: Counter,
    config: Config,
) -> None:
    strong_types = [
        r
        for r in by_type
        if int(r.get("已结算投注数") or 0) >= 8
        and (float(r.get("胜率") or 0.0) >= 0.55)
        and float(r.get("盈亏Unit") or 0.0) > 0
    ]
    lines = [
        "# 亚盘量化策略顺序回测",
        "",
        f"- 数据源：`{source}`",
        f"- 有意图比赛清单：`{intent_csv}`",
        f"- 明细CSV：`{detail_csv}`",
        f"- 类型拆分CSV：`{type_csv}`",
        "- 口径：严格 walk-forward，每场比赛只读取当前行之前的历史样本；读取后先按 `日期, 开赛时间, 比赛ID` 确定性排序。",
        f"- 样本门槛：标签历史 M>={config.min_tag_sample}，微观板块同标签 n>={config.min_micro_sample}；低于门槛只观察。",
        f"- 水位阈值：`1 / (Water + 1) + {config.safety_buffer:.4f}`；标准仓位 `{config.standard_stake_rate:.4f}`，昨日负 ROI 半仓，连续负 ROI/严重亏损静默。",
        "",
        "## 总体",
        f"- 完整测算比赛数：{summary['完整测算比赛数']}",
        f"- 符合投注条件数：{summary['符合投注条件数']}；已结算数：{summary['已结算数']}；已结算投注数：{summary['投注已结算数']}；不投数：{summary['不投数']}；熔断拦截数：{summary['熔断拦截数']}",
        f"- 红/红半/走/黑半/黑：{summary['红']}/{summary['红半']}/{summary['走水']}/{summary['黑半']}/{summary['黑']}",
        f"- 实际总胜率：{f4(summary['实际总胜率'])}；实际总负率：{f4(summary['实际总负率'])}",
        f"- 实际总盈亏：{f4(summary['实际总盈亏Unit'])} Unit；资金流水 ROI：{f4(summary['整体资金流水ROI'])}",
        "",
        "## 七重漏斗拦截",
        "| 阶段/原因 | 场数 |",
        "|---|---:|",
    ]
    for reason, count in block_counts.most_common():
        lines.append(f"| {reason} | {count} |")

    lines += ["", "## 分微观板块", *table_lines(by_region, "微观板块")]
    lines += ["", "## 分标签", *table_lines(by_tag, "盘口意图标签")]
    lines += ["", "## 胜率/收益较好的类型（样本>=8、胜率>=55%、Unit>0）"]
    lines += type_table_lines(strong_types, limit=40, min_sample=8)
    lines += ["", "## 全类型拆分Top（样本>=3）"]
    lines += type_table_lines(by_type, limit=40, min_sample=3)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_backtest(input_path: Path, out_dir: Path, config: Config) -> dict[str, Path | dict[str, object]]:
    raw = load_table(input_path)
    df = prepare_dataframe(raw)
    all_rows = [row_from_record(i + 1, record) for i, record in enumerate(df.to_dict("records"))]
    rows = [row for row in all_rows if not is_no_count_tag(row.tag)] if config.intent_only else all_rows

    settled_history: list[MatchRow] = []
    strategy_history: list[dict[str, object]] = []
    details: list[dict[str, object]] = []

    active_date: dt.date | None = None
    day_start_bankroll = config.starting_bankroll
    bankroll = config.starting_bankroll
    pending_day_profit = 0.0

    for row in rows:
        if active_date is None:
            active_date = row.date_obj
        elif row.date_obj != active_date:
            bankroll += pending_day_profit
            day_start_bankroll = bankroll
            pending_day_profit = 0.0
            active_date = row.date_obj

        decision = decide_match(row, settled_history, strategy_history, config)
        detail, strategy_record = make_detail_row(row, decision, day_start_bankroll, config)
        details.append(detail)
        if strategy_record is not None:
            strategy_history.append(strategy_record)
            pending_day_profit += float(strategy_record["profit_amount"])
        if row.settled:
            settled_history.append(row)

    bankroll += pending_day_profit

    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    intent_csv = out_dir / f"sequential_asian_backtest_{stamp}_intent_matches.csv"
    detail_csv = out_dir / f"sequential_asian_backtest_{stamp}_detail.csv"
    region_csv = out_dir / f"sequential_asian_backtest_{stamp}_by_region.csv"
    tag_csv = out_dir / f"sequential_asian_backtest_{stamp}_by_tag.csv"
    type_csv = out_dir / f"sequential_asian_backtest_{stamp}_by_type.csv"
    summary_json = out_dir / f"sequential_asian_backtest_{stamp}_summary.json"
    report_md = out_dir / f"sequential_asian_backtest_{stamp}.md"

    intent_fields = [
        "序号",
        "日期",
        "开赛时间",
        "比赛ID",
        "赛事",
        "比赛",
        "比赛分类",
        "微观板块",
        "盘口意图标签",
        "盘口档位",
        "正向水位",
        "反向水位",
        "已结算",
    ]
    intent_rows = [
        {
            "序号": row.seq,
            "日期": row.date,
            "开赛时间": row.kickoff,
            "比赛ID": row.match_id,
            "赛事": row.league,
            "比赛": row.match,
            "比赛分类": row.competition_class,
            "微观板块": row.region,
            "盘口意图标签": row.tag,
            "盘口档位": row.line_bucket,
            "正向水位": row.forward_water,
            "反向水位": row.reverse_water,
            "已结算": "是" if row.settled else "否",
        }
        for row in rows
    ]
    write_csv(intent_csv, intent_rows, intent_fields)
    write_csv(detail_csv, details, DETAIL_FIELDS)
    summary = summarize_rows(details)
    summary["期初资金"] = q4(config.starting_bankroll)
    summary["期末资金"] = q4(bankroll)
    summary["资金净盈亏"] = q4(bankroll - config.starting_bankroll)
    by_region = grouped_summary(details, "微观板块")
    by_tag = grouped_summary(details, "盘口意图标签")
    by_type = grouped_type_summary(details)
    block_counts = Counter(str(r.get("拦截原因") or r.get("拦截阶段")) for r in details if r["动作"] == NO_BET)
    write_csv(region_csv, by_region, ["微观板块", "已结算投注数", "胜率", "负率", "盈亏Unit", "ROI", "红", "红半", "走水", "黑半", "黑"])
    write_csv(tag_csv, by_tag, ["盘口意图标签", "已结算投注数", "胜率", "负率", "盈亏Unit", "ROI", "红", "红半", "走水", "黑半", "黑"])
    write_csv(type_csv, by_type, ["分组类型", "分组", "已结算投注数", "胜率", "负率", "盈亏Unit", "ROI", "红", "红半", "走水", "黑半", "黑"])

    summary_payload = {
        "source": str(input_path),
        "intent_matches_csv": str(intent_csv),
        "detail_csv": str(detail_csv),
        "region_csv": str(region_csv),
        "tag_csv": str(tag_csv),
        "type_csv": str(type_csv),
        "report_md": str(report_md),
        "config": {
            "safety_buffer": q4(config.safety_buffer),
            "same_line_min_sample": config.same_line_min_sample,
            "same_line_veto_rate": q4(config.same_line_veto_rate),
            "rolling_window": config.rolling_window,
            "rolling_min_sample": config.rolling_min_sample,
            "rolling_min_win_rate": q4(config.rolling_min_win_rate),
            "rolling_min_flat_pnl": q4(config.rolling_min_flat_pnl),
            "starting_bankroll": q4(config.starting_bankroll),
            "standard_stake_rate": q4(config.standard_stake_rate),
            "min_tag_sample": config.min_tag_sample,
            "min_micro_sample": config.min_micro_sample,
            "intent_only": config.intent_only,
        },
        "summary": summary,
        "by_region": by_region,
        "by_tag": by_tag,
        "by_type": by_type,
        "block_counts": dict(block_counts),
    }
    summary_json.write_text(json.dumps(summary_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    write_report(report_md, input_path, detail_csv, intent_csv, type_csv, summary, by_region, by_tag, by_type, block_counts, config)
    return {
        "intent_csv": intent_csv,
        "detail_csv": detail_csv,
        "region_csv": region_csv,
        "tag_csv": tag_csv,
        "type_csv": type_csv,
        "summary_json": summary_json,
        "report_md": report_md,
        "summary": summary,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sequential walk-forward Asian handicap backtest engine.")
    parser.add_argument("--input", type=Path, default=None, help="CSV/XLSX input. Defaults to latest asian_intent_history_detail_*.csv.")
    parser.add_argument("--out-dir", type=Path, default=OUT_ROOT)
    parser.add_argument("--starting-bankroll", type=float, default=100.0)
    parser.add_argument("--stake-rate", type=float, default=0.05, help="Standard stake as fraction of bankroll.")
    parser.add_argument("--safety-buffer", type=float, default=0.02)
    parser.add_argument("--same-line-min-sample", type=int, default=8)
    parser.add_argument("--same-line-veto-rate", type=float, default=0.40)
    parser.add_argument("--rolling-window", type=int, default=15)
    parser.add_argument("--rolling-min-sample", type=int, default=15)
    parser.add_argument("--rolling-min-win-rate", type=float, default=0.40)
    parser.add_argument("--rolling-min-flat-pnl", type=float, default=-3.0)
    parser.add_argument("--severe-loss-count", type=int, default=5)
    parser.add_argument("--min-tag-sample", type=int, default=8)
    parser.add_argument("--min-micro-sample", type=int, default=8)
    parser.add_argument("--include-no-intent", action="store_true", help="Include no-direction/balanced rows in the measured universe.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    input_path = args.input or latest_history_file()
    config = Config(
        safety_buffer=args.safety_buffer,
        same_line_min_sample=args.same_line_min_sample,
        same_line_veto_rate=args.same_line_veto_rate,
        rolling_window=args.rolling_window,
        rolling_min_sample=args.rolling_min_sample,
        rolling_min_win_rate=args.rolling_min_win_rate,
        rolling_min_flat_pnl=args.rolling_min_flat_pnl,
        severe_loss_count=args.severe_loss_count,
        min_tag_sample=args.min_tag_sample,
        min_micro_sample=args.min_micro_sample,
        intent_only=not args.include_no_intent,
        starting_bankroll=args.starting_bankroll,
        standard_stake_rate=args.stake_rate,
    )
    result = run_backtest(input_path, args.out_dir, config)
    summary = result["summary"]
    print(f"完整测算比赛数={summary['完整测算比赛数']}")
    print(f"符合投注条件数={summary['符合投注条件数']} 已结算数={summary['已结算数']} 已结算投注数={summary['投注已结算数']} 不投数={summary['不投数']} 熔断拦截数={summary['熔断拦截数']}")
    print(f"胜率={f4(summary['实际总胜率'])} 负率={f4(summary['实际总负率'])} 盈亏Unit={f4(summary['实际总盈亏Unit'])} ROI={f4(summary['整体资金流水ROI'])}")
    print(f"intent_matches_csv={result['intent_csv']}")
    print(f"detail_csv={result['detail_csv']}")
    print(f"region_csv={result['region_csv']}")
    print(f"tag_csv={result['tag_csv']}")
    print(f"type_csv={result['type_csv']}")
    print(f"summary_json={result['summary_json']}")
    print(f"report_md={result['report_md']}")


if __name__ == "__main__":
    main()
