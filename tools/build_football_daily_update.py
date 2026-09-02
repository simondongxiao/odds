from __future__ import annotations

import csv
import datetime as dt
import math
import importlib.util
import re
import sys
from collections import defaultdict
from pathlib import Path


ROOT = Path(r"D:\codex\outputs\football_odds_trader")
RAW = ROOT / "raw" / "titan007"
DAILY = ROOT / "daily"
LEDGER = ROOT / "ledger" / "simulated_bets.csv"
FLOW_DIR = ROOT / "flows"
TODAY = dt.datetime.now().date()
SLATE_END_HOUR = 12
BANKROLL = 500.0
MIN_STAKE = 20.0
FRACTIONAL_KELLY = 0.20


FRIENDLY_KEYWORDS = ("友谊", "球会友谊", "国际友谊", "热身", "慈善", "表演赛")
YOUTH_RESERVE_KEYWORDS = (
    "U17", "U18", "U19", "U20", "U21", "U22", "U23",
    "u17", "u18", "u19", "u20", "u21", "u22", "u23",
    "青年", "青少年", "青联", "青杯", "后备", "预备", "梯队", "学院",
    "Reserve", "Reserves", "reserve", "reserves", "Youth", "youth", "Academy", "academy",
)

SENIOR_TIER_BY_LEAGUE = {
    # England
    "英超": 1, "英冠": 2, "英甲": 3,
    # Spain / Italy / Germany / France
    "西甲": 1, "西乙": 2, "西协甲": 3,
    "意甲": 1, "意乙": 2, "意丙": 3,
    "德甲": 1, "德乙": 2, "德丙": 3,
    "法甲": 1, "法乙": 2, "法丙": 3,
    # Netherlands / Portugal / Belgium / Turkey / Switzerland
    "荷甲": 1, "荷乙": 2, "荷丙": 3,
    "葡超": 1, "葡甲": 2, "葡乙": 3,
    "比甲": 1, "比乙": 2, "比业余": 3,
    "土超": 1, "土甲": 2, "土乙": 3,
    "瑞士超": 1, "瑞士挑": 2, "瑞士甲": 3,
    # Northern/Eastern Europe
    "瑞典超": 1, "瑞典甲": 2, "瑞典乙": 3,
    "挪超": 1, "挪甲": 2, "挪乙": 3,
    "俄超": 1, "俄甲": 2, "俄乙": 3,
    "丹麦超": 1, "丹麦甲": 2, "丹麦乙": 3,
    "乌克超": 1, "乌超": 1, "乌克甲": 2, "乌甲": 2, "乌克乙": 3, "乌乙": 3,
    "克亚甲": 1, "克罗甲": 1, "克亚乙": 2, "克罗乙": 2,
    "冰岛超": 1, "冰岛甲": 2, "冰岛乙": 3,
    "捷甲": 1, "捷乙": 2, "捷丙": 3,
    "拉脱超": 1,
    "哈萨克超": 1, "哈萨克甲": 2,
    "保超": 1, "保乙": 2,
    "南非超": 1,
    # Asia / Australia
    "中超": 1, "中甲": 2, "中乙": 3,
    "韩K联": 1, "韩K2联": 2, "韩K3联": 3,
    "日职联": 1, "日职乙": 2, "日职丙": 3,
    "澳洲甲": 1, "澳威超": 2, "澳维超": 2, "澳昆超": 2,
    "卡塔尔联": 1, "卡塔尔乙": 2, "阿联酋超": 1, "阿联酋甲": 2,
    "乌兹超": 1, "乌兹甲": 2,
    "沙特联": 1, "沙特甲": 2, "沙特乙": 3,
    "伊拉联": 1, "科威特联": 1, "阿曼联": 1,
    # Americas
    "美职业": 1, "美冠联": 2, "美甲": 3,
    "巴西甲": 1, "巴西乙": 2, "巴西丙": 3,
    "阿甲": 1, "阿乙": 2, "阿乙曼特秋": 3, "阿乙曼特": 3,
    "乌拉甲": 1, "乌拉乙": 2,
    "智利甲": 1, "智利乙": 2, "智利丙": 3,
    "哥伦甲": 1, "哥伦甲秋": 1, "哥伦乙": 2, "哥伦乙秋": 2,
    "哥斯甲": 1, "哥斯乙": 2,
    "厄瓜甲": 1, "厄甲": 1, "厄瓜乙": 2, "厄乙": 2,
    "玻利甲": 1, "巴拉甲": 1, "巴拉甲秋": 1,
    "加拿超": 1,
}

SENIOR_CUP_KEYWORDS = (
    "世界杯", "欧洲杯", "亚洲杯", "美洲杯", "非洲杯", "中北美",
    "欧冠", "欧罗巴", "欧联", "欧会杯", "亚冠", "解放者", "南球杯",
    "英联杯", "英足总杯", "足总杯", "德国杯", "意大利杯", "澳足总",
    "巴西杯", "瑞士杯", "瑞典杯", "丹麦杯", "捷克杯", "巴拉杯", "乌拉杯",
    "杯", "超级杯", "盾", "附加赛", "季后赛", "资格赛",
)


def latest_snapshot() -> Path:
    files = sorted(RAW.glob("**/*_titan007_odds_snapshot.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        raise FileNotFoundError("no Titan007 snapshot")
    return files[0]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def ledger_match_key(row: dict[str, str]) -> tuple[str, str, str]:
    return (
        (row.get("日期") or "").strip(),
        (row.get("赛事") or "").strip(),
        (row.get("比赛") or "").strip(),
    )


def preserve_started_prematch_rows(
    sim_rows: list[dict[str, str]],
    existing_rows: list[dict[str, str]],
) -> list[dict[str, str]]:
    """Keep pre-match model fields immutable once a same-day match has kicked off."""
    prior_prematch: dict[tuple[str, str, str], dict[str, str]] = {}
    today = TODAY.isoformat()
    for row in existing_rows:
        if (row.get("日期") or "").strip() != today:
            continue
        market = (row.get("市场框架") or "").strip()
        if not market or market.startswith("赛况更新"):
            continue
        key = ledger_match_key(row)
        if all(key):
            prior_prematch[key] = row

    protected: list[dict[str, str]] = []
    for row in sim_rows:
        market = (row.get("市场框架") or "").strip()
        key = ledger_match_key(row)
        prior = prior_prematch.get(key)
        if prior and market.startswith("赛况更新"):
            kept = dict(prior)
            kept["赛果"] = row.get("赛果", kept.get("赛果", ""))
            note = "赛况已刷新，只更新比分/状态，不改赛前结论/盘口/标签"
            old_note = (kept.get("模型更新") or "").strip()
            kept["模型更新"] = f"{old_note}；{note}" if old_note and note not in old_note else note
            protected.append(kept)
        else:
            protected.append(row)
    return protected


def latest_flow_file() -> Path | None:
    files = sorted(FLOW_DIR.glob("chuqi_bifa_flow_*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def norm_team(value: str) -> str:
    text = re.sub(r"\[[^\]]+\]", "", value or "")
    text = re.sub(r"\([^)]*\)", "", text)
    text = re.sub(r"[\s　·・.．,，、/\\-]+", "", text)
    return text.strip().lower()


def norm_flow_time(value: str) -> str:
    text = (value or "").strip()
    m = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})\s+(\d{1,2}):(\d{2})", text)
    if m:
        return f"{int(m.group(2)):02d}-{int(m.group(3)):02d} {int(m.group(4)):02d}:{m.group(5)}"
    m = re.search(r"(\d{1,2})-(\d{1,2})\s+(\d{1,2}):(\d{2})", text)
    if m:
        return f"{int(m.group(1)):02d}-{int(m.group(2)):02d} {int(m.group(3)):02d}:{m.group(4)}"
    m = re.search(r"(\d{1,2}):(\d{2})", text)
    if m:
        return f"{TODAY.month:02d}-{TODAY.day:02d} {int(m.group(1)):02d}:{m.group(2)}"
    return text


def flow_key(home: str, away: str, when: str) -> tuple[str, str, str]:
    return (norm_flow_time(when), norm_team(home), norm_team(away))


def load_flow_lookup() -> tuple[Path | None, dict[tuple[str, str, str], list[dict[str, str]]]]:
    path = latest_flow_file()
    if not path:
        return None, {}
    lookup: dict[tuple[str, str, str], list[dict[str, str]]] = defaultdict(list)
    for row in read_csv(path):
        home = row.get("主队", "")
        away = row.get("客队", "")
        when = row.get("开赛时间_北京时间", "") or row.get("列表时间", "")
        if not (home and away and when):
            continue
        lookup[flow_key(home, away, when)].append(row)
    return path, dict(lookup)


def attach_flow(row: dict[str, str], flow_lookup: dict[tuple[str, str, str], list[dict[str, str]]]) -> None:
    row["_flow"] = flow_lookup.get(flow_key(row.get("home_cn", ""), row.get("away_cn", ""), row.get("bj_time", "")), [])


def flow_number(value: str) -> float | None:
    text = (value or "").replace(",", "").replace("%", "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def summarize_flow(row: dict[str, str], compact: bool = False) -> str:
    flow_rows = row.get("_flow") if isinstance(row.get("_flow"), list) else []
    if not flow_rows:
        return "资金流未验证：沿用亚盘EV框架（无PM/必发匹配）"
    items = []
    max_side = ""
    max_amount = -1.0
    total = ""
    source_url = ""
    for item in flow_rows:
        side = (item.get("市场项") or "").strip()
        amount = (item.get("交易量") or "").strip()
        pct = (item.get("交易比例") or "").strip()
        price = (item.get("必发价位") or "").strip()
        profit = (item.get("庄家盈亏") or "").strip()
        total = total or (item.get("总交易量_三项合计") or "").strip()
        source_url = source_url or (item.get("source_url") or "").strip()
        if side:
            items.append(f"{side}{amount or '无量'}({pct or '无比例'},价{price or 'NA'},盈亏{profit or 'NA'})")
        amount_num = flow_number(amount)
        if amount_num is not None and amount_num > max_amount and side in {"主", "客"}:
            max_amount = amount_num
            max_side = side
    direction = {"主": "主队", "客": "客队"}.get(max_side, "未判定")
    base = f"Chuqi必发衍生：实际资金流向={direction}；总成交{total or '未列'}；" + "；".join(items)
    if compact:
        return base if len(base) <= 130 else base[:130] + "..."
    if source_url:
        base += f"；来源{source_url}"
    return base


def summarize_liquidity(row: dict[str, str]) -> str:
    flow_rows = row.get("_flow") if isinstance(row.get("_flow"), list) else []
    if not flow_rows:
        return "Titan价格流；PM/必发/BTTS未匹配；资金流未验证不改变亚盘EV流程"
    max_trade = ""
    max_trade_time = ""
    latest_time = ""
    for item in flow_rows:
        latest_time = latest_time or (item.get("最新曲线时间") or "")
        amount = flow_number(item.get("最大明细成交额", ""))
        if amount is not None and (not max_trade or amount > (flow_number(max_trade) or -1)):
            max_trade = item.get("最大明细成交额", "")
            max_trade_time = item.get("最大明细时间", "")
    return f"Chuqi必发衍生流动性；最新曲线{latest_time or '未列'}；最大明细成交{max_trade or '未列'}@{max_trade_time or '未列'}；Titan盘口价格流"


def normalize_intent_from_text(value: str) -> str:
    text = value or ""
    marker = "亚盘意图候选："
    if marker in text:
        text = text.split(marker, 1)[1]
    text = text.split("（", 1)[0].split("；", 1)[0].strip()
    return text.replace(" / ", "/").replace(" ", "")


def intent_target_side(intent_tag: str) -> str:
    tag = intent_tag or ""
    if "阻上" in tag or "诱上" in tag:
        return "上盘"
    if "阻下" in tag or "诱下" in tag:
        return "下盘"
    return ""


def asian_upper_home_away(row: dict[str, str]) -> str:
    ah_now = fnum(row, "ah_full_current_line_or_draw")
    euro_home = fnum(row, "euro_full_current_home_or_over")
    euro_away = fnum(row, "euro_full_current_away_or_under")
    if ah_now is None:
        return ""
    if ah_now > 0:
        return "home"
    if ah_now < 0:
        return "away"
    if euro_home and euro_away:
        if euro_home < euro_away:
            return "home"
        if euro_away < euro_home:
            return "away"
    return ""


def flow_direction_home_away(row: dict[str, str]) -> str:
    flow_rows = row.get("_flow") if isinstance(row.get("_flow"), list) else []
    best_side = ""
    best_amount = -1.0
    for item in flow_rows:
        side = (item.get("市场项") or "").strip()
        amount = flow_number(item.get("交易量", ""))
        if amount is not None and amount > best_amount and side in {"主", "客"}:
            best_amount = amount
            best_side = side
    return {"主": "home", "客": "away"}.get(best_side, "")


def target_home_away(row: dict[str, str], target_side: str) -> str:
    upper = asian_upper_home_away(row)
    if not upper or target_side not in {"上盘", "下盘"}:
        return ""
    if target_side == "上盘":
        return upper
    return "away" if upper == "home" else "home"


def side_team(row: dict[str, str], side: str) -> str:
    if side == "home":
        return row.get("home_cn", "")
    if side == "away":
        return row.get("away_cn", "")
    return ""


def target_water_status(row: dict[str, str], target_side: str) -> str:
    upper = asian_upper_home_away(row)
    home_water = fnum(row, "ah_full_current_home_or_over")
    away_water = fnum(row, "ah_full_current_away_or_under")
    if upper not in {"home", "away"} or home_water is None or away_water is None or target_side not in {"上盘", "下盘"}:
        return "水位无法判定"
    upper_water = home_water if upper == "home" else away_water
    lower_water = away_water if upper == "home" else home_water
    target_water = upper_water if target_side == "上盘" else lower_water
    other_water = lower_water if target_side == "上盘" else upper_water
    if target_water >= 0.90 or target_water >= other_water + 0.06:
        return "甜头仍在"
    if target_water <= 0.84 or target_water <= other_water - 0.06:
        return "甜头收回"
    return "无明显甜头"


def flow_overlay_fields(row: dict[str, str]) -> dict[str, str]:
    intent = normalize_intent_from_text(asian_intent_candidate(row))
    flow_ha = flow_direction_home_away(row)
    upper = asian_upper_home_away(row)
    lower = "away" if upper == "home" else "home" if upper == "away" else ""
    upper_water_status = target_water_status(row, "上盘")
    lower_water_status = target_water_status(row, "下盘")
    target_side = intent_target_side(intent)
    target_ha = target_home_away(row, target_side)
    water_status = target_water_status(row, target_side)
    flow_rows = row.get("_flow") if isinstance(row.get("_flow"), list) else []
    if not flow_rows:
        return {
            "候选标签": intent,
            "阻诱目标侧": target_side or "未识别",
            "实际资金流向": "未验证",
            "目标侧水位甜头": water_status,
            "意图成败": "资金流缺口-沿用亚盘EV框架",
            "资金流修正方向": "不因资金流修正",
            "资金流修正球队": "",
            "资金流来源": "未匹配Chuqi/PM/Betfair",
            "资金流时间戳": "",
        }

    if "阻上" in intent and "诱下" in intent:
        if flow_ha == upper and upper_water_status == "甜头仍在":
            fix_side = "下盘"
            result = "阻上失败-反向警报"
        else:
            fix_side = "上盘"
            result = "诱下/保护上盘得到资金流验证" if flow_ha == lower else "阻上/诱下未完全验证-默认上盘"
        target_side = "上盘/下盘"
        water_status = f"上盘{upper_water_status};下盘{lower_water_status}"
    elif "诱上" in intent and "阻下" in intent:
        if flow_ha == lower and lower_water_status == "甜头仍在":
            fix_side = "上盘"
            result = "阻下失败-反向警报"
        else:
            fix_side = "下盘"
            result = "诱上得到资金流验证" if flow_ha == upper else "诱上/阻下未完全验证-默认下盘"
        target_side = "上盘/下盘"
        water_status = f"上盘{upper_water_status};下盘{lower_water_status}"
    else:
        flow_on_target = bool(flow_ha and target_ha and flow_ha == target_ha)
        if "阻上" in intent:
            success = not flow_on_target
            reverse = flow_on_target and water_status == "甜头仍在"
            fix_side = "下盘" if reverse else "上盘"
            result = "阻上成功/保护上盘" if success else ("阻上失败-反向警报" if reverse else "阻上未完全验证")
        elif "阻下" in intent:
            success = not flow_on_target
            reverse = flow_on_target and water_status == "甜头仍在"
            fix_side = "上盘" if reverse else "下盘"
            result = "阻下成功/保护下盘" if success else ("阻下失败-反向警报" if reverse else "阻下未完全验证")
        elif "诱上" in intent:
            fix_side = "下盘"
            result = "诱上成功-反向下盘" if flow_on_target else "诱上未成-回归下盘/观察"
        elif "诱下" in intent:
            fix_side = "上盘"
            result = "诱下成功-反向上盘" if flow_on_target else "诱下未成-回归上盘"
        else:
            fix_side = ""
            result = "非阻诱标签-仅记录资金流"
    if fix_side == "上盘":
        fix_ha = upper
    elif fix_side == "下盘":
        fix_ha = "away" if upper == "home" else "home" if upper == "away" else ""
    else:
        fix_ha = ""
    return {
        "候选标签": intent,
        "阻诱目标侧": target_side or "未识别",
        "实际资金流向": side_team(row, flow_ha) or "未判定",
        "目标侧水位甜头": water_status,
        "意图成败": result,
        "资金流修正方向": fix_side or "不修正",
        "资金流修正球队": side_team(row, fix_ha),
        "资金流来源": "Chuqi必发衍生",
        "资金流时间戳": (flow_rows[0].get("抓取时间") or "") if flow_rows else "",
    }


def write_flow_overlay(rows: list[dict[str, str]], source: Path | None) -> Path:
    out = ROOT / "ledger" / f"funds_flow_intent_overlay_{TODAY.isoformat()}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "统计日期", "资金流源文件", "日期", "开赛时间", "比赛ID", "赛事", "比赛",
        "盘口", "亚盘即时", "欧赔即时", "大小球即时", "候选标签", "阻诱目标侧",
        "实际资金流向", "目标侧水位甜头", "意图成败", "资金流修正方向",
        "资金流修正球队", "资金流来源", "资金流时间戳", "资金流摘要",
    ]
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            fields_row = flow_overlay_fields(row)
            writer.writerow(
                {
                    "统计日期": TODAY.isoformat(),
                    "资金流源文件": str(source or ""),
                    "日期": TODAY.isoformat(),
                    "开赛时间": f"2026-{row.get('bj_time','')}",
                    "比赛ID": row.get("match_id", ""),
                    "赛事": row.get("league_cn", ""),
                    "比赛": f"{row.get('home_cn','')} vs {row.get('away_cn','')}",
                    "盘口": row.get("ah_full_current_line_or_draw", ""),
                    "亚盘即时": fmt_ah(row),
                    "欧赔即时": fmt_euro(row),
                    "大小球即时": fmt_total(row),
                    **fields_row,
                    "资金流摘要": summarize_flow(row),
                }
            )
    return out


def load_details() -> dict[str, dict[str, str]]:
    path = ROOT / "ledger" / f"titan007_detail_{TODAY.isoformat()}.csv"
    if not path.exists():
        return {}
    out: dict[str, dict[str, str]] = {}
    for row in read_csv(path):
        match_id = (row.get("match_id") or "").strip()
        if match_id:
            out[match_id] = row
    return out


def detail_for(row: dict[str, str]) -> dict[str, str]:
    return row.get("_detail", {}) if isinstance(row.get("_detail"), dict) else {}


def fnum(row: dict[str, str], key: str) -> float | None:
    v = (row.get(key) or "").strip()
    if not v:
        return None
    try:
        return float(v)
    except ValueError:
        return None


def date_from_bj(value: str) -> dt.date | None:
    try:
        md, _hm = value.split()
        month, day = [int(x) for x in md.split("-")]
        return dt.date(TODAY.year, month, day)
    except Exception:
        return None


def datetime_from_bj(value: str) -> dt.datetime | None:
    try:
        md, hm = value.split()
        month, day = [int(x) for x in md.split("-")]
        hour, minute = [int(x) for x in hm.split(":")]
        return dt.datetime(TODAY.year, month, day, hour, minute)
    except Exception:
        return None


def in_trading_slate(value: str) -> bool:
    when = datetime_from_bj(value)
    if when is None:
        return False
    start = dt.datetime.combine(TODAY, dt.time.min)
    end = dt.datetime.combine(TODAY + dt.timedelta(days=1), dt.time(SLATE_END_HOUR, 0))
    return start <= when < end


def in_target_list_date(row: dict[str, str]) -> bool:
    list_date = (row.get("list_date") or "").strip()
    if list_date:
        return list_date == TODAY.isoformat()
    # Legacy snapshots without list_date are not used to create today's slate;
    # this prevents previous-list-date midnight matches from being duplicated.
    return False


def is_friendy_or_ignored(row: dict[str, str]) -> bool:
    text = " ".join(
        [
            row.get("league_cn", ""),
            row.get("league_tw", ""),
            row.get("home_cn", ""),
            row.get("away_cn", ""),
        ]
    )
    return any(keyword in text for keyword in FRIENDLY_KEYWORDS)


def is_youth_or_reserve(row: dict[str, str]) -> bool:
    text = " ".join(
        [
            row.get("league_cn", ""),
            row.get("league_tw", ""),
            row.get("home_cn", ""),
            row.get("away_cn", ""),
            row.get("home_tw", ""),
            row.get("away_tw", ""),
        ]
    )
    return any(keyword in text for keyword in YOUTH_RESERVE_KEYWORDS)


def senior_league_tier(row: dict[str, str]) -> int | None:
    league = (row.get("league_cn") or "").strip()
    return SENIOR_TIER_BY_LEAGUE.get(league)


def is_senior_cup_or_playoff(row: dict[str, str]) -> bool:
    league = (row.get("league_cn") or "").strip()
    return any(keyword in league for keyword in SENIOR_CUP_KEYWORDS)


def has_verifiable_market(row: dict[str, str]) -> bool:
    market_keys = (
        "ah_full_current_line_or_draw",
        "ah_full_open_line_or_draw",
        "euro_full_current_home_or_over",
        "euro_full_open_home_or_over",
        "total_full_current_line_or_draw",
        "total_full_open_line_or_draw",
        "xml_ah_line",
        "xml_euro_home",
        "xml_total_line",
    )
    return any((row.get(key) or "").strip() for key in market_keys)


def eligible_competitive_row(row: dict[str, str]) -> bool:
    return (
        bool((row.get("match_id") or "").strip())
        and bool((row.get("league_cn") or "").strip())
        and bool((row.get("home_cn") or "").strip())
        and bool((row.get("away_cn") or "").strip())
        and in_target_list_date(row)
        and not is_friendy_or_ignored(row)
        and not is_youth_or_reserve(row)
        and (senior_league_tier(row) is not None or is_senior_cup_or_playoff(row))
        and has_verifiable_market(row)
    )


STATE_LABELS = {
    "-1": "已完场",
    "-10": "取消",
    "-11": "待定",
    "-12": "腰斩/中止",
    "-13": "中断",
    "-14": "推迟",
    "0": "未开赛",
}


def is_live_state(state: str) -> bool:
    try:
        return int((state or "").strip()) > 0
    except ValueError:
        return False


def is_abnormal_state(state: str) -> bool:
    state = (state or "").strip()
    return state.startswith("-") and state != "-1"


def state_label(state: str) -> str:
    state = (state or "").strip()
    if state in STATE_LABELS:
        return STATE_LABELS[state]
    if is_live_state(state):
        return "进行中/待确认"
    return f"状态待核({state})" if state else "状态待核"


def market_type_for_row(row: dict[str, str]) -> str:
    ah_line = fnum(row, "ah_full_current_line_or_draw")
    total_line = fnum(row, "total_full_current_line_or_draw")
    if ah_line is not None:
        return "亚盘"
    if total_line is not None:
        return "大小球"
    return "胜平负"


def load_history() -> dict[tuple[str, str], tuple[int, int, int, float]]:
    stats: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0, 0])
    if not LEDGER.exists():
        return {}
    for row in read_csv(LEDGER):
        result = (row.get("模拟盈亏单位") or "").strip()
        if not result or "待" in result:
            continue
        league = (row.get("赛事") or "").strip()
        market = (row.get("市场框架") or "").strip()
        try:
            pnl = float(result.replace("+", ""))
        except ValueError:
            continue
        key = (league, market)
        if pnl > 0:
            stats[key][0] += 1
        elif pnl < 0:
            stats[key][1] += 1
        else:
            stats[key][2] += 1
    out = {}
    for key, (w, l, p) in stats.items():
        n = w + l
        if n:
            out[key] = (w, l, p, w / n)
    return out


def hk_to_decimal(hk: float | None) -> float | None:
    if hk is None or hk <= 0:
        return None
    return 1.0 + hk


def kelly(p: float, decimal_odds: float | None) -> tuple[float, float, str]:
    if decimal_odds is None or decimal_odds <= 1:
        return 0.0, 0.0, "不投-赔率缺失"
    full = (p * decimal_odds - 1) / (decimal_odds - 1)
    if full <= 0:
        return full, 0.0, "不投-凯利为负"
    stake = BANKROLL * FRACTIONAL_KELLY * full
    if stake < MIN_STAKE:
        return full, stake, "不投-低于最低投注额"
    return full, stake, "可投"


def euro_devig(row: dict[str, str]) -> str:
    home = fnum(row, "euro_full_current_home_or_over")
    draw = fnum(row, "euro_full_current_line_or_draw")
    away = fnum(row, "euro_full_current_away_or_under")
    if not home or not draw or not away or min(home, draw, away) <= 1:
        return "欧赔缺失-未去水"
    inv = [1 / home, 1 / draw, 1 / away]
    overround = sum(inv)
    fair = [x / overround for x in inv]
    return f"去水 主{fair[0]:.1%}/平{fair[1]:.1%}/客{fair[2]:.1%}；返还率{1 / overround:.1%}"


def choose_simulation(row: dict[str, str], hist: dict[tuple[str, str], tuple[int, int, int, float]]) -> dict[str, object]:
    league = row["league_cn"]
    ah_line = fnum(row, "ah_full_current_line_or_draw")
    ah_home = fnum(row, "ah_full_current_home_or_over")
    ah_away = fnum(row, "ah_full_current_away_or_under")

    if row.get("state") != "0":
        score = f"{row.get('home_score','')}-{row.get('away_score','')}"
        return {
            "market": "赛况更新-不新建赛前模拟",
            "pick": f"{state_label(row.get('state',''))} {score}",
            "price": None,
            "decimal": None,
            "p": 0.0,
            "full_kelly": 0.0,
            "stake": 0.0,
            "action": "不投-非赛前",
            "bucket": "已开赛/已完场",
            "hist": "不计入模拟胜率",
            "sort": (0, 0, 0),
        }

    if ah_line is not None and ah_home is not None and ah_away is not None:
        return {
            "market": "亚盘意图框架-待EV筛选",
            "pick": "待标签/微观/水位框架筛选",
            "price": None,
            "decimal": None,
            "p": 0.0,
            "full_kelly": 0.0,
            "stake": 0.0,
            "action": "等待HTML红框EV漏斗判断",
            "bucket": "PM/必发/BTTS缺口只作证据折扣；亚盘按标签+微观+水位+同档+风控判断",
            "hist": "未形成模拟，不计入胜率",
            "sort": (0, 0, 0),
        }

    return {
        "market": "亚盘盘口缺失-不形成模拟",
        "pick": "无市场模拟（亚盘线/水位缺失）",
        "price": None,
        "decimal": None,
        "p": 0.0,
        "full_kelly": 0.0,
        "stake": 0.0,
        "action": "盘口缺失/真实不投",
        "bucket": "缺盘口",
        "hist": "无",
        "sort": (0, 0, 0),
    }


def fmt_triplet(row: dict[str, str], prefix: str, missing: str) -> str:
    open_keys = (
        f"{prefix}_full_open_home_or_over",
        f"{prefix}_full_open_line_or_draw",
        f"{prefix}_full_open_away_or_under",
    )
    current_keys = (
        f"{prefix}_full_current_home_or_over",
        f"{prefix}_full_current_line_or_draw",
        f"{prefix}_full_current_away_or_under",
    )
    current_values = [(row.get(key, "") or "").strip() for key in current_keys]
    if not all(current_values):
        return f"{missing}缺失"
    open_values = [(row.get(key, "") or "").strip() for key in open_keys]
    open_text = "/".join(open_values) if all(open_values) else "未接入"
    return f"开 {open_text}；即 {'/'.join(current_values)}"


def fmt_ah(row: dict[str, str]) -> str:
    return fmt_triplet(row, "ah", "亚盘")


def fmt_euro(row: dict[str, str]) -> str:
    return fmt_triplet(row, "euro", "欧赔")


def fmt_total(row: dict[str, str]) -> str:
    return fmt_triplet(row, "total", "大小球")


def latest_prior_snapshot(current: Path) -> Path | None:
    files = sorted(current.parent.glob("*_titan007_odds_snapshot.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
    for path in files:
        if path != current and path.stat().st_mtime <= current.stat().st_mtime:
            return path
    return None


def triplet(row: dict[str, str], prefix: str) -> str:
    return "/".join(
        str(row.get(key, "") or "")
        for key in (
            f"{prefix}_full_current_home_or_over",
            f"{prefix}_full_current_line_or_draw",
            f"{prefix}_full_current_away_or_under",
        )
    )


def intent_label(row: dict[str, str]) -> str:
    text = asian_intent_candidate(row)
    marker = "亚盘意图候选："
    if marker not in text:
        return text[:60]
    return text.split(marker, 1)[1].split("；", 1)[0].strip()


def drift_window(row: dict[str, str]) -> str:
    when = datetime_from_bj(row.get("bj_time", ""))
    if when is None:
        return "时间未识别"
    hour = when.hour
    if 16 <= hour < 20:
        return "16:00-20:00"
    if 20 <= hour < 24:
        return "20:00-24:00"
    if 0 <= hour < 4:
        return "00:00-04:00"
    if 4 <= hour < 10:
        return "04:00-10:00"
    return "10:00-16:00"


def snapshot_drift(rows: list[dict[str, str]], current_snapshot: Path) -> tuple[Path | None, list[dict[str, str]]]:
    prior = latest_prior_snapshot(current_snapshot)
    if not prior:
        return None, []
    ids = {(r.get("match_id") or "").strip() for r in rows if (r.get("match_id") or "").strip()}
    prior_rows = {
        (r.get("match_id") or "").strip(): r
        for r in read_csv(prior)
        if (r.get("match_id") or "").strip() in ids
    }
    out: list[dict[str, str]] = []
    for row in rows:
        match_id = (row.get("match_id") or "").strip()
        if not match_id:
            continue
        before = prior_rows.get(match_id)
        if not before:
            out.append(
                {
                    "window": drift_window(row),
                    "league": row.get("league_cn", ""),
                    "time": f"2026-{row.get('bj_time','')}",
                    "match": f"{row.get('home_cn','')} vs {row.get('away_cn','')}",
                    "change": "上一版未覆盖/新增入今日列表日",
                    "before": "",
                    "after": f"亚盘 {fmt_ah(row)}；欧赔 {fmt_euro(row)}；大小球 {fmt_total(row)}",
                }
            )
            continue
        changes: list[str] = []
        for label, prefix in (("亚盘", "ah"), ("欧赔", "euro"), ("大小球", "total")):
            old = triplet(before, prefix)
            new = triplet(row, prefix)
            if old != new:
                changes.append(f"{label} {old} -> {new}")
        if (before.get("state") or "") != (row.get("state") or ""):
            changes.append(f"状态 {before.get('state','')} -> {row.get('state','')}")
        old_intent = intent_label(before)
        new_intent = intent_label(row)
        if old_intent != new_intent:
            changes.append(f"候选意图 {old_intent} -> {new_intent}")
        if changes:
            out.append(
                {
                    "window": drift_window(row),
                    "league": row.get("league_cn", ""),
                    "time": f"2026-{row.get('bj_time','')}",
                    "match": f"{row.get('home_cn','')} vs {row.get('away_cn','')}",
                    "change": "；".join(changes[:6]),
                    "before": f"亚盘 {fmt_ah(before)}；欧赔 {fmt_euro(before)}；大小球 {fmt_total(before)}",
                    "after": f"亚盘 {fmt_ah(row)}；欧赔 {fmt_euro(row)}；大小球 {fmt_total(row)}",
                }
            )
    return prior, out


def write_drift_files(current_snapshot: Path, prior_snapshot: Path | None, drifts: list[dict[str, str]]) -> tuple[Path, Path]:
    review_dir = ROOT / "reviews"
    review_dir.mkdir(parents=True, exist_ok=True)
    suffix = current_snapshot.stem.split("_titan007", 1)[0]
    md_path = review_dir / f"snapshot_drift_{TODAY.isoformat()}_{suffix}.md"
    csv_path = review_dir / f"snapshot_drift_{TODAY.isoformat()}_{suffix}.csv"
    fields = ["window", "league", "time", "match", "change", "before", "after"]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(drifts)
    lines = [
        f"# {TODAY.isoformat()} 快照变动预警",
        "",
        f"- 当前快照：`{current_snapshot}`",
        f"- 上一版快照：`{prior_snapshot}`" if prior_snapshot else "- 上一版快照：无",
        f"- 变动场次：{len(drifts)}",
        "",
        "| 时间段 | 联赛 | 北京时间 | 比赛 | 变化 |",
        "|---|---|---:|---|---|",
    ]
    for item in drifts[:80]:
        lines.append(f"| {item['window']} | {item['league']} | {item['time']} | {item['match']} | {item['change']} |")
    if len(drifts) > 80:
        lines.append(f"| ... | ... | ... | 其余 {len(drifts) - 80} 场见CSV | ... |")
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return md_path, csv_path


def has_price_triplet(row: dict[str, str], prefix: str) -> bool:
    return all(
        fnum(row, key) is not None
        for key in (
            f"{prefix}_full_current_home_or_over",
            f"{prefix}_full_current_line_or_draw",
            f"{prefix}_full_current_away_or_under",
        )
    )


def completeness_counts(rows: list[dict[str, str]]) -> list[tuple[str, int, int, str]]:
    specs = [
        ("赛程比分", lambda r: bool(r.get("match_id") and r.get("bj_time")), "Titan007/球探列表赛程与比分状态"),
        ("亚盘", lambda r: has_price_triplet(r, "ah"), "需让球线和两边水位"),
        ("欧赔", lambda r: has_price_triplet(r, "euro"), "需主/平/客三项即时赔率"),
        ("大小球", lambda r: has_price_triplet(r, "total"), "需总进球线和大小两边水位"),
        ("BTTS/二级盘口", lambda _r: False, "未接入结构化源，禁止双方进球方向"),
        ("伤停", lambda r: detail_for(r).get("injury_ok") == "1", "Titan007/球探Lineup伤停页；需临场复核"),
        ("首发", lambda r: detail_for(r).get("lineup_ok") == "1", "Titan007/球探Lineup首发/替补页；赛前1小时需重核"),
        ("近5场", lambda r: bool(detail_for(r).get("recent_form_summary")), "Titan007/球探Analysis状态/近况摘要"),
        ("H2H", lambda r: bool(detail_for(r).get("h2h_summary")), "Titan007/球探Analysis交锋摘要"),
        ("赢盘/输盘记录", lambda r: detail_for(r).get("handicap_record_ok") == "1", "Titan007/球探历史盘口片段已抓取，未完全归一化"),
        ("PM/必发资金流", lambda r: bool(r.get("_flow")), "Chuqi必发衍生精确匹配；未匹配则沿用亚盘EV框架，不作翻向依据"),
        ("公共分析观点", lambda _r: False, "未接入博主/盘口观点交叉验证"),
    ]
    total = len(rows)
    out: list[tuple[str, int, int, str]] = []
    for label, checker, note in specs:
        ok = sum(1 for row in rows if checker(row))
        out.append((label, ok, total - ok, note))
    return out


def asian_intent_candidate(row: dict[str, str]) -> str:
    ah_open = fnum(row, "ah_full_open_line_or_draw")
    ah_now = fnum(row, "ah_full_current_line_or_draw")
    home_water = fnum(row, "ah_full_current_home_or_over")
    away_water = fnum(row, "ah_full_current_away_or_under")
    euro_home_open = fnum(row, "euro_full_open_home_or_over")
    euro_away_open = fnum(row, "euro_full_open_away_or_under")
    euro_home_now = fnum(row, "euro_full_current_home_or_over")
    euro_away_now = fnum(row, "euro_full_current_away_or_under")
    if None in (ah_open, ah_now, home_water, away_water):
        return "亚盘意图候选：亚盘线/两边水位不完整，不能判断"

    if ah_now > 0:
        fav = "主队上盘"
        fav_water = home_water
        under_water = away_water
        fav_euro_open = euro_home_open
        fav_euro_now = euro_home_now
    elif ah_now < 0:
        fav = "客队上盘"
        fav_water = away_water
        under_water = home_water
        fav_euro_open = euro_away_open
        fav_euro_now = euro_away_now
    else:
        if euro_home_now and euro_away_now and euro_home_now < euro_away_now:
            fav = "主队上盘"
            fav_water = home_water
            under_water = away_water
            fav_euro_open = euro_home_open
            fav_euro_now = euro_home_now
        elif euro_home_now and euro_away_now and euro_away_now < euro_home_now:
            fav = "客队上盘"
            fav_water = away_water
            under_water = home_water
            fav_euro_open = euro_away_open
            fav_euro_now = euro_away_now
        else:
            fav = "两边接近"
            fav_water = min(home_water, away_water)
            under_water = max(home_water, away_water)
            fav_euro_open = None
            fav_euro_now = None

    line_delta = abs(ah_now) - abs(ah_open)
    if line_delta >= 0.25:
        line_state = "让球加深"
    elif line_delta <= -0.25:
        line_state = "让球退盘"
    else:
        line_state = "让球基本稳定"

    euro_state = "欧赔方向未确认"
    if fav_euro_open and fav_euro_now and fav_euro_open > 1 and fav_euro_now > 1:
        if fav_euro_now <= fav_euro_open - 0.08:
            euro_state = "欧赔支持上盘"
        elif fav_euro_now >= fav_euro_open + 0.08:
            euro_state = "欧赔削弱上盘"
        else:
            euro_state = "欧赔变化不大"

    if line_state == "让球加深" and fav_water >= 1.00:
        candidates = ["阻上", "诱下"]
    elif line_state == "让球加深" and fav_water <= 0.86:
        candidates = ["诱上", "阻下"]
    elif line_state == "让球加深":
        candidates = ["真实示强", "阻上"]
    elif line_state == "让球退盘" and euro_state == "欧赔支持上盘":
        candidates = ["降温保护", "诱下"]
    elif line_state == "让球退盘" and euro_state == "欧赔削弱上盘":
        candidates = ["真实示弱", "阻下"]
    elif line_state == "让球退盘":
        candidates = ["降温保护", "诱下"]
    elif fav_water >= 1.02:
        candidates = ["阻上", "降温保护"]
    elif fav_water <= 0.84:
        candidates = ["诱上", "阻下"]
    elif under_water >= 1.02:
        candidates = ["阻下", "上盘保护"]
    elif under_water <= 0.84:
        candidates = ["诱下", "上盘降温"]
    else:
        candidates = ["平衡盘", "等待临场确认"]

    detail = detail_for(row)
    evidence = "中证据" if any([detail.get("lineup_ok") == "1", detail.get("recent_form_summary"), detail.get("h2h_summary")]) else "低证据"
    missing = []
    if detail.get("injury_ok") != "1":
        missing.append("伤停")
    if detail.get("lineup_ok") != "1":
        missing.append("首发")
    if not detail.get("recent_form_summary"):
        missing.append("近5场")
    if not detail.get("h2h_summary"):
        missing.append("H2H")
    flow_text = summarize_flow(row, compact=True)
    if not row.get("_flow"):
        missing.extend(["PM/必发资金流"])
    return (
        f"亚盘意图候选：{'/'.join(candidates)}（{evidence}）；"
        f"依据：{fav}，{line_state}，上盘水位{fav_water:.2f}，下盘水位{under_water:.2f}，{euro_state}；"
        f"{'缺' + '、'.join(missing) + '；' if missing else ''}{flow_text}；亚盘下注由EV漏斗决定"
    )


def short(value: str, limit: int = 90) -> str:
    text = " ".join((value or "").split())
    if not text:
        return "未接入/待核"
    return text if len(text) <= limit else text[:limit] + "..."


def fundamental_text(row: dict[str, str]) -> str:
    d = detail_for(row)
    parts = [f"主客排名/阶段 {row.get('home_rank_or_stage','')}-{row.get('away_rank_or_stage','')}"]
    if d.get("strength_summary"):
        parts.append(d["strength_summary"])
    if d.get("home_injuries") or d.get("away_injuries"):
        parts.append(f"伤停 主[{short(d.get('home_injuries',''), 60)}] / 客[{short(d.get('away_injuries',''), 60)}]")
    else:
        parts.append("伤停未发现结构化名单/待临场核")
    if d.get("lineup_ok") == "1":
        parts.append(f"首发阵型 主{d.get('home_formation','')} / 客{d.get('away_formation','')}")
    else:
        parts.append("首发未接入/待赛前1小时核")
    if d.get("recent_form_summary"):
        parts.append(f"近况 {short(d.get('recent_form_summary',''), 120)}")
    if d.get("h2h_summary"):
        parts.append(f"H2H {short(d.get('h2h_summary',''), 100)}")
    return "；".join(parts)


def detail_status_line(rows: list[dict[str, str]]) -> str:
    total = len(rows)
    if not total:
        return "球探详情：今日覆盖比赛为空。"
    lineup = sum(1 for r in rows if detail_for(r).get("lineup_ok") == "1")
    injury = sum(1 for r in rows if detail_for(r).get("injury_ok") == "1")
    analysis = sum(1 for r in rows if detail_for(r).get("analysis_ok") == "1")
    return f"球探详情：Lineup首发 {lineup}/{total}，伤停名单 {injury}/{total}，Analysis近况/交锋 {analysis}/{total}。"


def main() -> int:
    snapshot = latest_snapshot()
    details = load_details()
    flow_path, flow_lookup = load_flow_lookup()
    all_snapshot_rows = [r for r in read_csv(snapshot) if in_target_list_date(r)]
    ignored_friendlies = [r for r in all_snapshot_rows if is_friendy_or_ignored(r)]
    ignored_youth_reserve = [
        r for r in all_snapshot_rows
        if not is_friendy_or_ignored(r) and is_youth_or_reserve(r)
    ]
    tier_unknown_rows = [
        r for r in all_snapshot_rows
        if not is_friendy_or_ignored(r)
        and not is_youth_or_reserve(r)
        and senior_league_tier(r) is None
        and not is_senior_cup_or_playoff(r)
    ]
    no_market_rows = [
        r for r in all_snapshot_rows
        if not is_friendy_or_ignored(r)
        and not is_youth_or_reserve(r)
        and (senior_league_tier(r) is not None or is_senior_cup_or_playoff(r))
        and not has_verifiable_market(r)
    ]
    rows = [r for r in all_snapshot_rows if eligible_competitive_row(r)]
    hist = load_history()
    sims = []
    for r in rows:
        r["_detail"] = details.get((r.get("match_id") or "").strip(), {})
        attach_flow(r, flow_lookup)
        sim = choose_simulation(r, hist)
        r["_sim"] = sim
        sims.append(r)
    flow_overlay_path = write_flow_overlay(rows, flow_path)
    prior_snapshot, drift_rows = snapshot_drift(rows, snapshot)
    drift_path, drift_csv_path = write_drift_files(snapshot, prior_snapshot, drift_rows)

    ended = [r for r in rows if r.get("state") == "-1"]
    live = [r for r in rows if is_live_state(r.get("state", ""))]
    abnormal = [r for r in rows if is_abnormal_state(r.get("state", ""))]
    future = [r for r in rows if r.get("state") == "0"]
    future_sorted = sorted(future, key=lambda r: r["_sim"]["sort"], reverse=True)
    ledger_sorted = sorted(rows, key=lambda r: (r.get("state") != "0", r.get("bj_time", ""), r.get("league_cn", ""), r.get("home_cn", "")))

    DAILY.mkdir(parents=True, exist_ok=True)
    report_path = DAILY / f"{TODAY.isoformat()}_titan007_strict_update.md"
    sim_path = ROOT / "ledger" / f"{TODAY.isoformat()}_titan007_simulations.csv"

    lines: list[str] = []
    lines.append(f"# {TODAY.isoformat()} 严格按 skill 更新（Titan007赔率快照）")
    lines.append("")
    lines.append(f"- 快照文件：`{snapshot}`")
    lines.append(f"- 列表日字段：优先使用 `list_date={TODAY.isoformat()}`；不再按自然日重复纳入前一列表日凌晨比赛。")
    lines.append(f"- 上一版变动预警：{len(drift_rows)} 场发生盘口/赔率/状态/候选意图变化；明细 `{drift_path}`，表格 `{drift_csv_path}`。")
    lines.append(f"- 交易日窗口：{TODAY.isoformat()} 00:00 至 {(TODAY + dt.timedelta(days=1)).isoformat()} {SLATE_END_HOUR:02d}:00 北京时间。")
    lines.append(f"- 球探列表日成年正式比赛覆盖：{len(rows)} 场；已完场 {len(ended)}，进行中/待确认 {len(live)}，异常/改期 {len(abnormal)}，未开赛 {len(future)}。")
    lines.append(f"- 友谊赛默认忽略：{len(ignored_friendlies)} 场；青年/后备/U系列忽略：{len(ignored_youth_reserve)} 场；层级未知待确认：{len(tier_unknown_rows)} 场；无可验证盘口/赔率字段暂不纳入：{len(no_market_rows)} 场。")
    matched_flow_count = sum(1 for r in rows if r.get("_flow"))
    lines.append(f"- 赔率源：Titan007即时快照；球探Lineup/Analysis详情已尝试结构化抓取；资金流源：`{flow_path or '未抓到Chuqi必发衍生文件'}`，精确匹配 {matched_flow_count}/{len(rows)} 场；未匹配则沿用亚盘EV框架。")
    lines.append(f"- 资金流验证底稿：`{flow_overlay_path}`。")
    lines.append(f"- {detail_status_line(rows)}")
    lines.append("- 严格纪律：未重新读取即时盘口不分析；没有对应市场真实价格不形成对应市场模拟；已开赛/已完场不补造赛前模拟。")
    lines.append("- 真实亚盘线+两边水位齐全的未开赛比赛进入亚盘EV漏斗；PM/必发/BTTS缺口只禁止对应市场主单，不再一票否决亚盘；有资金流时按新增资金流验证矩阵确认或修正方向。")
    lines.append("")

    watch_only_count = len([r for r in future if r.get("_sim", {}).get("market") in ("亚盘意图框架-待EV筛选", "盘口快照-不形成模拟")])
    full_analysis_count = len([r for r in future if r.get("_sim", {}).get("market") not in ("亚盘意图框架-待EV筛选", "盘口快照-不形成模拟", "亚盘盘口缺失-不形成模拟")])
    lines.append("## 覆盖分层（full-analysis / watch-only / no-market）")
    lines.append("| 分层 | 场数 | 处理口径 |")
    lines.append("|---|---:|---|")
    lines.append(f"| full-analysis candidates | {full_analysis_count} | 对应市场价格、基本面和资金流均完整的候选。 |")
    lines.append(f"| Asian-EV pending | {watch_only_count} | 已读取亚盘/欧赔/大小球及球探详情，进入标签历史+微观组合+水位阈值+同档否决+风控漏斗；PM/必发缺口仅作证据折扣。 |")
    lines.append(f"| no-market / missing-data | {len(no_market_rows)} | 今日球探名单里缺可验证盘口/赔率字段，按 skill 不进入模拟列表；仅保留缺口审计。 |")
    lines.append(f"| abnormal / non-prematch | {len(abnormal)} | 推迟、取消或非赛前状态，只更新状态，不补造赛前结论。 |")
    lines.append("")

    lines.append("## 数据完整性审计")
    lines.append("| 字段 | 已接入 | 缺失 | 说明 |")
    lines.append("|---|---:|---:|---|")
    for field, ok, miss, note in completeness_counts(rows):
        lines.append(f"| {field} | {ok} | {miss} | {note} |")
    lines.append("")
    lines.append("- 结论：Titan007列表快照+球探详情可以补齐部分基本面；BTTS和公共观点缺口只阻断对应市场主单；PM/必发未匹配时亚盘不被自动否决，PM/必发匹配时作为资金流验证层。亚盘是否可投以HTML红框EV漏斗为准。")
    lines.append("")

    lines.append("## 上一版变动预警")
    lines.append("| 时间段 | 联赛 | 北京时间 | 比赛 | 变化 |")
    lines.append("|---|---|---:|---|---|")
    for item in drift_rows[:30]:
        lines.append(f"| {item['window']} | {item['league']} | {item['time']} | {item['match']} | {item['change']} |")
    if not drift_rows:
        lines.append("| 无 | 无 | 无 | 无 | 与上一版相比未识别到关键盘口/候选变化 |")
    elif len(drift_rows) > 30:
        lines.append(f"| ... | ... | ... | 其余 {len(drift_rows) - 30} 场见 drift CSV | ... |")
    lines.append("")

    lines.append("## 已结束/进行中/异常状态赛果")
    lines.append("| 状态 | 联赛 | 北京时间 | 中文比赛 | 比分 | 亚盘即时 | 欧赔即时 | 欧赔去水 | 大小球即时 |")
    lines.append("|---|---:|---:|---|---:|---|---|---|---|")
    for r in (ended + live + abnormal)[:30]:
        lines.append(
            f"| {state_label(r.get('state',''))} | {r['league_cn']} | 2026-{r['bj_time']} | "
            f"{r['home_cn']} vs {r['away_cn']} | {r.get('home_score','')}-{r.get('away_score','')} | "
            f"{fmt_ah(r)} | {fmt_euro(r)} | {euro_devig(r)} | {fmt_total(r)} |"
        )
    if len(ended) + len(live) + len(abnormal) > 30:
        lines.append(f"| ... | ... | ... | 其余 {len(ended) + len(live) + len(abnormal) - 30} 场见CSV | ... | ... | ... | ... |")
    lines.append("")

    lines.append("## 拉力-价格-流动性公开表（今日未开赛覆盖比赛）")
    lines.append("| 联赛 | 北京时间 | 中文比赛 | 基本面拉力 | 盘口价格（Titan007） | 欧赔去水 | 亚盘意图候选 | PM/流动性 | 结论 |")
    lines.append("|---|---:|---|---|---|---|---|---|---|")
    for r in future_sorted:
        sim = r["_sim"]
        fundamental = fundamental_text(r)
        price = f"亚盘 {fmt_ah(r)}；欧赔 {fmt_euro(r)}；大小 {fmt_total(r)}"
        if sim["market"] in ("亚盘意图框架-待EV筛选", "盘口快照-不形成模拟"):
            conclusion = "亚盘EV漏斗待HTML红框判断；PM/必发缺口不一票否决亚盘"
        elif sim["market"] == "亚盘":
            conclusion = "亚盘纸面模拟-真实不投"
        else:
            conclusion = "盘口缺失-不形成模拟"
        flow_text = summarize_flow(r, compact=True)
        lines.append(
            f"| {r['league_cn']} | 2026-{r['bj_time']} | {r['home_cn']} vs {r['away_cn']} | "
            f"{fundamental} | {price} | {euro_devig(r)} | {asian_intent_candidate(r)} | {flow_text} | {conclusion} |"
        )
    lines.append("")

    lines.append("## 未开赛亚盘EV候选/盘口快照")
    lines.append("| 排名 | 联赛 | 北京时间 | 中文比赛 | 亚盘 | 欧赔去水 | 大小球 | 亚盘意图候选 | 结论 |")
    lines.append("|---:|---|---:|---|---|---|---|---|---|")
    for i, r in enumerate(future_sorted[:40], 1):
        sim = r["_sim"]
        lines.append(
            f"| {i} | {r['league_cn']} | 2026-{r['bj_time']} | {r['home_cn']} vs {r['away_cn']} | "
            f"{fmt_ah(r)} | {euro_devig(r)} | {fmt_total(r)} | {asian_intent_candidate(r)} | "
            f"{sim['action']}；{sim['bucket']} |"
        )
    lines.append("")

    lines.append("## 今日主单")
    lines.append("- 亚盘主单：以HTML红框EV漏斗为准；若标签历史、微观组合、水位阈值、同档否决和风控全部通过，可标为可投/半仓可投。")
    lines.append("- Polymarket主单：无。原因：本次未抓到对应PM合约、价格、盘口阈值和流动性。")
    lines.append("- BTTS/大小球主单：只在该市场真实盘口和价格齐全时给出；不得用进球倾向替代市场价格。")
    lines.append("")

    lines.append("## 五板链路总评")
    lines.append("1. 基本面拉力：已纳入球探Lineup/Analysis能抓到的伤停、首发、近况、交锋和综合评分；未抓到或临场未确认的字段继续降权。")
    lines.append("2. 欧赔去水：Titan007欧赔即时已做单场去水；未做跨公司共识，仍不能单独升级主单。")
    lines.append("3. 亚盘真实意图：阻上/诱上/阻下/诱下用于判断候选可能性；是否下注由标签历史、微观组合、贝叶斯合力、水位阈值、同档否决和风控状态决定。")
    lines.append("4. Polymarket/必发反向情绪：本次缺失，不能给PM/必发主单；该缺口不再自动否决亚盘EV。")
    lines.append("5. 最终盘口选择：亚盘看HTML红框EV漏斗，PM/BTTS/大小球必须等待各自真实市场价格。")

    report_path.write_text("\n".join(lines), encoding="utf-8")

    sim_fields = [
        "日期", "赛事", "比赛", "模拟ID", "赛制阶段", "市场框架", "模拟盘口/价格", "模拟方向",
        "虚拟仓位单位", "基本面拉力", "盘口倾向", "Polymarket/交易所情绪", "流动性", "模拟目的",
        "是否主单", "赛果", "模拟盈亏单位", "过程评级", "错误类型", "模型更新",
    ]
    with sim_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=sim_fields)
        writer.writeheader()
        sim_rows = []
        for r in ledger_sorted:
            sim = r["_sim"]
            is_future = r.get("state") == "0"
            score = f"{r.get('home_score','')}-{r.get('away_score','')}"
            if sim["market"] == "亚盘":
                price_text = f"{sim['pick']} @HK {sim['price']} 十进制{sim['decimal']}"
                stake_unit = "0.25"
                pnl_status = "待填"
                grade = "待完场"
                err = "待分类"
                result = "待赛"
            elif sim["market"] in ("亚盘意图框架-待EV筛选", "盘口快照-不形成模拟"):
                price_text = "已读取亚盘/欧赔/大小球即时快照；亚盘投注由标签历史+微观组合+水位阈值+同档否决+风控漏斗决定"
                stake_unit = "0"
                pnl_status = "不计"
                grade = "NA"
                err = "亚盘EV待筛选"
                result = "待赛"
            elif is_future:
                price_text = "对应市场真实盘口/水位缺失；不形成模拟"
                stake_unit = "0"
                pnl_status = "不计"
                grade = "NA"
                err = "盘口缺失-不形成模拟"
                result = "待赛"
            else:
                price_text = "已开赛/已完场；本次严格更新不补造赛前模拟"
                stake_unit = "0"
                pnl_status = "不计"
                grade = "NA"
                err = "非赛前-不形成模拟"
                label = state_label(r.get("state", ""))
                result = score if r.get("state") == "-1" else f"{label} {score}".strip()
            out_row = {
                "日期": TODAY.isoformat(),
                "赛事": r["league_cn"],
                "比赛": f"{r['home_cn']} vs {r['away_cn']}",
                "模拟ID": f"{TODAY.strftime('%Y%m%d')}-TITAN-{r['match_id']}-{sim['market']}",
                "赛制阶段": f"排名/阶段 {r.get('home_rank_or_stage','')}-{r.get('away_rank_or_stage','')}",
                "市场框架": sim["market"],
                "模拟盘口/价格": price_text,
                "模拟方向": sim["pick"],
                "虚拟仓位单位": stake_unit,
                "基本面拉力": fundamental_text(r),
                "盘口倾向": f"Titan007亚盘 {fmt_ah(r)}；欧赔 {fmt_euro(r)}；{euro_devig(r)}；大小球 {fmt_total(r)}；{asian_intent_candidate(r)}；{sim['bucket']}",
                "Polymarket/交易所情绪": summarize_flow(r),
                "流动性": summarize_liquidity(r),
                "模拟目的": "严格按skill：展示盘口快照和球探详情；PM/必发/BTTS缺口只禁止对应市场主单，亚盘按标签+微观+水位+同档+风控漏斗判断",
                "是否主单": "否",
                "赛果": result,
                "模拟盈亏单位": pnl_status,
                "过程评级": grade,
                "错误类型": err,
                "模型更新": "本次更新已重新读取即时盘口；亚盘方向由HTML红框EV漏斗给出；无投注数据时沿用原亚盘EV框架，有Chuqi/必发匹配时按资金流验证矩阵审计",
            }
            sim_rows.append(out_row)
            writer.writerow(out_row)

    existing_rows = read_csv(LEDGER) if LEDGER.exists() else []
    sim_rows = preserve_started_prematch_rows(sim_rows, existing_rows)
    with sim_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=sim_fields)
        writer.writeheader()
        for row in sim_rows:
            writer.writerow({field: row.get(field, "") for field in sim_fields})

    merged = [row for row in existing_rows if row.get("日期") != TODAY.isoformat()]
    seen = {row.get("模拟ID", "") for row in merged}
    for row in sim_rows:
        merged.append(row)
        seen.add(row["模拟ID"])

    with LEDGER.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=sim_fields)
        writer.writeheader()
        for row in merged:
            writer.writerow({field: row.get(field, "") for field in sim_fields})

    audit_script = Path(r"D:\codex\tools\audit_asian_intent_history.py")
    grouped_review_path = ROOT / "reviews" / f"grouped_edge_review_{TODAY.isoformat()}.md"
    if audit_script.exists():
        spec = importlib.util.spec_from_file_location("audit_asian_intent_history", audit_script)
        if spec and spec.loader:
            audit_module = importlib.util.module_from_spec(spec)
            old_argv = sys.argv[:]
            sys.argv = [str(audit_script), "2026-07-27", TODAY.isoformat()]
            try:
                spec.loader.exec_module(audit_module)
                audit_module.main()
            finally:
                sys.argv = old_argv

    micro_edge_script = Path(r"D:\codex\tools\build_micro_region_tag_edge.py")
    if micro_edge_script.exists():
        spec = importlib.util.spec_from_file_location("build_micro_region_tag_edge", micro_edge_script)
        if spec and spec.loader:
            micro_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(micro_module)
            micro_module.main()

    bettable_stats_script = Path(r"D:\codex\tools\build_bettable_event_stats.py")
    if bettable_stats_script.exists():
        spec = importlib.util.spec_from_file_location("build_bettable_event_stats", bettable_stats_script)
        if spec and spec.loader:
            bettable_module = importlib.util.module_from_spec(spec)
            old_argv = sys.argv[:]
            sys.argv = [str(bettable_stats_script), "--date", TODAY.isoformat()]
            try:
                spec.loader.exec_module(bettable_module)
                bettable_module.main()
            finally:
                sys.argv = old_argv

    dashboard_script = Path(r"D:\codex\tools\build_football_dashboard.py")
    if dashboard_script.exists():
        spec = importlib.util.spec_from_file_location("build_football_dashboard", dashboard_script)
        if spec and spec.loader:
            dashboard_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(dashboard_module)
            dashboard_module.main()

    publish_script = Path(r"D:\codex\tools\publish_football_dashboard_to_github.py")
    if publish_script.exists():
        spec = importlib.util.spec_from_file_location("publish_football_dashboard_to_github", publish_script)
        if spec and spec.loader:
            publish_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(publish_module)
            try:
                publish_result = publish_module.publish(push=True)
                print(f"github_publish_committed={publish_result.get('committed')} pushed={publish_result.get('pushed')}")
                if publish_result.get("error"):
                    print(f"github_publish_error={publish_result.get('error')}")
            except Exception as exc:
                print(f"github_publish_error={exc}")

    print(f"report={report_path}")
    print(f"sim_csv={sim_path}")
    print(f"grouped_review={grouped_review_path}")
    print(f"flow_overlay={flow_overlay_path}")
    print(f"drift_report={drift_path}")
    print(f"drift_csv={drift_csv_path}")
    print(f"covered_today={len(rows)} ended={len(ended)} live={len(live)} future={len(future)}")
    print("top_future=")
    for r in future_sorted[:8]:
        sim = r["_sim"]
        print(f"{r['league_cn']} {r['bj_time']} {r['home_cn']} vs {r['away_cn']} | 盘口快照 | {sim['action']} stake=0.0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
