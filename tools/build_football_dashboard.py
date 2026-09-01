from __future__ import annotations

import csv
import datetime as dt
import html
import json
import re
from collections import defaultdict
from pathlib import Path


ROOT = Path(r"D:\codex\outputs\football_odds_trader")
LEDGER = ROOT / "ledger" / "simulated_bets.csv"
DASHBOARD_DIR = ROOT / "dashboard"
RAW_TITAN = ROOT / "raw" / "titan007"
DETAIL_LEDGER = ROOT / "ledger"
SEQUENTIAL_BACKTEST_DIR = ROOT / "backtests" / "sequential_asian"
TODAY = dt.datetime.now().date()

LINE_ORDER = [
    "平手",
    "平手/半球",
    "半球",
    "半球/一球",
    "一球",
    "一球/球半",
    "球半",
    "球半/两球",
    "两球",
    "两球/两球半",
]

TAG_ORDER = [
    "真实示弱/阻下",
    "阻下/上盘保护",
    "降温保护/诱下",
    "阻上/诱下",
    "真实示强/阻上",
    "诱上/阻下",
    "诱下/上盘降温",
]

TEAM_CN = {
    "Brighton": "布莱顿",
    "Aston Villa": "阿斯顿维拉",
    "Newcastle United": "纽卡斯尔联",
    "Liverpool": "利物浦",
    "Atletico Madrid": "马德里竞技",
    "Villarreal": "比利亚雷亚尔",
    "Torino": "都灵",
    "AC Milan": "AC米兰",
    "Rennes": "雷恩",
    "PSG": "巴黎圣日耳曼",
    "Club Brugge": "布鲁日",
    "Cercle Brugge": "色格拉布鲁日",
    "Machida Zelvia": "町田泽维亚",
    "Urawa Reds": "浦和红钻",
    "IFK Gothenburg": "哥德堡",
    "Elfsborg": "埃尔夫斯堡",
    "Hammarby": "哈马比",
    "GAIS": "哥德堡盖斯",
    "Akron Tolyatti": "阿克伦托利亚蒂",
    "Krylia Sovetov": "苏维埃之翼",
    "Dynamo Makhachkala": "马哈奇卡拉迪纳摩",
    "Krasnodar": "克拉斯诺达尔",
    "Spartak Moscow": "莫斯科斯巴达",
    "Zenit St Petersburg": "圣彼得堡泽尼特",
    "Liaoning Tieren": "辽宁铁人",
    "Henan": "河南队",
    "Chongqing Tonglianglong": "重庆铜梁龙",
    "Dalian Yingbo": "大连英博",
    "Barracas Central": "巴拉卡斯中央",
    "Platense": "普拉滕斯",
    "Sarmiento": "萨米恩托",
    "Estudiantes": "拉普拉塔大学生",
    "Estudiantes RC": "里奥夸尔托学生",
    "San Lorenzo": "圣洛伦索",
    "Aldosivi": "阿尔多西维",
    "Union Santa Fe": "圣塔菲联",
    "Atletico Tucuman": "图库曼竞技",
    "Instituto": "科尔多瓦学院",
    "Gimnasia LP": "拉普拉塔体操",
    "Gimnasia Mendoza": "门多萨体操",
    "Independiente Rivadavia": "门多萨独立",
    "Independiente": "阿根廷独立",
    "Vitoria": "维多利亚",
    "Bahia": "巴伊亚",
    "New England Revolution": "新英格兰革命",
    "New York City FC": "纽约城FC",
    "Atlanta United": "亚特兰大联",
    "Sporting Kansas City": "堪萨斯城竞技",
}

LEAGUE_CN = {
    "MLS": "美职业",
    "EPL": "英超",
    "LIG1": "法甲",
    "SERIEA": "意甲",
    "LIGA": "西甲",
}


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def latest_file(pattern: str, root: Path) -> Path | None:
    files = sorted(root.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def latest_sequential_backtest() -> dict[str, object]:
    path = latest_file("sequential_asian_backtest_*_summary.json", SEQUENTIAL_BACKTEST_DIR)
    if not path:
        return {"available": False}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"available": False, "error": str(exc), "summary_json": str(path)}
    payload["available"] = True
    payload["summary_json"] = str(path)
    return payload


def fmt_rate(value: object) -> str:
    try:
        return f"{float(value) * 100:.1f}%"
    except Exception:
        return "NA"


def fmt_num(value: object) -> str:
    try:
        return f"{float(value):+.4f}"
    except Exception:
        return "NA"


def render_sequential_backtest_box(backtest: dict[str, object]) -> str:
    if not backtest.get("available"):
        error = html.escape(str(backtest.get("error", "尚未生成顺序回测结果")))
        return f"""
    <div class="pattern-card backtest-card">
      <div class="panel-title"><span>顺序回测引擎</span><span>未接入</span></div>
      <div class="pattern-body backtest-body"><div class="empty">{error}</div></div>
      <div class="pattern-note">运行 `python D:\\codex\\tools\\sequential_asian_backtest_engine.py` 后会自动显示最新回测摘要。</div>
    </div>"""

    summary = backtest.get("summary", {}) if isinstance(backtest.get("summary"), dict) else {}
    cfg = backtest.get("config", {}) if isinstance(backtest.get("config"), dict) else {}
    by_region = backtest.get("by_region", []) if isinstance(backtest.get("by_region"), list) else []
    by_tag = backtest.get("by_tag", []) if isinstance(backtest.get("by_tag"), list) else []
    top_regions = by_region[:3]
    top_tags = by_tag[:3]
    paths = [
        ("明细", backtest.get("detail_csv", "")),
        ("板块", backtest.get("region_csv", "")),
        ("标签", backtest.get("tag_csv", "")),
        ("报告", backtest.get("report_md", "")),
    ]

    def small_table(rows: list[dict[str, object]], key: str) -> str:
        if not rows:
            return '<div class="note">暂无分组结果</div>'
        tr = "".join(
            f"<tr><td>{html.escape(str(r.get(key, '')))}</td><td>{html.escape(str(r.get('已结算投注数', '')))}</td><td>{fmt_rate(r.get('胜率'))}</td><td>{fmt_num(r.get('盈亏Unit'))}</td><td>{fmt_rate(r.get('ROI'))}</td></tr>"
            for r in rows
        )
        return f"<table class='mini-table'><thead><tr><th>分组</th><th>注数</th><th>胜率</th><th>Unit</th><th>ROI</th></tr></thead><tbody>{tr}</tbody></table>"

    path_html = "".join(
        f"<div class='path-line'><strong>{html.escape(name)}</strong>：{html.escape(str(path))}</div>"
        for name, path in paths
        if path
    )
    return f"""
    <div class="pattern-card backtest-card">
      <div class="panel-title"><span>顺序回测引擎</span><span>Walk-Forward</span></div>
      <div class="pattern-body backtest-body">
        <div class="backtest-metrics">
          <div><b>{html.escape(str(summary.get('完整测算比赛数', '0')))}</b><span>测算</span></div>
          <div><b>{html.escape(str(summary.get('符合投注条件数', '0')))}</b><span>投注</span></div>
          <div><b>{html.escape(str(summary.get('已结算数', '0')))}</b><span>已结算</span></div>
          <div><b>{fmt_rate(summary.get('实际总胜率'))}</b><span>胜率</span></div>
          <div><b>{fmt_num(summary.get('实际总盈亏Unit'))}</b><span>Unit</span></div>
          <div><b>{fmt_rate(summary.get('整体资金流水ROI'))}</b><span>ROI</span></div>
        </div>
        <div class="backtest-note">阈值：1/(Water+1)+{html.escape(str(cfg.get('safety_buffer', '0.02')))}；熔断拦截 {html.escape(str(summary.get('熔断拦截数', '0')))} 场；标准仓位 {html.escape(str(cfg.get('standard_stake_rate', '0.05')))}。</div>
        <div class="two-mini">
          <div><div class="subcap">板块Top</div>{small_table(top_regions, '微观板块')}</div>
          <div><div class="subcap">标签Top</div>{small_table(top_tags, '盘口意图标签')}</div>
        </div>
        <details class="path-details"><summary>查看本地输出文件</summary>{path_html}</details>
      </div>
      <div class="pattern-note">该模块来自顺序回测脚本；每次策略/回测更新必须进入本地HTML并同步GitHub。</div>
    </div>"""


def read_text_auto(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "utf-8", "gb18030", "gb2312"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def strip_html(value: str) -> str:
    value = re.sub(r"<script\b.*?</script>", "", value or "", flags=re.S | re.I)
    value = re.sub(r"<style\b.*?</style>", "", value, flags=re.S | re.I)
    value = re.sub(r"<[^>]+>", "", value)
    value = html.unescape(value).replace("\xa0", " ")
    return re.sub(r"\s+", " ", value).strip()


def clean_team(value: str) -> str:
    value = strip_html(value)
    value = re.sub(r"\[[^\]]+\]", "", value)
    return re.sub(r"\s+", " ", value).strip()


def match_id_from_row(row: dict[str, str]) -> str:
    for key in ("match_id", "比赛ID", "模拟ID"):
        value = row.get(key, "")
        m = re.search(r"TITAN-(\d{6,})", value or "")
        if m:
            return m.group(1)
    for key in ("match_id", "比赛ID", "模拟ID"):
        value = row.get(key, "")
        m = re.search(r"\b(\d{6,})\b", value or "")
        if m:
            return m.group(1)
    return ""


def page_date_from_over_path(path: Path) -> dt.date | None:
    m = re.search(r"Over_(\d{8})", path.name)
    if not m:
        return None
    try:
        return dt.datetime.strptime(m.group(1), "%Y%m%d").date()
    except ValueError:
        return None


def actual_date_from_time(page_date: dt.date, time_text: str) -> dt.date:
    m = re.search(r"(\d{1,2})日", time_text or "")
    if not m:
        return page_date
    day = int(m.group(1))
    year = page_date.year
    month = page_date.month
    if day < page_date.day:
        if month == 12:
            year += 1
            month = 1
        else:
            month += 1
    try:
        return dt.date(year, month, day)
    except ValueError:
        return page_date


def load_titan_over_scores() -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for path in sorted(RAW_TITAN.glob("**/*Over_*.htm")):
        page_date = page_date_from_over_path(path)
        if not page_date:
            continue
        text = read_text_auto(path)
        for tr in re.finditer(r"<tr\b[^>]*\bsId=['\"]?(\d{6,})['\"]?[^>]*>(.*?)</tr>", text, re.S | re.I):
            match_id = tr.group(1)
            cells = re.findall(r"<td\b[^>]*>(.*?)</td>", tr.group(2), re.S | re.I)
            if len(cells) < 6:
                continue
            time_text = strip_html(cells[1])
            status = strip_html(cells[2])
            home = clean_team(cells[3])
            score_text = strip_html(cells[4])
            away = clean_team(cells[5])
            score_match = re.search(r"(\d+)\s*-\s*(\d+)", score_text)
            if "完" not in status or not score_match or not home or not away:
                continue
            actual_date = actual_date_from_time(page_date, time_text)
            time_match = re.search(r"(\d{1,2}:\d{2})", time_text)
            payload = {
                "match_id": match_id,
                "list_date": page_date.isoformat(),
                "actual_date": actual_date.isoformat(),
                "time": f"{actual_date.isoformat()} {time_match.group(1)}" if time_match else actual_date.isoformat(),
                "home": home,
                "away": away,
                "score": f"{score_match.group(1)}-{score_match.group(2)}",
                "state": "-1",
                "source": f"Titan007完场页:{path.name}",
            }
            out[f"id:{match_id}"] = payload
            out[f"match:{home} vs {away}"] = payload
    return out


def safe_float(value: str) -> float | None:
    try:
        return float(str(value).replace("+", "").strip())
    except Exception:
        return None


def parse_int(value: str) -> int:
    try:
        return int(float(str(value or "0").strip()))
    except ValueError:
        return 0


def asian_line_label(value: float | None) -> str:
    if value is None:
        return ""
    labels = {
        0.0: "平手",
        0.25: "平手/半球",
        0.5: "半球",
        0.75: "半球/一球",
        1.0: "一球",
        1.25: "一球/球半",
        1.5: "球半",
        1.75: "球半/两球",
        2.0: "两球",
        2.25: "两球/两球半",
        2.5: "两球半",
        2.75: "两球半/三球",
        3.0: "三球",
    }
    return labels.get(round(abs(value), 2), f"{abs(value):g}球")


def normalize_intent_tag(intent_text: str) -> str:
    match = re.search(r"亚盘意图候选：([^（。]+)", intent_text or "")
    if not match:
        return ""
    return re.sub(r"\s+", "", match.group(1).strip())


def intent_tag_side(tag: str) -> str:
    compact = re.sub(r"\s+", "", tag or "")
    if not compact or "平衡盘" in compact or "等待临场确认" in compact:
        return ""
    upper_patterns = (
        "阻上/诱下",
        "降温保护/诱下",
        "真实示强/阻上",
        "阻下/上盘保护",
        "诱下/上盘降温",
        "上盘保护",
        "上盘降温",
    )
    lower_patterns = (
        "诱上/阻下",
        "真实示弱/阻下",
    )
    if any(p in compact for p in upper_patterns):
        return "upper"
    if any(p in compact for p in lower_patterns):
        return "lower"
    if "阻上" in compact and "诱下" in compact:
        return "upper"
    if "诱上" in compact and "阻下" in compact:
        return "lower"
    return ""


def load_tag_performance(summary_path: Path | None) -> dict[str, object]:
    if not summary_path or not summary_path.exists():
        return {"source": "未生成", "good": [], "bad": [], "all": []}
    rows: list[dict[str, object]] = []
    for row in read_csv(summary_path):
        if row.get("分组类型") != "候选标签":
            continue
        sample = parse_int(row.get("样本", "0"))
        forward_pnl = safe_float(row.get("均注盈亏", "")) or 0.0
        reverse_pnl = safe_float(row.get("反向均注盈亏", "")) or 0.0
        rows.append(
            {
                "tag": row.get("分组", ""),
                "sample": sample,
                "win_rate": row.get("有效胜率", "") or "无",
                "forward_pnl": round(forward_pnl, 3),
                "reverse_rate": row.get("反向有效胜率", "") or "无",
                "reverse_pnl": round(reverse_pnl, 3),
                "verdict": row.get("建议方向", ""),
                "counts": (
                    f"{row.get('赢','0')}赢/{row.get('赢半','0')}赢半/"
                    f"{row.get('走','0')}走/{row.get('输半','0')}输半/{row.get('输','0')}输"
                ),
            }
        )

    good = sorted(
        [r for r in rows if float(r["forward_pnl"]) > 0],
        key=lambda r: (float(r["forward_pnl"]), int(r["sample"])),
        reverse=True,
    )
    bad = sorted(
        [r for r in rows if float(r["forward_pnl"]) < 0 and float(r["reverse_pnl"]) > 0],
        key=lambda r: (float(r["reverse_pnl"]), -float(r["forward_pnl"]), int(r["sample"])),
        reverse=True,
    )
    return {"source": str(summary_path), "good": good, "bad": bad, "all": rows}


def load_intent_matrix() -> dict[str, object]:
    path = latest_file("asian_intent_line_tag_matrix_*.csv", DETAIL_LEDGER)
    summary_path = latest_file("asian_intent_history_summary_*.csv", DETAIL_LEDGER)
    source_type = "line_tag_matrix"
    if not path:
        path = summary_path
        source_type = "history_summary"
    if not path:
        return {
            "source": "未生成",
            "source_type": "missing",
            "tags": TAG_ORDER,
            "matrix": [],
            "detail": [],
            "tag_performance": load_tag_performance(summary_path),
        }

    raw_rows = read_csv(path)
    rows: list[dict[str, object]] = []
    for row in raw_rows:
        if source_type == "history_summary":
            if row.get("分组类型") != "盘口档位+候选标签" or " / " not in row.get("分组", ""):
                continue
            line, tag = row.get("分组", "").split(" / ", 1)
        else:
            line = row.get("盘口档位", "")
            tag = row.get("候选标签", "")
        if not line or not tag:
            continue
        sample = parse_int(row.get("样本", "0"))
        forward_pnl = safe_float(row.get("均注盈亏", "")) or 0.0
        reverse_pnl = safe_float(row.get("反向均注盈亏", "")) or 0.0
        forward_rate = row.get("有效胜率", "") or "无"
        reverse_rate = row.get("反向有效胜率", "") or "无"
        if forward_pnl > 0 and forward_pnl >= reverse_pnl:
            direction = "正向"
        elif reverse_pnl > 0:
            direction = "反向"
        else:
            direction = "无正收益"
        rows.append(
            {
                "line": line,
                "tag": tag,
                "combo": f"{line} + {tag}",
                "sample": sample,
                "win_rate": forward_rate,
                "forward_rate": forward_rate,
                "reverse_rate": reverse_rate,
                "forward_pnl": round(forward_pnl, 3),
                "reverse_pnl": round(reverse_pnl, 3),
                "direction": direction,
                "note": row.get("矩阵建议", "") or row.get("推荐/标签", ""),
            }
        )

    lookup = {(str(r["line"]), str(r["tag"])): r for r in rows}
    matrix = []
    lines = [x for x in LINE_ORDER if any((x, tag) in lookup for tag in TAG_ORDER)]
    extra_lines = sorted({str(r["line"]) for r in rows} - set(lines))
    for line in lines + extra_lines:
        cells = []
        for tag in TAG_ORDER:
            cells.append(lookup.get((line, tag), {"line": line, "tag": tag, "empty": True}))
        matrix.append({"line": line, "cells": cells})

    detail = sorted(
        (r for r in rows if int(r["sample"]) >= 3),
        key=lambda r: (
            max(float(r["forward_pnl"]), float(r["reverse_pnl"])),
            int(r["sample"]),
        ),
        reverse=True,
    )

    return {
        "source": str(path),
        "source_type": source_type,
        "tags": TAG_ORDER,
        "matrix": matrix,
        "detail": detail,
        "tag_performance": load_tag_performance(summary_path),
    }


def extract_decimal(text: str) -> float | None:
    m = re.search(r"十进制([0-9.]+)", text or "")
    if not m:
        return None
    return safe_float(m.group(1))


def translate_text(text: str) -> str:
    out = strip_html(text or "")
    for en in sorted(TEAM_CN, key=len, reverse=True):
        out = out.replace(en, TEAM_CN[en])
    for en, cn in LEAGUE_CN.items():
        out = out.replace(en, cn)
    out = out.replace("BTTS Yes", "双方进球Yes")
    out = out.replace("BTTS No", "双方不进球")
    out = out.replace("U2.5", "小2.5")
    out = out.replace("O2.5", "大2.5")
    return out


def clean_missing_odds_text(text: str) -> str:
    if not text:
        return ""
    cleaned = str(text)
    replacements = {
        "Titan007亚盘 开 //；即 //": "Titan007亚盘 亚盘缺失",
        "亚盘 开 //；即 //": "亚盘 亚盘缺失",
        "欧赔 开 //；即 //": "欧赔 欧赔缺失",
        "大小球 开 //；即 //": "大小球 大小球缺失",
        "；即 //": "；即时缺失",
        "开 //；": "开盘缺失；",
        "开 //": "开盘缺失",
        "即 //": "即时缺失",
    }
    for old, new in replacements.items():
        cleaned = cleaned.replace(old, new)
    return cleaned


def display_time(value: str, matched: bool, date: str) -> str:
    if matched and value and value != "未匹配":
        return f"{value} 北京时间（东8区）"
    if date:
        return f"{date} 时间待球探匹配（东8区）"
    return "时间待球探匹配（东8区）"


def display_score(score: str, result: str, matched: bool) -> str:
    if result and result not in {"待赛", "待填"}:
        return strip_html(result)
    if matched and score and score != "未匹配" and score != "-":
        return strip_html(score)
    return strip_html(result) if result else "待赛"


TITAN_STATE_LABELS = {
    "-1": "完场",
    "-10": "取消",
    "-11": "待定",
    "-12": "腰斩/中止",
    "-13": "中断",
    "-14": "推迟",
    "0": "未开赛",
}


def is_titan_live_state(state: str) -> bool:
    try:
        return int((state or "").strip()) > 0
    except ValueError:
        return False


def is_titan_abnormal_state(state: str) -> bool:
    state = (state or "").strip()
    return state.startswith("-") and state != "-1"


def titan_state_name(state: str) -> str:
    state = (state or "").strip()
    if state in TITAN_STATE_LABELS:
        return TITAN_STATE_LABELS[state]
    if is_titan_live_state(state):
        return "进行中"
    return f"状态待核({state})" if state else "状态待核"


def titan_state_label(state: str, matched: bool, result: str) -> str:
    if result and ("未匹配" in result or "待人工核验" in result):
        return "待核"
    if result and result not in {"待赛", "待填"}:
        if is_titan_abnormal_state(state):
            return titan_state_name(state)
        if is_titan_live_state(state) or result.startswith("进行中"):
            return "进行中"
        return "已结算"
    if not matched:
        return "待核"
    if state == "-1":
        return "完场"
    if state == "0":
        return "未开赛"
    if is_titan_live_state(state):
        return "进行中"
    return titan_state_name(state)


def classify_action(row: dict[str, str]) -> str:
    result = row.get("赛果", "")
    pnl = row.get("模拟盈亏单位", "")
    if "待" in result or "待" in pnl:
        return "待赛"
    val = safe_float(pnl)
    if val is None:
        return "未结算"
    if val > 0:
        return "赢"
    if val < 0:
        return "输"
    return "走"


def market_from_text(row: dict[str, str]) -> str:
    market = row.get("市场框架", "") or row.get("具体盘口", "")
    if "大小" in market or "进球" in market or "Over" in market or "Under" in market:
        return "大小球"
    if "BTTS" in market or "双方" in market:
        return "双方进球"
    if "Polymarket" in market:
        return "Polymarket"
    if "亚盘" in market or "让" in market:
        return "亚盘"
    if "DNB" in market:
        return "DNB"
    if "胜平负" in market or "ML" in market:
        return "胜平负"
    return market or "未分类"


GOAL_MARKET_KEYS = ("BTTS", "双方进球", "进球盘", "大小球", "U2.5", "O2.5", "小2.5", "大2.5")


def is_goal_market(row: dict[str, str]) -> bool:
    text = " ".join(
        [
            row.get("市场框架", ""),
            row.get("模拟盘口/价格", ""),
            row.get("模拟方向", ""),
            row.get("模拟目的", ""),
        ]
    )
    return any(key in text for key in GOAL_MARKET_KEYS)


def goal_model_audit(row: dict[str, str], matched_odds: bool) -> tuple[str, str]:
    if not is_goal_market(row):
        return "非进球盘", "本场不是大小球/BTTS/球队进球数框架。"
    explicit_downgrade = " ".join(
        [
            row.get("市场框架", ""),
            row.get("模拟方向", ""),
            row.get("模拟盈亏单位", ""),
            row.get("错误类型", ""),
            row.get("模型更新", ""),
        ]
    )
    if any(k in explicit_downgrade for k in ("盘口缺失", "不形成模拟")):
        return (
            "盘口缺失-不形成模拟/真实不投",
            "该市场缺少真实盘口或赔率，不能输出市场方向，不能计入模拟胜率，真实下注凯利=0；需重新读取即时盘口后再分析。",
        )
    if any(k in explicit_downgrade for k in ("证据不足", "无下注", "不计胜率")):
        if "纸面验证" in explicit_downgrade or "纸面模拟" in explicit_downgrade:
            return (
                "证据不足-纸面验证/真实不投",
                "纸面模拟方向保留用于赛后校验；缺口：近5-10场进球/射门、射手/创造者/首发伤停、球风克制/比赛状态、进球时间分布/领先后策略、历史交锋/可比样本、盘口价格确认；真实下注凯利=0。",
            )
        return (
            "证据不足-无下注/仅观察",
            "缺口：近5-10场进球/射门、射手/创造者/首发伤停、球风克制/比赛状态、进球时间分布/领先后策略、历史交锋/可比样本、盘口价格确认；已降级为0仓位且不计胜率。",
        )
    text = " ".join(
        [
            row.get("基本面拉力", ""),
            row.get("盘口倾向", ""),
            row.get("模拟目的", ""),
            row.get("模型更新", ""),
            row.get("模拟盘口/价格", ""),
        ]
    )
    checks = {
        "近5-10场进球/射门": any(k in text for k in ("近5", "近况", "进球数", "射门", "xG", "SOT", "big chance", "大机会")),
        "射手/创造者/首发伤停": any(k in text for k in ("射手", "前锋", "创造", "核心", "主力", "首发", "伤停", "停赛", "set-piece", "定位球")),
        "球风克制/比赛状态": any(k in text for k in ("克制", "防反", "反击", "压迫", "控球", "低位", "转换", "节奏", "追分", "领先", "降速")),
        "进球时间分布/领先后策略": any(k in text for k in ("上半场", "下半场", "早球", "晚球", "终端", "尾部", "领先后", "继续进攻", "防守反击")),
        "历史交锋/可比样本": any(k in text for k in ("历史", "交锋", "H2H", "同档", "可比", "样本")),
        "盘口价格确认": matched_odds or any(k in text for k in ("Titan007", "开 ", "即 ", "盘口", "水位", "赔率", "HK", "Polymarket", "PM")),
    }
    mandatory = ["近5-10场进球/射门", "射手/创造者/首发伤停", "球风克制/比赛状态", "盘口价格确认"]
    passed = [name for name, ok in checks.items() if ok]
    missing = [name for name, ok in checks.items() if not ok]
    if len(passed) >= 4 and all(checks[name] for name in mandatory):
        status = "进球模型已通过"
    else:
        status = "证据不足-无下注/仅观察"
    detail = f"通过：{'、'.join(passed) if passed else '无'}；缺口：{'、'.join(missing) if missing else '无'}"
    return status, detail


def data_completeness_audit(
    row: dict[str, str],
    matched_odds: bool,
    detail: dict[str, str] | None = None,
    odds_info: dict[str, object] | None = None,
) -> tuple[str, str]:
    present: list[str] = []
    missing: list[str] = []
    if matched_odds:
        present.append("赛程/比分")
    else:
        missing.append("赛程/比分匹配")
    odds_info = odds_info or {}
    market_checks = [
        ("亚盘", bool(odds_info.get("ah_ok"))),
        ("欧赔", bool(odds_info.get("euro_ok"))),
        ("大小球", bool(odds_info.get("total_ok"))),
    ]
    for label, ok in market_checks:
        if ok:
            present.append(label)
        else:
            missing.append(label)
    detail = detail or {}
    checks = [
        ("伤停", detail_status(detail, "injury_ok")),
        ("首发", detail_status(detail, "lineup_ok")),
        ("近5场", bool(detail.get("recent_form_summary"))),
        ("H2H", bool(detail.get("h2h_summary"))),
        ("赢盘/输盘记录", detail_status(detail, "handicap_record_ok")),
    ]
    for label, ok in checks:
        if ok:
            present.append(label)
        else:
            missing.append(label)
    missing.extend(["BTTS/二级盘口", "PM/必发资金流", "公共分析观点"])
    if bool(odds_info.get("ah_ok")) and bool(odds_info.get("euro_ok")) and any(ok for _label, ok in checks):
        status = "亚盘/欧赔快照+球探详情已接入；资金流/二级盘口仍缺"
    elif bool(odds_info.get("any_odds")) and any(ok for _label, ok in checks):
        status = "部分赔率快照+球探详情已接入；缺口市场不显示"
    elif bool(odds_info.get("any_odds")):
        status = "部分赔率快照已接入；基本面详情未接入"
    else:
        status = "核心赔率与基本面均未完整接入"
    detail = f"已接入：{'、'.join(present) if present else '无'}；缺口：{'、'.join(missing)}"
    return status, detail


def asian_intent_candidate(row: dict[str, str] | None) -> str:
    if not row:
        return "亚盘意图候选：缺亚盘/欧赔快照，不能判断。"

    ah_open = safe_float(row.get("ah_full_open_line_or_draw", ""))
    ah_now = safe_float(row.get("ah_full_current_line_or_draw", ""))
    home_water = safe_float(row.get("ah_full_current_home_or_over", ""))
    away_water = safe_float(row.get("ah_full_current_away_or_under", ""))
    euro_home_open = safe_float(row.get("euro_full_open_home_or_over", ""))
    euro_away_open = safe_float(row.get("euro_full_open_away_or_under", ""))
    euro_home_now = safe_float(row.get("euro_full_current_home_or_over", ""))
    euro_away_now = safe_float(row.get("euro_full_current_away_or_under", ""))
    if None in (ah_open, ah_now, home_water, away_water):
        return "亚盘意图候选：亚盘线/两边水位不完整，不能判断。"

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

    candidates: list[str]
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

    return (
        f"亚盘意图候选：{' / '.join(candidates)}（低证据）。"
        f"依据：{fav}，{line_state}，上盘水位{fav_water:.2f}，下盘水位{under_water:.2f}，{euro_state}。"
        "缺伤停、首发、近5场、H2H、PM/必发资金流，不能定论/不能下注。"
    )


def asian_upper_side(row: dict[str, str]) -> str:
    ah_now = safe_float(row.get("ah_full_current_line_or_draw", ""))
    home_water = safe_float(row.get("ah_full_current_home_or_over", ""))
    away_water = safe_float(row.get("ah_full_current_away_or_under", ""))
    euro_home_now = safe_float(row.get("euro_full_current_home_or_over", ""))
    euro_away_now = safe_float(row.get("euro_full_current_away_or_under", ""))
    if ah_now is None:
        return ""
    if ah_now > 0:
        return "home"
    if ah_now < 0:
        return "away"
    if euro_home_now and euro_away_now:
        if euro_home_now < euro_away_now:
            return "home"
        if euro_away_now < euro_home_now:
            return "away"
    if home_water is not None and away_water is not None and abs(home_water - away_water) >= 0.05:
        return "home" if home_water <= away_water else "away"
    return ""


def intent_team_fields(row: dict[str, str], tag: str) -> dict[str, str]:
    home_team = translate_text(row.get("home_cn", ""))
    away_team = translate_text(row.get("away_cn", ""))
    upper_side = asian_upper_side(row)
    if upper_side == "home":
        upper_team = home_team
        lower_team = away_team
    elif upper_side == "away":
        upper_team = away_team
        lower_team = home_team
    else:
        upper_team = ""
        lower_team = ""

    forward_side = intent_tag_side(tag)
    if forward_side == "upper":
        forward_team = upper_team
        reverse_team = lower_team
    elif forward_side == "lower":
        forward_team = lower_team
        reverse_team = upper_team
    else:
        forward_team = ""
        reverse_team = ""

    return {
        "intent_upper_side": upper_side,
        "intent_upper_team": upper_team,
        "intent_lower_team": lower_team,
        "intent_forward_side": forward_side,
        "intent_forward_team": forward_team,
        "intent_reverse_team": reverse_team,
    }


def compute_stats(rows: list[dict[str, str]]) -> dict[str, object]:
    settled = [r for r in rows if classify_action(r) in {"赢", "输", "走"}]
    wins = sum(1 for r in settled if classify_action(r) == "赢")
    losses = sum(1 for r in settled if classify_action(r) == "输")
    pushes = sum(1 for r in settled if classify_action(r) == "走")
    pnl = sum(safe_float(r.get("模拟盈亏单位", "")) or 0 for r in settled)

    by_market: dict[str, list[int | float]] = defaultdict(lambda: [0, 0, 0, 0.0])
    by_league: dict[str, list[int | float]] = defaultdict(lambda: [0, 0, 0, 0.0])
    for r in settled:
        action = classify_action(r)
        pnl_v = safe_float(r.get("模拟盈亏单位", "")) or 0
        for bucket, key in ((by_market, market_from_text(r)), (by_league, r.get("赛事", "未分类"))):
            if action == "赢":
                bucket[key][0] += 1
            elif action == "输":
                bucket[key][1] += 1
            else:
                bucket[key][2] += 1
            bucket[key][3] += pnl_v

    def table(src: dict[str, list[int | float]]) -> list[dict[str, object]]:
        out = []
        for key, vals in src.items():
            w, l, p, v = vals
            n = int(w) + int(l)
            out.append(
                {
                    "name": key,
                    "wins": int(w),
                    "losses": int(l),
                    "pushes": int(p),
                    "rate": (float(w) / n) if n else None,
                    "pnl": round(float(v), 2),
                }
            )
        return sorted(out, key=lambda x: (x["rate"] or 0, x["wins"] + x["losses"]), reverse=True)

    return {
        "settled": len(settled),
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "win_rate": wins / (wins + losses) if wins + losses else None,
        "pnl": round(pnl, 2),
        "by_market": table(by_market),
        "by_league": table(by_league)[:12],
        "intent_matrix": load_intent_matrix(),
    }


def titan_lookup() -> dict[str, dict[str, str]]:
    out = {}
    files = sorted(RAW_TITAN.glob("**/*_titan007_odds_snapshot.csv"), key=lambda p: p.stat().st_mtime)
    for path in files:
        for row in read_csv(path):
            key = f"{row.get('home_cn','')} vs {row.get('away_cn','')}"
            match_id = (row.get("match_id") or "").strip()
            if key.strip() != "vs":
                out[key] = row
                out[f"match:{key}"] = row
            if match_id:
                out[f"id:{match_id}"] = row
    return out


def detail_lookup() -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for path in sorted(DETAIL_LEDGER.glob("titan007_detail_*.csv")):
        for row in read_csv(path):
            match_id = (row.get("match_id") or "").strip()
            match = (row.get("比赛") or "").strip()
            if match_id:
                out[match_id] = row
            if match:
                out[match] = row
    return out


def compact(value: str, limit: int = 180) -> str:
    text = " ".join((value or "").split())
    if not text:
        return ""
    return text if len(text) <= limit else text[:limit] + "..."


def detail_status(detail: dict[str, str], key: str, text_key: str | None = None) -> bool:
    if not detail:
        return False
    if detail.get(key) == "1":
        return True
    return bool(text_key and detail.get(text_key))


def detail_lineup(detail: dict[str, str]) -> str:
    if not detail:
        return "伤停/首发未核"
    if detail.get("lineup_ok") != "1":
        return "首发未接入/待赛前1小时核"
    return (
        f"球探首发已接入：主队阵型 {detail.get('home_formation','')}，"
        f"客队阵型 {detail.get('away_formation','')}；"
        f"主队首发 {compact(detail.get('home_starting',''), 140)}；"
        f"客队首发 {compact(detail.get('away_starting',''), 140)}"
    )


def detail_injury(detail: dict[str, str]) -> str:
    if not detail:
        return "伤停未接入/待核"
    home = compact(detail.get("home_injuries", ""), 130)
    away = compact(detail.get("away_injuries", ""), 130)
    if home or away:
        return f"球探伤停：主队[{home or '无结构化伤停'}]；客队[{away or '无结构化伤停'}]"
    return "球探Lineup页已抓取；未发现结构化伤停名单/需临场复核"


def has_values(row: dict[str, str], keys: list[str]) -> bool:
    return all((row.get(key, "") or "").strip() not in ("", "//") for key in keys)


def odds_triplet_text(row: dict[str, str], prefix: str, missing_label: str) -> tuple[str, bool]:
    open_keys = [
        f"{prefix}_full_open_home_or_over",
        f"{prefix}_full_open_line_or_draw",
        f"{prefix}_full_open_away_or_under",
    ]
    current_keys = [
        f"{prefix}_full_current_home_or_over",
        f"{prefix}_full_current_line_or_draw",
        f"{prefix}_full_current_away_or_under",
    ]
    current_ok = has_values(row, current_keys)
    if not current_ok:
        return f"未接入：{missing_label}", False
    open_text = (
        "/".join((row.get(key, "") or "").strip() for key in open_keys)
        if has_values(row, open_keys)
        else "未接入"
    )
    current_text = "/".join((row.get(key, "") or "").strip() for key in current_keys)
    return f"开 {open_text} → 即 {current_text}", True


def odds_summary(
    match: str,
    odds: dict[str, dict[str, str]],
    final_scores: dict[str, dict[str, str]] | None = None,
    ledger_row: dict[str, str] | None = None,
) -> dict[str, str]:
    final_scores = final_scores or {}
    match_id = match_id_from_row(ledger_row or {})
    row = (
        (odds.get(f"id:{match_id}") if match_id else None)
        or odds.get(f"match:{match}")
        or odds.get(match)
    )
    final_score = (
        (final_scores.get(f"id:{match_id}") if match_id else None)
        or final_scores.get(f"match:{match}")
        or {}
    )
    if not row:
        if final_score:
            return {
                "time": final_score.get("time", "未匹配"),
                "ah": "未匹配",
                "euro": "未匹配",
                "euro_devig": "欧赔未匹配",
                "total": "未匹配",
                "asian_intent": "亚盘意图候选：缺亚盘/欧赔快照，不能判断。",
                "intent_line_bucket": "",
                "intent_tag": "",
                "intent_upper_side": "",
                "intent_upper_team": "",
                "intent_lower_team": "",
                "intent_forward_side": "",
                "intent_forward_team": "",
            "intent_reverse_team": "",
            "score": final_score.get("score", "未匹配"),
            "state": final_score.get("state", "-1"),
            "rank": "未匹配",
            "match_id": match_id or final_score.get("match_id", ""),
            "ah_ok": False,
            "euro_ok": False,
            "total_ok": False,
            "any_odds": False,
            "odds_status": "赔率未匹配",
        }
        return {
            "time": "未匹配",
            "ah": "未匹配",
            "euro": "未匹配",
            "euro_devig": "欧赔未匹配",
            "total": "未匹配",
            "asian_intent": "亚盘意图候选：缺亚盘/欧赔快照，不能判断。",
            "intent_line_bucket": "",
            "intent_tag": "",
            "intent_upper_side": "",
            "intent_upper_team": "",
            "intent_lower_team": "",
            "intent_forward_side": "",
            "intent_forward_team": "",
            "intent_reverse_team": "",
            "score": "未匹配",
            "state": "未匹配",
            "rank": "未匹配",
            "match_id": "",
            "ah_ok": False,
            "euro_ok": False,
            "total_ok": False,
            "any_odds": False,
            "odds_status": "赔率未匹配",
        }
    ah, ah_ok = odds_triplet_text(row, "ah", "亚盘线/两边水位缺失")
    euro, euro_ok = odds_triplet_text(row, "euro", "欧赔主/平/客缺失")
    total, total_ok = odds_triplet_text(row, "total", "大小球线/两边水位缺失")
    any_odds = ah_ok or euro_ok or total_ok
    odds_status = (
        "Titan007赔率已匹配"
        if ah_ok and euro_ok and total_ok
        else ("Titan007部分赔率已匹配" if any_odds else "赔率未匹配")
    )
    euro_devig = "欧赔缺失-未去水"
    try:
        eh = float(row.get("euro_full_current_home_or_over", "") or "0")
        ed = float(row.get("euro_full_current_line_or_draw", "") or "0")
        ea = float(row.get("euro_full_current_away_or_under", "") or "0")
        if min(eh, ed, ea) > 1:
            inv = [1 / eh, 1 / ed, 1 / ea]
            overround = sum(inv)
            fair = [v / overround for v in inv]
            euro_devig = f"主{fair[0]:.1%} / 平{fair[1]:.1%} / 客{fair[2]:.1%}；返还率{1 / overround:.1%}"
    except Exception:
        euro_devig = "欧赔缺失-未去水"
    intent_text = asian_intent_candidate(row)
    intent_tag = normalize_intent_tag(intent_text)
    team_fields = intent_team_fields(row, intent_tag)
    current_line = safe_float(row.get("ah_full_current_line_or_draw", ""))
    score = f"{row.get('home_score','')}-{row.get('away_score','')}"
    state = row.get("state", "")
    if final_score:
        score = final_score.get("score", score)
        state = final_score.get("state", state or "-1")
    return {
        "time": f"2026-{row.get('bj_time','')}",
        "ah": ah,
        "euro": euro,
        "euro_devig": euro_devig,
        "total": total,
        "asian_intent": intent_text,
        "intent_line_bucket": asian_line_label(current_line),
        "intent_tag": intent_tag,
        **team_fields,
        "score": score,
        "state": state,
        "rank": f"{row.get('home_rank_or_stage','')}-{row.get('away_rank_or_stage','')}",
        "match_id": row.get("match_id", ""),
        "ah_ok": ah_ok,
        "euro_ok": euro_ok,
        "total_ok": total_ok,
        "any_odds": any_odds,
        "odds_status": odds_status,
    }


def build_rows() -> tuple[list[dict[str, object]], dict[str, object]]:
    ledger_rows = read_csv(LEDGER)
    today_rows = ledger_rows
    odds = titan_lookup()
    final_scores = load_titan_over_scores()
    details = detail_lookup()
    cards = []
    for r in today_rows:
        match = r.get("比赛", "")
        o = odds_summary(match, odds, final_scores, r)
        detail = details.get(o.get("match_id", "")) or details.get(match) or {}
        matched = o["time"] != "未匹配"
        date = r.get("日期", "")
        result = r.get("赛果", "")
        shown_match = translate_text(match)
        shown_time = display_time(o["time"], matched, date)
        shown_score = display_score(o["score"], result, matched)
        shown_status = titan_state_label(o["state"], matched, result)
        decimal = extract_decimal(r.get("模拟盘口/价格", ""))
        status = classify_action(r)
        goal_status, goal_detail = goal_model_audit(r, matched)
        data_status, data_detail = data_completeness_audit(r, matched, detail, o)
        if "盘口快照" in r.get("市场框架", "") or "五板证据缺失" in r.get("错误类型", ""):
            final_action = "盘口快照/不形成模拟"
        elif "盘口缺失" in r.get("市场框架", "") or "不形成模拟" in r.get("市场框架", "") or "盘口未读取" in r.get("错误类型", ""):
            final_action = "盘口缺失/真实不投"
        elif "纸面验证" in r.get("错误类型", "") or "纸面模拟" in r.get("市场框架", ""):
            final_action = "纸面模拟/真实不投"
        elif r.get("是否主单", "") == "是":
            final_action = "主单候选"
        else:
            final_action = "仅模拟/非主单"
        cards.append(
            {
                "date": date,
                "league": translate_text(r.get("赛事", "")),
                "match": shown_match,
                "display_match": shown_match,
                "time": o["time"],
                "display_time": shown_time,
                "score": o["score"],
                "display_score": shown_score,
                "state": o["state"],
                "state_label": titan_state_name(o["state"]),
                "display_status": shown_status,
                "matched_odds": matched,
                "rank": o["rank"],
                "market": market_from_text(r),
                "pick": translate_text(r.get("模拟方向", "")),
                "price": translate_text(r.get("模拟盘口/价格", "")),
                "decimal": decimal,
                "ah": o["ah"],
                "euro": o["euro"],
                "euro_devig": o["euro_devig"],
                "total": o["total"],
                "ah_ok": o["ah_ok"],
                "euro_ok": o["euro_ok"],
                "total_ok": o["total_ok"],
                "any_odds": o["any_odds"],
                "odds_status": o["odds_status"],
                "asian_intent": o["asian_intent"],
                "intent_line_bucket": o["intent_line_bucket"],
                "intent_tag": o["intent_tag"],
                "intent_upper_side": o["intent_upper_side"],
                "intent_upper_team": o["intent_upper_team"],
                "intent_lower_team": o["intent_lower_team"],
                "intent_forward_side": o["intent_forward_side"],
                "intent_forward_team": o["intent_forward_team"],
                "intent_reverse_team": o["intent_reverse_team"],
                "injury": translate_text(detail_injury(detail)),
                "lineup": translate_text(detail_lineup(detail)),
                "pull": clean_missing_odds_text(translate_text(r.get("盘口倾向", ""))),
                "flow": translate_text(r.get("Polymarket/交易所情绪", "") or "缺失"),
                "liquidity": translate_text(r.get("流动性", "")),
                "purpose": clean_missing_odds_text(translate_text(r.get("模拟目的", ""))),
                "main": r.get("是否主单", ""),
                "price_source": o["odds_status"],
                "settlement": "90分钟常规时间，除非盘口/合约另有明确说明",
                "evidence_status": data_status,
                "final_action": final_action,
                "goal_model_status": goal_status,
                "goal_model_detail": goal_detail,
                "data_complete_status": data_status,
                "data_complete_detail": data_detail,
                "schedule_source": "Titan007/球探已接入" if o["time"] != "未匹配" else "账本原始记录；待球探匹配",
                "odds_source": o["odds_status"],
                "btts_source": "未接入/待核",
                "h2h_source": f"球探Analysis：{compact(detail.get('h2h_summary',''), 240)}" if detail.get("h2h_summary") else "未接入/待核：待接球探/Flashscore/SofaScore/FotMob",
                "form_source": f"球探Analysis：{compact(detail.get('recent_form_summary',''), 260)}" if detail.get("recent_form_summary") else "未接入/待核：待接近5场和主客场拆分",
                "handicap_record_source": "球探Analysis历史盘口片段已抓取，待完全归一化" if detail.get("handicap_record_ok") == "1" else "未接入/待核：需历史盘口收盘线",
                "lineup_source": f"球探Lineup：{detail.get('lineup_url','')}" if detail.get("lineup_ok") == "1" else "伤停/首发未核",
                "motivation_source": "账本模拟目的/盘口拉力记录",
                "flow_source": "PM/必发缺失；Titan007仅作盘口价格流" if not r.get("Polymarket/交易所情绪", "") or "缺" in r.get("Polymarket/交易所情绪", "") else r.get("Polymarket/交易所情绪", ""),
                "analyst_source": "未接入/待核：待公共博主/盘口观点交叉验证",
                "result": translate_text(result),
                "pnl": r.get("模拟盈亏单位", ""),
                "status": status,
                "grade": r.get("过程评级", ""),
                "error": r.get("错误类型", ""),
                "update": translate_text(r.get("模型更新", "")),
            }
        )
    cards.sort(key=lambda r: (not r["matched_odds"], str(r["time"]), str(r["league"]), str(r["match"])))
    return cards, compute_stats(ledger_rows)


def js_data(obj: object) -> str:
    return json.dumps(obj, ensure_ascii=False)


def html_doc(cards: list[dict[str, object]], stats: dict[str, object]) -> str:
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>足球盘口模拟仪表盘</title>
  <style>
    :root {{
      color-scheme: dark;
      --bg: #07111d;
      --panel: #101c2b;
      --panel-2: #142338;
      --line: #263b55;
      --text: #eef5ff;
      --muted: #8ea8c5;
      --blue: #2f80ed;
      --cyan: #15b8d4;
      --green: #31c46d;
      --red: #ff5c6c;
      --amber: #f5c542;
      --purple: #9b7cff;
      --shadow: 0 16px 40px rgba(0,0,0,.28);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: radial-gradient(circle at top left, rgba(21,184,212,.10), transparent 32rem), var(--bg);
      color: var(--text);
      font-family: "Microsoft YaHei", "PingFang SC", "Segoe UI", Arial, sans-serif;
      letter-spacing: 0;
    }}
    .app {{ min-height: 100vh; }}
    .topbar {{
      position: sticky;
      top: 0;
      z-index: 5;
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 16px;
      align-items: center;
      padding: 16px 24px;
      background: rgba(7,17,29,.92);
      border-bottom: 1px solid var(--line);
      backdrop-filter: blur(10px);
    }}
    h1 {{ margin: 0; font-size: 22px; line-height: 1.2; }}
    .subtitle {{ color: var(--muted); margin-top: 5px; font-size: 13px; }}
    .source-pill {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 8px 12px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: var(--panel);
      color: var(--muted);
      font-size: 13px;
      white-space: nowrap;
    }}
    main {{ padding: 22px 24px 36px; max-width: 1540px; margin: 0 auto; }}
    .metrics {{
      display: grid;
      grid-template-columns: repeat(5, minmax(0, 1fr));
      gap: 12px;
      margin-bottom: 16px;
    }}
    .metric {{
      background: linear-gradient(180deg, var(--panel-2), var(--panel));
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
      box-shadow: var(--shadow);
      min-height: 90px;
    }}
    .metric .label {{ color: var(--muted); font-size: 13px; }}
    .metric .value {{ margin-top: 10px; font-size: 28px; font-weight: 800; }}
    .metric .hint {{ margin-top: 6px; color: var(--muted); font-size: 12px; }}
    .toolbar {{
      display: grid;
      grid-template-columns: 1.4fr repeat(3, minmax(150px, .6fr));
      gap: 10px;
      margin: 18px 0;
    }}
    input, select {{
      width: 100%;
      border: 1px solid var(--line);
      background: #0c1725;
      color: var(--text);
      border-radius: 6px;
      padding: 11px 12px;
      font-size: 14px;
      outline: none;
    }}
    .layout {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) 340px;
      gap: 16px;
      align-items: start;
    }}
    .summary-board {{
      margin: 16px 0 18px;
      border: 1px solid var(--line);
      background: rgba(16,28,43,.94);
      border-radius: 8px;
      overflow: hidden;
      box-shadow: var(--shadow);
    }}
    .summary-scroll {{ overflow-x: auto; }}
    .summary-table {{
      width: 100%;
      min-width: 1180px;
      border-collapse: collapse;
      font-size: 13px;
    }}
    .summary-table th, .summary-table td {{
      padding: 10px 9px;
      border-bottom: 1px solid var(--line);
      vertical-align: top;
      text-align: left;
      line-height: 1.45;
    }}
    .summary-table th {{
      color: #b9d7ff;
      background: #132236;
      font-weight: 800;
      position: sticky;
      top: 0;
    }}
    .summary-table tr:hover td {{ background: rgba(47,128,237,.08); }}
    .summary-match {{ font-weight: 800; color: var(--text); min-width: 170px; }}
    .summary-pick {{ color: var(--amber); font-weight: 800; min-width: 150px; }}
    .summary-analysis {{ min-width: 260px; color: #d7e6f8; }}
    .odds-box {{
      display: grid;
      gap: 4px;
      min-width: 170px;
      padding: 8px;
      border: 1px solid #31577d;
      border-radius: 6px;
      background: #0b1a2a;
      color: #e8f3ff;
      font-size: 12px;
      line-height: 1.35;
    }}
    .odds-box .odds-label {{
      color: #8fb8df;
      font-weight: 800;
      letter-spacing: .02em;
    }}
    .odds-missing {{
      border-color: #513244;
      color: #c6a7b4;
      background: #1a111b;
    }}
    .secondary-board {{
      margin-top: 14px;
      opacity: .92;
    }}
    .muted {{ color: var(--muted); }}
    .board {{
      border: 1px solid var(--line);
      background: rgba(16,28,43,.94);
      border-radius: 8px;
      overflow: hidden;
      box-shadow: var(--shadow);
    }}
    .board-head {{
      display: grid;
      grid-template-columns: 1fr auto;
      align-items: center;
      gap: 10px;
      padding: 13px 14px;
      border-bottom: 1px solid var(--line);
      background: #132236;
    }}
    .board-title {{ font-weight: 800; }}
    .count {{ color: var(--muted); font-size: 13px; }}
    .cards {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
      padding: 12px;
    }}
    .match-card {{
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #0c1725;
      overflow: hidden;
    }}
    .match-top {{
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 8px;
      padding: 12px;
      border-bottom: 1px solid var(--line);
      background: #101d2e;
    }}
    .teams {{ font-size: 16px; font-weight: 800; line-height: 1.35; }}
    .meta {{ margin-top: 5px; color: var(--muted); font-size: 12px; }}
    .badge {{
      display: inline-flex;
      align-items: center;
      height: 28px;
      padding: 0 9px;
      border-radius: 5px;
      font-size: 12px;
      font-weight: 800;
      border: 1px solid rgba(255,255,255,.08);
      white-space: nowrap;
    }}
    .b-wait {{ background: rgba(47,128,237,.16); color: #9fc9ff; }}
    .b-win {{ background: rgba(49,196,109,.16); color: #7df0a5; }}
    .b-loss {{ background: rgba(255,92,108,.16); color: #ff9ba5; }}
    .b-push {{ background: rgba(245,197,66,.16); color: #ffe08b; }}
    .match-body {{ padding: 12px; display: grid; gap: 10px; }}
    .pick-row {{
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 8px;
      align-items: center;
      padding: 10px;
      background: #132236;
      border-radius: 6px;
      border: 1px solid var(--line);
    }}
    .pick-main {{ font-weight: 800; color: #d8ecff; }}
    .price {{ color: var(--amber); font-weight: 800; }}
    .info-grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; }}
    .info {{
      min-height: 76px;
      padding: 9px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #091423;
    }}
    .info .k {{ color: var(--muted); font-size: 12px; margin-bottom: 6px; }}
    .info .v {{ font-size: 13px; line-height: 1.45; overflow-wrap: anywhere; }}
    .long-info {{
      padding: 10px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #091423;
      font-size: 13px;
      line-height: 1.55;
    }}
    .long-info strong {{ color: #b9d7ff; }}
    .side {{ display: grid; gap: 16px; }}
    .rank-table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
    .rank-table th, .rank-table td {{ padding: 9px 8px; border-bottom: 1px solid var(--line); text-align: left; }}
    .rank-table th {{ color: var(--muted); font-weight: 700; }}
    .rate-good {{ color: var(--green); font-weight: 800; }}
    .rate-bad {{ color: var(--red); font-weight: 800; }}
    .empty {{ padding: 24px; color: var(--muted); text-align: center; }}
    @media (max-width: 1180px) {{
      .metrics {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .toolbar {{ grid-template-columns: 1fr 1fr; }}
      .layout {{ grid-template-columns: 1fr; }}
    }}
    @media (max-width: 760px) {{
      .topbar {{ grid-template-columns: 1fr; padding: 14px; }}
      main {{ padding: 14px; }}
      .metrics, .cards, .info-grid, .toolbar {{ grid-template-columns: 1fr; }}
      h1 {{ font-size: 19px; }}
    }}
  </style>
</head>
<body>
<div class="app">
  <header class="topbar">
    <div>
      <h1>足球盘口模拟仪表盘</h1>
      <div class="subtitle">今日模拟、Titan007赔率、基本面核验状态、盘口拉力、资金流状态与历史盈亏</div>
    </div>
    <div class="source-pill">更新时间：{html.escape(now)} ｜ 数据目录：D:\\codex</div>
  </header>
  <main>
    <section class="metrics">
      <div class="metric"><div class="label">总已结算模拟</div><div class="value" id="m-settled"></div><div class="hint">不含待赛</div></div>
      <div class="metric"><div class="label">胜率</div><div class="value" id="m-rate"></div><div class="hint">扣除走盘</div></div>
      <div class="metric"><div class="label">赢 / 输 / 走</div><div class="value" id="m-wlp"></div><div class="hint">历史总账本</div></div>
      <div class="metric"><div class="label">累计盈亏单位</div><div class="value" id="m-pnl"></div><div class="hint">按账本模拟单位</div></div>
      <div class="metric"><div class="label">中文赔率匹配</div><div class="value" id="m-matched"></div><div class="hint" id="m-today-hint">Titan007已匹配</div></div>
    </section>

    <section class="summary-board">
      <div class="board-head">
        <div class="board-title">中文赔率已匹配模拟</div>
        <div class="count" id="summary-count">具体比赛、盘口与分析</div>
      </div>
      <div class="summary-scroll">
        <table class="summary-table">
          <thead>
            <tr>
              <th>时间/联赛</th>
              <th>比赛</th>
              <th>模拟盘口</th>
              <th>亚盘</th>
              <th>欧赔</th>
              <th>大小球</th>
              <th>伤停/首发</th>
              <th>盘口拉力及投注方向分析</th>
              <th>结论</th>
            </tr>
          </thead>
          <tbody id="summary-rows"></tbody>
        </table>
      </div>
    </section>

    <section class="summary-board secondary-board">
      <div class="board-head">
        <div class="board-title">未匹配/历史待核模拟</div>
        <div class="count" id="unmatched-count">待回填中文赔率</div>
      </div>
      <div class="summary-scroll">
        <table class="summary-table">
          <thead>
            <tr>
              <th>账本日期/联赛</th>
              <th>原始比赛名</th>
              <th>模拟盘口</th>
              <th>赔率状态</th>
              <th>盘口拉力及投注方向分析</th>
              <th>结论</th>
            </tr>
          </thead>
          <tbody id="unmatched-rows"></tbody>
        </table>
      </div>
    </section>

    <section class="toolbar">
      <input id="search" placeholder="搜索比赛、联赛、盘口、方向">
      <select id="league"></select>
      <select id="market"></select>
      <select id="status"></select>
    </section>

    <section class="layout">
      <div class="board">
        <div class="board-head">
          <div class="board-title">今日模拟明细</div>
          <div class="count" id="visible-count"></div>
        </div>
        <div class="cards" id="cards"></div>
      </div>
      <aside class="side">
        <div class="board">
          <div class="board-head"><div class="board-title">盘口类型胜率</div><div class="count">历史</div></div>
          <div id="market-stats"></div>
        </div>
        <div class="board">
          <div class="board-head"><div class="board-title">联赛胜率排行</div><div class="count">Top 12</div></div>
          <div id="league-stats"></div>
        </div>
      </aside>
    </section>
  </main>
</div>
<script>
const cardsData = {js_data(cards)};
const stats = {js_data(stats)};
const matchedRows = cardsData.filter(r => r.matched_odds);
const unmatchedRows = cardsData.filter(r => !r.matched_odds);

function pct(v) {{
  if (v === null || v === undefined) return "无";
  return (v * 100).toFixed(1) + "%";
}}

function statusClass(s) {{
  if (s === "赢") return "b-win";
  if (s === "输") return "b-loss";
  if (s === "走") return "b-push";
  return "b-wait";
}}

function uniqueOptions(key, label) {{
  const values = [...new Set(cardsData.map(x => x[key]).filter(Boolean))].sort();
  return `<option value="">${{label}}</option>` + values.map(v => `<option value="${{v}}">${{v}}</option>`).join("");
}}

function renderStats() {{
  document.getElementById("m-settled").textContent = stats.settled ?? 0;
  document.getElementById("m-rate").textContent = pct(stats.win_rate);
  document.getElementById("m-wlp").textContent = `${{stats.wins}}/${{stats.losses}}/${{stats.pushes}}`;
  document.getElementById("m-pnl").textContent = (stats.pnl > 0 ? "+" : "") + stats.pnl;
  document.getElementById("m-matched").textContent = matchedRows.length;
  document.getElementById("m-today-hint").textContent = `今日账本 ${{cardsData.length}} 场，待核 ${{unmatchedRows.length}} 场`;

  document.getElementById("market-stats").innerHTML = table(stats.by_market || []);
  document.getElementById("league-stats").innerHTML = table(stats.by_league || []);
}}

function table(rows) {{
  if (!rows.length) return '<div class="empty">暂无历史统计</div>';
  return `<table class="rank-table"><thead><tr><th>分类</th><th>胜负走</th><th>胜率</th><th>盈亏</th></tr></thead><tbody>` +
    rows.map(r => {{
      const cls = (r.rate || 0) >= .55 ? "rate-good" : ((r.rate || 0) < .45 ? "rate-bad" : "");
      const pnlCls = r.pnl >= 0 ? "rate-good" : "rate-bad";
      return `<tr><td>${{r.name}}</td><td>${{r.wins}}-${{r.losses}}-${{r.pushes}}</td><td class="${{cls}}">${{pct(r.rate)}}</td><td class="${{pnlCls}}">${{r.pnl > 0 ? "+" : ""}}${{r.pnl}}</td></tr>`;
    }}).join("") + `</tbody></table>`;
}}

function renderCards() {{
  const q = document.getElementById("search").value.trim().toLowerCase();
  const league = document.getElementById("league").value;
  const market = document.getElementById("market").value;
  const status = document.getElementById("status").value;
  const rows = cardsData.filter(r => {{
    const text = Object.values(r).join(" ").toLowerCase();
    return (!q || text.includes(q)) && (!league || r.league === league) && (!market || r.market === market) && (!status || r.status === status);
  }});
  document.getElementById("visible-count").textContent = `${{rows.length}} / ${{cardsData.length}}`;
  const wrap = document.getElementById("cards");
  if (!rows.length) {{
    wrap.innerHTML = '<div class="empty">没有匹配结果</div>';
    return;
  }}
  wrap.innerHTML = rows.map(r => `
    <article class="match-card">
      <div class="match-top">
        <div>
          <div class="teams">${{r.match}}</div>
          <div class="meta">${{r.league}} ｜ ${{r.time}} ｜ 排名/阶段 ${{r.rank}}</div>
        </div>
        <span class="badge ${{statusClass(r.status)}}">${{r.status}}</span>
      </div>
      <div class="match-body">
        <div class="pick-row">
          <div>
            <div class="pick-main">${{r.market}}：${{r.pick}}</div>
            <div class="meta">${{r.price}}</div>
          </div>
          <div class="price">${{r.decimal ? r.decimal.toFixed(2) : "无价"}}</div>
        </div>
        <div class="info-grid">
          <div class="info"><div class="k">亚盘</div><div class="v">${{r.ah}}</div></div>
          <div class="info"><div class="k">欧赔</div><div class="v">${{r.euro}}</div></div>
          <div class="info"><div class="k">大小球</div><div class="v">${{r.total}}</div></div>
        </div>
        <div class="info-grid">
          <div class="info"><div class="k">伤停/首发</div><div class="v">${{r.lineup}}<br>${{r.injury}}</div></div>
          <div class="info"><div class="k">资金流/流动性</div><div class="v">真实成交：${{r.flow}}<br>${{r.liquidity}}</div></div>
          <div class="info"><div class="k">历史结算</div><div class="v">赛果：${{r.result}}<br>盈亏：${{r.pnl}} ｜ 评级：${{r.grade}}</div></div>
        </div>
        <div class="long-info"><strong>盘口拉力及投注方向：</strong>${{r.pull}}</div>
        <div class="long-info"><strong>模拟目的：</strong>${{r.purpose}}<br><strong>复盘更新：</strong>${{r.update}}</div>
      </div>
    </article>
  `).join("");
}}

function shortText(v, n) {{
  v = String(v || "");
  return v.length > n ? v.slice(0, n - 1) + "…" : v;
}}

function oddsBox(label, value) {{
  const missing = String(value || "").includes("未匹配");
  return `<div class="odds-box ${{missing ? "odds-missing" : ""}}"><span class="odds-label">${{label}}</span><span>${{value || "未匹配"}}</span></div>`;
}}

function renderSummary() {{
  const tbody = document.getElementById("summary-rows");
  document.getElementById("summary-count").textContent = `${{matchedRows.length}} 场已显示中文名和赔率`;
  if (!matchedRows.length) {{
    tbody.innerHTML = '<tr><td colspan="9" class="empty">今天暂无模拟</td></tr>';
    return;
  }}
  tbody.innerHTML = matchedRows.map(r => `
    <tr>
      <td><strong>${{r.time}}</strong><br><span class="muted">${{r.league}}</span></td>
      <td class="summary-match">${{r.match}}<br><span class="muted">排名/阶段：${{r.rank}}</span></td>
      <td class="summary-pick">${{r.pick}}<br><span class="muted">${{r.price}}</span></td>
      <td>${{oddsBox("亚盘开盘 → 即时", r.ah)}}</td>
      <td>${{oddsBox("欧赔开盘 → 即时", r.euro)}}</td>
      <td>${{oddsBox("大小球开盘 → 即时", r.total)}}</td>
      <td>${{r.lineup}}<br><span class="muted">${{shortText(r.injury, 58)}}</span></td>
      <td class="summary-analysis">${{shortText(r.pull, 130)}}<br><span class="muted">资金流：${{r.flow}}；${{r.liquidity}}</span></td>
      <td><span class="badge ${{statusClass(r.status)}}">${{r.status}}</span><br><span class="muted">赛果：${{r.result}}｜盈亏：${{r.pnl}}</span></td>
    </tr>
  `).join("");

  const ub = document.getElementById("unmatched-rows");
  document.getElementById("unmatched-count").textContent = `${{unmatchedRows.length}} 场未匹配 Titan007 中文赔率`;
  if (!unmatchedRows.length) {{
    ub.innerHTML = '<tr><td colspan="6" class="empty">没有未匹配记录</td></tr>';
    return;
  }}
  ub.innerHTML = unmatchedRows.map(r => `
    <tr>
      <td><strong>${{r.date}}</strong><br><span class="muted">${{r.league}}</span></td>
      <td class="summary-match">${{r.match}}</td>
      <td class="summary-pick">${{r.pick}}<br><span class="muted">${{r.price}}</span></td>
      <td>${{oddsBox("赔率状态", "未匹配：待回填中文比赛名/赔率")}}</td>
      <td class="summary-analysis">${{shortText(r.pull, 120)}}<br><span class="muted">资金流：${{r.flow}}；${{r.liquidity}}</span></td>
      <td><span class="badge ${{statusClass(r.status)}}">${{r.status}}</span><br><span class="muted">赛果：${{r.result}}｜盈亏：${{r.pnl}}</span></td>
    </tr>
  `).join("");
}}

function init() {{
  document.getElementById("league").innerHTML = uniqueOptions("league", "全部联赛");
  document.getElementById("market").innerHTML = uniqueOptions("market", "全部盘口");
  document.getElementById("status").innerHTML = uniqueOptions("status", "全部状态");
  ["search", "league", "market", "status"].forEach(id => document.getElementById(id).addEventListener("input", renderCards));
  renderStats();
  renderSummary();
  renderCards();
}}
init();
</script>
</body>
</html>"""


def html_doc_v2(cards: list[dict[str, object]], stats: dict[str, object], backtest: dict[str, object]) -> str:
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    default_date = TODAY.isoformat()
    backtest_box = render_sequential_backtest_box(backtest)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>足球盘口模拟操盘台</title>
  <style>
    :root {{
      color-scheme: light;
      --page: #d9e8f6;
      --line: #8eb1d0;
      --line-soft: #c1d6e8;
      --head: #1f69a7;
      --head-2: #2f7fbd;
      --subhead: #eaf4fc;
      --panel: #ffffff;
      --panel-2: #f6fbff;
      --text: #17324d;
      --muted: #607a93;
      --red: #d74444;
      --green: #138a48;
      --blue: #095fa6;
      --amber: #b36b00;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--page);
      color: var(--text);
      font-family: "Microsoft YaHei", "PingFang SC", Arial, sans-serif;
      font-size: 13px;
    }}
    .topbar {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 16px;
      padding: 10px 14px;
      background: linear-gradient(180deg, var(--head-2), var(--head));
      color: white;
      border-bottom: 2px solid #174e7e;
    }}
    h1 {{ margin: 0; font-size: 18px; line-height: 1.2; }}
    .topbar .sub {{ color: #d8ecff; margin-top: 3px; }}
    .source {{ color: #eaf6ff; white-space: nowrap; }}
    .pattern-dock {{
      display: grid;
      grid-template-columns: minmax(0, 1.35fr) minmax(330px, .72fr) minmax(330px, .72fr);
      gap: 10px;
      padding: 10px 10px 0;
    }}
    .pattern-card {{
      min-width: 0;
      border: 1px solid var(--line);
      background: var(--panel);
    }}
    .pattern-body {{
      max-height: 218px;
      overflow: auto;
      background: #fff;
    }}
    .pattern-note {{
      padding: 6px 9px;
      color: var(--muted);
      background: #f2f8fe;
      border-top: 1px solid var(--line-soft);
      font-size: 12px;
    }}
    .backtest-dock {{
      padding: 10px 10px 0;
    }}
    .backtest-card {{
      width: 100%;
    }}
    .backtest-body {{
      max-height: 280px;
      padding: 8px;
    }}
    .backtest-metrics {{
      display: grid;
      grid-template-columns: repeat(6, minmax(0, 1fr));
      gap: 8px;
      margin-bottom: 8px;
    }}
    .backtest-metrics div {{
      border: 1px solid var(--line-soft);
      background: #f5fbff;
      padding: 7px;
    }}
    .backtest-metrics b {{
      display: block;
      color: var(--blue);
      font-size: 16px;
      line-height: 1.2;
    }}
    .backtest-metrics span {{
      display: block;
      margin-top: 3px;
      color: var(--muted);
      font-size: 12px;
    }}
    .backtest-note {{
      padding: 6px 7px;
      border: 1px solid #f0d6a8;
      background: #fffaf0;
      color: #7b4d00;
      line-height: 1.45;
      margin-bottom: 8px;
    }}
    .two-mini {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 8px;
    }}
    .subcap {{
      color: #174e7e;
      font-weight: 800;
      margin: 2px 0 5px;
    }}
    .mini-table th, .mini-table td {{
      padding: 5px 6px;
      font-size: 12px;
    }}
    .path-details {{
      margin-top: 8px;
      padding: 6px 7px;
      background: #f7fbff;
      border: 1px solid var(--line-soft);
    }}
    .path-details summary {{
      cursor: pointer;
      color: var(--blue);
      font-weight: 800;
    }}
    .path-line {{
      margin-top: 5px;
      color: var(--muted);
      overflow-wrap: anywhere;
    }}
    .matrix-table {{
      min-width: 980px;
      font-size: 12px;
    }}
    .matrix-table th, .matrix-table td {{
      vertical-align: top;
      min-width: 126px;
    }}
    .matrix-table th:first-child, .matrix-table td:first-child {{
      position: sticky;
      left: 0;
      z-index: 1;
      min-width: 86px;
      background: #edf6ff;
      color: #174e7e;
      font-weight: 800;
    }}
    .matrix-empty {{
      color: #9aacbf;
      text-align: center;
    }}
    .matrix-cell {{
      line-height: 1.45;
      white-space: nowrap;
    }}
    .matrix-cell .direction {{
      display: inline-block;
      margin-top: 2px;
      padding: 1px 4px;
      border-radius: 2px;
      background: #edf6ff;
      color: var(--blue);
      font-weight: 800;
    }}
    .shell {{
      display: grid;
      grid-template-columns: 360px minmax(0, 1fr);
      gap: 10px;
      padding: 10px;
      height: calc(100vh - 292px);
      min-height: 560px;
    }}
    .left, .right {{
      min-height: 0;
      border: 1px solid var(--line);
      background: var(--panel);
    }}
    .left {{
      display: grid;
      grid-template-rows: auto auto 1fr;
    }}
    .section-title {{
      padding: 7px 10px;
      background: var(--head);
      color: #fff;
      font-weight: 700;
      border-bottom: 1px solid #155081;
    }}
    .date-strip {{
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 8px;
      padding: 9px;
      background: var(--subhead);
      border-bottom: 1px solid var(--line-soft);
    }}
    select, input {{
      width: 100%;
      border: 1px solid var(--line);
      background: #fff;
      color: var(--text);
      border-radius: 2px;
      padding: 7px 8px;
      font-size: 13px;
      outline: none;
    }}
    .mini-stat {{
      min-width: 74px;
      text-align: center;
      border: 1px solid var(--line);
      background: #fff;
      padding: 5px 7px;
      color: var(--blue);
      font-weight: 700;
    }}
    .searchbox {{
      padding: 8px 9px;
      background: #f2f8fe;
      border-bottom: 1px solid var(--line-soft);
    }}
    .match-list {{
      overflow: auto;
      background: #fff;
    }}
    .match-item {{
      width: 100%;
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 6px;
      padding: 8px 9px;
      border: 0;
      border-bottom: 1px solid #d4e2ef;
      background: #fff;
      color: var(--text);
      text-align: left;
      cursor: pointer;
      font: inherit;
    }}
    .match-item:hover {{ background: #f1f8ff; }}
    .match-item.active {{
      background: #dceeff;
      box-shadow: inset 4px 0 0 var(--red);
    }}
    .mobile-detail {{
      display: none;
    }}
    .mobile-detail-top {{
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 8px;
      align-items: start;
      padding: 8px;
      background: #f4f9ff;
      border: 1px solid var(--line);
      border-bottom: 0;
    }}
    .mobile-detail-title {{
      font-weight: 900;
      color: #123c62;
      line-height: 1.35;
    }}
    .mobile-detail-meta {{
      margin-top: 3px;
      color: var(--muted);
      font-size: 12px;
      line-height: 1.45;
    }}
    .match-main {{ font-weight: 700; line-height: 1.35; }}
    .match-meta {{ margin-top: 3px; color: var(--muted); font-size: 12px; }}
    .tag {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 42px;
      height: 22px;
      padding: 0 7px;
      border-radius: 2px;
      color: white;
      font-weight: 700;
      font-size: 12px;
    }}
    .tag-win {{ background: var(--green); }}
    .tag-loss {{ background: var(--red); }}
    .tag-push {{ background: var(--amber); }}
    .tag-wait {{ background: #6f8faa; }}
    .right {{
      display: grid;
      grid-template-rows: auto 1fr;
      overflow: hidden;
    }}
    .match-header {{
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 12px;
      padding: 10px 12px;
      background: #f4f9ff;
      border-bottom: 1px solid var(--line);
    }}
    .selected-title {{ font-size: 19px; font-weight: 800; color: #123c62; }}
    .selected-meta {{ margin-top: 4px; color: var(--muted); }}
    .score-box {{
      min-width: 110px;
      text-align: center;
      border: 1px solid var(--line);
      background: #fff;
      padding: 6px;
    }}
    .score-box .score {{ font-size: 22px; font-weight: 900; color: var(--red); }}
    .detail-grid {{
      min-height: 0;
      overflow: auto;
      display: grid;
      grid-template-columns: 1fr 1fr;
      align-content: start;
      gap: 10px;
      padding: 10px;
      background: #eef6fd;
    }}
    .panel {{
      border: 1px solid var(--line);
      background: var(--panel);
      min-width: 0;
    }}
    .panel.wide {{ grid-column: 1 / -1; }}
    .panel-title {{
      display: flex;
      justify-content: space-between;
      gap: 8px;
      padding: 7px 9px;
      background: linear-gradient(180deg, #2f7fbd, #206ba7);
      color: #fff;
      font-weight: 800;
    }}
    .panel-body {{ padding: 9px; }}
    table {{
      width: 100%;
      border-collapse: collapse;
      background: #fff;
    }}
    th, td {{
      border: 1px solid #c8d9e8;
      padding: 7px 8px;
      vertical-align: top;
      line-height: 1.45;
    }}
    th {{
      background: #e3f0fb;
      color: #174e7e;
      text-align: left;
      font-weight: 800;
    }}
    .odds-now {{ color: var(--red); font-weight: 800; }}
    .odds-open {{ color: var(--blue); font-weight: 700; }}
    .note {{
      color: var(--muted);
      font-size: 12px;
      line-height: 1.5;
    }}
    .analysis-line {{
      border: 1px solid #c8d9e8;
      background: #fbfdff;
      padding: 8px;
      min-height: 54px;
      line-height: 1.55;
      overflow-wrap: anywhere;
    }}
    .intent-ev-badge {{
      margin-top: 8px;
      padding: 7px 8px;
      border: 1px solid #efb1b1;
      background: #fff3f3;
      color: var(--red);
      font-weight: 900;
      line-height: 1.55;
    }}
    .kv {{
      display: grid;
      grid-template-columns: 128px 1fr;
      border: 1px solid #c8d9e8;
      border-bottom: 0;
    }}
    .kv:last-child {{ border-bottom: 1px solid #c8d9e8; }}
    .kv .k {{
      background: #edf6ff;
      color: #174e7e;
      font-weight: 800;
      padding: 7px 8px;
      border-right: 1px solid #c8d9e8;
    }}
    .kv .v {{ padding: 7px 8px; line-height: 1.5; overflow-wrap: anywhere; }}
    .rate-good {{ color: var(--green); font-weight: 900; }}
    .rate-bad {{ color: var(--red); font-weight: 900; }}
    .empty {{ padding: 20px; color: var(--muted); text-align: center; }}
    @media (max-width: 1050px) {{
      .pattern-dock {{ grid-template-columns: 1fr; }}
      .shell {{ grid-template-columns: 1fr; height: auto; }}
      .left {{ min-height: 420px; }}
      .right {{ overflow: visible; }}
      .detail-grid {{ overflow: visible; }}
      .detail-grid {{ grid-template-columns: 1fr; }}
      .panel.wide {{ grid-column: auto; }}
      .source {{ white-space: normal; }}
    }}
    @media (max-width: 760px) {{
      body {{ overflow-x: hidden; }}
      .topbar {{ grid-template-columns: 1fr; gap: 6px; padding: 10px 12px; }}
      .topbar h1 {{ font-size: 19px; }}
      .sub, .source {{ font-size: 12px; }}
      .pattern-dock {{
        margin: 8px;
        gap: 8px;
        max-height: 240px;
        overflow: auto;
      }}
      .pattern-card .panel-title {{ font-size: 13px; }}
      .pattern-body {{ padding: 8px; }}
      .shell {{
        display: flex;
        flex-direction: column;
        gap: 8px;
        padding: 0 8px 12px;
        height: auto;
        overflow: visible;
      }}
      .left {{ order: 1; min-height: 0; max-height: none; }}
      .right {{ display: none; }}
      .match-list {{ display: block; max-height: none; overflow: visible; }}
      .mobile-detail {{
        display: block;
        grid-column: 1 / -1;
        padding: 0 6px 10px;
        background: #eef6fd;
        border-bottom: 1px solid #bfd4e7;
      }}
      .mobile-detail-grid {{
        display: grid;
        grid-template-columns: 1fr;
        gap: 8px;
        padding: 0;
        background: transparent;
        overflow: visible;
      }}
      .mobile-detail .panel {{
        width: 100%;
      }}
      .date-strip {{ grid-template-columns: 1fr 74px; }}
      .match-header {{ grid-template-columns: 1fr; }}
      .selected-title {{ font-size: 18px; }}
      .selected-meta {{ font-size: 12px; }}
      .score-box {{ min-width: 0; width: 100%; }}
      .detail-grid {{
        display: grid;
        grid-template-columns: 1fr;
        gap: 8px;
        padding: 8px;
        overflow: visible;
      }}
      .panel-body {{ padding: 7px; }}
      th, td {{ padding: 6px; font-size: 13px; }}
      .kv {{ grid-template-columns: 96px 1fr; }}
      .kv .k, .kv .v {{ padding: 6px; font-size: 13px; }}
      .backtest-metrics, .two-mini {{ grid-template-columns: 1fr 1fr; }}
    }}
  </style>
</head>
<body>
  <header class="topbar">
    <div>
      <h1>足球盘口模拟操盘台</h1>
      <div class="sub">日期筛选、中文比赛、赔率盘口、基本面拉力、资金流与历史胜率</div>
    </div>
    <div class="source">更新时间：{html.escape(now)} ｜ 数据目录：D:\\codex</div>
  </header>

  <section class="pattern-dock">
    <div class="pattern-card">
      <div class="panel-title"><span>图1 盘口档位 x 阻诱标签矩阵</span><span id="intentSource">历史回测</span></div>
      <div class="pattern-body" id="intentMatrix"></div>
      <div class="pattern-note">样本低于8场只作为观察，不升级为稳定主单规则；红色EV框只给当前正向/反向结论和对应球队。</div>
    </div>
    <div class="pattern-card">
      <div class="panel-title"><span>图3 盘口/标签收益明细</span><span>样本>=3</span></div>
      <div class="pattern-body" id="intentDetail"></div>
      <div class="pattern-note">每次结算赛果后，本表必须随亚盘意图历史回测同步刷新。</div>
    </div>
    <div class="pattern-card">
      <div class="panel-title"><span>候选标签表现榜</span><span>标签整体</span></div>
      <div class="pattern-body" id="tagPerformance"></div>
      <div class="pattern-note">好/差标签来自 `候选标签` 历史分组；样本更新后必须随回测和HTML同步更新。</div>
    </div>
  </section>
  <section class="backtest-dock">
    {backtest_box}
  </section>

  <main class="shell">
    <aside class="left">
      <div class="section-title">日期与比赛</div>
      <div class="date-strip">
        <select id="dateSelect"></select>
        <div class="mini-stat" id="dateCount">0 场</div>
      </div>
      <div class="searchbox"><input id="matchSearch" placeholder="搜索中文比赛、联赛、盘口"></div>
      <div class="match-list" id="matchList"></div>
    </aside>

    <section class="right">
      <div class="match-header">
        <div>
          <div class="selected-title" id="selectedTitle">请选择比赛</div>
          <div class="selected-meta" id="selectedMeta"></div>
        </div>
        <div class="score-box">
          <div class="note">赛果/状态</div>
          <div class="score" id="selectedScore">-</div>
        </div>
      </div>

      <div class="detail-grid">
        <section class="panel">
          <div class="panel-title"><span>1. 盘口与赔率</span><span id="marketTag"></span></div>
          <div class="panel-body">
            <table>
              <thead><tr><th>盘口类型</th><th>开盘</th><th>即时/当前</th></tr></thead>
              <tbody id="oddsTable"></tbody>
            </table>
            <div class="analysis-line" id="pickBox" style="margin-top:8px;"></div>
          </div>
        </section>

        <section class="panel">
          <div class="panel-title"><span>2. 交锋/近况/输赢盘</span><span>资料层</span></div>
          <div class="panel-body" id="historyBox"></div>
        </section>

        <section class="panel wide">
          <div class="panel-title"><span>3. 本场基本面、拉力与资金流</span><span>五板链路</span></div>
          <div class="panel-body" id="fundamentalBox"></div>
        </section>

        <section class="panel wide">
          <div class="panel-title"><span>4. 历史同盘口模拟胜率</span><span>账本统计</span></div>
          <div class="panel-body" id="rateBox"></div>
        </section>

        <section class="panel wide">
          <div class="panel-title"><span>5. Polymarket/必发执行门槛</span><span>价格与流动性</span></div>
          <div class="panel-body" id="pmBox"></div>
        </section>

        <section class="panel wide">
          <div class="panel-title"><span>6. Kelly、最终选择与证据完整性</span><span>skill强制字段</span></div>
          <div class="panel-body" id="decisionBox"></div>
        </section>

        <section class="panel wide">
          <div class="panel-title"><span>7. 数据源核验矩阵</span><span>多方验证</span></div>
          <div class="panel-body" id="sourceBox"></div>
        </section>
      </div>
    </section>
  </main>

<script>
const cardsData = {js_data(cards)};
const stats = {js_data(stats)};
const defaultDate = "{default_date}";
const intentMatrixData = stats.intent_matrix || {{tags: [], matrix: [], detail: [], source: "未生成"}};
const tagPerformanceData = intentMatrixData.tag_performance || {{good: [], bad: [], all: [], source: "未生成"}};

function pct(v) {{
  if (v === null || v === undefined || Number.isNaN(v)) return "无";
  return (v * 100).toFixed(1) + "%";
}}

function signed(v) {{
  const n = Number(v || 0);
  return `${{n > 0 ? "+" : ""}}${{n.toFixed(2)}}`;
}}

function pnlClass(v) {{
  return Number(v || 0) >= 0 ? "rate-good" : "rate-bad";
}}

function rateValue(v) {{
  const s = String(v || "").trim();
  if (!s) return 0;
  const n = Number(s.replace("%", ""));
  if (!Number.isFinite(n)) return 0;
  return s.includes("%") ? n / 100 : n;
}}

function smallSampleReverseAlert(cell) {{
  const n = Number(cell?.sample || 0);
  const reverseRate = rateValue(cell?.reverse_rate);
  const forwardPnl = Number(cell?.forward_pnl || 0);
  const reversePnl = Number(cell?.reverse_pnl || 0);
  return n >= 5 && n < 8 && reverseRate >= 0.8 && reversePnl > 0 && reversePnl > forwardPnl;
}}

function intentMatrixCell(line, tag) {{
  if (!line || !tag) return null;
  for (const row of intentMatrixData.matrix || []) {{
    if (row.line !== line) continue;
    for (const cell of row.cells || []) {{
      if (!cell.empty && cell.tag === tag) return cell;
    }}
  }}
  return null;
}}

function sampleWarning(sample) {{
  const n = Number(sample || 0);
  if (n < 3) return "样本不足";
  if (n < 8) return "小样本观察";
  return "可观察";
}}

function tagPerformanceEntry(tag) {{
  if (!tag) return null;
  return (tagPerformanceData.all || []).find(x => x.tag === tag) || null;
}}

function tagPerformanceLabel(tag) {{
  const entry = tagPerformanceEntry(tag);
  if (!entry) return "标签整体表现：暂无历史标签样本。";
  const forward = Number(entry.forward_pnl || 0);
  const reverse = Number(entry.reverse_pnl || 0);
  let label = "中性/需资金流过滤";
  if (forward > 0 && forward >= reverse) label = "表现好的标签";
  else if (forward < 0 && reverse > 0) label = "表现差的标签-倾向反向验证";
  else if (forward <= 0) label = "无正向优势";
  return `标签整体表现：${{label}}；${{entry.sample}}场，正向胜率${{entry.win_rate}}/收益${{signed(entry.forward_pnl)}}，反向胜率${{entry.reverse_rate}}/收益${{signed(entry.reverse_pnl)}}。`;
}}

function sideLabel(side) {{
  if (side === "upper") return "上盘";
  if (side === "lower") return "下盘";
  return "方向未识别";
}}

function reverseSide(side) {{
  if (side === "upper") return "lower";
  if (side === "lower") return "upper";
  return "";
}}

function positiveTeamText(r, mode) {{
  if (mode === "none") return "无，不投";
  const forwardSide = String(r.intent_forward_side || "");
  const side = mode === "forward" ? forwardSide : reverseSide(forwardSide);
  const rawTeam = mode === "forward" ? r.intent_forward_team : r.intent_reverse_team;
  const team = clean(rawTeam);
  if (team === "未接入/待核") return `球队未识别（${{sideLabel(side)}}）`;
  const direction = mode === "forward" ? sideLabel(side) : `反向=${{sideLabel(side)}}`;
  return `${{team}}（${{direction}}）`;
}}

function skillBetDecision(r) {{
  const finalAction = String(r.final_action || "");
  const dataStatus = String(r.data_complete_status || "");
  const flowStatus = String(r.flow_source || r.flow || "");
  const priceText = String(r.price || "");
  const goalStatus = String(r.goal_model_status || "");
  const main = String(r.main || "");
  if (main === "是" && !finalAction.includes("真实不投") && !finalAction.includes("不形成模拟") && !finalAction.includes("盘口快照")) {{
    return "是否投注：可投候选；仍需确认临场可成交价、资金流/流动性和限价。";
  }}
  if (finalAction.includes("盘口快照") || priceText.includes("五板证据未完整")) {{
    return "是否投注：不投；未通过环节：五板证据未完整，缺PM/必发资金流、公共观点或确认首发；只做盘口观察。";
  }}
  if (finalAction.includes("盘口缺失")) {{
    return "是否投注：不投；未通过环节：对应盘口/水位缺失。";
  }}
  if (finalAction.includes("纸面模拟")) {{
    return "是否投注：纸面模拟/真实不投；未通过环节：真实资金流、执行价或Kelly。";
  }}
  if (goalStatus.includes("盘口缺失") || goalStatus.includes("证据不足")) {{
    return `是否投注：不投；未通过环节：${{clean(goalStatus)}}。`;
  }}
  if (dataStatus.includes("缺") || dataStatus.includes("未通过") || dataStatus.includes("待核")) {{
    return `是否投注：不投；未通过环节：${{clean(dataStatus)}}。`;
  }}
  if (flowStatus.includes("缺")) {{
    return "是否投注：不投；未通过环节：PM/必发资金流未通过。";
  }}
  return "是否投注：观察；未升级主单。";
}}

function intentEvBadge(r) {{
  const line = String(r.intent_line_bucket || "").trim();
  const tag = String(r.intent_tag || "").trim();
  const betDecision = skillBetDecision(r);
  if (!line || !tag) {{
    return `亚盘意图历史EV：当前盘口档位/候选标签缺失，不能据历史矩阵下注；正期望方：无，球队未识别。<br>${{betDecision}}`;
  }}
  const cell = intentMatrixCell(line, tag);
  if (!cell) {{
    return `亚盘意图历史EV：${{line}} + ${{tag}} 无同档样本，历史矩阵无正向/反向依据，不据此下注；正期望方：无同档样本，不能判定。<br>${{tagPerformanceLabel(tag)}}<br>${{betDecision}}`;
  }}
  const forward = Number(cell.forward_pnl || 0);
  const reverse = Number(cell.reverse_pnl || 0);
  let action = "无正期望/不投";
  let positiveTeam = positiveTeamText(r, "none");
  if (forward > 0 && forward >= reverse) {{
    action = "正向";
    positiveTeam = positiveTeamText(r, "forward");
  }} else if (reverse > 0) {{
    action = smallSampleReverseAlert(cell) ? "反向（小样本反向警戒）" : "反向";
    positiveTeam = positiveTeamText(r, "reverse");
  }}
  return `亚盘意图历史EV：${{line}} + ${{tag}}，结论：${{action}}；正期望方：${{positiveTeam}}；样本${{cell.sample}}（${{sampleWarning(cell.sample)}}），正向胜率${{cell.forward_rate}}/收益${{signed(cell.forward_pnl)}}，反向胜率${{cell.reverse_rate}}/收益${{signed(cell.reverse_pnl)}}。<br>${{tagPerformanceLabel(tag)}}<br>${{betDecision}}`;
}}

function tagClass(status) {{
  if (status === "赢" || status === "完场" || status === "已结算") return "tag-win";
  if (status === "输") return "tag-loss";
  if (status === "走" || status === "进行中") return "tag-push";
  return "tag-wait";
}}

function clean(v) {{
  return String(v || "").trim() || "未接入/待核";
}}

function isOddsUnavailable(v) {{
  const s = String(v || "").trim();
  if (!s) return true;
  if (s.includes("未接入") || s.includes("未匹配") || s.includes("缺失")) return true;
  const compact = s.replace(/\\s/g, "");
  return compact === "//" || compact.includes("开//") || compact.includes("即//") || compact.includes("/未接入");
}}

function sourceStatus(v) {{
  const s = clean(v);
  if (s.includes("冲突")) return "冲突待核";
  if (s.includes("未接入") || s.includes("未匹配") || s.includes("未核") || s.includes("缺失")) return "未接入/待核";
  if (s.includes("部分") || s.includes("账本")) return "部分接入";
  return "已接入";
}}

function sourceBadge(v) {{
  const status = sourceStatus(v);
  const cls = status === "已接入" ? "rate-good" : (status === "冲突待核" ? "rate-bad" : "");
  return `<span class="${{cls}}">${{status}}</span>`;
}}

function splitOdds(v) {{
  const s = clean(v);
  if (s.includes("→")) {{
    const parts = s.split("→");
    return [parts[0].trim(), parts.slice(1).join("→").trim()];
  }}
  return [s, s];
}}

function settledRows(rows) {{
  return rows.filter(r => ["赢", "输", "走"].includes(r.status));
}}

function winRate(rows) {{
  const settled = settledRows(rows);
  const wins = settled.filter(r => r.status === "赢").length;
  const losses = settled.filter(r => r.status === "输").length;
  const pushes = settled.filter(r => r.status === "走").length;
  const denom = wins + losses;
  const pnl = settled.reduce((acc, r) => acc + (parseFloat(r.pnl) || 0), 0);
  return {{ wins, losses, pushes, rate: denom ? wins / denom : null, pnl }};
}}

function sampleSize(rateObj) {{
  return rateObj.wins + rateObj.losses + rateObj.pushes;
}}

function rateLabel(rateObj) {{
  const n = sampleSize(rateObj);
  const mark = n >= 15 ? "优先模式" : (n >= 8 ? "可用样本" : "小样本观察");
  return `${{pct(rateObj.rate)}}（${{mark}}，样本 ${{n}}）`;
}}

function modelProxy(r) {{
  const sameCombo = winRate(cardsData.filter(x => x.league === r.league && x.market === r.market));
  const sameMarket = winRate(cardsData.filter(x => x.market === r.market));
  const source = sampleSize(sameCombo) >= 8 ? "同联赛+同盘口历史胜率" : "同盘口历史胜率代理";
  const picked = sampleSize(sameCombo) >= 8 ? sameCombo : sameMarket;
  return {{ source, rate: picked.rate, sample: sampleSize(picked) }};
}}

function kellyCalc(r) {{
  const p = modelProxy(r).rate;
  const d = Number(r.decimal || 0);
  if (!d || !p) return {{ text: "赔率或模型概率未入账，不能计算真实Kelly金额", fraction: null, stake: 0, action: "仅模拟/赔率待核" }};
  const full = (p * d - 1) / (d - 1);
  const fractional = .25;
  const bankroll = 500;
  const minimum = 20;
  const stake = Math.max(0, full * fractional * bankroll);
  const action = full <= 0 ? "不投-Kelly为负" : (stake < minimum ? "不投-低于最低投注额" : "可投候选");
  return {{
    text: `代理概率 ${{(p * 100).toFixed(1)}}%，十进制赔率 ${{d.toFixed(2)}}，全Kelly ${{(full * 100).toFixed(2)}}%，0.25Kelly测算 ${{stake.toFixed(1)}}，本金500，最低20，结论：${{action}}`,
    fraction: full,
    stake,
    action
  }};
}}

function renderIntentMatrix() {{
  const sourceName = clean(intentMatrixData.source).split(/[\\\\/]/).pop();
  document.getElementById("intentSource").textContent = sourceName === "未接入/待核" ? "未生成" : sourceName;

  const tags = intentMatrixData.tags || [];
  const matrix = intentMatrixData.matrix || [];
  const matrixBox = document.getElementById("intentMatrix");
  if (!matrix.length || !tags.length) {{
    matrixBox.innerHTML = '<div class="empty">暂无亚盘意图矩阵，需先运行赛果结算与候选意图回测</div>';
  }} else {{
    matrixBox.innerHTML = `
      <table class="matrix-table">
        <thead>
          <tr><th>盘口档位</th>${{tags.map(t => `<th>${{t}}</th>`).join("")}}</tr>
        </thead>
        <tbody>
          ${{matrix.map(row => `
            <tr>
              <td>${{row.line}}</td>
              ${{(row.cells || []).map(c => {{
                if (c.empty) return '<td class="matrix-empty">-</td>';
                const directionText = smallSampleReverseAlert(c) ? `小样本反向警戒｜${{c.direction}}` : c.direction;
                return `<td>
                  <div class="matrix-cell">
                    <strong>n=${{c.sample}}</strong><br>
                    正胜 ${{c.forward_rate}} / <span class="${{pnlClass(c.forward_pnl)}}">${{signed(c.forward_pnl)}}</span><br>
                    反胜 ${{c.reverse_rate}} / <span class="${{pnlClass(c.reverse_pnl)}}">${{signed(c.reverse_pnl)}}</span><br>
                    <span class="direction">${{directionText}}</span>
                  </div>
                </td>`;
              }}).join("")}}
            </tr>
          `).join("")}}
        </tbody>
      </table>`;
  }}

  const detail = intentMatrixData.detail || [];
  const detailBox = document.getElementById("intentDetail");
  if (!detail.length) {{
    detailBox.innerHTML = '<div class="empty">暂无样本>=3的盘口/标签组合</div>';
    return;
  }}
  detailBox.innerHTML = `
    <table>
      <thead><tr><th>盘口/标签</th><th>样本数量</th><th>胜率</th><th>正向收益</th><th>反向收益</th></tr></thead>
      <tbody>
        ${{detail.map(r => `
          <tr>
            <td><strong>${{r.combo}}</strong><br><span class="muted">${{smallSampleReverseAlert(r) ? "小样本反向警戒｜" : ""}}${{r.direction}}｜${{r.note || "小样本观察"}}</span></td>
            <td>${{r.sample}}</td>
            <td>${{r.win_rate}}</td>
            <td class="${{pnlClass(r.forward_pnl)}}">${{signed(r.forward_pnl)}}</td>
            <td class="${{pnlClass(r.reverse_pnl)}}">${{signed(r.reverse_pnl)}}</td>
          </tr>
        `).join("")}}
      </tbody>
    </table>`;
}}

function tagRows(rows, emptyText) {{
  if (!rows.length) return `<div class="empty">${{emptyText}}</div>`;
  return `
    <table>
      <thead><tr><th>标签</th><th>样本</th><th>胜率</th><th>正向</th><th>反向</th></tr></thead>
      <tbody>
        ${{rows.map(r => `
          <tr>
            <td><strong>${{r.tag}}</strong><br><span class="muted">${{r.counts}}｜${{r.verdict}}</span></td>
            <td>${{r.sample}}</td>
            <td>${{r.win_rate}}</td>
            <td class="${{pnlClass(r.forward_pnl)}}">${{signed(r.forward_pnl)}}</td>
            <td class="${{pnlClass(r.reverse_pnl)}}">${{signed(r.reverse_pnl)}}</td>
          </tr>
        `).join("")}}
      </tbody>
    </table>`;
}}

function renderTagPerformance() {{
  const box = document.getElementById("tagPerformance");
  const good = tagPerformanceData.good || [];
  const bad = tagPerformanceData.bad || [];
  if (!good.length && !bad.length) {{
    box.innerHTML = '<div class="empty">暂无候选标签表现榜，需先运行亚盘意图历史回测</div>';
    return;
  }}
  box.innerHTML = `
    <div class="section-title" style="padding:5px 8px;">表现好的标签</div>
    ${{tagRows(good, "暂无正向收益标签")}}
    <div class="section-title" style="padding:5px 8px; margin-top:8px;">表现差的标签</div>
    ${{tagRows(bad, "暂无明显反向标签")}}`;
}}

function allDates() {{
  return [...new Set(cardsData.map(r => r.date).filter(Boolean))].sort().reverse();
}}

function rowsForDate() {{
  const d = document.getElementById("dateSelect").value;
  const q = document.getElementById("matchSearch").value.trim().toLowerCase();
  return cardsData
    .filter(r => r.date === d)
    .filter(r => !q || Object.values(r).join(" ").toLowerCase().includes(q))
    .sort((a, b) => {{
      const am = a.matched_odds ? 0 : 1;
      const bm = b.matched_odds ? 0 : 1;
      const ak = kellyCalc(a);
      const bk = kellyCalc(b);
      const ap = modelProxy(a);
      const bp = modelProxy(b);
      return am - bm
        || (bk.stake - ak.stake)
        || ((bp.rate || 0) - (ap.rate || 0))
        || String(a.display_time).localeCompare(String(b.display_time), "zh-Hans-CN")
        || String(a.display_match).localeCompare(String(b.display_match), "zh-Hans-CN");
    }});
}}

function renderDates() {{
  const dates = allDates();
  const selected = dates.includes(defaultDate) ? defaultDate : dates[0];
  document.getElementById("dateSelect").innerHTML = dates.map(d => `<option value="${{d}}" ${{d === selected ? "selected" : ""}}>${{d}}</option>`).join("");
}}

function renderList(selectedMatch = null) {{
  const rows = rowsForDate();
  const list = document.getElementById("matchList");
  document.getElementById("dateCount").textContent = `${{rows.length}} 场`;
  if (!rows.length) {{
    list.innerHTML = '<div class="empty">该日期暂无模拟比赛</div>';
    renderDetail(null);
    return;
  }}
  const selected = selectedMatch || rows[0].display_match;
  const selectedRow = rows.find(r => r.display_match === selected) || rows[0];
  const mobile = isMobileView();
  list.innerHTML = rows.map((r, idx) => `
    <button class="match-item ${{!mobile && r.display_match === selected ? "active" : ""}}" data-idx="${{idx}}" aria-expanded="false">
      <div>
        <div class="match-main">${{r.display_match}}</div>
        <div class="match-meta">${{r.display_time}} ｜ ${{r.league}} ｜ ${{r.market}}：${{r.pick}} ｜ 比分：${{r.display_score}}</div>
      </div>
      <span class="tag ${{tagClass(r.display_status)}}">${{r.display_status}}</span>
    </button>
  `).join("");
  list.querySelectorAll(".match-item").forEach(btn => {{
    btn.addEventListener("click", () => {{
      const alreadyOpen = isMobileView()
        && btn.classList.contains("active")
        && btn.nextElementSibling
        && btn.nextElementSibling.classList.contains("mobile-detail");
      if (alreadyOpen) {{
        btn.classList.remove("active");
        btn.setAttribute("aria-expanded", "false");
        list.querySelectorAll(".mobile-detail").forEach(x => x.remove());
        return;
      }}
      list.querySelectorAll(".match-item").forEach(x => x.classList.remove("active"));
      list.querySelectorAll(".match-item").forEach(x => x.setAttribute("aria-expanded", "false"));
      btn.classList.add("active");
      btn.setAttribute("aria-expanded", "true");
      const row = rows[Number(btn.dataset.idx)];
      renderDetail(row);
      renderMobileDetail(row, btn);
    }});
  }});
  renderDetail(selectedRow);
  if (!mobile) {{
    const active = list.querySelector(".match-item.active");
    if (active) active.setAttribute("aria-expanded", "true");
  }}
}}

function oddsRow(label, value) {{
  if (isOddsUnavailable(value)) return "";
  const [open, now] = splitOdds(value);
  return `<tr><td><strong>${{label}}</strong></td><td class="odds-open">${{open}}</td><td class="odds-now">${{now}}</td></tr>`;
}}

function oddsRows(r) {{
  const rows = [
    oddsRow("亚盘", r.ah),
    oddsRow("欧赔", r.euro),
    oddsRow("大小球", r.total),
    oddsRow("双方进球", "未接入：等待BTTS稳定赔率源")
  ].filter(Boolean).join("");
  return rows || '<tr><td colspan="3" class="muted">暂无可显示盘口赔率；缺口见数据源核验矩阵</td></tr>';
}}

function rateClass(v) {{
  return v !== null && v >= .55 ? "rate-good" : (v !== null && v < .45 ? "rate-bad" : "");
}}

function rateTableHtml(r) {{
  const sameMarket = winRate(cardsData.filter(x => x.market === r.market));
  const sameLeague = winRate(cardsData.filter(x => x.league === r.league));
  const sameCombo = winRate(cardsData.filter(x => x.league === r.league && x.market === r.market));
  return `
    <table>
      <thead><tr><th>统计口径</th><th>样本</th><th>赢/输/走</th><th>胜率</th><th>盈亏单位</th></tr></thead>
      <tbody>
        <tr><td>同盘口类型：${{clean(r.market)}}</td><td>${{sameMarket.wins + sameMarket.losses + sameMarket.pushes}}</td><td>${{sameMarket.wins}}/${{sameMarket.losses}}/${{sameMarket.pushes}}</td><td class="${{rateClass(sameMarket.rate)}}">${{pct(sameMarket.rate)}}</td><td>${{sameMarket.pnl.toFixed(2)}}</td></tr>
        <tr><td>同联赛：${{clean(r.league)}}</td><td>${{sameLeague.wins + sameLeague.losses + sameLeague.pushes}}</td><td>${{sameLeague.wins}}/${{sameLeague.losses}}/${{sameLeague.pushes}}</td><td class="${{rateClass(sameLeague.rate)}}">${{pct(sameLeague.rate)}}</td><td>${{sameLeague.pnl.toFixed(2)}}</td></tr>
        <tr><td>同联赛 + 同盘口</td><td>${{sameCombo.wins + sameCombo.losses + sameCombo.pushes}}</td><td>${{sameCombo.wins}}/${{sameCombo.losses}}/${{sameCombo.pushes}}</td><td class="${{rateClass(sameCombo.rate)}}">${{pct(sameCombo.rate)}}</td><td>${{sameCombo.pnl.toFixed(2)}}</td></tr>
      </tbody>
    </table>
    <div class="note" style="margin-top:8px;">样本不足 8 场时只作观察，不作为主单依据。历史战绩、近5场输赢盘和BTTS赔率尚未稳定接入时均明确标注待核。</div>
  `;
}}

function sourceRowsFor(r) {{
  return [
    ["赛程/中文名/比分", r.schedule_source],
    ["亚盘/欧赔/大小球", r.odds_source],
    ["数据完整性审计", `${{r.data_complete_status}}；${{r.data_complete_detail}}`],
    ["亚盘意图候选", r.asian_intent],
    ["BTTS/球队进球/角球/半场", r.btts_source],
    ["进球模型/射手/时间分布", `${{r.goal_model_status}}；${{r.goal_model_detail}}`],
    ["双方历史战绩", r.h2h_source],
    ["近5场/主客场状态", r.form_source],
    ["历史赢盘/输盘/大小球", r.handicap_record_source],
    ["伤停/首发/停赛", r.lineup_source],
    ["战意/积分/杯赛赛制", r.motivation_source],
    ["Polymarket/必发/投注流", r.flow_source],
    ["公共博主/盘口观点", r.analyst_source],
  ];
}}

function sourceTableHtml(r) {{
  return `
    <table>
      <thead><tr><th>数据字段</th><th>状态</th><th>当前来源/缺口</th></tr></thead>
      <tbody>
        ${{sourceRowsFor(r).map(([name, value]) => `<tr><td>${{name}}</td><td>${{sourceBadge(value)}}</td><td>${{clean(value)}}</td></tr>`).join("")}}
      </tbody>
    </table>
    <div class="note" style="margin-top:8px;">主单升级规则：关键字段必须至少有一个市场价格源和一个基本面源通过核验；盘口、阵容、投注流三者冲突时，自动降为观察或仅模拟。</div>
  `;
}}

function mobileDetailHtml(r) {{
  const proxy = modelProxy(r);
  const kelly = kellyCalc(r);
  return `
    <div class="mobile-detail">
      <div class="mobile-detail-top">
        <div>
          <div class="mobile-detail-title">${{clean(r.display_match)}}</div>
          <div class="mobile-detail-meta">${{clean(r.display_time)}} ｜ ${{clean(r.league)}} ｜ 排名/阶段：${{clean(r.rank)}} ｜ 球探状态：${{clean(r.state_label || r.state)}}（${{clean(r.state)}}）</div>
        </div>
        <span class="tag ${{tagClass(r.display_status)}}">${{clean(r.display_status)}}</span>
      </div>
      <div class="detail-grid mobile-detail-grid">
        <section class="panel">
          <div class="panel-title"><span>1. 盘口与赔率</span><span>${{r.matched_odds ? "Titan007赔率已匹配" : "赔率待核"}}</span></div>
          <div class="panel-body">
            <table>
              <thead><tr><th>盘口类型</th><th>开盘</th><th>即时/当前</th></tr></thead>
              <tbody>${{oddsRows(r)}}</tbody>
            </table>
            <div class="analysis-line" style="margin-top:8px;">
              <strong>模拟盘口：</strong>${{clean(r.market)}} ｜ ${{clean(r.pick)}}<br>
              <strong>价格/赔率：</strong>${{clean(r.price)}}<br>
              <strong>赔率来源：</strong>${{clean(r.price_source)}}<br>
              <strong>结算口径：</strong>${{clean(r.settlement)}}
              <div class="intent-ev-badge">${{intentEvBadge(r)}}</div>
            </div>
          </div>
        </section>
        <section class="panel">
          <div class="panel-title"><span>2. 交锋/近况/输赢盘</span><span>资料层</span></div>
          <div class="panel-body">
            <div class="kv"><div class="k">双方历史战绩</div><div class="v">${{clean(r.h2h_source)}}</div></div>
            <div class="kv"><div class="k">近5场/状态</div><div class="v">${{clean(r.form_source)}}</div></div>
            <div class="kv"><div class="k">赢盘/输盘与大小球记录</div><div class="v">${{clean(r.handicap_record_source)}}</div></div>
            <div class="kv"><div class="k">本场结算</div><div class="v">状态：${{clean(r.status)}}；赛果：${{clean(r.result)}}；模拟盈亏：${{clean(r.pnl)}}；过程评级：${{clean(r.grade)}}；错误类型：${{clean(r.error)}}</div></div>
          </div>
        </section>
        <section class="panel wide">
          <div class="panel-title"><span>3. 本场基本面、拉力与资金流</span><span>五板链路</span></div>
          <div class="panel-body">
            <div class="kv"><div class="k">伤停/首发</div><div class="v">${{clean(r.lineup)}}<br>${{clean(r.injury)}}</div></div>
            <div class="kv"><div class="k">战意/场景</div><div class="v">${{clean(r.purpose)}}</div></div>
            <div class="kv"><div class="k">盘口拉力</div><div class="v">${{clean(r.pull)}}</div></div>
            <div class="kv"><div class="k">数据完整性</div><div class="v">${{clean(r.data_complete_status)}}<br>${{clean(r.data_complete_detail)}}</div></div>
            <div class="kv"><div class="k">进球模型核验</div><div class="v">${{clean(r.goal_model_status)}}<br>${{clean(r.goal_model_detail)}}</div></div>
            <div class="kv"><div class="k">欧赔去水</div><div class="v">${{clean(r.euro_devig)}}<br>来源：Titan007即时欧赔；未做跨公司共识时不能单独升级主单。</div></div>
            <div class="kv"><div class="k">亚盘真实意图</div><div class="v">${{clean(r.asian_intent)}}<br>盘口拉力：${{clean(r.pull)}}</div></div>
            <div class="kv"><div class="k">资金/流动性</div><div class="v">真实成交/PM/必发：${{clean(r.flow)}}<br>盘口流动性：${{clean(r.liquidity)}}</div></div>
            <div class="kv"><div class="k">模型更新</div><div class="v">${{clean(r.update)}}</div></div>
          </div>
        </section>
        <section class="panel wide">
          <div class="panel-title"><span>4. 历史同盘口模拟胜率</span><span>账本统计</span></div>
          <div class="panel-body">${{rateTableHtml(r)}}</div>
        </section>
        <section class="panel wide">
          <div class="panel-title"><span>5. Polymarket/必发执行门槛</span><span>价格与流动性</span></div>
          <div class="panel-body">
            <div class="kv"><div class="k">Polymarket价格</div><div class="v">${{clean(r.flow)}}<br>若无Gamma/CLOB bid/ask、spread、volume、liquidity和合约口径，则不能给Polymarket主单。</div></div>
            <div class="kv"><div class="k">必发/交易所</div><div class="v">当前字段：${{clean(r.flow)}}。必须区分真实投注量、流动性、盘口价格流；Titan007只算盘口价格流，不算投注量。</div></div>
            <div class="kv"><div class="k">盘口等价</div><div class="v">Asian quarter line 不能直接映射成 Polymarket ±1.5/±2.5；若要下PM，必须重算 P(赢2+) / P(赢3+) / 不败等二元桶。</div></div>
            <div class="kv"><div class="k">执行状态</div><div class="v">默认无PM主单；只有合约、结算时钟、可成交价、流动性、保守胜率和最大买入价全部通过才升级。</div></div>
          </div>
        </section>
        <section class="panel wide">
          <div class="panel-title"><span>6. Kelly、最终选择与证据完整性</span><span>skill强制字段</span></div>
          <div class="panel-body">
            <div class="kv"><div class="k">模型概率</div><div class="v">${{proxy.rate ? (proxy.rate * 100).toFixed(1) + "%" : "未入账"}}；来源：${{proxy.source}}，样本 ${{proxy.sample}}。这是历史代理概率，不等同完整五板模型概率。</div></div>
            <div class="kv"><div class="k">Kelly测算</div><div class="v">${{kelly.text}}</div></div>
            <div class="kv"><div class="k">最终盘口选择</div><div class="v">${{clean(r.final_action)}}；是否主单：${{clean(r.main)}}；模拟方向：${{clean(r.pick)}}。</div></div>
            <div class="kv"><div class="k">证据完整性</div><div class="v">${{clean(r.evidence_status)}}。主单必须同时满足至少一个基本面输入和一个市场拉力输入。</div></div>
            <div class="kv"><div class="k">赛后复盘</div><div class="v">赛果：${{clean(r.result)}}；盈亏：${{clean(r.pnl)}}；过程评级：${{clean(r.grade)}}；错误类型：${{clean(r.error)}}；规则更新：${{clean(r.update)}}</div></div>
          </div>
        </section>
        <section class="panel wide">
          <div class="panel-title"><span>7. 数据源核验矩阵</span><span>多方验证</span></div>
          <div class="panel-body">${{sourceTableHtml(r)}}</div>
        </section>
      </div>
    </div>
  `;
}}

function isMobileView() {{
  return window.matchMedia("(max-width: 760px)").matches;
}}

function renderMobileDetail(r, btn) {{
  const list = document.getElementById("matchList");
  list.querySelectorAll(".mobile-detail").forEach(x => x.remove());
  if (!r || !btn || !isMobileView()) return;
  btn.insertAdjacentHTML("afterend", mobileDetailHtml(r));
}}

function renderDetail(r) {{
  if (!r) {{
    document.getElementById("selectedTitle").textContent = "请选择比赛";
    document.getElementById("selectedMeta").textContent = "";
    document.getElementById("selectedScore").textContent = "-";
    document.getElementById("oddsTable").innerHTML = "";
    document.getElementById("pickBox").textContent = "";
    document.getElementById("historyBox").innerHTML = "";
    document.getElementById("fundamentalBox").innerHTML = "";
    document.getElementById("rateBox").innerHTML = "";
    document.getElementById("pmBox").innerHTML = "";
    document.getElementById("decisionBox").innerHTML = "";
    document.getElementById("sourceBox").innerHTML = "";
    return;
  }}

  const proxy = modelProxy(r);
  const kelly = kellyCalc(r);
  document.getElementById("selectedTitle").textContent = r.display_match;
  document.getElementById("selectedMeta").textContent = `${{r.date}} ｜ ${{r.display_time}} ｜ ${{r.league}} ｜ 排名/阶段：${{clean(r.rank)}} ｜ 球探状态：${{clean(r.state_label || r.state)}}（${{clean(r.state)}}）`;
  document.getElementById("selectedScore").textContent = clean(r.display_score);
  document.getElementById("marketTag").textContent = r.odds_status || (r.matched_odds ? "Titan007部分赔率已匹配" : "赔率待核");
  document.getElementById("oddsTable").innerHTML = oddsRows(r);
  document.getElementById("pickBox").innerHTML =
    `<strong>模拟盘口：</strong>${{clean(r.market)}} ｜ ${{clean(r.pick)}}<br>` +
    `<strong>价格/赔率：</strong>${{clean(r.price)}}<br>` +
    `<strong>赔率来源：</strong>${{clean(r.price_source)}}<br>` +
    `<strong>结算口径：</strong>${{clean(r.settlement)}}` +
    `<div class="intent-ev-badge">${{intentEvBadge(r)}}</div>`;

  document.getElementById("historyBox").innerHTML = `
    <div class="kv"><div class="k">双方历史战绩</div><div class="v">${{clean(r.h2h_source)}}</div></div>
    <div class="kv"><div class="k">近5场/状态</div><div class="v">${{clean(r.form_source)}}</div></div>
    <div class="kv"><div class="k">赢盘/输盘与大小球记录</div><div class="v">${{clean(r.handicap_record_source)}}</div></div>
    <div class="kv"><div class="k">本场结算</div><div class="v">状态：${{clean(r.status)}}；赛果：${{clean(r.result)}}；模拟盈亏：${{clean(r.pnl)}}；过程评级：${{clean(r.grade)}}；错误类型：${{clean(r.error)}}</div></div>
  `;

  document.getElementById("fundamentalBox").innerHTML = `
    <div class="kv"><div class="k">伤停/首发</div><div class="v">${{clean(r.lineup)}}<br>${{clean(r.injury)}}</div></div>
    <div class="kv"><div class="k">战意/场景</div><div class="v">${{clean(r.purpose)}}</div></div>
    <div class="kv"><div class="k">盘口拉力</div><div class="v">${{clean(r.pull)}}</div></div>
    <div class="kv"><div class="k">数据完整性</div><div class="v">${{clean(r.data_complete_status)}}<br>${{clean(r.data_complete_detail)}}</div></div>
    <div class="kv"><div class="k">进球模型核验</div><div class="v">${{clean(r.goal_model_status)}}<br>${{clean(r.goal_model_detail)}}</div></div>
    <div class="kv"><div class="k">欧赔去水</div><div class="v">${{clean(r.euro_devig)}}<br>来源：Titan007即时欧赔；未做跨公司共识时不能单独升级主单。</div></div>
    <div class="kv"><div class="k">亚盘真实意图</div><div class="v">${{clean(r.asian_intent)}}<br>盘口拉力：${{clean(r.pull)}}</div></div>
    <div class="kv"><div class="k">资金/流动性</div><div class="v">真实成交/PM/必发：${{clean(r.flow)}}<br>盘口流动性：${{clean(r.liquidity)}}</div></div>
    <div class="kv"><div class="k">模型更新</div><div class="v">${{clean(r.update)}}</div></div>
  `;

  const sameMarket = winRate(cardsData.filter(x => x.market === r.market));
  const sameLeague = winRate(cardsData.filter(x => x.league === r.league));
  const sameCombo = winRate(cardsData.filter(x => x.league === r.league && x.market === r.market));
  const rateClass = v => (v !== null && v >= .55 ? "rate-good" : (v !== null && v < .45 ? "rate-bad" : ""));
  document.getElementById("rateBox").innerHTML = `
    <table>
      <thead><tr><th>统计口径</th><th>样本</th><th>赢/输/走</th><th>胜率</th><th>盈亏单位</th></tr></thead>
      <tbody>
        <tr><td>同盘口类型：${{clean(r.market)}}</td><td>${{sameMarket.wins + sameMarket.losses + sameMarket.pushes}}</td><td>${{sameMarket.wins}}/${{sameMarket.losses}}/${{sameMarket.pushes}}</td><td class="${{rateClass(sameMarket.rate)}}">${{pct(sameMarket.rate)}}</td><td>${{sameMarket.pnl.toFixed(2)}}</td></tr>
        <tr><td>同联赛：${{clean(r.league)}}</td><td>${{sameLeague.wins + sameLeague.losses + sameLeague.pushes}}</td><td>${{sameLeague.wins}}/${{sameLeague.losses}}/${{sameLeague.pushes}}</td><td class="${{rateClass(sameLeague.rate)}}">${{pct(sameLeague.rate)}}</td><td>${{sameLeague.pnl.toFixed(2)}}</td></tr>
        <tr><td>同联赛 + 同盘口</td><td>${{sameCombo.wins + sameCombo.losses + sameCombo.pushes}}</td><td>${{sameCombo.wins}}/${{sameCombo.losses}}/${{sameCombo.pushes}}</td><td class="${{rateClass(sameCombo.rate)}}">${{pct(sameCombo.rate)}}</td><td>${{sameCombo.pnl.toFixed(2)}}</td></tr>
      </tbody>
    </table>
    <div class="note" style="margin-top:8px;">样本不足 8 场时只作观察，不作为主单依据。历史战绩、近5场输赢盘和BTTS赔率尚未稳定接入时均明确标注待核。</div>
  `;

  document.getElementById("pmBox").innerHTML = `
    <div class="kv"><div class="k">Polymarket价格</div><div class="v">${{clean(r.flow)}}<br>若无Gamma/CLOB bid/ask、spread、volume、liquidity和合约口径，则不能给Polymarket主单。</div></div>
    <div class="kv"><div class="k">必发/交易所</div><div class="v">当前字段：${{clean(r.flow)}}。必须区分真实投注量、流动性、盘口价格流；Titan007只算盘口价格流，不算投注量。</div></div>
    <div class="kv"><div class="k">盘口等价</div><div class="v">Asian quarter line 不能直接映射成 Polymarket ±1.5/±2.5；若要下PM，必须重算 P(赢2+) / P(赢3+) / 不败等二元桶。</div></div>
    <div class="kv"><div class="k">执行状态</div><div class="v">默认无PM主单；只有合约、结算时钟、可成交价、流动性、保守胜率和最大买入价全部通过才升级。</div></div>
  `;

  document.getElementById("decisionBox").innerHTML = `
    <div class="kv"><div class="k">模型概率</div><div class="v">${{proxy.rate ? (proxy.rate * 100).toFixed(1) + "%" : "未入账"}}；来源：${{proxy.source}}，样本 ${{proxy.sample}}。这是历史代理概率，不等同完整五板模型概率。</div></div>
    <div class="kv"><div class="k">Kelly测算</div><div class="v">${{kelly.text}}</div></div>
    <div class="kv"><div class="k">最终盘口选择</div><div class="v">${{clean(r.final_action)}}；是否主单：${{clean(r.main)}}；模拟方向：${{clean(r.pick)}}。</div></div>
    <div class="kv"><div class="k">证据完整性</div><div class="v">${{clean(r.evidence_status)}}。主单必须同时满足至少一个基本面输入和一个市场拉力输入。</div></div>
    <div class="kv"><div class="k">赛后复盘</div><div class="v">赛果：${{clean(r.result)}}；盈亏：${{clean(r.pnl)}}；过程评级：${{clean(r.grade)}}；错误类型：${{clean(r.error)}}；规则更新：${{clean(r.update)}}</div></div>
    <div class="kv"><div class="k">备份规则</div><div class="v">以后每日更新前先备份 skill、dashboard生成器、当前HTML和当日账本，再抓取赔率、写日报、更新HTML。</div></div>
  `;

  const sourceRows = [
    ["赛程/中文名/比分", r.schedule_source],
    ["亚盘/欧赔/大小球", r.odds_source],
    ["数据完整性审计", `${{r.data_complete_status}}；${{r.data_complete_detail}}`],
    ["亚盘意图候选", r.asian_intent],
    ["BTTS/球队进球/角球/半场", r.btts_source],
    ["进球模型/射手/时间分布", `${{r.goal_model_status}}；${{r.goal_model_detail}}`],
    ["双方历史战绩", r.h2h_source],
    ["近5场/主客场状态", r.form_source],
    ["历史赢盘/输盘/大小球", r.handicap_record_source],
    ["伤停/首发/停赛", r.lineup_source],
    ["战意/积分/杯赛赛制", r.motivation_source],
    ["Polymarket/必发/投注流", r.flow_source],
    ["公共博主/盘口观点", r.analyst_source],
  ];
  document.getElementById("sourceBox").innerHTML = `
    <table>
      <thead><tr><th>数据字段</th><th>状态</th><th>当前来源/缺口</th></tr></thead>
      <tbody>
        ${{sourceRows.map(([name, value]) => `<tr><td>${{name}}</td><td>${{sourceBadge(value)}}</td><td>${{clean(value)}}</td></tr>`).join("")}}
      </tbody>
    </table>
    <div class="note" style="margin-top:8px;">主单升级规则：关键字段必须至少有一个市场价格源和一个基本面源通过核验；盘口、阵容、投注流三者冲突时，自动降为观察或仅模拟。</div>
  `;
}}

function init() {{
  renderIntentMatrix();
  renderTagPerformance();
  renderDates();
  document.getElementById("dateSelect").addEventListener("change", () => renderList());
  document.getElementById("matchSearch").addEventListener("input", () => renderList());
  window.addEventListener("resize", () => {{
    const rows = rowsForDate();
    const active = document.querySelector(".match-item.active");
    const row = active ? rows[Number(active.dataset.idx)] : null;
    renderMobileDetail(row, active);
  }});
  renderList();
}}

init();
</script>
</body>
</html>"""


def main() -> int:
    DASHBOARD_DIR.mkdir(parents=True, exist_ok=True)
    cards, stats = build_rows()
    backtest = latest_sequential_backtest()
    output = DASHBOARD_DIR / "index.html"
    output.write_text(html_doc_v2(cards, stats, backtest), encoding="utf-8")
    print(f"dashboard={output}")
    print(f"cards={len(cards)} settled={stats['settled']} win_rate={stats['win_rate']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
