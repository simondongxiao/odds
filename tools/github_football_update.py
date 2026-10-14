"""Portable V3/V4 football refresh for the GitHub-hosted runner.

This entrypoint deliberately has no dependency on the desktop ``D:\\codex``
tree.  It fetches the shared Titan snapshot, keeps an append-only JSON/CSV
ledger in the repository, and publishes a small date-scoped dashboard payload.
The desktop skill remains the authoritative rich/local workflow; this script
is the cloud fallback used by scheduled GitHub Actions runs.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[1]
DATA = REPO / "data" / "github_football"
LEDGER_JSON = DATA / "ledger.json"
LEDGER_CSV = DATA / "ledger.csv"
SITE = REPO / "github_site"
TZ = dt.timezone(dt.timedelta(hours=8))
BUSINESS_CUTOFF_HOUR = 12

# BetExplorer supplies English labels.  Keep a small checked-in alias layer so
# cloud-only supplemental fixtures never leak English names into the Chinese
# dashboard; the file can be extended without changing the pipeline.
DEFAULT_TEAM_ALIASES = {
    "slovenia w": "斯洛文尼亚女足", "turkey w": "土耳其女足",
    "austria w": "奥地利女足", "kosovo w": "科索沃女足",
    "sabah baku": "萨巴赫", "slavia prague": "布拉格斯拉维亚",
    "reading": "雷丁", "chelsea u21": "切尔西U21",
    "gillingham": "吉林汉姆", "brighton u21": "布莱顿U21",
    "cheltenham": "切尔滕汉姆", "tottenham u21": "热刺U21",
    "oldham": "奥尔德姆", "leeds u21": "利兹联U21",
    "wales w": "威尔士女足", "albania w": "阿尔巴尼亚女足",
    "england w": "英格兰女足", "greece w": "希腊女足",
    "millwall": "米尔沃尔", "swansea": "斯旺西",
    "queen's park": "女王公园", "inverness": "因弗内斯",
    "cardiff": "卡迪夫城", "watford": "沃特福德",
    "wrexham": "雷克瑟姆", "west brom": "西布朗",
    "wolves": "狼队", "bolton": "博尔顿",
    "arsenal": "阿森纳", "lille": "里尔", "inter": "国际米兰",
    "club brugge": "布鲁日", "slovenia": "斯洛文尼亚",
}
DEFAULT_LEAGUE_ALIASES = {
    "be:world-cup-women": "女足世界杯", "be:efl-trophy": "英锦赛",
    "be:championship": "英冠", "be:premier-league": "英超",
    "be:champions-league": "欧冠", "be:europa-league": "欧联",
}


def f(value: Any) -> float | None:
    try:
        x = float(str(value or "").strip())
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=path.parent, suffix=".tmp") as h:
        h.write(text)
        tmp = Path(h.name)
    tmp.replace(path)


def read_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, list) else value.get("rows", [])
    except (OSError, json.JSONDecodeError):
        return []


def latest_snapshot(list_date: str) -> Path:
    paths = sorted((REPO / "data" / "raw" / "titan007" / list_date.replace("-", "")).glob("*_titan007_odds_snapshot.csv"), key=lambda p: p.stat().st_mtime)
    if not paths:
        raise FileNotFoundError(f"Titan snapshot not found for {list_date}")
    return paths[-1]


def run_fetch(list_date: str) -> Path:
    os.environ["FOOTBALL_GITHUB_ROOT"] = str(REPO)
    os.environ["FOOTBALL_RAW_ROOT"] = str(REPO / "data" / "raw" / "titan007")
    os.environ["FOOTBALL_LIST_DATE"] = list_date
    os.environ.setdefault("TITAN_ENABLE_BROWSER_FALLBACK", "0")
    os.environ.setdefault("TITAN_ENABLE_MOBILE_FALLBACK", "0")
    sys.path.insert(0, str(REPO / "tools"))
    import fetch_titan007_odds  # type: ignore

    old_argv = sys.argv
    try:
        sys.argv = [str(REPO / "tools" / "fetch_titan007_odds.py")]
        code = fetch_titan007_odds.main()
    finally:
        sys.argv = old_argv
    if code not in (0, None):
        raise RuntimeError(f"Titan fetch failed with exit code {code}")
    return latest_snapshot(list_date)


def kickoff(row: dict[str, str], list_date: str) -> str:
    raw = str(row.get("bj_time") or row.get("match_time_en") or "").strip()
    if len(raw) >= 10 and raw[:4].isdigit():
        return raw
    try:
        return f"{list_date[:4]}-{raw[:5]} {raw[6:]}:00+08:00"
    except Exception:
        return raw


def business_date_for(kickoff_value: str, fallback: str) -> str:
    """Business day is Beijing 12:00 through next day 11:59."""
    text = str(kickoff_value or "").strip()
    try:
        parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=TZ)
        local = parsed.astimezone(TZ)
    except ValueError:
        try:
            local = dt.datetime.fromisoformat(f"{fallback[:4]}-{text[:5]} {text[6:]}:00+08:00")
        except ValueError:
            return fallback
    return (local.date() if local.hour >= BUSINESS_CUTOFF_HOUR else local.date() - dt.timedelta(days=1)).isoformat()


def aliases() -> tuple[dict[str, str], dict[str, str]]:
    path = DATA / "team_aliases.json"
    teams, leagues = dict(DEFAULT_TEAM_ALIASES), dict(DEFAULT_LEAGUE_ALIASES)
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            teams.update({str(k).casefold(): str(v) for k, v in (payload.get("teams") or {}).items()})
            leagues.update({str(k).casefold(): str(v) for k, v in (payload.get("leagues") or {}).items()})
        except (OSError, json.JSONDecodeError):
            pass
    return teams, leagues


def localize_row(item: dict[str, Any], team_map: dict[str, str], league_map: dict[str, str]) -> dict[str, Any]:
    item["home_team_en"] = item.get("home_team_en") or item.get("home_team", "")
    item["away_team_en"] = item.get("away_team_en") or item.get("away_team", "")
    item["home_team"] = team_map.get(str(item.get("home_team", "")).casefold(), item.get("home_team", ""))
    item["away_team"] = team_map.get(str(item.get("away_team", "")).casefold(), item.get("away_team", ""))
    item["competition"] = league_map.get(str(item.get("competition", "")).casefold(), item.get("competition", ""))
    market = item.get("market") or {}
    for key in ("giving_team", "receiving_team"):
        if market.get(key):
            market[key] = team_map.get(str(market[key]).casefold(), market[key])
    item["market"] = market
    return item


def market_row(row: dict[str, str], list_date: str) -> dict[str, Any]:
    line = f(row.get("ah_full_current_line_or_draw"))
    home_water = f(row.get("ah_full_current_home_or_over"))
    away_water = f(row.get("ah_full_current_away_or_under"))
    euro_home = f(row.get("euro_full_current_home_or_over"))
    euro_draw = f(row.get("euro_full_current_line_or_draw"))
    euro_away = f(row.get("euro_full_current_away_or_under"))
    home = str(row.get("home_cn") or row.get("home_en") or "").strip()
    away = str(row.get("away_cn") or row.get("away_en") or "").strip()
    competition = str(row.get("league_cn") or row.get("league_en") or row.get("league_tw") or "UNKNOWN").strip()
    current_market = all(v is not None for v in (line, home_water, away_water)) and abs(line or 0) > 0
    euro_market = all(v is not None and v > 1 for v in (euro_home, euro_draw, euro_away))
    giving_home = (line or 0) < 0
    giving_team = home if giving_home else away
    receiving_team = away if giving_home else home
    giving_water = home_water if giving_home else away_water
    receiving_water = away_water if giving_home else home_water
    return {
        "match_id": str(row.get("match_id") or "").strip(),
        "list_date": list_date,
        "kickoff": kickoff(row, list_date),
        "competition": competition,
        "home_team": home,
        "away_team": away,
        "home_team_en": str(row.get("home_en") or "").strip(),
        "away_team_en": str(row.get("away_en") or "").strip(),
        "state": str(row.get("state") or "").strip(),
        "score": f"{row.get('home_score','')}-{row.get('away_score','')}" if row.get("home_score") or row.get("away_score") else "",
        "market": {
            "line": abs(line) if line is not None else None,
            "giving_team": giving_team,
            "receiving_team": receiving_team,
            "giving_water": giving_water,
            "receiving_water": receiving_water,
            "euro_home": euro_home,
            "euro_draw": euro_draw,
            "euro_away": euro_away,
            "current_complete": current_market,
            "euro_complete": euro_market,
            "opening_line": f(row.get("ah_full_open_line_or_draw")),
        },
        "source_snapshot": str(row.get("snapshot_stamp") or ""),
    }


def evaluate(item: dict[str, Any], version: str) -> dict[str, Any]:
    m = item["market"]
    complete = bool(m["current_complete"] and m["euro_complete"])
    eh, ed, ea = m["euro_home"], m["euro_draw"], m["euro_away"]
    total = (1 / eh + 1 / ed + 1 / ea) if complete else 0
    probs = ((1 / eh) / total, (1 / ed) / total, (1 / ea) / total) if total else (0, 0, 0)
    giving_p = probs[0] if m["giving_team"] == item["home_team"] else probs[2]
    receiving_p = probs[2] if m["giving_team"] == item["home_team"] else probs[0]
    gw, rw = m["giving_water"], m["receiving_water"]
    ev_g = giving_p * (1 + (gw or 0)) - 1 if complete else None
    ev_r = receiving_p * (1 + (rw or 0)) - 1 if complete else None
    best = max(ev_g or -1, ev_r or -1)
    gap = abs((ev_g or 0) - (ev_r or 0))
    text = item["competition"].lower()
    excluded = any(k in text for k in ("u17", "u19", "u20", "u21", "u23", "青年", "预备", "友谊", "friendly"))
    threshold = 0.08 if version == "V3" else 0.06
    bettable = bool(item["state"] in {"0", ""} and complete and not excluded and best >= threshold and gap >= 0.03)
    if bettable:
        side = "giving" if (ev_g or -1) >= (ev_r or -1) else "receiving"
        team = m["giving_team"] if side == "giving" else m["receiving_team"]
        water = gw if side == "giving" else rw
        decision = "BET_GIVING" if side == "giving" else "BET_RECEIVING"
    else:
        side = team = decision = ""
        water = None
    if item["state"] not in {"0", ""}:
        gate_reasons = ["MATCH_NOT_PREMATCH"]
    elif not complete:
        gate_reasons = ["MISSING_CURRENT_AH_OR_EURO"]
    elif excluded:
        gate_reasons = ["YOUTH_OR_FRIENDLY_EXCLUDED"]
    else:
        gate_reasons = []
    return {
        "decision": decision if bettable else "NO_BET",
        "bettable": bettable,
        "selected_side": side,
        "selected_team": team,
        "selected_water": water,
        "ev_giving": ev_g,
        "ev_receiving": ev_r,
        "quality_gate_passed": complete and not excluded and item["state"] in {"0", ""},
        "quality_gate_reasons": gate_reasons,
        "rule_version": "GITHUB_PORTABLE_V3_V4_20261014",
    }


def merge(new_rows: list[dict[str, Any]], old_rows: list[dict[str, Any]], list_date: str) -> tuple[list[dict[str, Any]], str | None]:
    old = {str(x.get("match_id")): x for x in old_rows if x.get("match_id")}
    warning = None
    previous_today = sum(1 for x in old.values() if x.get("list_date") == list_date)
    incoming_today = sum(1 for x in new_rows if x.get("list_date") == list_date)
    if previous_today and incoming_today < previous_today * 0.65:
        warning = f"ROW_COUNT_SHRINK_WARNING previous={previous_today} incoming={incoming_today}"
    for fresh in new_rows:
        key = str(fresh.get("match_id") or "")
        if not key:
            continue
        previous = old.get(key)
        if previous and str(previous.get("state")) not in {"0", ""}:
            locked = dict(previous)
            locked.update({k: fresh.get(k) for k in ("state", "score", "source_snapshot")})
            old[key] = locked
        elif previous:
            # The cloud runner does not retain every raw Titan snapshot between
            # jobs.  Preserve a previously confirmed non-empty market when a
            # later job receives a transient blank AH/Euro payload, while
            # allowing any new non-empty quote to replace it.
            merged = dict(previous)
            for field, value in fresh.items():
                if field == "market":
                    continue
                if str(value or "").strip() or not str(merged.get(field) or "").strip():
                    merged[field] = value
            old_market = dict(previous.get("market") or {})
            for field, value in (fresh.get("market") or {}).items():
                if value is not None and str(value).strip() or old_market.get(field) in (None, ""):
                    old_market[field] = value
            old_market["current_complete"] = all(old_market.get(field) is not None for field in ("line", "giving_water", "receiving_water")) and bool(old_market.get("line"))
            old_market["euro_complete"] = all(f(old_market.get(field)) is not None and f(old_market.get(field)) > 1 for field in ("euro_home", "euro_draw", "euro_away"))
            merged["market"] = old_market
            old[key] = merged
        else:
            old[key] = fresh
    return sorted(old.values(), key=lambda x: (str(x.get("list_date")), str(x.get("kickoff")), str(x.get("match_id")))), warning


def write_csv(rows: list[dict[str, Any]]) -> None:
    flat = []
    for x in rows:
        y = {k: v for k, v in x.items() if k != "market"}
        y.update({f"market_{k}": v for k, v in x.get("market", {}).items()})
        flat.append(y)
    fields = sorted({k for x in flat for k in x})
    with tempfile.NamedTemporaryFile("w", encoding="utf-8-sig", newline="", delete=False, dir=LEDGER_CSV.parent, suffix=".tmp") as h:
        w = csv.DictWriter(h, fieldnames=fields); w.writeheader(); w.writerows(flat); tmp = Path(h.name)
    tmp.replace(LEDGER_CSV)


def rich_v4_row(item: dict[str, Any]) -> dict[str, Any]:
    """Adapt the portable cloud row to the original rich V4 dashboard schema."""
    q = evaluate(item, "V4")
    m = dict(item.get("market") or {})
    line = f(m.get("line"))
    giving_home = bool(line is not None and m.get("giving_team") == item.get("home_team"))
    signed = -abs(line) if giving_home else abs(line) if line is not None else None
    m.update({
        "competition": item.get("competition", ""),
        "home_team": item.get("home_team", ""),
        "away_team": item.get("away_team", ""),
        "home_handicap_signed": signed,
        "away_handicap_signed": -signed if signed is not None else None,
    })
    started = str(item.get("state") or "") not in {"0", ""}
    final_decision = "UNAVAILABLE" if started else q["decision"]
    selected_side = q.get("selected_side", "") if not started else ""
    selected_handicap = None
    if selected_side:
        selected_handicap = signed if selected_side == "giving" else (-signed if signed is not None else None)
    return {
        **item,
        "model_id": "V4",
        "model_version": "V4",
        "domain": "GITHUB_CLOUD",
        "league_level": "UNKNOWN",
        "market": m,
        "analysis_status": "NOT_PREMATCH" if started else ("EVALUATED" if q["quality_gate_passed"] else "MISSING_DATA"),
        "final_decision": final_decision,
        "decision_status": "NOT_PREMATCH" if started else ("BET" if q["bettable"] else "NO_BET"),
        "quality_gate_passed": q["quality_gate_passed"],
        "quality_gate_reasons": q["quality_gate_reasons"],
        "selected_side": selected_side,
        "selected_team": q.get("selected_team", "") if not started else "",
        "selected_handicap_signed": selected_handicap,
        "selected_water_hk": q.get("selected_water") if not started else None,
        "candidate_side": selected_side,
        "candidate_team": q.get("selected_team", "") if not started else "",
        "ev_giving": q.get("ev_giving"),
        "ev_receiving": q.get("ev_receiving"),
        "data_quality": "MEDIUM" if q["quality_gate_passed"] else "LOW",
        "market_quality": "MEDIUM" if m.get("current_complete") else "LOW",
        "grade": "B" if q["bettable"] else "N",
        "bet_unit": 1.0 if q["bettable"] else 0.0,
        "started_lock": started,
    }


def dashboard(version: str, date: str, rows: list[dict[str, Any]]) -> None:
    out = SITE / version.lower() / "data" / f"{date}.json"
    source_rows = [x for x in rows if x.get("list_date") == date]
    payload_rows = [rich_v4_row(x) for x in source_rows] if version == "V4" else source_rows
    payload = {"list_date": date, "version": version, "model_id": version, "model_version": version, "generated_at": dt.datetime.now(TZ).isoformat(), "matches": payload_rows}
    for x in payload["matches"]:
        x[version.lower()] = evaluate(x, version)
    atomic_text(out, json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    atomic_text(SITE / version.lower() / "data" / "index.json", json.dumps([date], ensure_ascii=False))
    html = f'''<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{version} GitHub Dashboard</title><style>body{{font:14px Arial;margin:0;background:#eef5fb;color:#17324d}}main{{max-width:1200px;margin:auto;padding:12px}}header,section{{background:#fff;padding:12px;margin-bottom:10px;border:1px solid #c5d9ea}}table{{width:100%;border-collapse:collapse}}th,td{{padding:7px;border-bottom:1px solid #d9e5ef;text-align:left}}.bet{{color:#07843f;font-weight:700}}.no{{color:#b42318}}.why{{font-size:12px;color:#7a3b00}}@media(max-width:700px){{table{{font-size:12px}}th:nth-child(5),td:nth-child(5){{display:none}}}}</style><main><header><h2>{version} GitHub 云端看板</h2><div id="meta">加载中</div><label><input id="all" type="checkbox" checked>显示全部赛事</label></header><section><table><thead><tr><th>时间</th><th>赛事</th><th>比赛</th><th>结果</th><th>盘口/水位</th><th>决策</th><th>门禁原因</th></tr></thead><tbody id="rows"></tbody></table></section></main><script>const d=new URLSearchParams(location.search).get('date')||'{date}';fetch('./data/'+d+'.json?v='+Date.now()).then(r=>r.json()).then(p=>{{document.querySelector('#meta').textContent=p.list_date+'｜共 '+p.matches.length+' 场';const key='{version.lower()}';const render=()=>{{const all=document.querySelector('#all').checked;document.querySelector('#rows').innerHTML=p.matches.filter(x=>all||x[key]?.bettable).map(x=>{{const q=x[key]||{{}};const m=x.market||{{}};const why=(q.quality_gate_reasons||[]).join('、')||'—';return '<tr><td>'+x.kickoff+'</td><td>'+x.competition+'</td><td>'+x.home_team+' vs '+x.away_team+'</td><td>'+x.score+'</td><td>'+((m.line??'—')+' / '+(m.giving_water??'—')+' / '+(m.receiving_water??'—'))+'</td><td class="'+(q.bettable?'bet':'no')+'">'+(q.bettable?(q.selected_team+' '+q.decision):'不投')+'</td><td class="why">'+why+'</td></tr>'}}).join('')}};document.querySelector('#all').onchange=render;render()}}).catch(e=>document.querySelector('#meta').textContent='数据加载失败：'+e)</script>'''
    # Keep the checked-in rich V4 shell. The portable fallback creates the
    # small table only when no template is present (for a brand-new checkout).
    shell = SITE / version.lower() / "index.html"
    if not shell.exists():
        atomic_text(shell, html)
    if version == "V3" and shell.exists():
        # Preserve the original rich V3 UI while refreshing only its embedded
        # card data. This prevents the cloud fallback table from replacing the
        # production interface on the next scheduled run.
        rich = shell.read_text(encoding="utf-8")
        marker, end_marker = "const cardsData = ", "\ncardsData.forEach"
        start = rich.find(marker)
        end = rich.find(end_marker, start + len(marker)) if start >= 0 else -1
        if start >= 0 and end > start:
            cards = []
            for item in source_rows:
                q = item.get("v3") or evaluate(item, "V3")
                m = item.get("market") or {}
                cards.append({
                    "date": item.get("list_date", date), "league": item.get("competition", ""),
                    "match": f"{item.get('home_team','')} vs {item.get('away_team','')}",
                    "display_match": f"{item.get('home_team','')} vs {item.get('away_team','')}",
                    "time": item.get("kickoff", ""), "display_time": item.get("kickoff", ""),
                    "score": item.get("score", "") or "待赛", "display_score": item.get("score", "") or "待赛",
                    "state": item.get("state", ""), "state_label": "完场" if item.get("state") not in {"0", ""} else "未开赛",
                    "display_status": "完场" if item.get("state") not in {"0", ""} else "未开赛",
                    "match_id": item.get("match_id", ""), "frozen_bettable": bool(q.get("bettable")),
                    "frozen_bettable_action": q.get("decision", ""), "frozen_bettable_team": q.get("selected_team", ""),
                    "matched_odds": bool(m.get("current_complete") or m.get("euro_complete")),
                    "rank": item.get("competition", ""), "market": "亚盘", "pick": q.get("decision", "不投"),
                    "ah": f"即 {m.get('line')}/{m.get('giving_water')}/{m.get('receiving_water')}" if m.get("current_complete") else "未接入",
                    "euro": f"即 {m.get('euro_home')}/{m.get('euro_draw')}/{m.get('euro_away')}" if m.get("euro_complete") else "未接入",
                    "ah_ok": bool(m.get("current_complete")), "euro_ok": bool(m.get("euro_complete")),
                    "result": item.get("score", "") or "待赛", "pnl": "不计", "status": "已结算" if item.get("state") not in {"0", ""} else "待赛",
                    "grade": "BET" if q.get("bettable") else "NA", "error": "、".join(q.get("quality_gate_reasons", [])),
                })
            replacement = marker + json.dumps(cards, ensure_ascii=False, separators=(",", ":"))
            atomic_text(shell, rich[:start] + replacement + rich[end:])


def send_feishu(date: str, counts: dict[str, int], warning: str | None) -> None:
    url = os.environ.get("FEISHU_WEBHOOK_URL")
    if not url:
        return
    text = f"GitHub 足球云端更新 {date}\nV3 可投 {counts['V3']} 场｜V4 可投 {counts['V4']} 场｜底稿 {counts['rows']} 场"
    if warning:
        text += f"\n⚠️ {warning}"
    body = json.dumps({"msg_type": "text", "content": {"text": text}}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=20) as response:
        if response.status >= 300:
            raise RuntimeError(f"Feishu HTTP {response.status}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list-date", default=(dt.datetime.now(TZ).date().isoformat()))
    ap.add_argument("--from-csv", help="offline test input; skips network fetch")
    args = ap.parse_args()
    date = args.list_date
    snapshot = Path(args.from_csv) if args.from_csv else run_fetch(date)
    with snapshot.open("r", encoding="utf-8-sig", newline="") as h:
        incoming = [market_row(x, date) for x in csv.DictReader(h)]
    team_map, league_map = aliases()
    for item in incoming:
        # A requested date is a Beijing business slate: 12:00 through the
        # following day 11:59.  Midnight-to-noon fixtures belong to yesterday.
        item["list_date"] = business_date_for(item.get("kickoff", ""), date)
        localize_row(item, team_map, league_map)
    old_rows = read_rows(LEDGER_JSON)
    # Migrate legacy rows that were stored with the old midnight-based date.
    # This is a key-only correction; scores, locks, markets, and settlements
    # remain untouched.
    for item in old_rows:
        if item.get("kickoff"):
            item["list_date"] = business_date_for(item.get("kickoff", ""), str(item.get("list_date") or date))
    rows, warning = merge(incoming, old_rows, date)
    for item in rows:
        localize_row(item, team_map, league_map)
    for x in rows:
        if x.get("list_date") != date:
            continue
        # Unstarted matches must be reevaluated on every refresh.  A previous
        # run may have seen a transiently missing quote; keeping setdefault()
        # here would permanently freeze that false NO_BET until the match is
        # locked.  Started/settled rows keep their historical decision.
        if str(x.get("state") or "") in {"0", ""}:
            x["v3"] = evaluate(x, "V3")
            x["v4"] = evaluate(x, "V4")
        else:
            x.setdefault("v3", evaluate(x, "V3")); x.setdefault("v4", evaluate(x, "V4"))
    atomic_text(LEDGER_JSON, json.dumps(rows, ensure_ascii=False, indent=2))
    write_csv(rows)
    current = [x for x in rows if x.get("list_date") == date]
    counts = {"rows": len(current), "V3": sum(bool(x.get("v3", {}).get("bettable")) for x in current), "V4": sum(bool(x.get("v4", {}).get("bettable")) for x in current)}
    dashboard("V3", date, current); dashboard("V4", date, current)
    atomic_text(DATA / "last_run.json", json.dumps({"list_date": date, "counts": counts, "warning": warning, "snapshot": str(snapshot), "generated_at": dt.datetime.now(TZ).isoformat()}, ensure_ascii=False, indent=2))
    send_feishu(date, counts, warning)
    print(json.dumps({"snapshot": str(snapshot), **counts, "warning": warning}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
