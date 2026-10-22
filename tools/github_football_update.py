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
import time
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[1]
DATA = REPO / "data" / "github_football"
LEDGER_JSON = DATA / "ledger.json"
LEDGER_CSV = DATA / "ledger.csv"
SITE = REPO / "github_site"
TZ = dt.timezone(dt.timedelta(hours=8))
BUSINESS_CUTOFF_HOUR = 12
HISTORY_RESULTS = {"W", "HW", "P", "HL", "L"}
HISTORY_LABELS = {"W": "红", "HW": "半红", "P": "走", "HL": "半黑", "L": "黑"}
# The GitHub entry point intentionally remains a portable companion.  The
# desktop V3/V4 implementations are the formal authorities (V3 legacy JS
# parity and V4 ``core_model.evaluate_match``).  Until the same inputs,
# calibration files and freeze snapshot can be executed here, cloud decisions
# must never be written into the formal history ledger as if they were equal.
MODEL_STATUS = "PORTABLE_DIAGNOSTIC"
FORMAL_MODEL_EQUIVALENCE = "NOT_VERIFIED"

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
    "be:usa-mls": "美职业", "be:major-league-soccer": "美职业",
    "usa:mls": "美职业", "major league soccer": "美职业", "mls": "美职业",
}

# BetExplorer uses slug names while Titan uses the Chinese competition
# label. These aliases are also used by the cross-provider identity key.
DEFAULT_LEAGUE_ALIASES.update({
    "be:j1-league": "\u65e5\u804c\u8054", "j1-league": "\u65e5\u804c\u8054",
    "be:j2-league": "\u65e5\u804c\u4e59", "j2-league": "\u65e5\u804c\u4e59",
    "be:j3-league": "\u65e5\u804c\u4e19", "j3-league": "\u65e5\u804c\u4e19",
    "be:j-league-cup": "\u65e5\u8054\u676f", "j-league-cup": "\u65e5\u8054\u676f",
})

# Display translation and fixture identity are intentionally separate. This
# table only tells the de-duplicator that two provider labels are the same
# club; it never changes odds, sides, scores, or frozen decisions.
CROSS_PROVIDER_TEAM_ALIASES = {
    "fc tokyo": "jp:fc-tokyo", "\u0046\u0043\u4e1c\u4eac": "jp:fc-tokyo",
    "kashiwa reysol": "jp:kashiwa-reysol", "\u67cf\u592a\u9633\u795e": "jp:kashiwa-reysol",
    "kyoto": "jp:kyoto", "kyoto sanga": "jp:kyoto", "\u4eac\u90fd\u4e0d\u6b7b\u9e1f": "jp:kyoto",
    "kashima antlers": "jp:kashima-antlers", "\u9e7f\u5c9b\u9e7f\u89d2": "jp:kashima-antlers",
    "okayama": "jp:okayama", "fagiano okayama": "jp:okayama", "\u5188\u5c71\u7eff\u96c9": "jp:okayama",
    "mito": "jp:mito", "mito hollyhock": "jp:mito", "\u6c34\u6237\u871c\u67a0": "jp:mito",
    "shimizu s-pulse": "jp:shimizu", "\u6e05\u6c34\u9f13\u52a8": "jp:shimizu",
    "machida": "jp:machida", "machida zelvia": "jp:machida", "\u753a\u7530\u6cfd\u7ef4\u4e9a": "jp:machida",
    "yokohama f. marinos": "jp:yokohama-marinos", "yokohama marinos": "jp:yokohama-marinos", "\u6a2a\u6ee8\u6c34\u624b": "jp:yokohama-marinos",
    "verdy": "jp:tokyo-verdy", "tokyo verdy": "jp:tokyo-verdy", "\u4e1c\u4eac\u7eff\u8335": "jp:tokyo-verdy",
    "montedio yamagata": "jp:yamagata", "yamagata": "jp:yamagata", "\u5c71\u5f62\u5c71\u795e": "jp:yamagata",
    "hokkaido consadole sapporo": "jp:sapporo", "consadole sapporo": "jp:sapporo", "\u672d\u5e4c\u5188\u8428\u591a": "jp:sapporo",
    "v-varen nagasaki": "jp:nagasaki", "\u957f\u5d0e\u6210\u529f\u4e38": "jp:nagasaki",
    "sanfrecce hiroshima": "jp:hiroshima", "hiroshima sanfrecce": "jp:hiroshima", "\u5e7f\u5c9b\u4e09\u7bad": "jp:hiroshima",
    "urawa reds": "jp:urawa", "urawa red diamonds": "jp:urawa", "\u6d66\u548c\u7ea2\u94bb": "jp:urawa",
    "chiba": "jp:chiba", "jef united chiba": "jp:chiba", "\u5343\u53f6\u5e02\u539f": "jp:chiba",
    "kofu": "jp:kofu", "ventforet kofu": "jp:kofu", "\u7532\u5e9c\u98ce\u6797": "jp:kofu",
    "yokohama fc": "jp:yokohama-fc", "\u6a2a\u6ee8fc": "jp:yokohama-fc",
    "iwata": "jp:iwata", "jubilo iwata": "jp:iwata", "\u78d0\u7530\u559c\u60a6": "jp:iwata",
    "oita trinita": "jp:oita", "\u5927\u5206\u4e09\u795e": "jp:oita",
    "omiya ardija": "jp:omiya", "\u5927\u5bae\u677e\u9f20": "jp:omiya",
    "toyama": "jp:toyama", "kataller toyama": "jp:toyama", "\u5bcc\u5c71\u80dc\u5229": "jp:toyama",
    "tegevajaro miyazaki": "jp:miyazaki", "\u5bab\u5d0e\u68d2\u725b\u9e1f": "jp:miyazaki",
    "blaublitz": "jp:akita", "blaublitz akita": "jp:akita", "\u79cb\u7530\u84dd\u8272\u95ea\u7535": "jp:akita",
    "tokushima": "jp:tokushima", "tokushima vortis": "jp:tokushima", "\u5fb7\u5c9b\u6f29\u6da1": "jp:tokushima",
    "vanraure": "jp:hachinohe", "vanraure hachinohe": "jp:hachinohe", "\u516b\u6237\u4e91\u7f57\u91cc": "jp:hachinohe",
    "kawasaki frontale": "jp:kawasaki", "\u5ddd\u5d0e\u524d\u950b": "jp:kawasaki",
    "nagoya grampus": "jp:nagoya", "\u540d\u53e4\u5c4b\u9cb8\u516b": "jp:nagoya",
}



def f(value: Any) -> float | None:
    try:
        x = float(str(value or "").strip())
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def _history_score(value: Any) -> tuple[int, int] | None:
    """Read a final 1X2 score without accepting a placeholder/live string."""
    match = re.search(r"^(\d+)\s*[-:]\s*(\d+)(?:\D|$)", str(value or "").strip())
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def _split_history_line(value: float) -> list[float]:
    quarter = round(abs(value) * 4) / 4
    if int(round(quarter * 4)) % 2 == 0:
        return [quarter]
    return [math.floor(quarter * 2) / 2, math.ceil(quarter * 2) / 2]


def _settle_history_giving(margin: int, line: float) -> str:
    parts = []
    for handicap in _split_history_line(line):
        value = margin - handicap
        parts.append("W" if value > 1e-9 else "L" if value < -1e-9 else "P")
    if all(x == "W" for x in parts):
        return "W"
    if all(x == "L" for x in parts):
        return "L"
    if all(x == "P" for x in parts):
        return "P"
    if set(parts) == {"W", "P"}:
        return "HW"
    if set(parts) == {"L", "P"}:
        return "HL"
    raise ValueError(f"unsupported Asian settlement parts: {parts}")


def _mirror_history_result(result: str) -> str:
    return {"W": "L", "HW": "HL", "P": "P", "HL": "HW", "L": "W"}[result]


def _history_result(row: dict[str, Any], version: str) -> tuple[str, float] | None:
    """Settle one locked cloud row using its frozen side, line and water."""
    score = _history_score(row.get("score"))
    if score is None or str(row.get("state") or "") in {"", "0"}:
        return None
    decision = row.get(version.lower()) or {}
    if not decision.get("bettable"):
        return None
    market = row.get("market") or {}
    line = f(market.get("line"))
    water = f(decision.get("selected_water"))
    side = str(decision.get("selected_side") or "").strip()
    giving_team = str(market.get("giving_team") or "").strip()
    home, away = str(row.get("home_team") or "").strip(), str(row.get("away_team") or "").strip()
    if line is None or water is None or not side or giving_team not in {home, away}:
        return None
    home_goals, away_goals = score
    margin = home_goals - away_goals if giving_team == home else away_goals - home_goals
    result = _settle_history_giving(margin, abs(line))
    if side == "receiving":
        result = _mirror_history_result(result)
    if result not in HISTORY_RESULTS:
        return None
    payout = {"W": water, "HW": water * 0.5, "P": 0.0, "HL": -0.5, "L": -1.0}[result]
    return result, round(payout, 6)


def _history_detail(row: dict[str, Any], version: str, result: str, pnl: float) -> dict[str, Any]:
    decision = row.get(version.lower()) or {}
    market = row.get("market") or {}
    return {
        "ledger_key": f"{version}|{row.get('list_date', '')}|{row.get('match_id', '')}",
        "history_key": f"{row.get('competition', '')}|{row.get('list_date', '')}|{row.get('match_id', '')}",
        "match_id": str(row.get("match_id") or ""),
        "date": str(row.get("list_date") or ""),
        "list_date": str(row.get("list_date") or ""),
        "kickoff": str(row.get("kickoff") or ""),
        "competition": str(row.get("competition") or "").strip(),
        "canonical_competition_name": str(row.get("competition") or "").strip(),
        "match": f"{row.get('home_team', '')} vs {row.get('away_team', '')}",
        "score": str(row.get("score") or ""),
        "selected_team": str(decision.get("selected_team") or ""),
        "selected_side": str(decision.get("selected_side") or ""),
        "line": market.get("line"),
        "water": decision.get("selected_water"),
        "settlement": HISTORY_LABELS[result],
        "result": result,
        "pnl_1u": pnl,
        "roi": pnl,
        "action": str(decision.get("decision") or ""),
        "source": str(row.get("source_snapshot") or ""),
        "settlement_status": "SETTLED",
        "countable_history": True,
    }


def _normalise_history_result(value: Any) -> str:
    text = str(value or "").strip().upper()
    aliases = {
        "红": "W", "红半": "HW", "半红": "HW", "走": "P", "走水": "P",
        "黑": "L", "黑半": "HL", "半黑": "HL",
    }
    return aliases.get(text, text if text in HISTORY_RESULTS else "")


def _load_existing_history_details(version: str) -> list[dict[str, Any]]:
    path = SITE / version.lower() / "data" / f"{version.lower()}_history_detail.json"
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = payload.get("rows", []) if isinstance(payload, dict) else payload
        return [row for row in rows if isinstance(row, dict)]
    except (OSError, json.JSONDecodeError):
        return []


def build_competition_history(rows: list[dict[str, Any]], target_date: str) -> None:
    """Build date-scoped V3/V4 same-competition stats from locked history.

    Existing Excel-derived detail artifacts are the formal source of truth.
    Cloud rows are written to a separate diagnostic artifact only: the
    portable evaluator is not proven equivalent to the desktop models and
    therefore must not contaminate formal V3/V4 backtests.
    """
    all_dates = sorted({str(x.get("list_date") or "") for x in rows if x.get("list_date")})
    if target_date not in all_dates:
        all_dates.append(target_date)
    for version in ("V3", "V4"):
        details = _load_existing_history_details(version)
        seen = {str(x.get("ledger_key") or "") for x in details if x.get("ledger_key")}
        diagnostic_details: list[dict[str, Any]] = []
        # Keep this calculation for audit visibility, but never append these
        # rows to ``details`` used by the formal history panels.
        for row in rows:
            key = f"{version}|{row.get('list_date', '')}|{row.get('match_id', '')}"
            if key in seen or not str(row.get("list_date") or ""):
                continue
            settled = _history_result(row, version)
            if not settled:
                continue
            result, pnl = settled
            diagnostic_details.append(_history_detail(row, version, result, pnl))
        details = [x for x in details if _normalise_history_result(x.get("result") or x.get("settlement")) in HISTORY_RESULTS]
        for date in all_dates:
            historical = [x for x in details if str(x.get("list_date") or x.get("date") or "")[:10] < date]
            grouped: dict[str, list[dict[str, Any]]] = {}
            for item in historical:
                competition = str(item.get("canonical_competition_name") or item.get("competition") or "").strip()
                if competition:
                    grouped.setdefault(competition, []).append(item)
            output_rows = []
            for current in rows:
                if str(current.get("list_date") or "") != date:
                    continue
                competition = str(current.get("competition") or "").strip()
                matches = grouped.get(competition, [])
                counts = {key: 0 for key in HISTORY_RESULTS}
                pnl_total = 0.0
                for item in matches:
                    result = _normalise_history_result(item.get("result") or item.get("settlement"))
                    if result not in HISTORY_RESULTS:
                        continue
                    counts[result] += 1
                    value = f(item.get("pnl_1u"))
                    if value is not None:
                        pnl_total += value
                sample = sum(counts.values())
                denominator = counts["W"] + 0.5 * counts["HW"] + counts["L"] + 0.5 * counts["HL"]
                effective = ((counts["W"] + 0.5 * counts["HW"]) / denominator) if denominator else None
                rate_band = ""
                if sample > 8 and effective is not None:
                    if effective >= 0.55:
                        rate_band = "高：历史有效胜率≥55%"
                    elif effective < 0.45:
                        rate_band = "严重：历史有效胜率<45%"
                output_rows.append({
                    "version": version, "list_date": date,
                    "match_id": str(current.get("match_id") or ""),
                    "competition": competition,
                    "match": f"{current.get('home_team', '')} vs {current.get('away_team', '')}",
                    "selected_team": str((current.get(version.lower()) or {}).get("selected_team") or ""),
                    "historical_settled_sample": sample,
                    "红": counts["W"], "半红": counts["HW"], "走": counts["P"],
                    "半黑": counts["HL"], "黑": counts["L"],
                    "effective_win_rate": round(effective, 8) if effective is not None else "",
                    "pnl_1u": round(pnl_total, 6) if sample else "",
                    "roi": round(pnl_total / sample, 8) if sample else "",
                    "pnl_rows": sample, "rate_band": rate_band, "alert_band": rate_band,
                    "history_cutoff": f"list_date < {date}",
                    "history_matches": sorted(({
                        "date": str(item.get("date") or item.get("list_date") or "")[:10],
                        "match": item.get("match", ""), "score": item.get("score", ""),
                        "selected_team": item.get("selected_team", ""),
                        "settlement": HISTORY_LABELS.get(_normalise_history_result(item.get("result") or item.get("settlement")), item.get("settlement", "")),
                        "water": item.get("water"), "pnl_1u": item.get("pnl_1u"), "roi": item.get("roi"),
                        "line": item.get("line"), "action": item.get("action", ""), "source": item.get("source", ""),
                    } for item in matches), key=lambda item: (item["date"], item["match"]), reverse=True),
                })
            payload = {
                "schema_version": "football-competition-history-v2",
                "list_date": date, "version": version,
                "history_cutoff": f"list_date < {date}",
                "generated_at": dt.datetime.now(TZ).isoformat(),
                "history_provenance": "EXCEL_FORMAL_HISTORY_ONLY",
                "model_status": MODEL_STATUS,
                "formal_model_equivalence": FORMAL_MODEL_EQUIVALENCE,
                "diagnostic_rows_excluded": len(diagnostic_details),
                "source_detail_rows": len(historical), "rows": output_rows,
            }
            path = SITE / version.lower() / "data" / f"{version.lower()}_competition_history_{date}.json"
            atomic_text(path, json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
            if date == target_date:
                atomic_text(SITE / version.lower() / "data" / f"{version.lower()}_competition_history.json", json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
        if diagnostic_details:
            diagnostic_payload = {
                "schema_version": "football-competition-history-diagnostic-v1",
                "list_date": target_date, "version": version,
                "generated_at": dt.datetime.now(TZ).isoformat(),
                "model_status": MODEL_STATUS,
                "formal_model_equivalence": FORMAL_MODEL_EQUIVALENCE,
                "rows": diagnostic_details,
                "note": "云端便携评估结果，仅供审计；未写入原版正式历史账本。",
            }
            atomic_text(
                SITE / version.lower() / "data" / f"{version.lower()}_competition_history_diagnostic_{target_date}.json",
                json.dumps(diagnostic_payload, ensure_ascii=False, separators=(",", ":")),
            )


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
    target_dir = REPO / "data" / "raw" / "titan007" / list_date.replace("-", "")
    paths = sorted(target_dir.glob("*_titan007_odds_snapshot.csv"), key=lambda p: p.stat().st_mtime)
    # The next-day 20:07 job requests tomorrow's business date, while the
    # fetcher writes the snapshot under the runner's current Beijing date.
    # Accept that same-run snapshot instead of failing after a successful
    # scrape.  Never search arbitrary historical folders.
    if not paths:
        # The fetcher timestamp is intentionally runner-local/UTC for
        # backwards-compatible raw folders, while the requested slate is a
        # Beijing business date.  Around 05:07 Beijing these dates differ by
        # one day; accept only the two current-run date folders, never an
        # arbitrary historical snapshot.
        run_days = {
            dt.datetime.now(TZ).strftime("%Y%m%d"),
            dt.datetime.now().strftime("%Y%m%d"),
        }
        for run_day in run_days:
            run_dir = REPO / "data" / "raw" / "titan007" / run_day
            paths.extend(run_dir.glob("*_titan007_odds_snapshot.csv"))
        paths = sorted(paths, key=lambda p: p.stat().st_mtime)
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

    fetch_started = time.time()
    old_argv = sys.argv
    try:
        sys.argv = [str(REPO / "tools" / "fetch_titan007_odds.py")]
        code = fetch_titan007_odds.main()
    finally:
        sys.argv = old_argv
    if code not in (0, None):
        raise RuntimeError(f"Titan fetch failed with exit code {code}")
    snapshot = latest_snapshot(list_date)
    # Never treat an old file as a successful fresh scrape when a source
    # returned zero rows or exited without materialising a new snapshot.
    if snapshot.stat().st_mtime < fetch_started - 1:
        raise RuntimeError(f"Titan snapshot was not refreshed during this run: {snapshot}")
    return snapshot


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
    def translate(raw: Any, english: Any) -> str:
        raw_text = str(raw or "").strip()
        english_text = str(english or "").strip()
        # Prefer a direct source-label mapping, then use the English provider
        # label.  The latter is essential for BetExplorer-only rows whose
        # Chinese field is blank or arrived as mojibake.
        return (team_map.get(raw_text.casefold()) or
                team_map.get(english_text.casefold()) or raw_text or english_text)
    item["home_team"] = translate(item.get("home_team"), item.get("home_team_en"))
    item["away_team"] = translate(item.get("away_team"), item.get("away_team_en"))
    item["competition"] = (league_map.get(str(item.get("competition", "")).casefold()) or
                            league_map.get(str(item.get("competition_en", "")).casefold()) or
                            item.get("competition", ""))
    market = item.get("market") or {}
    for key in ("giving_team", "receiving_team"):
        if market.get(key):
            market[key] = translate(market[key], market[key])
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
    # All feeds are normalized at ingestion to the project convention:
    # positive home line = home gives, negative home line = home receives.
    # Do not reverse this sign again or let 1X2 prices overwrite a valid AH
    # direction.  Euro prices are only a fallback when the line is exactly
    # level; they are an audit signal, not the handicap-side source of truth.
    if line is not None and abs(line) > 1e-9:
        giving_home = line > 0
    elif euro_home is not None and euro_away is not None:
        giving_home = euro_home < euro_away
    else:
        giving_home = False
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
            "line_home_signed": line,
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
        "model_status": MODEL_STATUS,
        "formal_model_equivalence": FORMAL_MODEL_EQUIVALENCE,
        "is_formal_signal": False,
    }


def ledger_key(item: dict[str, Any]) -> str:
    """Use a date-scoped identity so a reused provider id cannot erase history."""
    date = str(item.get("list_date") or "").strip()
    match_id = str(item.get("match_id") or "").strip()
    if match_id:
        return f"{date}|match_id:{match_id}"
    home = str(item.get("home_team") or "").strip().casefold()
    away = str(item.get("away_team") or "").strip().casefold()
    kickoff_at = str(item.get("kickoff") or "").strip()
    return f"{date}|fixture:{kickoff_at}|{home}|{away}"


def merge(new_rows: list[dict[str, Any]], old_rows: list[dict[str, Any]], list_date: str) -> tuple[list[dict[str, Any]], str | None]:
    old = {ledger_key(x): x for x in old_rows if ledger_key(x)}
    warning = None
    previous_today = sum(1 for x in old.values() if x.get("list_date") == list_date)
    incoming_today = sum(1 for x in new_rows if x.get("list_date") == list_date)
    if previous_today and incoming_today < previous_today * 0.65:
        warning = f"ROW_COUNT_SHRINK_WARNING previous={previous_today} incoming={incoming_today}"
    for fresh in new_rows:
        key = ledger_key(fresh)
        if not str(fresh.get("match_id") or "") and not (fresh.get("home_team") and fresh.get("away_team")):
            continue
        previous = old.get(key)
        # A sudden slate shrink is a source failure until an official
        # cancellation/ postponement feed is supplied. Preserve every prior
        # prematch row and only allow score/state reconciliation while the
        # warning is active; genuinely new fixtures may still be appended.
        if warning and previous and str(fresh.get("list_date")) == list_date and str(previous.get("state")) in {"0", ""}:
            continue
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


def dedupe_fixture_rows(rows: list[dict[str, Any]], list_date: str) -> list[dict[str, Any]]:
    """Collapse Titan/BetExplorer copies of one fixture in a date slate.

    Provider IDs are intentionally *not* the public identity: Titan uses a
    numeric ID while the BetExplorer supplement uses ``BE_<id>``.  We first
    canonicalise competition and team labels, then match the same home/away
    pair on the same Beijing business date within a two-hour time tolerance.
    The winning row is retained with a compact source audit so raw provenance
    is visible without rendering the fixture twice.
    """
    def token(value: Any) -> str:
        text = re.sub(r"<[^>]*>", "", str(value or "")).strip().casefold()
        text = text.replace("&", "and")
        text = re.sub(r"\bfootball\s+club\b", "", text)
        return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", text)

    team_map, league_map = aliases()
    team_identity: dict[str, str] = {}
    for raw, stable in CROSS_PROVIDER_TEAM_ALIASES.items():
        team_identity[token(raw)] = stable
    # Also invert the checked-in English -> source-label aliases.  This covers
    # provider mojibake/source spellings without making those labels visible.
    for raw, display in team_map.items():
        stable = f"alias:{token(raw)}"
        if token(raw):
            team_identity.setdefault(token(raw), stable)
        # A legacy alias file may contain U+FFFD replacement characters after
        # a provider encoding failure. Do not turn that lossy text into an
        # identity key; it can collapse unrelated clubs.
        if "\ufffd" not in str(display) and token(display):
            team_identity.setdefault(token(display), stable)

    competition_identity: dict[str, str] = {}
    for raw, display in league_map.items():
        stable = token(display)
        if token(raw):
            competition_identity.setdefault(token(raw), stable)
        if stable:
            competition_identity.setdefault(stable, stable)
    competition_identity.update({
        token("be:j1-league"): "j1",
        token("j1-league"): "j1",
        token("\u65e5\u804c\u8054"): "j1",
        token("be:j2-league"): "j2",
        token("j2-league"): "j2",
        token("\u65e5\u804c\u4e59"): "j2",
        token("be:j3-league"): "j3",
        token("j3-league"): "j3",
        token("\u65e5\u804c\u4e19"): "j3",
        token("be:j-league-cup"): "jleaguecup",
        token("j-league-cup"): "jleaguecup",
        token("\u65e5\u8054\u676f"): "jleaguecup",
    })

    def team(item: dict[str, Any], side: str) -> str:
        market = item.get("market") or {}
        candidates = (
            item.get(f"{side}_team_en"),
            item.get(f"{side}_team"),
            market.get(f"{side}_team"),
        )
        for raw in candidates:
            key = token(raw)
            if not key:
                continue
            if key in team_identity:
                return team_identity[key]
            mapped = team_map.get(str(raw).strip().casefold())
            if mapped and token(mapped) in team_identity:
                return team_identity[token(mapped)]
            return key
        return ""

    def competition(item: dict[str, Any]) -> str:
        market = item.get("market") or {}
        candidates = (
            item.get("competition_en"), item.get("competition"),
            item.get("league_en"), item.get("league_cn"),
            market.get("competition"),
        )
        for raw in candidates:
            key = token(raw)
            if not key:
                continue
            if key in competition_identity:
                return competition_identity[key]
            mapped = league_map.get(str(raw).strip().casefold())
            if mapped:
                return token(mapped)
            return key
        return ""

    def kickoff_at(item: dict[str, Any]) -> dt.datetime | None:
        raw = str(item.get("kickoff") or item.get("bj_time") or item.get("match_time_en") or "").strip()
        if not raw:
            return None
        try:
            parsed = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            try:
                parsed = dt.datetime.strptime(raw[:16], "%Y-%m-%d %H:%M")
            except ValueError:
                return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=TZ)
        return parsed.astimezone(TZ)

    def provider(item: dict[str, Any]) -> str:
        source = " ".join(str(item.get(k) or "") for k in ("match_id", "source_provider", "source_snapshot", "source_page"))
        return "BetExplorer" if source.casefold().startswith("be_") or "betexplorer" in source.casefold() else "Titan007"

    def score(item: dict[str, Any]) -> tuple[int, int, int, int, int]:
        market = item.get("market") or {}
        has_score = bool(_history_score(item.get("score")))
        started = str(item.get("state") or "") not in {"", "0"}
        return (
            1 if has_score and started else 0,
            1 if market.get("current_complete") else 0,
            1 if market.get("euro_complete") else 0,
            1 if provider(item) == "Titan007" else 0,
            1 if item.get("kickoff") else 0,
        )

    def same_group(left: dict[str, Any], right: dict[str, Any]) -> bool:
        if str(left.get("list_date")) != str(right.get("list_date")):
            return False
        if competition(left) != competition(right) or team(left, "home") != team(right, "home") or team(left, "away") != team(right, "away"):
            return False
        ltime, rtime = kickoff_at(left), kickoff_at(right)
        if ltime is None or rtime is None:
            # Missing kickoff is never enough to collapse two provider rows.
            return False
        return abs((ltime - rtime).total_seconds()) <= 2 * 3600

    groups: list[list[dict[str, Any]]] = []
    output: list[dict[str, Any]] = []
    for item in rows:
        if str(item.get("list_date")) != list_date:
            output.append(item)
            continue
        group = next((g for g in groups if same_group(g[0], item)), None)
        if group is None:
            groups.append([item])
        else:
            group.append(item)

    for group in groups:
        winner = max(group, key=score)
        if len(group) > 1:
            source_ids = list(dict.fromkeys(str(x.get("match_id") or "") for x in group if str(x.get("match_id") or "")))
            winner["duplicate_source_match_ids"] = source_ids
            winner["duplicate_source_count"] = len(source_ids)
            winner["duplicate_sources"] = [
                {"match_id": str(x.get("match_id") or ""), "provider": provider(x), "kickoff": x.get("kickoff") or x.get("bj_time") or ""}
                for x in group
            ]
        output.append(winner)

    # Preserve the original ordering of non-target dates while keeping the
    # target slate in the first provider's feed order.
    target_ids = {id(x) for g in groups for x in g}
    target_output = [x for x in output if id(x) not in target_ids]
    target_output.extend(max(g, key=score) for g in groups)
    # The construction above may reorder rows; restore the incoming order by
    # the earliest member of each group.
    order = {id(item): index for index, item in enumerate(rows)}
    target_output.sort(key=lambda x: order.get(id(x), 10**9))
    return target_output

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


def source_quality_audit(incoming: list[dict[str, Any]], current: list[dict[str, Any]]) -> dict[str, Any]:
    """Record source/market completeness without changing model gates."""
    def source_name(row: dict[str, Any]) -> str:
        text = " ".join(str(row.get(key) or "") for key in ("source_snapshot", "match_id", "source"))
        return "BetExplorer" if "betexplorer" in text.casefold() or str(row.get("match_id", "")).startswith("BE_") else "Titan007"

    def complete(row: dict[str, Any], field: str) -> bool:
        return bool((row.get("market") or {}).get(field))

    source_counts: dict[str, int] = {}
    for row in incoming:
        source_counts[source_name(row)] = source_counts.get(source_name(row), 0) + 1
    return {
        "incoming_rows": len(incoming),
        "target_rows_after_dedupe": len(current),
        "provider_duplicate_rows_removed": sum(max(int(row.get("duplicate_source_count", 1)) - 1, 0) for row in current),
        "provider_duplicate_groups": sum(1 for row in current if int(row.get("duplicate_source_count", 1) or 1) > 1),
        "source_counts": source_counts,
        "titan007_rows": source_counts.get("Titan007", 0),
        "betexplorer_rows": source_counts.get("BetExplorer", 0),
        "asian_complete_rows": sum(complete(row, "current_complete") for row in incoming),
        "euro_complete_rows": sum(complete(row, "euro_complete") for row in incoming),
        "both_markets_complete_rows": sum(complete(row, "current_complete") and complete(row, "euro_complete") for row in incoming),
        "missing_asian_rows": sum(not complete(row, "current_complete") for row in incoming),
        "missing_euro_rows": sum(not complete(row, "euro_complete") for row in incoming),
        "started_rows": sum(str(row.get("state") or "") not in {"0", ""} for row in incoming),
        "captured_at": dt.datetime.now(TZ).isoformat(),
    }


def rich_v4_row(item: dict[str, Any]) -> dict[str, Any]:
    """Adapt the portable cloud row to the original rich V4 dashboard schema."""
    q = evaluate(item, "V4")
    m = dict(item.get("market") or {})
    line = f(m.get("line"))
    giving_home = bool(line is not None and m.get("giving_team") == item.get("home_team"))
    # `signed` is the home-team perspective.  The selected handicap shown in
    # the card must instead use the selected side's perspective: a giving
    # side is always shown with a negative line and a receiving side positive.
    signed = -abs(line) if giving_home else abs(line) if line is not None else None
    m.update({
        "competition": item.get("competition", ""),
        "home_team": item.get("home_team", ""),
        "away_team": item.get("away_team", ""),
        "home_handicap_signed": signed,
        "away_handicap_signed": -signed if signed is not None else None,
    })
    started = str(item.get("state") or "") not in {"0", ""}
    # A started/settled row is decision-locked.  Preserve the frozen choice
    # for history queries instead of replacing it with an empty UNAVAILABLE
    # payload; only the live market refresh is prohibited.
    frozen = item.get("v4") if isinstance(item.get("v4"), dict) else {}
    locked_q = frozen or q
    final_decision = str(locked_q.get("decision") or q["decision"]) if started else q["decision"]
    selected_side = locked_q.get("selected_side", "") if started else q.get("selected_side", "")
    selected_team = locked_q.get("selected_team", "") if started else q.get("selected_team", "")
    selected_water = locked_q.get("selected_water") if started else q.get("selected_water")
    selected_handicap = None
    if selected_side:
        selected_handicap = (-abs(line) if selected_side == "giving" else abs(line)) if line is not None else None
    return {
        **item,
        "model_id": "V4",
        "model_version": "V4",
        "model_status": MODEL_STATUS,
        "formal_model_equivalence": FORMAL_MODEL_EQUIVALENCE,
        "is_formal_signal": False,
        "domain": "GITHUB_CLOUD",
        "league_level": "UNKNOWN",
        "market": m,
        "analysis_status": "NOT_PREMATCH" if started else ("EVALUATED" if q["quality_gate_passed"] else "MISSING_DATA"),
        "final_decision": final_decision,
        "decision_status": "NOT_PREMATCH" if started else ("BET" if q["bettable"] else "NO_BET"),
        "quality_gate_passed": q["quality_gate_passed"],
        "quality_gate_reasons": q["quality_gate_reasons"],
        "selected_side": selected_side,
        "selected_team": selected_team,
        "selected_handicap_signed": selected_handicap,
        "selected_handicap_team": selected_team,
        "selected_water_hk": selected_water,
        "candidate_side": selected_side,
        "candidate_team": selected_team,
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
    decision_key = version.lower()

    def decision_payload(row: dict[str, Any]) -> dict[str, Any]:
        value = row.get(decision_key)
        return value if isinstance(value, dict) else {}

    payload = {
        "list_date": date, "version": version, "model_id": version,
        "model_version": version, "generated_at": dt.datetime.now(TZ).isoformat(),
        "model_status": MODEL_STATUS,
        "formal_model_equivalence": FORMAL_MODEL_EQUIVALENCE,
        "is_formal_signal": False,
        "summary": {
            "total": len(payload_rows),
            "computed": sum(1 for row in payload_rows if decision_payload(row).get("decision")),
            # The checked-in rich V4 shell consumes these exact lower-case
            # counters.  Keep the legacy `BET` alias for the portable shell.
            "giving": sum(1 for row in payload_rows if decision_payload(row).get("decision") == "BET_GIVING"),
            "receiving": sum(1 for row in payload_rows if decision_payload(row).get("decision") == "BET_RECEIVING"),
            "no_bet": sum(1 for row in payload_rows if str(decision_payload(row).get("decision") or "") == "NO_BET"),
            "BET": sum(1 for row in payload_rows if decision_payload(row).get("bettable")),
            "A": sum(1 for row in payload_rows if str(row.get("grade") or "") == "A"),
            "B": sum(1 for row in payload_rows if str(row.get("grade") or "") == "B"),
            "C": sum(1 for row in payload_rows if str(row.get("grade") or "") == "C"),
            "N": sum(1 for row in payload_rows if str(row.get("grade") or "") == "N"),
            "neutral": sum(1 for row in payload_rows if str(decision_payload(row).get("decision") or "") in {"NO_BET", ""}),
            "missing_data": sum(1 for row in payload_rows if not (row.get("market") or {}).get("current_complete")),
            "not_prematch": sum(1 for row in payload_rows if str(row.get("state") or "") not in {"0", ""}),
            "excluded_abnormal": 0,
            "errors": 0,
        },
        "dedupe_audit": {
            "output_rows": len(payload_rows),
            "duplicates_removed": sum(max(int(row.get("duplicate_source_count", 1)) - 1, 0) for row in payload_rows),
            "duplicate_groups": sum(1 for row in payload_rows if int(row.get("duplicate_source_count", 1) or 1) > 1),
        },
        "matches": payload_rows,
    }
    for x in payload["matches"]:
        # Started/settled rows are decision-locked.  Rendering must not
        # re-evaluate them with the current state and erase the historical
        # V3/V4 decision that is used by the history panels.
        if str(x.get("state") or "") in {"0", ""} or not x.get(decision_key):
            x[decision_key] = evaluate(x, version)
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
        rich = re.sub(r'const defaultDate = "[^"]*"', f'const defaultDate = "{date}"', rich, count=1)
        marker, end_marker = "const cardsData = ", "\ncardsData.forEach"
        start = rich.find(marker)
        end = rich.find(end_marker, start + len(marker)) if start >= 0 else -1
        if start >= 0 and end > start:
            old_cards = []
            try:
                old_start = start + len(marker)
                old_payload = rich[old_start:end].strip().rstrip(";")
                old_cards = json.loads(old_payload) if old_payload.startswith("[") else []
            except (json.JSONDecodeError, TypeError):
                old_cards = []
            cards = []
            for item in source_rows:
                q = item.get("v3") or evaluate(item, "V3")
                m = item.get("market") or {}
                cards.append({
                    "date": item.get("list_date", date), "league": item.get("competition", ""),
                    "model_status": MODEL_STATUS, "formal_model_equivalence": FORMAL_MODEL_EQUIVALENCE,
                    "is_formal_signal": False,
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
                    "ah": (f"让球方 {m.get('giving_team','')} | 盘口 {-abs(m.get('line')) if m.get('line') is not None else ''} | "
                           f"让球方水位 {m.get('giving_water')} / 受让方水位 {m.get('receiving_water')}" if m.get("current_complete") else "未接入"),
                    "handicap_giving_team": m.get("giving_team", ""),
                    "handicap_receiving_team": m.get("receiving_team", ""),
                    "handicap_home_signed": m.get("line_home_signed"),
                    "euro": f"即 {m.get('euro_home')}/{m.get('euro_draw')}/{m.get('euro_away')}" if m.get("euro_complete") else "未接入",
                    "ah_ok": bool(m.get("current_complete")), "euro_ok": bool(m.get("euro_complete")),
                    "result": item.get("score", "") or "待赛", "pnl": "不计", "status": "已结算" if item.get("state") not in {"0", ""} else "待赛",
                    "grade": "BET" if q.get("bettable") else "NA", "error": "、".join(q.get("quality_gate_reasons", [])),
                })
            # Keep prior dates in the rich shell so competition/side history
            # panels continue to have historical samples after a refresh.
            historical = [item for item in old_cards if str(item.get("date", "")) != date]
            replacement = marker + json.dumps(historical + cards, ensure_ascii=False, separators=(",", ":"))
            atomic_text(shell, rich[:start] + replacement + rich[end:])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list-date", default=(dt.datetime.now(TZ).date().isoformat()))
    ap.add_argument("--from-csv", help="offline test input; skips network fetch")
    args = ap.parse_args()
    date = args.list_date
    snapshot = Path(args.from_csv) if args.from_csv else run_fetch(date)
    with snapshot.open("r", encoding="utf-8-sig", newline="") as h:
        incoming = [market_row(x, date) for x in csv.DictReader(h)]
    if not incoming:
        raise RuntimeError(f"FETCH_EMPTY_SNAPSHOT date={date} snapshot={snapshot}")
    if not any(str(x.get("match_id") or "").strip() for x in incoming):
        raise RuntimeError(f"FETCH_INVALID_SNAPSHOT_NO_MATCH_IDS date={date} snapshot={snapshot}")
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
    rows = dedupe_fixture_rows(rows, date)
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
        for version in ("v3", "v4"):
            decision = x.get(version)
            if isinstance(decision, dict):
                decision.setdefault("model_status", MODEL_STATUS)
                decision.setdefault("formal_model_equivalence", FORMAL_MODEL_EQUIVALENCE)
                decision["is_formal_signal"] = False
    atomic_text(LEDGER_JSON, json.dumps(rows, ensure_ascii=False, indent=2))
    write_csv(rows)
    current = [x for x in rows if x.get("list_date") == date]
    build_competition_history(rows, date)
    counts = {"rows": len(current), "V3": sum(bool(x.get("v3", {}).get("bettable")) for x in current), "V4": sum(bool(x.get("v4", {}).get("bettable")) for x in current)}
    quality = source_quality_audit(incoming, current)
    source_counts = {
        "incoming_snapshot_rows": len(incoming),
        "previous_ledger_rows": len(old_rows),
        "merged_ledger_rows": len(rows),
        "target_date_rows": len(current),
    }
    dashboard("V3", date, current); dashboard("V4", date, current)
    atomic_text(DATA / "last_run.json", json.dumps({
        "list_date": date, "counts": counts, "source_counts": source_counts,
        "source_quality": quality, "warning": warning, "snapshot": str(snapshot),
        "generated_at": dt.datetime.now(TZ).isoformat(), "model_status": MODEL_STATUS,
        "formal_model_equivalence": FORMAL_MODEL_EQUIVALENCE,
    }, ensure_ascii=False, indent=2))
    # Notification is intentionally sent by the workflow only after the
    # gh-pages push and online Pages verification.  Sending here would report
    # success before the published dashboard exists.
    print(json.dumps({"snapshot": str(snapshot), "source_counts": source_counts, "source_quality": quality, "model_status": MODEL_STATUS, **counts, "warning": warning}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
