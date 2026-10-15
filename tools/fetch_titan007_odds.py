from __future__ import annotations

import asyncio
import csv
from concurrent.futures import ThreadPoolExecutor, as_completed
import datetime as dt
import hashlib
import html
import json
import re
import runpy
import shutil
import subprocess
import sys
import time
import threading
import unicodedata
import os
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path


# The livestatic host intermittently resets TLS connections.  The bf host
# serves the same official Titan007 VBS/XML payloads and is the stable
# transport fallback for the daily refresh.
BASE = "https://bf.titan007.com/vbsxml"
REFERER = "https://live.titan007.com/oldIndexall.aspx"
# Portable root: local runs keep the legacy path; GitHub runs set FOOTBALL_RAW_ROOT.
_DEFAULT_OUT_ROOT = Path(r'D:\codex\v3_legacy\outputs\football_odds_trader\raw\titan007')
OUT_ROOT = Path(os.environ.get('FOOTBALL_RAW_ROOT', str(_DEFAULT_OUT_ROOT)))
BF_BASE = "https://bf.titan007.com"
VIP_BASE = "https://vip.titan007.com"
EURO_INDEX = "https://1x2.titan007.com/index_vip.aspx"
EURO_TXT_BASE = "https://txt.titan007.com/1x2"
FIVEHUNDRED_MATCH_XML = "https://www.500.com/static/public/jczq/xml/match/match.xml"
FIVEHUNDRED_ODDS_XML = "https://www.500.com/static/public/jczq/xml/odds/odds.xml"
FIVEHUNDRED_REFERER = "https://trade.500.com/jczq/"
# The landing page intentionally exposes only a small "next 10" slice.  The
# public next-matches page contains the broader fixture roster (including the
# major leagues and the Japan/Korea tiers we use as the first fallback).
BETEXPLORER_HOME = "https://www.betexplorer.com/football/"
BETEXPLORER_NEXT = "https://www.betexplorer.com/football/next/"
BETEXPLORER_ODDS = "https://www.betexplorer.com/match-odds/{event_id}/0/ah/bestOdds/?lang=en"
BETEXPLORER_EURO_ODDS = "https://www.betexplorer.com/match-odds/{event_id}/0/1x2/bestOdds/?lang=en"
ROSTER_ROOT = OUT_ROOT.parents[1] / "ledger" / "slate_rosters"
HTTP_CACHE = OUT_ROOT / "cache" / "http"
SNAPSHOT_META_INDEX = HTTP_CACHE / "snapshot_metadata_index_v1.json"
PREMATCH_ODDS_INDEX = HTTP_CACHE / "prematch_odds_index_v1.json"
_REQUEST_LOCK = threading.Lock()
_LAST_REQUEST_AT = 0.0
_MIN_REQUEST_INTERVAL = float(os.environ.get("TITAN_MIN_REQUEST_INTERVAL", "0.30"))


def throttle(min_interval_seconds: float | None = None) -> None:
    """Bound request rate across worker threads for Titan public pages."""
    global _LAST_REQUEST_AT
    if min_interval_seconds is None:
        min_interval_seconds = _MIN_REQUEST_INTERVAL
    with _REQUEST_LOCK:
        wait = min_interval_seconds - (time.monotonic() - _LAST_REQUEST_AT)
        if wait > 0:
            time.sleep(wait)
        _LAST_REQUEST_AT = time.monotonic()


def cached_public_payload(url: str, max_age_seconds: int = 300) -> bytes | None:
    key = hashlib.sha256(url.encode("utf-8")).hexdigest()
    path = HTTP_CACHE / f"{key}.bin"
    if path.exists() and time.time() - path.stat().st_mtime <= max_age_seconds:
        return path.read_bytes()
    return None


def save_public_cache(url: str, raw: bytes) -> None:
    HTTP_CACHE.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(url.encode("utf-8")).hexdigest()
    (HTTP_CACHE / f"{key}.bin").write_bytes(raw)
    (HTTP_CACHE / f"{key}.json").write_text(
        json.dumps({"url": url, "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(), "bytes": len(raw)}, ensure_ascii=False),
        encoding="utf-8",
    )


def fetch(name: str, stamp: str, out_dir: Path) -> Path:
    url = f"{BASE}/{name}?r=007{int(time.time() * 1000)}"
    target = out_dir / f"{stamp}_{name.replace('/', '_')}"
    req = urllib.request.Request(
        url,
        headers={
            "Referer": REFERER,
            "User-Agent": "Mozilla/5.0",
            "Accept": "*/*",
        },
    )
    raw = cached_public_payload(f"{BASE}/{name}")
    if raw is not None and len(raw) <= 2048:
        # Do not reuse a cached 404/500 HTML error as if it were market data.
        raw = None
    last_error = None
    curl = shutil.which("curl.exe") or shutil.which("curl")
    # The public VBS/XML files are sometimes served by a slow legacy handler.
    # Probe with curl first so one stale endpoint cannot stall the daily run.
    if raw is None and curl:
        try:
            completed = subprocess.run(
                [
                    curl, "-k", "-sS", "-L", "--max-time", "15",
                    "-A", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36",
                    "-e", REFERER, "-H", "Accept: */*", url,
                ],
                check=True,
                capture_output=True,
                timeout=20,
            )
            if completed.stdout:
                raw = completed.stdout
        except Exception as curl_exc:
            last_error = curl_exc
    if raw is None:
        for attempt in range(2):
            try:
                throttle()
                with urllib.request.urlopen(req, timeout=12) as resp:
                    raw = resp.read()
                break
            except Exception as exc:
                last_error = exc
                time.sleep(0.5 * (attempt + 1))
    if raw is None:
        raise last_error or RuntimeError("Titan public fetch failed")
    if len(raw) > 2048:
        save_public_cache(f"{BASE}/{name}", raw)
    target.write_bytes(raw)
    return target


def fetch_url(url: str, stamp: str, out_dir: Path, label: str, referer: str = REFERER) -> tuple[Path, bytes]:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", label).strip("_")
    target = out_dir / f"{stamp}_{safe}"
    cached = cached_public_payload(url)
    if cached is not None:
        target.write_bytes(cached)
        return target, cached
    cache_key = f"r=007{int(time.time() * 1000)}"
    fresh_url = f"{url}&{cache_key}" if "?" in url else f"{url}?{cache_key}"
    urls = [fresh_url]
    if fresh_url.startswith("https://bf.titan007.com/"):
        urls.append("http://bf.titan007.com/" + fresh_url.removeprefix("https://bf.titan007.com/"))
    last_error: Exception | None = None
    raw = b""
    for candidate in urls:
        curl = shutil.which("curl.exe") or shutil.which("curl")
        if curl:
            try:
                throttle()
                completed = subprocess.run(
                    [
                        curl, "-k", "-sS", "-L", "--max-time", "15",
                        "-A", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36",
                        "-e", referer, "-H", "Accept: */*", candidate,
                    ],
                    check=True,
                    capture_output=True,
                    timeout=20,
                )
                if completed.stdout:
                    raw = completed.stdout
                    break
            except Exception as curl_exc:
                last_error = curl_exc
        req = urllib.request.Request(
            candidate,
            headers={
                "Referer": referer,
                "User-Agent": "Mozilla/5.0",
                "Accept": "*/*",
            },
        )
        for attempt in range(2):
            try:
                throttle()
                with urllib.request.urlopen(req, timeout=12) as resp:
                    raw = resp.read()
                break
            except Exception as exc:
                last_error = exc
                time.sleep(0.75 * (attempt + 1))
        if raw:
            break
    else:
        assert last_error is not None
        raise last_error
    target.write_bytes(raw)
    save_public_cache(url, raw)
    return target, raw


def fetch_betexplorer_event(url: str, stamp: str, out_dir: Path, label: str, referer: str) -> tuple[Path, bytes]:
    """Fetch a public BetExplorer event page with a short bounded timeout.

    BetExplorer is a supplement.  A single dead/slow event must never hold the
    whole daily refresh behind Titan's strict missing-data gate.
    """
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", label).strip("_")
    target = out_dir / f"{stamp}_{safe}"
    cached = cached_public_payload(url)
    if cached is not None:
        target.write_bytes(cached)
        return target, cached
    throttle(float(os.environ.get("BETEXPLORER_MIN_REQUEST_INTERVAL", "0.15")))
    req = urllib.request.Request(
        url,
        headers={
            "Referer": referer,
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36",
            "Accept": "application/json,text/plain,*/*",
        },
    )
    with urllib.request.urlopen(req, timeout=float(os.environ.get("BETEXPLORER_TIMEOUT", "10"))) as resp:
        raw = resp.read()
    target.write_bytes(raw)
    if len(raw) > 2048:
        save_public_cache(url, raw)
    return target, raw


def read_text(path: Path) -> str:
    raw = path.read_bytes()
    return decode_text(raw)


def decode_text(raw: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def parse_schedule(text: str) -> dict[str, dict[str, str]]:
    matches: dict[str, dict[str, str]] = {}
    for m in re.finditer(r'A\[\d+\]="(.*?)"\.split\(\'\^\'\);', text, re.S):
        row = m.group(1).split("^")
        if len(row) < 37:
            continue
        match_id = row[0]
        matches[match_id] = {
            "match_id": match_id,
            "league_cn": row[2],
            "league_tw": row[3],
            "home_cn": row[5],
            "home_tw": row[6],
            "away_cn": row[8],
            "away_tw": row[9],
            "bj_time": f"{row[36]} {row[11]}",
            "state": row[13],
            "home_score": row[14],
            "away_score": row[15],
            "home_rank_or_stage": row[22] if len(row) > 22 else "",
            "away_rank_or_stage": row[23] if len(row) > 23 else "",
            "initial_ah_hint": row[29] if len(row) > 29 else "",
            # Titan's current bfdata_ut schema puts the opening total line at
            # index 46.  Index 43 is the year from the date tuple; treating it
            # as a total line silently creates a bogus "2026" market hint.
            "initial_total_hint": row[46] if len(row) > 46 else "",
        }
    return matches


def to_number(value: str) -> float | None:
    value = value.strip()
    if value == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def parse_matrix(raw: str) -> list[list[float | None]]:
    raw = raw.strip()
    if raw.startswith("[["):
        raw = raw[2:]
    if raw.endswith("]]"):
        raw = raw[:-2]
    rows = []
    for row in raw.split("],["):
        rows.append([to_number(x) for x in row.split(",")])
    return rows


def parse_sbodds(text: str) -> dict[str, list[list[float | None]]]:
    data: dict[str, list[list[float | None]]] = {}
    for m in re.finditer(r"sData\[(\d+)\]=(\[\[.*?\]\]);", text, re.S):
        data[m.group(1)] = parse_matrix(m.group(2))
    return data


def parse_change_xml(text: str) -> dict[str, dict[str, str]]:
    changes: dict[str, dict[str, str]] = {}
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        # Titan auxiliary XML may return an HTML 404 page while the main
        # roster remains available.  Treat that auxiliary source as missing;
        # never interpret the error page as market data.
        return changes
    for node in root.findall(".//m"):
        fields = (node.text or "").split(",")
        if len(fields) < 13:
            continue
        changes[fields[0]] = {
            "xml_ah_line": fields[2],
            "xml_ah_home_water": fields[3],
            "xml_ah_away_water": fields[4],
            "xml_euro_home": fields[6],
            "xml_euro_draw": fields[7],
            "xml_euro_away": fields[8],
            "xml_total_line": fields[10],
            "xml_total_over_water": fields[11],
            "xml_total_under_water": fields[12],
        }
    return changes


def clean_html_text(value: str) -> str:
    value = re.sub(r"<br\s*/?>", " ", value, flags=re.I)
    value = re.sub(r"<[^>]+>", "", value)
    value = html.unescape(value)
    return " ".join(value.replace("\xa0", " ").split()).strip()


def playwright_executable() -> str | None:
    """Return an explicit browser path when one is installed.

    GitHub-hosted Ubuntu runners use Playwright's managed Chromium, while the
    local Windows skill normally uses Chrome/Edge.  The old Windows-only path
    made the fallback silently impossible in cloud runs.
    """
    configured = str(os.environ.get("TITAN_BROWSER_EXECUTABLE", "")).strip()
    if configured and Path(configured).exists():
        return configured
    candidates = (
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
    )
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    for command in ("chromium", "chromium-browser", "google-chrome", "microsoft-edge"):
        resolved = shutil.which(command)
        if resolved:
            return resolved
    return None


def clean_team_text(value: str) -> tuple[str, str]:
    text = clean_html_text(value)
    ranks = re.findall(r"\[([^\]]+)\]", text)
    name = re.sub(r"\[[^\]]+\]", "", text)
    name = re.sub(r"\(主\)", "", name)
    name = " ".join(name.split()).strip()
    return name, (ranks[-1] if ranks else "")


def extract_cells(row_html: str) -> list[tuple[str, str]]:
    return re.findall(r"<td\b([^>]*)>(.*?)</td>", row_html, re.I | re.S)


def parse_future_schedule(text: str) -> dict[str, dict[str, str]]:
    rows: dict[str, dict[str, str]] = {}
    for m in re.finditer(r"<tr\b(?=[^>]*\bsId=['\"](\d+)['\"])(.*?)</tr>", text, re.I | re.S):
        match_id = m.group(1)
        block = m.group(0)
        cells = extract_cells(block)
        if len(cells) < 6:
            continue
        league = clean_html_text(cells[0][1])
        bj_time = clean_html_text(cells[1][1])
        status = clean_html_text(cells[2][1])
        home, home_rank = clean_team_text(cells[3][1])
        away, away_rank = clean_team_text(cells[5][1])
        if not (league and bj_time and home and away):
            continue
        state = "0"
        if "推迟" in status:
            state = "-14"
        elif "取消" in status:
            state = "-10"
        elif "待定" in status:
            state = "-11"
        rows[match_id] = {
            "match_id": match_id,
            "league_cn": league,
            "league_tw": "",
            "home_cn": home,
            "home_tw": "",
            "away_cn": away,
            "away_tw": "",
            "bj_time": bj_time,
            "state": state,
            "home_score": "",
            "away_score": "",
            "home_rank_or_stage": home_rank,
            "away_rank_or_stage": away_rank,
            "initial_ah_hint": "",
            "initial_total_hint": "",
            "source_page": "Titan007 Next",
        }
    return rows


def parse_common_lines(text: str) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for part in text.strip().split("!"):
        fields = part.split("^")
        if len(fields) < 3:
            continue
        match_id, ah_line, total_line = fields[:3]
        out[match_id] = {
            "future_ah_line_hint": ah_line,
            "future_total_line_hint": total_line,
        }
    return out


def _fivehundred_team_key(value: str) -> str:
    """Normalize 500.com/Titan team labels for conservative cross-source joins."""
    text = clean_html_text(value)
    text = unicodedata.normalize("NFKC", text).lower()
    text = re.sub(
        r"(?<![a-z])(fc|cf|sc|afc|ac|cd|fk|sk|sv|if|bk|ik|as|us|ud|ue)(?![a-z])",
        "",
        text,
        flags=re.I,
    )
    text = text.replace("队", "")
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", text)


FIVEHUNDRED_TEAM_ALIASES = {
    "京都": "京都不死鸟",
    "町田泽维": "町田泽维亚",
    "拜仁": "拜仁慕尼黑",
    "巴列卡诺": "巴列卡诺竞技",
    "毕尔巴鄂": "毕尔巴鄂竞技",
    "柏林联合": "柏林联合",
    "埃沃斯堡": "埃弗斯堡",
    "伊普斯": "伊普斯维奇",
    "维拉": "阿斯顿维拉",
    "布伦特": "布伦特福德",
    "马竞": "马德里竞技",
}


def _fivehundred_team_canonical(value: str) -> str:
    key = _fivehundred_team_key(value)
    return _fivehundred_team_key(FIVEHUNDRED_TEAM_ALIASES.get(key, key))


def _fivehundred_match_time(value: str) -> tuple[str, str] | None:
    match = re.search(r"(\d{4}-\d{1,2}-\d{1,2})\s+(\d{1,2}:\d{2})", str(value or ""))
    if not match:
        return None
    year, month, day = match.group(1).split("-")
    hour, minute = match.group(2).split(":")
    return f"{int(year):04d}-{int(month):02d}-{int(day):02d}", f"{int(hour):02d}:{minute}"


def _future_row_time(value: str, year: str) -> tuple[str, str] | None:
    match = re.search(r"(\d{1,2})-(\d{1,2})\s+(\d{1,2}:\d{2})", str(value or ""))
    if not match:
        return None
    month, day = match.group(1), match.group(2)
    hour, minute = match.group(3).split(":")
    return f"{int(year):04d}-{int(month):02d}-{int(day):02d}", f"{int(hour):02d}:{minute}"


def _parse_handicap_text(value: str) -> float | None:
    text = unicodedata.normalize("NFKC", clean_html_text(value)).strip().lower()
    if not text:
        return None
    negative = text.startswith("受") or text.startswith("-")
    text = text.lstrip("受让 ")
    aliases = {
        "平手": 0.0,
        "平": 0.0,
        "平手/半球": 0.25,
        "平/半": 0.25,
        "平半": 0.25,
        "半球": 0.5,
        "半": 0.5,
        "半球/一球": 0.75,
        "半/一": 0.75,
        "半一": 0.75,
        "一球": 1.0,
        "一": 1.0,
        "一球/球半": 1.25,
        "一/球半": 1.25,
        "一球半": 1.5,
        "球半": 1.5,
        "球半/两球": 1.75,
        "球半/二": 1.75,
        "两球": 2.0,
        "二球": 2.0,
        "两球/两球半": 2.25,
        "二/二半": 2.25,
        "两球半": 2.5,
    }
    number = re.fullmatch(r"[-+]?\d+(?:\.\d+)?", text)
    if number:
        line = float(number.group(0))
        return -abs(line) if negative else line
    if text in aliases:
        line = aliases[text]
        return -line if negative else line
    parts = re.split(r"[/\\]", text)
    if len(parts) == 2:
        # Mobile Analysis expresses quarter-ball lines as numeric pairs such
        # as ``-0/0.5``.  Treat the pair as the midpoint while preserving the
        # sign; this is a source value, not an inferred market.
        numeric_parts: list[float] = []
        for part in parts:
            try:
                numeric_parts.append(abs(float(part)))
            except ValueError:
                numeric_parts = []
                break
        if len(numeric_parts) == 2:
            line = sum(numeric_parts) / 2.0
            return -line if negative else line
    if len(parts) == 2 and parts[0] in aliases and parts[1] in aliases:
        line = (aliases[parts[0]] + aliases[parts[1]]) / 2.0
        return -line if negative else line
    return None


def _parse_fivehundred_triplet(value: str) -> tuple[float, float, float] | None:
    parts = [part.strip() for part in str(value or "").split(",")]
    if len(parts) != 3:
        return None
    try:
        left, right = float(parts[0]), float(parts[2])
    except (TypeError, ValueError):
        return None
    line = _parse_handicap_text(parts[1])
    if line is None or not (0.01 <= left <= 3.0 and 0.01 <= right <= 3.0):
        return None
    return left, line, right


def _parse_fivehundred_europe_triplet(value: str) -> tuple[float, float, float] | None:
    """Parse 500.com's three-way decimal odds (not an AH line)."""
    parts = [part.strip() for part in str(value or "").split(",")]
    if len(parts) != 3:
        return None
    try:
        values = tuple(float(part) for part in parts)
    except (TypeError, ValueError):
        return None
    if any(value <= 1.0 or value > 100.0 for value in values):
        return None
    return values  # type: ignore[return-value]


def _fetch_fivehundred_xml(url: str, stamp: str, out_dir: Path, label: str) -> ET.Element:
    # A cache-buster is intentional: 500.com occasionally serves a short WAF
    # page with HTTP 200.  Never cache that page as if it were a feed.
    fresh_url = f"{url}?x={int(time.time() * 1000)}"
    _path, raw = fetch_url(fresh_url, stamp, out_dir, label, referer=FIVEHUNDRED_REFERER)
    text = decode_text(raw).lstrip()
    if "<matches>" not in text or "<match" not in text:
        raise RuntimeError(f"500.com XML invalid or WAF page: bytes={len(raw)}")
    try:
        return ET.fromstring(text)
    except ET.ParseError as exc:
        raise RuntimeError(f"500.com XML parse failed: {exc}") from exc


def load_fivehundred_odds(stamp: str, out_dir: Path, target_date: str) -> dict[str, dict[str, object]]:
    """Load the public 500.com current Asian/OU feed for exact cross-source joins.

    This is a supplement, not a replacement for Titan IDs.  It intentionally
    returns only rows whose teams and Beijing kickoff minute agree; unmatched
    Titan fixtures remain missing and therefore unbettable.
    """
    match_root = _fetch_fivehundred_xml(FIVEHUNDRED_MATCH_XML, stamp, out_dir, "fivehundred_match.xml")
    odds_root = _fetch_fivehundred_xml(FIVEHUNDRED_ODDS_XML, stamp, out_dir, "fivehundred_odds.xml")
    feed: dict[str, dict[str, object]] = {}
    for node in match_root.findall(".//match"):
        item: dict[str, object] = dict(node.attrib)
        item["fivehundred_id"] = str(node.attrib.get("id", ""))
        feed[str(node.attrib.get("id", ""))] = item
    for node in odds_root.findall(".//match"):
        item = feed.setdefault(str(node.attrib.get("id", "")), {"fivehundred_id": str(node.attrib.get("id", ""))})
        item["processdate"] = node.attrib.get("processdate", "")
        for child in node:
            item[f"{child.tag}_attrs"] = dict(child.attrib)

    mapped: dict[str, dict[str, object]] = {}
    five_by_time: dict[tuple[str, str], list[dict[str, object]]] = {}
    for item in feed.values():
        item_time = _fivehundred_match_time(f"{item.get('matchdate', '')} {item.get('matchtime', '')}")
        if item_time:
            five_by_time.setdefault(item_time, []).append(item)

    # The caller performs the actual Titan join.  Keep the feed keyed by 500
    # ID here and expose its prebuilt time index for the join helper below.
    return {"__feed__": feed, "__by_time__": five_by_time, "__target_date__": target_date}  # type: ignore[return-value]


def match_fivehundred_to_titan(
    future_rows: dict[str, dict[str, str]], five: dict[str, dict[str, object]], stamp: str,
) -> dict[str, dict[str, object]]:
    feed = five.get("__feed__", {})
    by_time = five.get("__by_time__", {})
    if not isinstance(feed, dict) or not isinstance(by_time, dict):
        return {}
    target_year = stamp[:4]
    mapped: dict[str, dict[str, object]] = {}
    ambiguous = 0
    for titan_id, row in future_rows.items():
        time_key = _future_row_time(str(row.get("bj_time", "")), target_year)
        if not time_key:
            continue
        candidates = by_time.get(time_key, [])
        home_key = _fivehundred_team_canonical(str(row.get("home_cn", "")))
        away_key = _fivehundred_team_canonical(str(row.get("away_cn", "")))
        scored: list[tuple[int, dict[str, object]]] = []
        for item in candidates:
            five_home = _fivehundred_team_canonical(str(item.get("homename", "")))
            five_away = _fivehundred_team_canonical(str(item.get("awayname", "")))
            if not home_key or not away_key or not five_home or not five_away:
                continue
            score = 0
            if home_key == five_home:
                score += 50
            if away_key == five_away:
                score += 50
            if score < 90:
                continue
            asian_attrs = item.get("asian_attrs", {})
            dxq_attrs = item.get("dxq_attrs", {})
            europe_attrs = item.get("europe_attrs", {})
            if not isinstance(asian_attrs, dict):
                asian_attrs = {}
            if not isinstance(dxq_attrs, dict):
                dxq_attrs = {}
            if not isinstance(europe_attrs, dict):
                europe_attrs = {}
            asian = None
            asian_company = ""
            for company in ("bet365", "am", "hg", "lb"):
                asian = _parse_fivehundred_triplet(str(asian_attrs.get(company, "")))
                if asian:
                    asian_company = company
                    break
            total = None
            total_company = ""
            for company in ("bet365", "am", "hg", "lb"):
                total = _parse_fivehundred_triplet(str(dxq_attrs.get(company, "")))
                if total:
                    total_company = company
                    break
            euro = None
            euro_company = ""
            for company in ("bet365", "avg", "am", "hg", "lb"):
                euro = _parse_fivehundred_europe_triplet(str(europe_attrs.get(company, "")))
                if euro:
                    euro_company = company
                    break
            if not asian and not total and not euro:
                continue
            candidate = dict(item)
            candidate["_asian"] = asian
            candidate["_asian_company"] = asian_company
            candidate["_total"] = total
            candidate["_total_company"] = total_company
            candidate["_euro"] = euro
            candidate["_euro_company"] = euro_company
            scored.append((score, candidate))
        if not scored:
            continue
        scored.sort(key=lambda pair: pair[0], reverse=True)
        if len(scored) > 1 and scored[0][0] == scored[1][0]:
            ambiguous += 1
            continue
        candidate = scored[0][1]
        out: dict[str, object] = {
            "fivehundred_id": candidate.get("fivehundred_id", ""),
            "fivehundred_processdate": candidate.get("processdate", ""),
            "fivehundred_matchdate": candidate.get("matchdate", ""),
            "fivehundred_matchtime": candidate.get("matchtime", ""),
        }
        asian = candidate.get("_asian")
        if isinstance(asian, tuple):
            out.update({
                "ah_full_current_home_or_over": asian[0],
                "ah_full_current_line_or_draw": asian[1],
                "ah_full_current_away_or_under": asian[2],
                "ah_full_company": f"500.com {candidate.get('_asian_company', '')}".strip(),
                "future_ah_fetch_fallback": "500_COM_PUBLIC_XML",
            })
        total = candidate.get("_total")
        if isinstance(total, tuple):
            out.update({
                "total_full_current_home_or_over": total[0],
                "total_full_current_line_or_draw": total[1],
                "total_full_current_away_or_under": total[2],
                "total_full_company": f"500.com {candidate.get('_total_company', '')}".strip(),
                "future_total_fetch_fallback": "500_COM_PUBLIC_XML",
            })
        euro = candidate.get("_euro")
        if isinstance(euro, tuple):
            out.update({
                "euro_full_current_home_or_over": euro[0],
                "euro_full_current_line_or_draw": euro[1],
                "euro_full_current_away_or_under": euro[2],
                "euro_full_company": f"500.com {candidate.get('_euro_company', '')}".strip(),
            })
        mapped[titan_id] = out
    print(f"fivehundred_feed={len(feed)} fivehundred_mapped={len(mapped)} fivehundred_ambiguous={ambiguous}", file=sys.stderr)
    return mapped


def _betexplorer_team_key(value: str) -> str:
    """Normalize English team names for the public BetExplorer join."""
    text = unicodedata.normalize("NFKC", html.unescape(clean_html_text(value))).lower()
    text = re.sub(r"\b(fc|cf|sc|afc|ac|fk|sk|club|women|w|u19|u20|u21|u23|b)\b", " ", text)
    return re.sub(r"[^a-z0-9]+", "", text)


def _team_name_similarity(left: str, right: str) -> float:
    """Return a conservative name score for cross-site fixture matching."""
    a = _betexplorer_team_key(left)
    b = _betexplorer_team_key(right)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if a in b or b in a:
        return min(len(a), len(b)) / max(len(a), len(b))
    # Avoid a new dependency in the daily scraper; this is only a secondary
    # join after date and home/away order have already been checked.
    from difflib import SequenceMatcher
    return SequenceMatcher(None, a, b).ratio()


def parse_betexplorer_schedule(text: str, target_date: str) -> list[dict[str, str]]:
    """Parse the public daily fixture index into event ids and English teams."""
    target = dt.date.fromisoformat(target_date)
    out: list[dict[str, str]] = []
    for match in re.finditer(r"<tr\b[^>]*data-dt=['\"]([^'\"]+)['\"][^>]*>(.*?)</tr>", text, re.I | re.S):
        parts = [part.strip() for part in match.group(1).split(",")]
        if len(parts) < 5:
            continue
        try:
            provider_dt = dt.datetime(int(parts[2]), int(parts[1]), int(parts[0]), int(parts[3]), int(parts[4]))
            local_dt = provider_dt + dt.timedelta(hours=int(os.environ.get("BETEXPLORER_UTC_OFFSET_HOURS", "8")))
            if local_dt.date() != target:
                continue
        except (ValueError, IndexError):
            continue
        row_html = match.group(2)
        link = re.search(r"<a\b[^>]*href=['\"]([^'\"]*/football/[^'\"]+)['\"][^>]*>(.*?)</a>", row_html, re.I | re.S)
        if not link:
            continue
        display = clean_html_text(link.group(2))
        teams = re.split(r"\s+-\s+", display, maxsplit=1)
        if len(teams) != 2:
            continue
        href = html.unescape(link.group(1))
        event_id = href.rstrip("/").split("/")[-1]
        if not event_id:
            continue
        out.append({
            "betexplorer_id": event_id,
            "home_en": teams[0].strip(),
            "away_en": teams[1].strip(),
            "betexplorer_dt": ",".join(parts[:5]),
            "bj_time": local_dt.strftime("%m-%d %H:%M"),
            "betexplorer_href": href,
        })
    return out


def parse_betexplorer_next_schedule(text: str, target_date: str) -> list[dict[str, str]]:
    """Parse BetExplorer's broader upcoming-fixture page.

    ``/football/`` is capped at the next ten upcoming matches.  The
    ``/football/next/`` page uses ``ul[data-dt]`` blocks instead of the table
    rows used by the landing page, so keep a dedicated parser and preserve
    the same conservative date/team join contract.
    """
    target = dt.date.fromisoformat(target_date)
    out: list[dict[str, str]] = []
    for match in re.finditer(r"<ul\b[^>]*data-dt=['\"]([^'\"]+)['\"][^>]*>(.*?)</ul>", text, re.I | re.S):
        parts = [part.strip() for part in match.group(1).split(",")]
        if len(parts) < 5:
            continue
        try:
            provider_dt = dt.datetime(int(parts[2]), int(parts[1]), int(parts[0]), int(parts[3]), int(parts[4]))
            local_dt = provider_dt + dt.timedelta(hours=int(os.environ.get("BETEXPLORER_UTC_OFFSET_HOURS", "8")))
            if local_dt.date() != target:
                continue
        except (ValueError, IndexError):
            continue
        block = match.group(2)
        link = re.search(
            r"<a\b[^>]*data-live-cell=['\"]matchlink['\"][^>]*href=['\"]([^'\"]+)['\"][^>]*>(.*?)</a>",
            block,
            re.I | re.S,
        )
        if not link:
            # Attribute order is not contractual; accept the reverse order.
            link = re.search(
                r"<a\b[^>]*href=['\"]([^'\"]+)['\"][^>]*data-live-cell=['\"]matchlink['\"][^>]*>(.*?)</a>",
                block,
                re.I | re.S,
            )
        if not link:
            continue
        href = html.unescape(link.group(1))
        event_id = href.rstrip("/").split("/")[-1]
        if not event_id:
            continue
        home_match = re.search(
            r"<div\b[^>]*class=['\"][^'\"]*participantHome[^'\"]*['\"][^>]*>.*?<p\b[^>]*>(.*?)</p>",
            block,
            re.I | re.S,
        )
        away_match = re.search(
            r"<div\b[^>]*class=['\"][^'\"]*participantAway[^'\"]*['\"][^>]*>.*?<p\b[^>]*>(.*?)</p>",
            block,
            re.I | re.S,
        )
        if not home_match or not away_match:
            continue
        home_en = clean_html_text(home_match.group(1))
        away_en = clean_html_text(away_match.group(1))
        if not home_en or not away_en:
            continue
        out.append({
            "betexplorer_id": event_id,
            "home_en": home_en,
            "away_en": away_en,
            "betexplorer_dt": ",".join(parts[:5]),
            "bj_time": local_dt.strftime("%m-%d %H:%M"),
            "betexplorer_href": href,
        })
    return out


def load_betexplorer_schedule(stamp: str, out_dir: Path, target_date: str) -> list[dict[str, str]]:
    """Load the BetExplorer schedule using Beijing-date normalization.

    BetExplorer's ``data-dt`` is UTC.  The old join compared that raw date to
    Titan's Beijing ``list_date`` and silently discarded every fixture that
    crossed midnight.  Reuse the saved response when available so a second
    pass does not issue another schedule request during the same run.
    """
    next_path = _maybe_saved(out_dir, stamp, "betexplorer_football_next.html")
    if next_path:
        next_text = next_path.read_text(encoding="utf-8", errors="replace")
    else:
        _path, raw = fetch_url(BETEXPLORER_NEXT, stamp, out_dir, "betexplorer_football_next.html")
        next_text = decode_text(raw)
    landing_path = _maybe_saved(out_dir, stamp, "betexplorer_football.html")
    if landing_path:
        landing_text = landing_path.read_text(encoding="utf-8", errors="replace")
    else:
        _path, raw = fetch_url(BETEXPLORER_HOME, stamp, out_dir, "betexplorer_football.html")
        landing_text = decode_text(raw)
    by_event = {event["betexplorer_id"]: event for event in parse_betexplorer_next_schedule(next_text, target_date)}
    by_event.update({event["betexplorer_id"]: event for event in parse_betexplorer_schedule(landing_text, target_date)})

    # ``/football/next/`` is intentionally a short rolling list.  It often
    # stops before the afternoon/evening part of the requested Beijing slate,
    # which made valid BetExplorer Asian odds look unavailable.  The daily
    # calendar contains a much broader table.  Fetch both dates because one
    # business slate is 12:00 through next-day 11:59 Beijing; the parser still
    # applies the provider UTC -> Beijing conversion and keeps only the exact
    # requested local date.  A failed optional calendar request must never
    # discard the already parsed rolling schedule.
    try:
        target = dt.date.fromisoformat(target_date)
        for day in (target, target + dt.timedelta(days=1)):
            suffix = f"betexplorer_football_calendar_{day.isoformat()}.html"
            saved = _maybe_saved(out_dir, stamp, suffix)
            if saved:
                calendar_text = saved.read_text(encoding="utf-8", errors="replace")
            else:
                url = f"https://www.betexplorer.com/football/?date={day.isoformat()}"
                _path, raw = fetch_url(url, stamp, out_dir, suffix, referer=BETEXPLORER_HOME)
                calendar_text = decode_text(raw)
            by_event.update({event["betexplorer_id"]: event for event in parse_betexplorer_schedule(calendar_text, target_date)})
        print(f"betexplorer_calendar_schedule={len(by_event)}", file=sys.stderr)
    except Exception as exc:
        print(f"betexplorer_calendar_optional_failed={exc}", file=sys.stderr)
    return list(by_event.values())


def parse_betexplorer_euro(text: str) -> dict[str, float | str]:
    """Parse a BetExplorer best-odds 1X2 response.

    Supplemental fixtures do not have Titan numeric IDs, so their Titan
    ``euro.js`` request cannot succeed.  BetExplorer exposes the same three
    current 1X2 prices through ``/0/1x2/bestOdds``.  Prefer Bet365 when it is
    present, then use a stable bookmaker row with three valid prices.
    """
    raw = str(text or "")
    rows = re.findall(r"<tr\b([^>]*)>(.*?)</tr>", raw, flags=re.I | re.S)
    preferred = {
        "bet365": 0,
        "pinnacle": 1,
        "williamhill": 2,
        "william hill": 2,
        "betway": 3,
        "1xbet": 4,
    }
    candidates: list[tuple[int, str, list[float]]] = []
    for attrs, body in rows:
        match = re.search(r"data-bookie=[\"']([^\"']+)", attrs + body, flags=re.I)
        if not match:
            # Current BetExplorer markup keeps only a numeric bookmaker id on
            # the row and puts the readable bookmaker name on the first cell.
            match = re.search(r"dataLayer\.push\(\{['\"]event-name['\"]:\s*['\"]([^'\"]+)", body, flags=re.I)
        bookmaker = str(match.group(1) if match else "").strip().lower()
        if not bookmaker:
            continue
        values: list[float] = []
        for value in re.findall(r"data-odd=[\"']([0-9]+(?:\.[0-9]+)?)[\"']", body, flags=re.I):
            try:
                number = float(value)
            except ValueError:
                continue
            if number > 1.0:
                values.append(number)
        if len(values) < 3:
            continue
        candidates.append((preferred.get(bookmaker, 50), bookmaker, values[:3]))
    if not candidates:
        return {}
    _rank, bookmaker, values = sorted(candidates, key=lambda item: item[0])[0]
    return {
        "euro_full_current_home_or_over": values[0],
        "euro_full_current_line_or_draw": values[1],
        "euro_full_current_away_or_under": values[2],
        "euro_full_open_home_or_over": values[0],
        "euro_full_open_line_or_draw": values[1],
        "euro_full_open_away_or_under": values[2],
        "euro_full_company": f"BetExplorer {bookmaker}",
        "euro_source": "BETEXPLORER_1X2_BEST_ODDS",
    }


def parse_betexplorer_asian(text: str) -> dict[str, float | str]:
    """Pick a real BetExplorer AH line from a preferred bookmaker row.

    The endpoint returns many alternate handicap lines.  Select the preferred
    bookmaker's line whose two prices are closest to a balanced 1.90/1.90
    market, which is the public page's main market rather than an extreme
    alternate line.  No value is synthesized when the endpoint has no odds.
    """
    preferred = ("bet365", "pinnacle", "sbo", "betfair exchange")
    candidates: list[tuple[int, float, float, float, float, str]] = []
    for table_match in re.finditer(r"<table\b[^>]*data-handicap=['\"]([^'\"]+)['\"][^>]*>(.*?)</table>", text, re.I | re.S):
        try:
            line = float(table_match.group(1))
        except ValueError:
            continue
        table_html = table_match.group(2)
        for row in re.findall(r"<tr\b[^>]*>.*?</tr>", table_html, re.I | re.S):
            name_match = re.search(r"<a\b[^>]*data-bid=['\"][^'\"]+['\"][^>]*>(.*?)</a>", row, re.I | re.S)
            if not name_match:
                continue
            company = clean_html_text(name_match.group(1))
            company_key = company.lower().replace(" ", "")
            preference = next((idx for idx, item in enumerate(preferred) if item.replace(" ", "") in company_key), 99)
            if preference == 99:
                continue
            odds = [text_to_float(value) for value in re.findall(r"data-odd=['\"]([0-9]+(?:\.[0-9]+)?)['\"]", row, re.I)]
            if len(odds) < 2 or odds[0] is None or odds[1] is None:
                continue
            balance = abs(float(odds[0]) - 1.90) + abs(float(odds[1]) - 1.90)
            candidates.append((preference, balance, line, float(odds[0]), float(odds[1]), company))
    if not candidates:
        return {}
    candidates.sort(key=lambda item: (item[0], item[1]))
    _preference, _balance, provider_line, home, away, company = candidates[0]
    # BetExplorer exposes the standard bookmaker perspective: a negative
    # home line means the home team gives the handicap, while a positive home
    # line means the home team receives it.  The football project contract
    # used by V3/V4 is the opposite signed convention (positive home line
    # means the home team gives).  Normalize at ingestion so every downstream
    # model and ledger sees one sign contract.  Keep the provider sign for
    # audit/debugging; never let it leak into the model-facing field.
    line = -float(provider_line)
    return {
        "ah_full_current_home_or_over": home,
        "ah_full_current_line_or_draw": line,
        "ah_full_current_away_or_under": away,
        "ah_full_company": f"BetExplorer {company}",
        "betexplorer_provider_line": float(provider_line),
        "betexplorer_line_convention": "STANDARD_HOME_SIGN_NEGATIVE_GIVING",
        "ah_line_convention": "TITAN_HOME_SIGN_POSITIVE_GIVING",
        "future_ah_fetch_fallback": "BETEXPLORER_PUBLIC_JSON",
    }


def match_betexplorer_to_titan(
    future_rows: dict[str, dict[str, str]],
    euro: dict[str, dict[str, float | str]],
    stamp: str,
    out_dir: Path,
    target_date: str,
) -> dict[str, dict[str, object]]:
    """Use BetExplorer's public JSON AH endpoint as a bounded fallback."""
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        # Keep the landing-page slice as well: it currently contains several
        # Japan/Korea fixtures that are not repeated on BetExplorer's broad
        # next-matches page.  Dedupe by the provider event id.
        schedule = load_betexplorer_schedule(stamp, out_dir, target_date)
    except Exception as exc:
        print(f"betexplorer_schedule_failed={exc}", file=sys.stderr)
        return {}
    mapped_events: dict[str, dict[str, str]] = {}
    ambiguous = 0
    def time_key(value: object) -> str:
        text = str(value or "").strip().replace("T", " ")
        # Keep month-day and hour-minute; both feeds use Beijing local time
        # after schedule normalization even when the source timestamp is UTC.
        m = re.search(r"(\d{2})[-/](\d{2}).*?(\d{2}):(\d{2})", text)
        return "".join(m.groups()) if m else ""
    for match_id, row in future_rows.items():
        source = dict(row)
        source.update(euro.get(match_id, {}))
        # Future Titan rows often carry only the Chinese schedule labels.
        # Falling back to home_cn/away_cn is required for the BetExplorer
        # supplement join; otherwise valid AH quotes are fetched but mapped
        # to zero Titan rows and disappear before V3/V4 evaluation.
        home_en = str(source.get("home_en", "") or source.get("home_cn", "") or "")
        away_en = str(source.get("away_en", "") or source.get("away_cn", "") or "")
        if not home_en or not away_en:
            continue
        scored: list[tuple[float, dict[str, str]]] = []
        for event in schedule:
            score = (_team_name_similarity(home_en, event["home_en"]) + _team_name_similarity(away_en, event["away_en"])) / 2.0
            if score >= 0.70:
                scored.append((score, event))
        # When Titan has only Chinese labels, the team score is unavailable.
        # Use an exact Beijing kickoff match as a conservative secondary key;
        # ties remain ambiguous and are deliberately not joined.
        # A weak name score is common when Titan exposes only mojibake Chinese
        # labels.  In that case an exact Beijing kickoff is still a safe join
        # when it identifies one BetExplorer event.  The old code only tried
        # this path when ``scored`` was empty, so a single weak candidate could
        # suppress the deterministic time key and silently lose the market.
        source_time = time_key(source.get("bj_time") or source.get("match_time_en") or source.get("kickoff"))
        if source_time and (not scored or max(item[0] for item in scored) < 0.78):
            timed = [event for event in schedule if source_time == time_key(event.get("bj_time") or event.get("betexplorer_dt"))]
            if len(timed) == 1:
                scored = [(0.80, timed[0])]
        scored.sort(key=lambda item: item[0], reverse=True)
        if not scored or scored[0][0] < 0.78:
            continue
        if len(scored) > 1 and scored[0][0] - scored[1][0] < 0.06:
            ambiguous += 1
            continue
        mapped_events[match_id] = scored[0][1]

    out: dict[str, dict[str, object]] = {}

    def fetch_event(match_id: str, event: dict[str, str]) -> tuple[str, dict[str, object] | None, str]:
        try:
            url = BETEXPLORER_ODDS.format(event_id=event["betexplorer_id"])
            _path, raw = fetch_betexplorer_event(
                url,
                stamp,
                out_dir,
                f"betexplorer_{event['betexplorer_id']}_ah.json",
                referer=BETEXPLORER_HOME,
            )
            payload = json.loads(decode_text(raw))
            market_html = str(payload.get("odds", "")) if isinstance(payload, dict) else ""
            ah = parse_betexplorer_asian(market_html)
            # The Titan per-match 1X2 endpoint is not available for every
            # future row.  BetExplorer exposes a second public endpoint for
            # the same fixture, so carry its real 1X2 prices together with
            # the Asian line instead of leaving the row in 待核.
            euro_path, euro_raw = fetch_betexplorer_event(
                BETEXPLORER_EURO_ODDS.format(event_id=event["betexplorer_id"]),
                stamp,
                out_dir,
                f"betexplorer_{event['betexplorer_id']}_1x2.json",
                referer=BETEXPLORER_HOME,
            )
            euro_payload = json.loads(decode_text(euro_raw))
            euro_html = str(euro_payload.get("odds", "")) if isinstance(euro_payload, dict) else ""
            euro_values = parse_betexplorer_euro(euro_html)
            combined = dict(ah)
            combined.update(euro_values)
            if combined:
                combined.update({
                    "betexplorer_id": event["betexplorer_id"],
                    "betexplorer_home_en": event["home_en"],
                    "betexplorer_away_en": event["away_en"],
                })
                return match_id, combined, ""
        except Exception as exc:
            return match_id, None, str(exc)
        return match_id, None, ""

    max_workers = max(1, int(os.environ.get("BETEXPLORER_MAX_WORKERS", "8")))
    with ThreadPoolExecutor(max_workers=min(max_workers, max(1, len(mapped_events)))) as pool:
        futures = [pool.submit(fetch_event, match_id, event) for match_id, event in mapped_events.items()]
        for future in as_completed(futures):
            match_id, value, error = future.result()
            if value:
                out[match_id] = value
            if error:
                print(f"betexplorer_match_failed={match_id}:{error}", file=sys.stderr)
    print(f"betexplorer_schedule={len(schedule)} betexplorer_joined={len(mapped_events)} betexplorer_mapped={len(out)} betexplorer_ambiguous={ambiguous}", file=sys.stderr)
    return out


def _betexplorer_competition(event: dict[str, str]) -> tuple[str, str]:
    """Return stable display labels from a BetExplorer fixture URL."""
    parts = [part for part in str(event.get("betexplorer_href", "")).split("/") if part]
    slug = parts[2] if len(parts) >= 3 and parts[0] == "football" else ""
    labels = {
        "championship": "英冠",
        "champions-league": "欧冠",
        "europa-league": "欧联",
        "conference-league": "欧协联",
    }
    return labels.get(slug, f"BE:{slug}" if slug else "BE:UNKNOWN"), slug.replace("-", " ").title()


def build_betexplorer_supplemental_rows(
    future_rows: dict[str, dict[str, str]],
    euro: dict[str, dict[str, float | str]],
    stamp: str,
    out_dir: Path,
    target_date: str,
    existing_rows: dict[str, dict[str, object]] | None = None,
) -> dict[str, dict[str, object]]:
    """Append fixtures absent from Titan's Next page using BetExplorer IDs.

    BetExplorer is a roster supplement here, not a replacement for Titan's
    numeric match IDs.  Supplemental rows are marked explicitly, receive a
    stable ``BE_<event_id>`` key, and stay outside the Titan detail/browser
    recovery queue.  This prevents a source-coverage gap from becoming an
    apparent odds transport failure while keeping the fixture available in
    the full ledger and HTML audit view.
    """
    if os.environ.get("TITAN_ENABLE_BETEXPLORER_SUPPLEMENT", "1") != "1":
        return {}
    try:
        schedule = load_betexplorer_schedule(stamp, out_dir, target_date)
    except Exception as exc:
        print(f"betexplorer_supplement_schedule_failed={exc}", file=sys.stderr)
        return {}
    if not schedule:
        print("betexplorer_supplement_schedule=0", file=sys.stderr)
        return {}

    existing_pairs: list[tuple[str, str]] = []
    for source in euro.values():
        home = _betexplorer_team_key(str(source.get("home_en", "") or ""))
        away = _betexplorer_team_key(str(source.get("away_en", "") or ""))
        if home and away:
            existing_pairs.append((home, away))
    # Prefer the enriched Titan rows (which carry English labels from the
    # per-match 1X2 response) over the aggregate Euro index.  This prevents a
    # BetExplorer-only alias such as "Port MTI FC" from duplicating an
    # already-present Titan fixture such as "Port FC".
    if existing_rows:
        existing_pairs.extend(
            (
                _betexplorer_team_key(str(item.get("home_en", "") or item.get("home_cn", ""))),
                _betexplorer_team_key(str(item.get("away_en", "") or item.get("away_cn", ""))),
            )
            for item in existing_rows.values()
            if _betexplorer_team_key(str(item.get("home_en", "") or item.get("home_cn", "")))
            and _betexplorer_team_key(str(item.get("away_en", "") or item.get("away_cn", "")))
        )

    def already_in_titan(event: dict[str, str]) -> bool:
        home = _betexplorer_team_key(event.get("home_en", ""))
        away = _betexplorer_team_key(event.get("away_en", ""))
        if not home or not away:
            return False
        for existing_home, existing_away in existing_pairs:
            score = (_team_name_similarity(home, existing_home) + _team_name_similarity(away, existing_away)) / 2.0
            if score >= 0.90:
                return True
        return False

    candidates = [event for event in schedule if not already_in_titan(event)]
    if not candidates:
        print(f"betexplorer_supplement_schedule={len(schedule)} supplemental=0", file=sys.stderr)
        return {}

    def fetch_one(event: dict[str, str]) -> tuple[str, dict[str, object]]:
        event_id = event["betexplorer_id"]
        market: dict[str, object] = {}
        try:
            saved = _maybe_saved(out_dir, stamp, f"betexplorer_{event_id}_ah.json")
            if saved:
                raw = saved.read_bytes()
            else:
                _path, raw = fetch_betexplorer_event(
                    BETEXPLORER_ODDS.format(event_id=event_id),
                    stamp,
                    out_dir,
                    f"betexplorer_{event_id}_ah.json",
                    referer=BETEXPLORER_HOME,
                )
            payload = json.loads(decode_text(raw))
            market_html = str(payload.get("odds", "")) if isinstance(payload, dict) else ""
            market = parse_betexplorer_asian(market_html)
        except Exception as exc:
            market["future_ah_supplement_error"] = str(exc)
        # BetExplorer-only fixtures have no Titan numeric ID, so fetch their
        # 1X2 prices from the same public provider instead of leaving euro
        # fields blank by construction.
        try:
            euro_saved = _maybe_saved(out_dir, stamp, f"betexplorer_{event_id}_1x2.json")
            if euro_saved:
                euro_raw = euro_saved.read_bytes()
            else:
                _path, euro_raw = fetch_betexplorer_event(
                    BETEXPLORER_EURO_ODDS.format(event_id=event_id),
                    stamp,
                    out_dir,
                    f"betexplorer_{event_id}_1x2.json",
                    referer=BETEXPLORER_HOME,
                )
            euro_payload = json.loads(decode_text(euro_raw))
            euro_html = str(euro_payload.get("odds", "")) if isinstance(euro_payload, dict) else ""
            market.update(parse_betexplorer_euro(euro_html))
        except Exception as exc:
            market["future_euro_supplement_error"] = str(exc)
        competition_cn, competition_en = _betexplorer_competition(event)
        match_id = f"BE_{event_id}"
        row: dict[str, object] = {
            "match_id": match_id,
            "league_cn": competition_cn,
            "league_en": competition_en,
            "league_tw": "",
            "home_cn": event.get("home_en", ""),
            "away_cn": event.get("away_en", ""),
            "home_en": event.get("home_en", ""),
            "away_en": event.get("away_en", ""),
            "bj_time": event.get("bj_time", ""),
            "match_time_en": event.get("betexplorer_dt", ""),
            "state": "0",
            "home_score": "",
            "away_score": "",
            "source_page": "BetExplorer supplemental",
            "source_provider": "BetExplorer",
            "betexplorer_id": event_id,
            "betexplorer_href": event.get("betexplorer_href", ""),
            "supplemental_roster": "BETEXPLORER_ONLY",
            "market_coverage_note": "BetExplorer AH + 1X2; Titan numeric detail ID unavailable",
        }
        row.update(market)
        if not market.get("ah_full_current_home_or_over"):
            row["future_ah_market_status"] = "NOT_PUBLISHED"
        return match_id, row

    output: dict[str, dict[str, object]] = {}
    max_workers = max(1, int(os.environ.get("BETEXPLORER_SUPPLEMENT_MAX_WORKERS", "8")))
    with ThreadPoolExecutor(max_workers=min(max_workers, len(candidates))) as pool:
        futures = [pool.submit(fetch_one, event) for event in candidates]
        for future in as_completed(futures):
            match_id, row = future.result()
            output[match_id] = row
    print(
        f"betexplorer_supplement_schedule={len(schedule)} supplemental={len(output)} "
        f"supplement_with_ah={sum(1 for row in output.values() if row.get('ah_full_current_home_or_over'))}",
        file=sys.stderr,
    )
    return output


def text_to_float(value: str) -> float | None:
    value = clean_html_text(value)
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def goal_attr(attrs: str, fallback: str) -> float | None:
    m = re.search(r"goals=['\"]?(-?\d+(?:\.\d+)?)", attrs, re.I)
    if m:
        return text_to_float(m.group(1))
    return text_to_float(fallback)


def parse_primary_odds_triplet(text: str) -> dict[str, float | str]:
    candidates: list[dict[str, float | str]] = []
    for block in re.findall(r"<tr\b.*?</tr>", text, re.I | re.S):
        opening = block.split(">", 1)[0].lower()
        if "display: none" in opening:
            continue
        cells = extract_cells(block)
        if len(cells) < 9:
            continue
        company = clean_html_text(cells[1][1])
        if not company or "公司" in company or "盘2" in company or "盘3" in company:
            continue
        open_home = text_to_float(cells[3][1])
        open_line = goal_attr(cells[4][0], cells[4][1])
        open_away = text_to_float(cells[5][1])
        current_home = text_to_float(cells[6][1])
        current_line = goal_attr(cells[7][0], cells[7][1])
        current_away = text_to_float(cells[8][1])
        if None in (open_home, open_line, open_away, current_home, current_line, current_away):
            continue
        candidates.append(
            {
                "company": company,
                "open_home": open_home,
                "open_line": open_line,
                "open_away": open_away,
                "current_home": current_home,
                "current_line": current_line,
                "current_away": current_away,
            }
        )
    if not candidates:
        return {}
    # Browser-rendered Titan pages may contain a visible but malformed
    # promotional/live row (for example 7.14/0.02).  Those are not valid HK
    # Asian prices and must not win the bookmaker preference just because the
    # company name matches first.  Keep only plausible decimal prices when at
    # least one complete row is available.
    usable = [
        cand
        for cand in candidates
        if all(0.20 <= float(cand[key]) <= 2.50 for key in (
            "open_home", "open_away", "current_home", "current_away"
        ))
    ]
    if usable:
        candidates = usable
    preferences = ("Crow", "36", "澳", "易胜", "伟", "明", "10", "12", "利", "盈", "18")
    for pref in preferences:
        for cand in candidates:
            if pref in str(cand["company"]):
                return cand
    return candidates[0]


def browser_market_priority(row: dict[str, object]) -> tuple[int, str, str]:
    """Order emergency market recovery by the requested competition hierarchy.

    Lower numbers are fetched first.  This is only a queue priority: it never
    synthesizes odds and never removes a fixture from the append-only roster.
    The order is mainstream senior tier 1/2 first, then Japan/Korea/Australia
    leagues and eligible European tier 3, then Japan/Korea/Australia cups,
    other senior adult competitions, and other cups. Lower European tier 3,
    youth, and friendlies remain last.
    """
    text = " ".join(
        str(row.get(key, "") or "")
        for key in ("league_cn", "league_tw", "league_en", "competition")
    ).casefold()
    kickoff = str(row.get("bj_time") or row.get("match_time_en") or "")
    match_id = str(row.get("match_id") or "")

    def has(*tokens: str) -> bool:
        return any(token.casefold() in text for token in tokens)

    # Youth/reserve/development rows and friendlies are deliberately last,
    # even when their label also contains a first-tier club name.
    if has(
        "u17", "u18", "u19", "u20", "u21", "u22", "u23", "青年", "青年队",
        "后备", "预备", "reserve", "reserves", "academy", "development",
    ):
        priority = 7
    elif has(
        "友谊", "友誼", "friendly", "club friendly", "international friendly",
        "test match", "testimonial",
    ):
        priority = 8
    # European big-five and continental senior competitions are the first
    # adult block, followed by other countries' senior tier 1/2 leagues.
    elif has(
        "英超", "西甲", "意甲", "德甲", "法甲", "premier league", "la liga",
        "serie a", "bundesliga", "ligue 1", "欧冠", "欧联", "欧协联",
        "champions league", "europa league", "conference league", "亚冠",
    ):
        priority = 0
    elif has(
        # Country tier 1/2 names and normalized tier markers.
        "英冠", "西乙", "意乙", "德乙", "法乙", "葡超", "葡甲", "荷甲", "荷乙",
        "比甲", "比乙", "土超", "土甲", "苏超", "苏冠", "俄超", "俄甲",
        "乌超", "乌甲", "丹超", "挪超", "瑞超", "奥超", "瑞士超",
        "巴西甲", "巴西乙", "阿甲", "阿乙", "中超", "中甲", "美职联",
        "美职业", "mls", "usl championship", "first division", "second division",
        "premier division", "super league", "championship", "eredivisie",
        "eerste divisie", "primeira liga", "segunda liga", "super lig", "1. lig",
        "liga portugal", "1. liga", "2. liga", "division 1", "division 2",
        "tier_1", "tier_2", "一级", "二级", "甲级", "乙级",
    ):
        priority = 1
    elif has(
        # Japan/Korea/Australia domestic cups are the dedicated third tier.
        "日联杯", "日聯杯", "日联赛杯", "日聯賽杯", "日足总杯", "日足總杯", "日本杯", "天皇杯",
        "韩国杯", "韓國杯", "韩足总杯", "韓足總杯", "澳洲杯", "澳洲盃", "澳大利亚杯", "澳大利亞盃",
        "j-league cup", "j league cup", "japan cup", "emperor's cup", "k league cup", "korea cup",
        "a-league cup", "australia cup",
    ):
        priority = 3
    elif has(
        # Requested second block: Japan/Korea/Australia senior leagues and
        # priority European third tiers.
        "日职", "日乙", "日丙", "日足", "日本", "j1", "j2", "j3", "j.league",
        "韩k", "韩国", "k league", "k3", "澳超", "澳甲", "a-league", "australia",
        "意丙", "英甲", "德丙", "法丙", "西协甲", "西協甲", "3. liga", "league one",
        "primera federación", "primera federacion", "czech 3", "3. česk", "3. ces",
        "2. divisjon", "norsk tipping-ligaen", "2. deild", "ettan",
    ):
        priority = 2
    elif has(
        # Other senior adult competitions follow the dedicated Asia/Oceania
        # cup tier but remain ahead of generic domestic cups.
        "其他成人", "other adult",
    ):
        priority = 4
    elif has(
        # Generic senior cups are kept in their own lower reserved queue.
        "杯", "cup", "copa", "coppa", "coupe", "pokal", "beker", "kup", "taça", "taca", "trofeo",
    ):
        priority = 5
    elif has(
        # Other European third tiers may wait when the bounded queue is full.
        "tier_3", "三级", "liga 3", "serie c", "national league", "division 3", "3. lig",
    ):
        priority = 6
    else:
        # Unknown adult rows remain ahead of generic cups. They stay in the
        # roster and are still subject to the normal odds quality gate.
        priority = 4
    return priority, kickoff, match_id


def browser_priority2_group(row: dict[str, object]) -> str:
    """Split the reserved second-tier queue so each requested group gets a turn."""
    text = " ".join(
        str(row.get(key, "") or "")
        for key in ("league_cn", "league_tw", "league_en", "competition")
    ).casefold()
    asia_tokens = ("日职", "日乙", "日丙", "日足", "日本", "日联杯", "日聯杯", "日联赛杯", "日聯賽杯", "日足总杯", "日足總杯", "j1", "j2", "j3", "j.league", "韩k", "韩国", "韩足总杯", "韓足總杯", "k league", "k3", "澳超", "澳甲", "澳洲", "澳大利亚", "澳洲杯", "澳洲盃", "australia cup", "a-league", "australia", "japan", "korea")
    cup_tokens = ("杯", "cup", "copa", "coppa", "coupe", "pokal", "beker", "kup", "taça", "taca", "trofeo")
    if any(token in text for token in asia_tokens) and any(token in text for token in cup_tokens):
        return "asia_oceania_cup"
    if any(token in text for token in asia_tokens):
        return "asia_oceania"
    if any(token in text for token in ("意丙", "英甲", "德丙", "法丙", "西协甲", "西協甲", "3. liga", "league one", "primera federación", "primera federacion", "czech 3", "3. česk", "3. ces", "2. divisjon", "norsk tipping-ligaen", "2. deild", "ettan")):
        return "europe_tier3"
    return "other_adult"


def browser_recover_vip_pages(
    completed: dict[str, tuple[dict[str, object], bool]],
    ids_to_fetch: list[str],
    stamp: str,
    out_dir: Path,
) -> tuple[int, int, int]:
    """Recover missing Titan VIP markets through a real Chromium session.

    The VIP host rejects the curl/urllib transport but serves the same pages
    to Chromium.  Use bounded async pages so this fallback restores coverage
    without serially opening a new browser for every match.  Returned odds are
    still parsed from the source HTML; no value is inferred or synthesized.
    """
    jobs: list[tuple[str, str]] = []
    markets = {
        item.strip().lower()
        for item in os.environ.get("TITAN_BROWSER_MARKETS", "ah").split(",")
        if item.strip().lower() in {"ah", "total"}
    } or {"ah"}
    for match_id in ids_to_fetch:
        row = completed[match_id][0]
        ah_complete = all(
            str(row.get(key, "") or "").strip()
            for key in (
                "ah_full_current_home_or_over",
                "ah_full_current_line_or_draw",
                "ah_full_current_away_or_under",
            )
        )
        total_complete = all(
            str(row.get(key, "") or "").strip()
            for key in (
                "total_full_current_home_or_over",
                "total_full_current_line_or_draw",
                "total_full_current_away_or_under",
            )
        )
        if "ah" in markets and not ah_complete:
            jobs.append((match_id, "ah"))
        if "total" in markets and not total_complete:
            jobs.append((match_id, "total"))
    if not jobs:
        return 0, 0, 0

    # Do not fan out an entire 1,000-match slate against a rate-limited host.
    # The next daily refresh will resume from the still-missing rows.  Set the
    # variable to 0 explicitly when a controlled full pass is desired.
    jobs.sort(key=lambda item: browser_market_priority(completed[item[0]][0]))
    # Browser recovery is an emergency path.  Reserve part of the bounded
    # queue for the user's second-level coverage (Japan/Korea/Australia,
    # priority European tier 3 and senior cups), so a very large tier-1/2
    # slate cannot consume all 48 slots before that group is reached.
    batch_limit = max(0, int(os.environ.get("TITAN_BROWSER_BATCH_LIMIT", "48")))
    queued_jobs = len(jobs)
    if batch_limit:
        priority_jobs = [job for job in jobs if browser_market_priority(completed[job[0]][0])[0] <= 1]
        second_jobs = [job for job in jobs if browser_market_priority(completed[job[0]][0])[0] in {2, 3, 4}]
        cup_jobs = [job for job in jobs if browser_market_priority(completed[job[0]][0])[0] == 5]
        lower_jobs = [job for job in jobs if browser_market_priority(completed[job[0]][0])[0] >= 6]
        reserve = min(
            len(second_jobs),
            max(0, int(os.environ.get("TITAN_BROWSER_PRIORITY2_MIN", "16"))),
            batch_limit,
        )
        cup_reserve = min(
            len(cup_jobs),
            max(0, int(os.environ.get("TITAN_BROWSER_CUP_MIN", "4"))),
            max(0, batch_limit - reserve),
        )
        groups = {"asia_oceania_cup": [], "other_adult": [], "asia_oceania": [], "europe_tier3": []}
        for job in second_jobs:
            groups.setdefault(browser_priority2_group(completed[job[0]][0]), []).append(job)
        second_selected = []
        # Asia/Oceania domestic cups are the third tier; other adult rows then
        # get turns before the generic cup reserve.
        while len(second_selected) < reserve and any(groups.values()):
            progressed = False
            for name in ("asia_oceania_cup", "other_adult", "asia_oceania", "europe_tier3"):
                if groups.get(name):
                    second_selected.append(groups[name].pop(0))
                    progressed = True
                    if len(second_selected) >= reserve:
                        break
            if not progressed:
                break
        used = {id(job) for job in second_selected}
        second_selected.extend(job for job in second_jobs if id(job) not in used)
        second_selected = second_selected[:reserve]
        selected_cups = cup_jobs[:cup_reserve]
        core_slots = max(0, batch_limit - len(second_selected) - len(selected_cups))
        selected = priority_jobs[:core_slots] + second_selected + selected_cups
        # If there are fewer core/second-level/cup jobs than the cap, use any
        # remaining rows; youth/friendlies and non-mainstream tier 3 stay last.
        if len(selected) < batch_limit:
            selected_ids = {id(job) for job in selected}
            for job in priority_jobs[core_slots:] + second_jobs[reserve:] + cup_jobs[cup_reserve:] + lower_jobs:
                if id(job) not in selected_ids:
                    selected.append(job); selected_ids.add(id(job))
                if len(selected) >= batch_limit:
                    break
        jobs = selected[:batch_limit]
        print(f"future_browser_priority2_reserved={len(second_selected)}/{len(second_jobs)}", file=sys.stderr)
        print(f"future_browser_cup_reserved={len(selected_cups)}/{len(cup_jobs)}", file=sys.stderr)
        if queued_jobs > len(jobs):
            print(f"future_browser_capped={len(jobs)}/{queued_jobs}", file=sys.stderr)

    executable = playwright_executable()

    async def fetch_all() -> list[tuple[str, str, dict[str, float | str], str]]:
        from playwright.async_api import async_playwright

        max_workers = max(1, int(os.environ.get("TITAN_BROWSER_MAX_WORKERS", "4")))
        timeout_ms = max(5_000, int(os.environ.get("TITAN_BROWSER_TIMEOUT_MS", "12_000")))
        max_attempts = max(1, int(os.environ.get("TITAN_BROWSER_ATTEMPTS", "1")))
        request_interval = max(0.0, float(os.environ.get("TITAN_BROWSER_REQUEST_INTERVAL", "0.75")))
        save_browser_html = os.environ.get("TITAN_SAVE_BROWSER_HTML", "0") == "1"
        semaphore = asyncio.Semaphore(max_workers)
        request_lock = asyncio.Lock()
        next_request_at = 0.0
        # A single HTTP/2 reset used to trip a global circuit breaker and
        # mark every remaining match as a browser failure.  That made a
        # transient VIP outage look like a complete market outage.  Keep the
        # browser session alive and let the mobile endpoint decide whether a
        # market is genuinely unpublished.

        async def before_request() -> bool:
            nonlocal next_request_at
            async with request_lock:
                now = time.monotonic()
                wait = max(0.0, next_request_at - now)
                next_request_at = max(now, next_request_at) + request_interval
            if wait:
                await asyncio.sleep(wait)
            return True

        async with async_playwright() as playwright:
            launch_options = {"headless": True}
            if executable:
                launch_options["executable_path"] = executable
            browser = await playwright.chromium.launch(**launch_options)
            context = await browser.new_context(
                ignore_https_errors=True,
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36",
            )

            async def fetch_one(match_id: str, market: str) -> tuple[str, str, dict[str, float | str], str]:
                async with semaphore:
                    endpoint = "AsianOdds_n.aspx" if market == "ah" else "OverDown_n.aspx"
                    url = f"{VIP_BASE}/{endpoint}?id={match_id}&l=0"
                    last_error = ""
                    for attempt in range(max_attempts):
                        if not await before_request():
                            return match_id, market, {}, "browser_host_cooldown"
                        page = await context.new_page()
                        try:
                            response = await page.goto(
                                url,
                                wait_until="domcontentloaded",
                                timeout=timeout_ms,
                                referer=f"{BF_BASE}/football/Next_{stamp[:8]}.htm",
                            )
                            html_text = await page.content()
                            parsed = parse_primary_odds_triplet(html_text)
                            status = str(response.status if response else "")
                            if parsed:
                                if save_browser_html:
                                    await asyncio.to_thread(
                                        (out_dir / f"{stamp}_future_{match_id}_{market}_browser.html").write_text,
                                        html_text,
                                        encoding="utf-8",
                                    )
                                return match_id, market, parsed, ""
                            last_error = f"browser_empty_market_http_{status}"
                        except Exception as exc:
                            last_error = f"{type(exc).__name__}: {exc}"
                        finally:
                            await page.close()
                        if attempt + 1 < max_attempts:
                            await asyncio.sleep(1.5 * (attempt + 1))
                    return match_id, market, {}, last_error

            try:
                return await asyncio.gather(*(fetch_one(match_id, market) for match_id, market in jobs))
            finally:
                await browser.close()

    results = asyncio.run(fetch_all())
    recovered_ah = 0
    recovered_total = 0
    failed = 0
    for match_id, market, parsed, error in results:
        base_row, fetched_any = completed[match_id]
        if parsed:
            prefix = "ah" if market == "ah" else "total"
            base_row.update({
                f"{prefix}_full_open_home_or_over": parsed["open_home"],
                f"{prefix}_full_open_line_or_draw": parsed["open_line"],
                f"{prefix}_full_open_away_or_under": parsed["open_away"],
                f"{prefix}_full_current_home_or_over": parsed["current_home"],
                f"{prefix}_full_current_line_or_draw": parsed["current_line"],
                f"{prefix}_full_current_away_or_under": parsed["current_away"],
                f"{prefix}_full_company": f"Titan007 Chromium {parsed['company']}",
                f"future_{market}_fetch_fallback": "PLAYWRIGHT_CHROMIUM",
            })
            base_row.pop(f"future_{market}_fetch_error", None)
            fetched_any = True
            if market == "ah":
                recovered_ah += 1
            else:
                recovered_total += 1
        else:
            failed += 1
            base_row[f"future_{market}_browser_error"] = error
        completed[match_id] = (base_row, fetched_any)
    print(
        f"future_browser_queue={queued_jobs} batch={len(jobs)} skipped={max(0, queued_jobs - len(jobs))}",
        file=sys.stderr,
    )
    return recovered_ah, recovered_total, failed


def parse_mobile_analysis_triplet(values: list[str]) -> dict[str, float | str]:
    """Parse the six realOdds spans from the mobile Analysis market row.

    The mobile page presents three opening values followed by three current
    values.  For Asian handicap those are home water, line, away water; for
    totals they are over water, line, under water.  Keep the exact source
    values and reject malformed/placeholder rows instead of manufacturing a
    fallback market.
    """
    values = [clean_html_text(value) for value in values]
    if len(values) < 6:
        return {}
    values = values[:6]
    open_home = text_to_float(values[0])
    open_line = _parse_handicap_text(values[1])
    open_away = text_to_float(values[2])
    current_home = text_to_float(values[3])
    current_line = _parse_handicap_text(values[4])
    current_away = text_to_float(values[5])
    if None in (open_home, open_line, open_away, current_home, current_line, current_away):
        return {}
    if not all(0.20 <= float(value) <= 2.50 for value in (open_home, open_away, current_home, current_away)):
        return {}
    return {
        "company": "Titan007 Mobile Analysis",
        "open_home": open_home,
        "open_line": open_line,
        "open_away": open_away,
        "current_home": current_home,
        "current_line": current_line,
        "current_away": current_away,
    }


def browser_recover_mobile_analysis_pages(
    completed: dict[str, tuple[dict[str, object], bool]],
    ids_to_fetch: list[str],
    stamp: str,
    out_dir: Path,
) -> tuple[int, int, int]:
    """Recover missing markets from Titan's mobile Analysis page.

    This is a separate host and a separate circuit from the VIP detail pages.
    It is intentionally sequential by default because the mobile endpoint is
    the broad-coverage safety net for a large daily slate.
    """
    jobs: list[tuple[str, str]] = []
    markets = {
        item.strip().lower()
        for item in os.environ.get("TITAN_MOBILE_BROWSER_MARKETS", "ah,total").split(",")
        if item.strip().lower() in {"ah", "total"}
    } or {"ah"}
    for match_id in ids_to_fetch:
        row = completed[match_id][0]
        ah_complete = all(
            str(row.get(key, "") or "").strip()
            for key in (
                "ah_full_current_home_or_over",
                "ah_full_current_line_or_draw",
                "ah_full_current_away_or_under",
            )
        )
        total_complete = all(
            str(row.get(key, "") or "").strip()
            for key in (
                "total_full_current_home_or_over",
                "total_full_current_line_or_draw",
                "total_full_current_away_or_under",
            )
        )
        if "ah" in markets and not ah_complete:
            jobs.append((match_id, "ah"))
        if "total" in markets and not total_complete:
            jobs.append((match_id, "total"))
    if not jobs:
        return 0, 0, 0

    jobs.sort(key=lambda item: browser_market_priority(completed[item[0]][0]))
    batch_limit = max(0, int(os.environ.get("TITAN_MOBILE_BROWSER_BATCH_LIMIT", "0")))
    queued_jobs = len(jobs)
    if batch_limit:
        jobs = jobs[:batch_limit]

    executable = playwright_executable()

    async def fetch_all() -> list[tuple[str, str, dict[str, float | str], str]]:
        from playwright.async_api import async_playwright

        timeout_ms = max(5_000, int(os.environ.get("TITAN_MOBILE_BROWSER_TIMEOUT_MS", "25_000")))
        request_interval = max(0.15, float(os.environ.get("TITAN_MOBILE_BROWSER_REQUEST_INTERVAL", "0.60")))
        max_attempts = max(1, int(os.environ.get("TITAN_MOBILE_BROWSER_ATTEMPTS", "3")))
        save_browser_html = os.environ.get("TITAN_SAVE_BROWSER_HTML", "0") == "1"
        next_request_at = 0.0
        request_lock = asyncio.Lock()
        async def before_request() -> bool:
            nonlocal next_request_at
            async with request_lock:
                now = time.monotonic()
                wait = max(0.0, next_request_at - now)
                next_request_at = max(now, next_request_at) + request_interval
            if wait:
                await asyncio.sleep(wait)
            return True

        async with async_playwright() as playwright:
            launch_options = {"headless": True}
            if executable:
                launch_options["executable_path"] = executable
            browser = await playwright.chromium.launch(**launch_options)
            context = await browser.new_context(
                ignore_https_errors=True,
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36",
            )
            page = await context.new_page()
            results: list[tuple[str, str, dict[str, float | str], str]] = []
            try:
                for index, (match_id, market) in enumerate(jobs, start=1):
                    if not await before_request():
                        results.append((match_id, market, {}, "mobile_host_cooldown"))
                        continue
                    row_selector = f'#Odds tr[onclick^="GoDetail({1 if market == "ah" else 2},"]'
                    last_error = ""
                    for attempt in range(max_attempts):
                        try:
                            scheme = "https" if attempt % 2 == 0 else "http"
                            response = await page.goto(
                                f"{scheme}://m.titan007.com/analy/Analysis/{match_id}.htm?refresh={stamp}_{attempt}",
                                wait_until="domcontentloaded",
                                timeout=timeout_ms,
                            )
                            # The mobile page is static HTML, but the row
                            # attribute has changed casing/spacing before.
                            # Keep the strict market id while allowing the
                            # harmless attribute-format variants.
                            market_row = page.locator(row_selector).first
                            if not await market_row.count():
                                market_row = page.locator(
                                    f'#Odds tr[onclick*="GoDetail({1 if market == "ah" else 2},"]'
                                ).first
                            spans = (
                                await market_row.locator(".realOdds").all_inner_texts()
                                if await market_row.count()
                                else []
                            )
                            parsed = parse_mobile_analysis_triplet(spans)
                            status = str(response.status if response else "")
                            if parsed:
                                if save_browser_html:
                                    html_text = await page.content()
                                    await asyncio.to_thread(
                                        (out_dir / f"{stamp}_future_{match_id}_{market}_mobile_browser.html").write_text,
                                        html_text,
                                        encoding="utf-8",
                                    )
                                results.append((match_id, market, parsed, ""))
                                break
                            last_error = (
                                f"market_not_published_http_{status}"
                                if not await page.locator(
                                    f'#Odds tr[onclick*="GoDetail({1 if market == "ah" else 2},"]'
                                ).count()
                                else f"mobile_market_parse_failed_http_{status}"
                            )
                        except Exception as exc:
                            last_error = f"{type(exc).__name__}: {exc}"
                        if attempt + 1 < max_attempts:
                            await asyncio.sleep(1.0 * (attempt + 1))
                    else:
                        results.append((match_id, market, {}, last_error or "mobile_empty_market"))
                    if index % 50 == 0:
                        print(f"future_mobile_progress={index}/{len(jobs)}", file=sys.stderr)
            finally:
                await browser.close()
            return results

    results = asyncio.run(fetch_all())
    recovered_ah = 0
    recovered_total = 0
    failed = 0
    not_published = 0
    for match_id, market, parsed, error in results:
        base_row, fetched_any = completed[match_id]
        if parsed:
            prefix = "ah" if market == "ah" else "total"
            base_row.update({
                f"{prefix}_full_open_home_or_over": parsed["open_home"],
                f"{prefix}_full_open_line_or_draw": parsed["open_line"],
                f"{prefix}_full_open_away_or_under": parsed["open_away"],
                f"{prefix}_full_current_home_or_over": parsed["current_home"],
                f"{prefix}_full_current_line_or_draw": parsed["current_line"],
                f"{prefix}_full_current_away_or_under": parsed["current_away"],
                f"{prefix}_full_company": parsed["company"],
                f"future_{market}_fetch_fallback": "TITAN_MOBILE_ANALYSIS",
            })
            base_row.pop(f"future_{market}_fetch_error", None)
            base_row.pop(f"future_{market}_browser_error", None)
            fetched_any = True
            if market == "ah":
                recovered_ah += 1
            else:
                recovered_total += 1
        else:
            if error.startswith(("market_not_published_", "mobile_empty_market_http_200")):
                # A valid 200 response with no matching market row is a
                # source state, not a transport failure.  Preserve it as an
                # explicit missing-data reason so the model cannot mistake it
                # for a fetch outage or a zero-priced market.
                base_row[f"future_{market}_market_status"] = "NOT_PUBLISHED"
                not_published += 1
                base_row.pop(f"future_{market}_mobile_browser_error", None)
                base_row.pop(f"future_{market}_fetch_error", None)
            else:
                failed += 1
                base_row[f"future_{market}_mobile_browser_error"] = error
        completed[match_id] = (base_row, fetched_any)
    print(
        f"future_mobile_queue={queued_jobs} batch={len(jobs)} skipped={max(0, queued_jobs - len(jobs))} "
        f"not_published={not_published}",
        file=sys.stderr,
    )
    return recovered_ah, recovered_total, failed


def parse_euro_index(text: str) -> dict[str, dict[str, float | str]]:
    out: dict[str, dict[str, float | str]] = {}
    pattern = re.compile(
        r"(<tr\b[^>]*\bid=tr_(\d+)\b.*?</tr>)\s*(<tr\b[^>]*\bid=['\"]?tr2_\2['\"]?.*?</tr>)",
        re.I | re.S,
    )
    for m in pattern.finditer(text):
        row1, row2 = m.group(1), m.group(3)
        id_match = re.search(r"Oddslist/(\d+)\.htm", row1, re.I)
        if not id_match:
            continue
        match_id = id_match.group(1)
        cells1 = extract_cells(row1)
        cells2 = extract_cells(row2)
        if len(cells1) < 12 or len(cells2) < 3:
            continue
        cur_home = text_to_float(cells1[4][1])
        cur_draw = text_to_float(cells1[5][1])
        cur_away = text_to_float(cells1[6][1])
        open_home = text_to_float(cells2[0][1])
        open_draw = text_to_float(cells2[1][1])
        open_away = text_to_float(cells2[2][1])
        if None in (cur_home, cur_draw, cur_away, open_home, open_draw, open_away):
            continue
        out[match_id] = {
            "euro_full_current_home_or_over": cur_home,
            "euro_full_current_line_or_draw": cur_draw,
            "euro_full_current_away_or_under": cur_away,
            "euro_full_open_home_or_over": open_home,
            "euro_full_open_line_or_draw": open_draw,
            "euro_full_open_away_or_under": open_away,
            "euro_full_company": "Titan007百家欧赔均值",
        }
    return out


def parse_euro_txt(text: str) -> dict[str, dict[str, float | str]]:
    """Parse Titan's per-match txt/1x2 JS fallback.

    The public aggregate 1x2 page is intermittently unavailable, while the
    per-match JS contains the same bookmaker opening/current 1X2 values.
    Average only complete numeric bookmaker rows to retain the existing
    Titan007百家欧赔均值 semantics.
    """
    id_match = re.search(r"var\s+ScheduleID\s*=\s*(\d+)", text, re.I)
    if not id_match:
        return {}
    game_match = re.search(r"var\s+game\s*=\s*Array\((.*?)\);\s*var\s+gameDetail", text, re.I | re.S)
    if not game_match:
        return {}
    current: list[tuple[float, float, float]] = []
    opening: list[tuple[float, float, float]] = []
    for item in re.findall(r'"([^"\\]*(?:\\.[^"\\]*)*)"', game_match.group(1)):
        fields = item.split("|")
        if len(fields) < 13:
            continue
        try:
            op = tuple(float(fields[idx]) for idx in (3, 4, 5))
            cur = tuple(float(fields[idx]) for idx in (10, 11, 12))
        except (TypeError, ValueError):
            continue
        if all(value > 1.0 for value in op + cur):
            opening.append(op); current.append(cur)
    if not current:
        return {}
    avg = lambda rows, idx: round(sum(row[idx] for row in rows) / len(rows), 4)
    match_id = id_match.group(1)
    result: dict[str, float | str] = {
            "euro_full_current_home_or_over": avg(current, 0),
            "euro_full_current_line_or_draw": avg(current, 1),
            "euro_full_current_away_or_under": avg(current, 2),
            "euro_full_open_home_or_over": avg(opening, 0),
            "euro_full_open_line_or_draw": avg(opening, 1),
            "euro_full_open_away_or_under": avg(opening, 2),
            "euro_full_company": "Titan007百家欧赔均值(txt/1x2)",
    }
    # These public English labels are used only for a conservative secondary
    # source join (BetExplorer).  They never replace the Titan Chinese
    # fixture identity or the immutable match id.
    for key, pattern in (
        ("home_en", r"var\s+hometeam\s*=\s*[\"'](.*?)[\"']"),
        ("away_en", r"var\s+guestteam\s*=\s*[\"'](.*?)[\"']"),
        ("league_en", r"var\s+matchname\s*=\s*[\"'](.*?)[\"']"),
        ("match_time_en", r"var\s+MatchTime\s*=\s*[\"'](.*?)[\"']"),
    ):
        value = re.search(pattern, text, re.I | re.S)
        if value:
            result[key] = html.unescape(value.group(1)).strip()
    return {match_id: result}


def enrich_future_odds(
    rows: dict[str, dict[str, object]],
    future_rows: dict[str, dict[str, str]],
    lines: dict[str, dict[str, str]],
    euro: dict[str, dict[str, float | str]],
    stamp: str,
    out_dir: Path,
    fivehundred: dict[str, dict[str, object]] | None = None,
    betexplorer: dict[str, dict[str, object]] | None = None,
) -> int:
    # CommonInterface is only a hint/index and may be incomplete.  The daily
    # page must not silently omit matches when that optional feed has only a
    # partial response; fetch each scheduled match's VIP Asian/total detail.
    ids_to_fetch = list(future_rows)
    fivehundred = fivehundred or {}
    betexplorer = betexplorer or {}

    # English labels are only join metadata for BetExplorer; they are not a
    # current market.  Reuse the last successful label snapshot when present
    # and allow an optional operator cap on fresh metadata calls for
    # low-coverage fixtures.  The default is unlimited so the optimization
    # never drops a fallback join merely because the slate is large.
    metadata_fields = ("home_en", "away_en", "league_en", "match_time_en")
    prior_rows = latest_snapshot_metadata_by_id(stamp)
    metadata_fetch_limit = max(0, int(os.environ.get("TITAN_EURO_METADATA_LIMIT", "0")))
    metadata_fetch_ids: set[str] = set()
    for match_id in sorted(ids_to_fetch, key=lambda key: str(future_rows[key].get("bj_time", ""))):
        row = future_rows[match_id]
        prior = prior_rows.get(match_id, {})
        for field in metadata_fields:
            if not str(row.get(field, "") or "").strip() and str(prior.get(field, "") or "").strip():
                row[field] = prior[field]
        probe_row = dict(row)
        probe_row.update(rows.get(match_id) or {})
        probe_row.update(lines.get(match_id, {}))
        probe_row.update(euro.get(match_id, {}))
        fallback_probe = fivehundred.get(match_id, {}) or betexplorer.get(match_id, {})
        if fallback_probe:
            probe_row.update(fallback_probe)
        # Fetch txt/1x2 only where the aggregate Euro board is incomplete or
        # where a missing English label is required for BetExplorer matching.
        # Previously every row missing labels consumed a detail request even
        # when its Euro triplet was already complete and no AH fallback was
        # needed.
        euro_complete = all(
            str(value or "").strip()
            for value in (
                probe_row.get("euro_full_current_home_or_over"),
                probe_row.get("euro_full_current_line_or_draw"),
                probe_row.get("euro_full_current_away_or_under"),
            )
        )
        labels_missing = not (
            str(probe_row.get("home_en", "") or "").strip()
            and str(probe_row.get("away_en", "") or "").strip()
        )
        ah_complete = all(
            str(value or "").strip()
            for value in (
                probe_row.get("ah_full_current_home_or_over"),
                probe_row.get("ah_full_current_line_or_draw"),
                probe_row.get("ah_full_current_away_or_under"),
            )
        )
        if (not euro_complete or (labels_missing and not ah_complete)):
            if metadata_fetch_limit <= 0 or len(metadata_fetch_ids) < metadata_fetch_limit:
                metadata_fetch_ids.add(match_id)
    print(
        f"euro_metadata_reused={len(ids_to_fetch) - len(metadata_fetch_ids)} "
        f"euro_metadata_fetch={len(metadata_fetch_ids)}",
        file=sys.stderr,
    )
    vip_allowed = os.environ.get("TITAN_SKIP_VIP", "0") != "1"
    vip_probe_error = ""
    if vip_allowed and os.environ.get("TITAN_FORCE_VIP", "0") != "1" and ids_to_fetch:
        # Probe once before launching hundreds of workers.  The current VIP
        # host closes the connection for every request; without this gate the
        # refresh wastes time and produces identical per-match failures.
        probe_limit = max(1, int(os.environ.get("TITAN_VIP_PROBE_LIMIT", "10")))
        vip_probe_ok = False
        for probe_id in ids_to_fetch[:probe_limit]:
            try:
                _path, raw = fetch_url(
                    f"{VIP_BASE}/AsianOdds_n.aspx?id={probe_id}&l=0",
                    stamp,
                    out_dir,
                    f"vip_probe_{probe_id}_asian.html",
                    referer=f"{BF_BASE}/football/Next_{stamp[:8]}.htm",
                )
                if parse_primary_odds_triplet(decode_text(raw)):
                    vip_probe_ok = True
                    break
            except Exception as exc:
                vip_probe_error = str(exc)
        if not vip_probe_ok:
            vip_allowed = False
            vip_probe_error = vip_probe_error or "vip_asian_endpoint_empty_or_unparseable"
            print(f"vip_global_disabled={vip_probe_error}", file=sys.stderr)
    elif not vip_allowed:
        vip_probe_error = "skipped_vip_after_endpoint_failure"

    def fetch_one(match_id: str) -> tuple[str, dict[str, object], bool]:
        # Start from the enriched future row so reused English labels survive
        # even when the live schedule row already exists in ``rows``.
        base_row = dict(future_rows[match_id])
        base_row.update(rows.get(match_id) or {})
        base_row.update(lines.get(match_id, {})); base_row.update(euro.get(match_id, {}))
        fetched_any = False
        fallback = fivehundred.get(match_id, {})
        if not fallback:
            fallback = betexplorer.get(match_id, {})
        if fallback:
            base_row.update(fallback)
            fetched_any = True

        if not vip_allowed:
            if not base_row.get("future_ah_fetch_fallback"):
                base_row["future_ah_fetch_error"] = vip_probe_error
            if not base_row.get("future_total_fetch_fallback"):
                base_row["future_total_fetch_error"] = vip_probe_error
        else:
            try:
                if not base_row.get("future_ah_fetch_fallback"):
                    _path, raw = fetch_url(f"{VIP_BASE}/AsianOdds_n.aspx?id={match_id}&l=0", stamp, out_dir, f"future_{match_id}_asian.html", referer=f"{BF_BASE}/football/Next_{stamp[:8]}.htm")
                    ah = parse_primary_odds_triplet(decode_text(raw))
                    if ah:
                        base_row.update({"ah_full_open_home_or_over": ah["open_home"], "ah_full_open_line_or_draw": ah["open_line"], "ah_full_open_away_or_under": ah["open_away"], "ah_full_current_home_or_over": ah["current_home"], "ah_full_current_line_or_draw": ah["current_line"], "ah_full_current_away_or_under": ah["current_away"], "ah_full_company": ah["company"]})
                        fetched_any = True
            except Exception as exc:
                base_row["future_ah_fetch_error"] = str(exc)
            try:
                if not base_row.get("future_total_fetch_fallback"):
                    _path, raw = fetch_url(f"{VIP_BASE}/OverDown_n.aspx?id={match_id}&l=0", stamp, out_dir, f"future_{match_id}_total.html", referer=f"{BF_BASE}/football/Next_{stamp[:8]}.htm")
                    total = parse_primary_odds_triplet(decode_text(raw))
                    if total:
                        base_row.update({"total_full_open_home_or_over": total["open_home"], "total_full_open_line_or_draw": total["open_line"], "total_full_open_away_or_under": total["open_away"], "total_full_current_home_or_over": total["current_home"], "total_full_current_line_or_draw": total["current_line"], "total_full_current_away_or_under": total["current_away"], "total_full_company": total["company"]})
                        fetched_any = True
            except Exception as exc:
                base_row["future_total_fetch_error"] = str(exc)
        if match_id in metadata_fetch_ids:
            try:
                _path, raw = fetch_url(f"{EURO_TXT_BASE}/{match_id}.js", stamp, out_dir, f"future_{match_id}_euro.js", referer=f"{BF_BASE}/football/Next_{stamp[:8]}.htm")
                euro_row = parse_euro_txt(decode_text(raw)).get(str(match_id), {})
                if euro_row:
                    base_row.update(euro_row)
                    fetched_any = True
            except Exception as exc:
                base_row["future_euro_fetch_error"] = str(exc)
        return match_id, base_row, fetched_any

    added = 0
    # Bounded concurrency avoids a slow detail endpoint serially blocking the
    # whole slate while keeping the source load moderate.
    max_workers = max(1, int(os.environ.get("TITAN_MAX_WORKERS", "10")))
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [pool.submit(fetch_one, match_id) for match_id in ids_to_fetch]
        completed: dict[str, tuple[dict[str, object], bool]] = {}
        for future in as_completed(futures):
            match_id, base_row, fetched_any = future.result()
            completed[match_id] = (base_row, fetched_any)

    # BetExplorer exposes English fixture labels only after its schedule page
    # has been joined to Titan's per-match euro.js metadata.  That metadata is
    # fetched above, so run this bounded secondary-source join here rather than
    # before enrich_future_odds (where the aggregate euro index has no team
    # names and necessarily produces zero joins).  500.com remains preferred;
    # BetExplorer only fills rows still missing a real Asian market.
    if os.environ.get("TITAN_ENABLE_BETEXPLORER", "1") == "1":
        # Run the secondary source even when 500.com supplied a partial
        # fallback.  The merge below only fills missing fields, so this adds
        # coverage without replacing a confirmed 500/Titan quote.
        euro_metadata = {
            match_id: {
                key: base_row.get(key, "")
                for key in ("home_en", "away_en")
            }
            for match_id, (base_row, _fetched_any) in completed.items()
        }
        try:
            betexplorer = match_betexplorer_to_titan(
                future_rows,
                euro_metadata,
                stamp,
                out_dir,
                os.environ.get(
                    "FOOTBALL_LIST_DATE",
                    dt.datetime.strptime(stamp[:8], "%Y%m%d").date().isoformat(),
                ),
            )
        except Exception as exc:
            print(f"betexplorer_after_euro_failed={exc}", file=sys.stderr)
            betexplorer = {}
        for match_id, fallback in betexplorer.items():
            if not fallback or match_id not in completed:
                continue
            base_row, fetched_any = completed[match_id]
            # Keep a confirmed primary/500 value; use BetExplorer for any
            # missing Asian or Euro component.
            for field, value in fallback.items():
                if value is not None and str(value).strip() and not str(base_row.get(field) or "").strip():
                    base_row[field] = value
            base_row.pop("future_ah_fetch_error", None)
            completed[match_id] = (base_row, True or fetched_any)

        # Some reused labels did not need a fresh txt/1x2 request above.  For
        # the small set of BetExplorer Asian matches only, add the real public
        # Titan 1X2 snapshot so V4 can evaluate the complete market tuple.
        for match_id in betexplorer:
            if match_id not in completed:
                continue
            base_row, fetched_any = completed[match_id]
            euro_ok = all(
                str(base_row.get(key, "") or "").strip()
                for key in (
                    "euro_full_current_home_or_over",
                    "euro_full_current_line_or_draw",
                    "euro_full_current_away_or_under",
                )
            )
            if euro_ok:
                continue
            try:
                _path, raw = fetch_url(
                    f"{EURO_TXT_BASE}/{match_id}.js",
                    stamp,
                    out_dir,
                    f"future_{match_id}_euro_public_fallback.js",
                    referer=f"{BF_BASE}/football/Next_{stamp[:8]}.htm",
                )
                euro_row = parse_euro_txt(decode_text(raw)).get(str(match_id), {})
                if euro_row:
                    for key in (
                        "euro_full_current_home_or_over",
                        "euro_full_current_line_or_draw",
                        "euro_full_current_away_or_under",
                        "euro_full_open_home_or_over",
                        "euro_full_open_line_or_draw",
                        "euro_full_open_away_or_under",
                        "euro_full_company",
                    ):
                        if key in euro_row:
                            base_row[key] = euro_row[key]
                    completed[match_id] = (base_row, True)
            except Exception as exc:
                base_row["future_euro_fallback_error"] = str(exc)
                completed[match_id] = (base_row, fetched_any)

    # Titan's VIP detail host can reset urllib/curl connections in the early
    # morning while still serving the same pages to a real Chromium client.
    # Recover only failed pages in one persistent headless-browser session so
    # a transport failure is never misreported as "market not opened".
    failed_ids = [
        match_id for match_id in ids_to_fetch
        if completed[match_id][0].get("future_ah_fetch_error")
        or completed[match_id][0].get("future_total_fetch_error")
    ]
    browser_recovered = 0
    if failed_ids and os.environ.get("TITAN_ENABLE_BROWSER_FALLBACK", "1") == "1":
        try:
            browser_recovered_ah, browser_recovered_total, browser_failed = browser_recover_vip_pages(
                completed, ids_to_fetch, stamp, out_dir,
            )
            browser_recovered = browser_recovered_ah + browser_recovered_total
            print(
                f"future_browser_recovered_ah={browser_recovered_ah} "
                f"future_browser_recovered_total={browser_recovered_total} "
                f"future_browser_failed={browser_failed}",
                file=sys.stderr,
            )
        except Exception as exc:
            for match_id in failed_ids:
                base_row, fetched_any = completed[match_id]
                base_row["future_browser_fallback_error"] = str(exc)
                completed[match_id] = (base_row, fetched_any)
            print(f"future_browser_fallback_failed={exc}", file=sys.stderr)
    elif failed_ids and vip_probe_error:
        # The one-shot VIP probe already proved that the endpoint is
        # unreachable from this runner.  Do not fan out the same known-bad
        # request to every match; the mobile Analysis fallback below is the
        # independent recovery path and gives a truthful 200/no-market
        # result when a fixture has no published Asian line yet.
        print(f"future_browser_skipped_due_probe={vip_probe_error}", file=sys.stderr)
    # The mobile Analysis page is a separate, broad-coverage Titan endpoint.
    # It remains usable when the VIP detail host is rate-limited, and exposes
    # the source opening/current AH and total triplets in the rendered DOM.
    # Run it after VIP recovery so it only fills still-missing markets.
    if ids_to_fetch and os.environ.get("TITAN_ENABLE_MOBILE_FALLBACK", "0") == "1":
        try:
            mobile_recovered_ah, mobile_recovered_total, mobile_failed = browser_recover_mobile_analysis_pages(
                completed, ids_to_fetch, stamp, out_dir,
            )
            print(
                f"future_mobile_recovered_ah={mobile_recovered_ah} "
                f"future_mobile_recovered_total={mobile_recovered_total} "
                f"future_mobile_failed={mobile_failed}",
                file=sys.stderr,
            )
        except Exception as exc:
            for match_id in ids_to_fetch:
                base_row, fetched_any = completed[match_id]
                base_row["future_mobile_fallback_error"] = str(exc)
                completed[match_id] = (base_row, fetched_any)
            print(f"future_mobile_fallback_failed={exc}", file=sys.stderr)
    # Keep the old serial Playwright path available only as an explicit
    # emergency mode; the async Chromium path above is the normal fallback.
    if failed_ids and os.environ.get("TITAN_ENABLE_BROWSER_FALLBACK", "1") == "legacy":
        try:
            from playwright.sync_api import sync_playwright

            chrome_candidates = (
                Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
                Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
                Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
            )
            executable = next((path for path in chrome_candidates if path.exists()), None)
            if executable is None:
                raise RuntimeError("Chromium executable unavailable for Titan VIP fallback")

            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True, executable_path=str(executable))
                context = browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36"
                )
                page = context.new_page()
                referer = f"{BF_BASE}/football/Next_{stamp[:8]}.htm"
                for match_id in failed_ids:
                    base_row, fetched_any = completed[match_id]
                    if base_row.get("future_ah_fetch_error"):
                        try:
                            page.goto(
                                f"{VIP_BASE}/AsianOdds_n.aspx?id={match_id}&l=0",
                                wait_until="domcontentloaded", timeout=30_000, referer=referer,
                            )
                            text = page.content()
                            (out_dir / f"{stamp}_future_{match_id}_asian_browser.html").write_text(text, encoding="utf-8")
                            ah = parse_primary_odds_triplet(text)
                            if ah:
                                base_row.update({
                                    "ah_full_open_home_or_over": ah["open_home"],
                                    "ah_full_open_line_or_draw": ah["open_line"],
                                    "ah_full_open_away_or_under": ah["open_away"],
                                    "ah_full_current_home_or_over": ah["current_home"],
                                    "ah_full_current_line_or_draw": ah["current_line"],
                                    "ah_full_current_away_or_under": ah["current_away"],
                                    "ah_full_company": ah["company"],
                                    "future_ah_fetch_fallback": "PLAYWRIGHT_CHROMIUM",
                                })
                                base_row.pop("future_ah_fetch_error", None)
                                fetched_any = True
                                browser_recovered += 1
                        except Exception as exc:
                            base_row["future_ah_browser_error"] = str(exc)
                    if base_row.get("future_total_fetch_error"):
                        try:
                            page.goto(
                                f"{VIP_BASE}/OverDown_n.aspx?id={match_id}&l=0",
                                wait_until="domcontentloaded", timeout=30_000, referer=referer,
                            )
                            text = page.content()
                            (out_dir / f"{stamp}_future_{match_id}_total_browser.html").write_text(text, encoding="utf-8")
                            total = parse_primary_odds_triplet(text)
                            if total:
                                base_row.update({
                                    "total_full_open_home_or_over": total["open_home"],
                                    "total_full_open_line_or_draw": total["open_line"],
                                    "total_full_open_away_or_under": total["open_away"],
                                    "total_full_current_home_or_over": total["current_home"],
                                    "total_full_current_line_or_draw": total["current_line"],
                                    "total_full_current_away_or_under": total["current_away"],
                                    "total_full_company": total["company"],
                                    "future_total_fetch_fallback": "PLAYWRIGHT_CHROMIUM",
                                })
                                base_row.pop("future_total_fetch_error", None)
                                fetched_any = True
                        except Exception as exc:
                            base_row["future_total_browser_error"] = str(exc)
                    completed[match_id] = (base_row, fetched_any)
                browser.close()
        except Exception as exc:
            for match_id in failed_ids:
                base_row, fetched_any = completed[match_id]
                base_row["future_browser_fallback_error"] = str(exc)
                completed[match_id] = (base_row, fetched_any)
        print(f"future_browser_recovered={browser_recovered}/{len(failed_ids)}", file=sys.stderr)

    for idx, match_id in enumerate(ids_to_fetch, 1):
        base_row, fetched_any = completed[match_id]
        # Preserve the recovered English labels for the supplement join and
        # for the next run's append-only cache.
        future_rows[match_id].update({k: v for k, v in base_row.items() if v is not None and str(v).strip()})
        if match_id not in rows:
            rows[match_id] = base_row; added += 1
        elif fetched_any:
            rows[match_id].update(base_row)
        if idx % 25 == 0:
            print(f"future_odds={idx}/{len(ids_to_fetch)}", file=sys.stderr)
    return added


def odds_fields(prefix: str, row: list[float | None] | None) -> dict[str, float | None]:
    if not row:
        return {}
    labels = [
        "open_home_or_over",
        "open_line_or_draw",
        "open_away_or_under",
        "current_home_or_over",
        "current_line_or_draw",
        "current_away_or_under",
        "live_home_or_over",
        "live_line_or_draw",
        "live_away_or_under",
    ]
    return {f"{prefix}_{labels[i]}": row[i] if i < len(row) else None for i in range(len(labels))}


ODDS_PREFIXES = ("ah_full", "euro_full", "total_full", "ah_half", "total_half", "euro_half")


def is_odds_key(key: str) -> bool:
    return key.endswith("_company") or any(key.startswith(f"{prefix}_") for prefix in ODDS_PREFIXES)


def snapshot_csv_files() -> list[Path]:
    return sorted(OUT_ROOT.glob("**/*_titan007_odds_snapshot.csv"), key=lambda p: p.stat().st_mtime)


def _snapshot_signature(path: Path) -> dict[str, int]:
    stat = path.stat()
    return {"size": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns)}


def _incremental_snapshot_index(
    index_path: Path,
    current_stamp: str,
    mode: str,
) -> dict[str, dict[str, str]]:
    """Read only new immutable snapshots after the first build.

    The old implementation reparsed every historical CSV twice on every
    refresh: once for started-match odds and once for English labels.  The
    snapshots are append-only, so an index keyed by file signature preserves
    the same latest-row semantics while making later refreshes proportional to
    the number of new snapshots.  If a snapshot is changed or removed, the
    index is rebuilt conservatively.
    """
    files = [path for path in snapshot_csv_files() if not path.name.startswith(current_stamp)]
    signatures = {str(path): _snapshot_signature(path) for path in files}
    cached: dict[str, object] = {}
    try:
        cached_value = json.loads(index_path.read_text(encoding="utf-8"))
        if isinstance(cached_value, dict):
            cached = cached_value
    except (OSError, json.JSONDecodeError):
        cached = {}

    cached_files = cached.get("files") if isinstance(cached.get("files"), dict) else {}
    cached_rows = cached.get("rows") if isinstance(cached.get("rows"), dict) else {}
    # Version 3 stores non-empty market fields as an append-only overlay.
    # Earlier indexes replaced a complete Euro/AH quote with a later blank
    # transport response, so the restore step had nothing left to reuse.
    rebuild = cached.get("version") != 3 or cached.get("mode") != mode
    if set(cached_files) - set(signatures):
        rebuild = True
    if any(cached_files.get(path) != signature for path, signature in signatures.items() if path in cached_files):
        rebuild = True
    rows: dict[str, dict[str, str]] = {} if rebuild else {
        str(match_id): dict(value)
        for match_id, value in cached_rows.items()
        if isinstance(value, dict)
    }
    processed_files: dict[str, dict[str, int]] = {} if rebuild else {
        str(path): dict(signature)
        for path, signature in cached_files.items()
        if path in signatures and isinstance(signature, dict)
    }
    pending = files if rebuild else [path for path in files if str(path) not in processed_files]
    for path in pending:
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                for source_row in csv.DictReader(handle):
                    match_id = str(source_row.get("match_id") or "").strip()
                    if not match_id:
                        continue
                    if mode == "prematch":
                        if str(source_row.get("state") or "").strip() != "0":
                            continue
                        projected = {
                            key: str(value or "")
                            for key, value in source_row.items()
                            if is_odds_key(key)
                        }
                        if not any(value.strip() for value in projected.values()):
                            continue
                        projected.update({
                            "match_id": match_id,
                            "state": str(source_row.get("state") or ""),
                            "snapshot_stamp": str(source_row.get("snapshot_stamp") or ""),
                            "list_date": str(source_row.get("list_date") or ""),
                        })
                    else:
                        projected = {
                            key: str(source_row.get(key) or "")
                            for key in (
                                "match_id", "state", "home_en", "away_en", "league_en",
                                "match_time_en", "snapshot_stamp", "list_date", "home_cn",
                                "away_cn", "league_cn", "bj_time",
                            )
                        }
                    projected["_source"] = str(path)
                    previous = rows.get(match_id, {})
                    merged = dict(previous)
                    # A later snapshot may omit a market. Keep the last
                    # non-empty value while allowing new quotes to replace it.
                    for key, value in projected.items():
                        if str(value or "").strip() or not str(merged.get(key) or "").strip():
                            merged[key] = value
                    rows[match_id] = merged
        except (OSError, UnicodeError):
            continue
        processed_files[str(path)] = signatures[str(path)]

    if rebuild or pending:
        index_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": 3, "mode": mode, "files": signatures, "rows": rows}
        index_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return rows


def load_prior_prematch_odds(current_stamp: str) -> dict[str, dict[str, str]]:
    return _incremental_snapshot_index(PREMATCH_ODDS_INDEX, current_stamp, "prematch")


def restore_missing_prematch_quotes(
    rows: list[dict[str, object]], current_stamp: str, list_date: str,
) -> int:
    """Restore same-list-date quotes when a later refresh loses a market.

    Titan's schedule endpoint can return a complete fixture row with blank
    odds after a transient transport/WAF response.  For an unstarted match,
    dropping a previously confirmed same-list-date quote turns a valid
    candidate into a false missing-data row.  Reuse only complete market
    triplets from an earlier immutable snapshot of the *same* list date and
    mark the provenance; never reuse a quote across list dates.
    """
    prior = load_prior_prematch_odds(current_stamp)
    restored = 0
    prefixes = ("ah_full", "euro_full", "total_full")
    for row in rows:
        if str(row.get("state") or "").strip() != "0":
            continue
        if str(row.get("list_date") or "").strip()[:10] != str(list_date or "").strip()[:10]:
            continue
        match_id = str(row.get("match_id") or "").strip()
        previous = prior.get(match_id)
        if not previous or str(previous.get("list_date") or "").strip()[:10] != str(list_date or "").strip()[:10]:
            continue
        restored_for_row = False
        for prefix in prefixes:
            fields = (
                f"{prefix}_open_home_or_over", f"{prefix}_open_line_or_draw", f"{prefix}_open_away_or_under",
                f"{prefix}_current_home_or_over", f"{prefix}_current_line_or_draw", f"{prefix}_current_away_or_under",
            )
            current_complete = all(str(row.get(field) or "").strip() for field in fields[-3:])
            previous_complete = all(str(previous.get(field) or "").strip() for field in fields[-3:])
            if current_complete or not previous_complete:
                continue
            for field in fields:
                value = str(previous.get(field) or "").strip()
                if value:
                    row[field] = value
            restored_for_row = True
        if restored_for_row:
            row["odds_reused_from_snapshot"] = previous.get("snapshot_stamp", "")
            row["odds_reuse_reason"] = "SAME_LIST_DATE_TRANSIENT_MARKET_GAP"
            restored += 1
    return restored


def freeze_started_match_odds(rows: list[dict[str, object]], current_stamp: str) -> int:
    prematch = load_prior_prematch_odds(current_stamp)
    frozen = 0
    for row in rows:
        match_id = str(row.get("match_id", "") or "").strip()
        state = str(row.get("state", "") or "").strip()
        prior = prematch.get(match_id)
        if not match_id or state == "0" or not prior:
            continue
        for key, value in prior.items():
            # An older snapshot may contain the column but no market value.
            # Never let that empty placeholder erase a real quote fetched in
            # the current refresh (especially after the browser fallback).
            if is_odds_key(key) and str(value or "").strip():
                row[key] = value
        row["odds_frozen_from_snapshot"] = prior.get("snapshot_stamp", "")
        row["latest_snapshot_stamp"] = current_stamp
        frozen += 1
    return frozen


def build_rows(schedule: dict[str, dict[str, str]], sbodds: dict[str, list[list[float | None]]], changes: dict[str, dict[str, str]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for match_id, item in schedule.items():
        row: dict[str, object] = dict(item)
        matrix = sbodds.get(match_id, [])
        row.update(odds_fields("ah_full", matrix[0] if len(matrix) > 0 else None))
        row.update(odds_fields("euro_full", matrix[1] if len(matrix) > 1 else None))
        row.update(odds_fields("total_full", matrix[2] if len(matrix) > 2 else None))
        row.update(odds_fields("ah_half", matrix[3] if len(matrix) > 3 else None))
        row.update(odds_fields("total_half", matrix[4] if len(matrix) > 4 else None))
        row.update(odds_fields("euro_half", matrix[5] if len(matrix) > 5 else None))
        row.update(changes.get(match_id, {}))
        rows.append(row)
    return rows


def roster_path(day: dt.date) -> Path:
    return ROSTER_ROOT / f"titan007_roster_{day.strftime('%Y%m%d')}.json"


def load_roster(day: dt.date) -> dict[str, dict[str, str]]:
    path = roster_path(day)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    rows = data.get("matches", {})
    return rows if isinstance(rows, dict) else {}


def save_roster(day: dt.date, roster: dict[str, dict[str, str]]) -> Path:
    ROSTER_ROOT.mkdir(parents=True, exist_ok=True)
    path = roster_path(day)
    payload = {
        "list_date": day.isoformat(),
        "updated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "matches": roster,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def roster_date_from_path(path: Path) -> str:
    m = re.search(r"titan007_roster_(\d{8})", path.name)
    if not m:
        return ""
    try:
        return dt.datetime.strptime(m.group(1), "%Y%m%d").date().isoformat()
    except ValueError:
        return ""


def load_global_roster_index() -> dict[str, dict[str, str]]:
    """Return the earliest locked list_date for every known match_id."""
    index: dict[str, dict[str, str]] = {}
    for path in sorted(ROSTER_ROOT.glob("titan007_roster_*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        list_date = str(data.get("list_date") or roster_date_from_path(path) or "").strip()
        matches = data.get("matches", {})
        if not list_date or not isinstance(matches, dict):
            continue
        for match_id, row in matches.items():
            match_id = str(match_id or "").strip()
            if not match_id or not isinstance(row, dict):
                continue
            current = index.get(match_id)
            if current and str(current.get("list_date", "")) <= list_date:
                continue
            locked = {str(k): str(v) for k, v in row.items()}
            locked["match_id"] = match_id
            locked["list_date"] = list_date
            locked["_roster_file"] = str(path)
            index[match_id] = locked
    return index


def roster_record(match_id: str, item: dict[str, object], source: str) -> dict[str, str]:
    return {
        "match_id": match_id,
        "league_cn": str(item.get("league_cn", "") or ""),
        "home_cn": str(item.get("home_cn", "") or ""),
        "away_cn": str(item.get("away_cn", "") or ""),
        "bj_time": str(item.get("bj_time", "") or ""),
        "list_source": source,
    }


def apply_list_date_lock(
    match_id: str,
    item: dict[str, object],
    target_list_date: str,
    source: str,
    day_roster: dict[str, dict[str, str]],
    global_roster: dict[str, dict[str, str]],
) -> None:
    """Keep match list_date immutable across refreshes and cross-day reappearances."""
    locked = global_roster.get(match_id)
    if locked:
        locked_date = str(locked.get("list_date") or target_list_date)
        item["list_date"] = locked_date
        item["list_source"] = str(item.get("list_source") or locked.get("list_source") or source)
        item["list_lock_source"] = str(locked.get("_roster_file", ""))
        if locked_date == target_list_date:
            day_roster[match_id] = roster_record(match_id, item, str(item["list_source"]))
        return

    item["list_date"] = target_list_date
    item["list_source"] = source
    day_roster[match_id] = roster_record(match_id, item, source)
    locked = dict(day_roster[match_id])
    locked["list_date"] = target_list_date
    locked["_roster_file"] = str(roster_path(dt.date.fromisoformat(target_list_date)))
    global_roster[match_id] = locked


def latest_snapshot_rows_by_id(current_stamp: str) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for path in reversed(snapshot_csv_files()):
        if path.name.startswith(current_stamp):
            continue
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as f:
                rows = list(csv.DictReader(f))
        except Exception:
            continue
        for row in rows:
            match_id = (row.get("match_id") or "").strip()
            if match_id and match_id not in out:
                out[match_id] = row
    return out


def latest_snapshot_metadata_by_id(current_stamp: str) -> dict[str, dict[str, str]]:
    """Return the small metadata projection used by the public fallback join."""
    return _incremental_snapshot_index(SNAPSHOT_META_INDEX, current_stamp, "metadata")


def restore_missing_roster_rows(
    rows_by_id: dict[str, dict[str, object]],
    roster: dict[str, dict[str, str]],
    current_stamp: str,
    target_list_date: str,
) -> int:
    missing_ids = [str(match_id or "").strip() for match_id in roster if str(match_id or "").strip() not in rows_by_id]
    if not missing_ids:
        return 0
    prior_rows = latest_snapshot_rows_by_id(current_stamp)
    restored = 0
    for match_id, locked in roster.items():
        match_id = str(match_id or "").strip()
        if not match_id or match_id in rows_by_id:
            continue
        prior = prior_rows.get(match_id)
        if prior:
            row: dict[str, object] = dict(prior)
            row["snapshot_stamp"] = current_stamp
            row["not_refreshed_from_snapshot"] = prior.get("snapshot_stamp", "")
        else:
            row = dict(locked)
            row["snapshot_stamp"] = current_stamp
            row["match_id"] = match_id
        row["list_date"] = target_list_date
        row["list_source"] = locked.get("list_source", row.get("list_source", f"roster_{target_list_date.replace('-', '')}"))
        row["refresh_status"] = "本次未刷新到-保留上一版快照"
        rows_by_id[match_id] = row
        restored += 1
    return restored


def _require_saved(out_dir: Path, stamp: str, suffix: str) -> Path:
    matches = sorted(out_dir.glob(f"{stamp}_{suffix}"))
    if not matches:
        raise FileNotFoundError(f"missing {stamp}_{suffix} in {out_dir}")
    return matches[0]


def _maybe_saved(out_dir: Path, stamp: str, suffix: str) -> Path | None:
    matches = sorted(out_dir.glob(f"{stamp}_{suffix}"))
    return matches[0] if matches else None


def materialize_saved_snapshot(stamp: str) -> int:
    """Build a snapshot CSV from already downloaded Titan007 raw files."""
    day = dt.datetime.strptime(stamp[:8], "%Y%m%d").date()
    ymd = day.strftime("%Y%m%d")
    out_dir = OUT_ROOT / ymd

    bf_path = _require_saved(out_dir, stamp, "bfdata_ut.js")
    sb_path = _require_saved(out_dir, stamp, "sbOddsData.js")
    xml_path = _require_saved(out_dir, stamp, "ch_goalbf3.xml")
    next_path = _maybe_saved(out_dir, stamp, f"Next_{ymd}.htm")
    common_path = _maybe_saved(out_dir, stamp, f"CommonInterface_type3_{ymd}.txt")
    euro_path = _maybe_saved(out_dir, stamp, f"index_vip_{ymd}.html")

    schedule = parse_schedule(read_text(bf_path))
    for item in schedule.values():
        item["snapshot_stamp"] = stamp
    sbodds = parse_sbodds(read_text(sb_path))
    changes = parse_change_xml(read_text(xml_path))
    rows_by_id = {str(row["match_id"]): row for row in build_rows(schedule, sbodds, changes)}

    roster = load_roster(day)
    global_roster = load_global_roster_index()
    future_rows: dict[str, dict[str, str]] = {}
    if next_path:
        future_rows = parse_future_schedule(decode_text(next_path.read_bytes()))
        for match_id, item in future_rows.items():
            item["snapshot_stamp"] = stamp
            apply_list_date_lock(match_id, item, day.isoformat(), f"Next_{ymd}", roster, global_roster)

    common_lines = parse_common_lines(decode_text(common_path.read_bytes())) if common_path else {}
    euro = parse_euro_index(decode_text(euro_path.read_bytes())) if euro_path else {}

    future_added = 0
    detail_asian = 0
    detail_total = 0
    for match_id, item in future_rows.items():
        base_row = rows_by_id.get(match_id) or dict(item)
        base_row.update(common_lines.get(match_id, {}))
        base_row.update(euro.get(match_id, {}))

        asian_path = _maybe_saved(out_dir, stamp, f"future_{match_id}_asian.html")
        if asian_path:
            ah = parse_primary_odds_triplet(decode_text(asian_path.read_bytes()))
            if ah:
                base_row.update(
                    {
                        "ah_full_open_home_or_over": ah["open_home"],
                        "ah_full_open_line_or_draw": ah["open_line"],
                        "ah_full_open_away_or_under": ah["open_away"],
                        "ah_full_current_home_or_over": ah["current_home"],
                        "ah_full_current_line_or_draw": ah["current_line"],
                        "ah_full_current_away_or_under": ah["current_away"],
                        "ah_full_company": ah["company"],
                    }
                )
                detail_asian += 1
        elif match_id in common_lines:
            base_row["future_ah_fetch_error"] = "partial_materialize_missing_saved_asian_detail"

        total_path = _maybe_saved(out_dir, stamp, f"future_{match_id}_total.html")
        if total_path:
            total = parse_primary_odds_triplet(decode_text(total_path.read_bytes()))
            if total:
                base_row.update(
                    {
                        "total_full_open_home_or_over": total["open_home"],
                        "total_full_open_line_or_draw": total["open_line"],
                        "total_full_open_away_or_under": total["open_away"],
                        "total_full_current_home_or_over": total["current_home"],
                        "total_full_current_line_or_draw": total["current_line"],
                        "total_full_current_away_or_under": total["current_away"],
                        "total_full_company": total["company"],
                    }
                )
                detail_total += 1
        elif match_id in common_lines:
            base_row["future_total_fetch_error"] = "partial_materialize_missing_saved_total_detail"

        if match_id not in rows_by_id:
            rows_by_id[match_id] = base_row
            future_added += 1
        else:
            rows_by_id[match_id].update(base_row)

    for match_id, row in rows_by_id.items():
        row["snapshot_stamp"] = stamp
        locked = global_roster.get(match_id)
        if locked:
            row["list_date"] = locked.get("list_date", day.isoformat())
            row["list_source"] = row.get("list_source") or locked.get("list_source", f"roster_{ymd}")
            row["list_lock_source"] = locked.get("_roster_file", "")
        elif match_id in roster:
            row["list_date"] = day.isoformat()
            row["list_source"] = row.get("list_source") or roster[match_id].get("list_source", f"roster_{ymd}")

    restored_count = restore_missing_roster_rows(rows_by_id, roster, stamp, day.isoformat())
    roster_file = save_roster(day, roster)
    rows = list(rows_by_id.values())
    frozen_count = freeze_started_match_odds(rows, stamp)
    reused_count = restore_missing_prematch_quotes(rows, stamp, target_list_date)

    csv_path = out_dir / f"{stamp}_titan007_odds_snapshot.csv"
    fieldnames = sorted({key for row in rows for key in row.keys()})
    with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"raw_dir={out_dir}")
    print(f"csv={csv_path}")
    print(f"matches={len(rows)}")
    print(f"future_schedule={len(future_rows)}")
    print(f"future_added={future_added}")
    print(f"detail_asian={detail_asian}")
    print(f"detail_total={detail_total}")
    print(f"frozen_started_odds={frozen_count}")
    print(f"reused_same_list_date_odds={reused_count}")
    print(f"restored_roster_rows={restored_count}")
    print(f"roster={roster_file}")
    print(f"roster_matches={len(roster)}")
    return 0


def _restore_time_key(value: str) -> str:
    match = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})\s+(\d{1,2}):(\d{2})", str(value or ""))
    if not match:
        return "9999-12-31 23:59"
    year, month, day, hour, minute = match.groups()
    return f"{int(year):04d}-{int(month):02d}-{int(day):02d} {int(hour):02d}:{minute}"


def _freeze_header(ledger_dir: Path, detail_header: list[str]) -> list[str]:
    canonical = sorted(ledger_dir.glob("bettable_signal_freeze_*.csv"))
    if canonical:
        with canonical[-1].open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames:
                return list(reader.fieldnames)
    extras = [
        "冻结时间",
        "阻诱目标侧",
        "理论资金主队占比",
        "理论资金客队占比",
        "实际资金主队占比",
        "实际资金客队占比",
        "资金偏离主队",
        "资金偏离客队",
        "资金过热侧",
        "过热阈值",
        "理论占比依据",
        "实际资金流向",
        "目标侧水位甜头",
        "意图成败",
        "资金流修正方向",
        "资金流修正球队",
        "资金流来源",
        "资金流时间戳",
        "下注建议",
        "未通过/通过原因",
    ]
    return list(dict.fromkeys([*detail_header, *extras]))


def restore_historical_bettable_freezes(dates: list[str], rebuild_dashboard: bool = False) -> int:
    """Freeze old same-day bettable rows without recomputing them under today's model."""
    root = OUT_ROOT.parents[1]
    ledger_dir = root / "ledger"
    restored_counts: dict[str, int] = {}
    frozen_at = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")

    for list_date in dates:
        detail_path = ledger_dir / f"bettable_event_detail_{list_date}.csv"
        if not detail_path.exists():
            print(f"restore_missing_detail={detail_path}", file=sys.stderr)
            restored_counts[list_date] = 0
            continue
        with detail_path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            source_header = list(reader.fieldnames or [])
            fieldnames = _freeze_header(ledger_dir, source_header)
            rows: list[dict[str, str]] = []
            seen: set[str] = set()
            for row in reader:
                if str(row.get("日期", "")).strip() != list_date:
                    continue
                if str(row.get("动作", "")).strip() not in {"正向", "反向"}:
                    continue
                dedupe = str(row.get("比赛ID", "") or row.get("比赛", "")).strip()
                if dedupe and dedupe in seen:
                    continue
                if dedupe:
                    seen.add(dedupe)
                out = {field: "" for field in fieldnames}
                for key, value in row.items():
                    if key in out:
                        out[key] = value
                out["统计日期"] = list_date
                out["冻结时间"] = frozen_at
                out["数据源"] = f"旧版快照恢复:{detail_path}"
                out["日期"] = list_date
                out["过热阈值"] = out.get("过热阈值") or "5pct"
                out["理论占比依据"] = out.get("理论占比依据") or "旧版同日明细恢复；资金占比未重算"
                out["实际资金流向"] = out.get("实际资金流向") or "旧版恢复：未追加资金流，不影响原亚盘EV结论"
                out["资金流来源"] = out.get("资金流来源") or "旧版恢复"
                out["资金流时间戳"] = out.get("资金流时间戳") or frozen_at
                out["下注建议"] = out.get("下注建议") or "可投"
                out["未通过/通过原因"] = "恢复同日可投明细；不按赛后/新口径重算"
                rows.append(out)

        rows.sort(key=lambda item: (_restore_time_key(item.get("开赛时间", "")), item.get("比赛ID", "")))
        out_path = ledger_dir / f"bettable_signal_freeze_{list_date}_{stamp}_restored.csv"
        with out_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        restored_counts[list_date] = len(rows)
        print(f"freeze_csv={out_path}")
        print(f"restore_date={list_date} rows={len(rows)}")

    if rebuild_dashboard:
        try:
            runpy.run_path(str(Path(r"D:\codex\tools\build_football_dashboard.py")), run_name="__main__")
        except SystemExit as exc:
            if exc.code not in (0, None):
                raise
        print(f"dashboard={root / 'dashboard' / 'index.html'}")
    print(f"restore_summary={restored_counts}")
    return 0 if any(restored_counts.values()) else 1


def dashboard_bettable_counts(date_filter: str = "") -> int:
    path = Path(r"D:\codex\outputs\football_odds_trader\dashboard\index.html")
    text = path.read_text(encoding="utf-8")
    marker = "const cardsData = "
    start = text.index(marker) + len(marker)
    end_marker = "\ncardsData.forEach"
    end = text.index(end_marker, start) if end_marker in text[start:] else text.index("\nconst stats", start)
    payload = text[start:end].strip().rstrip(";").strip()
    cards = json.loads(payload)
    counts: dict[str, dict[str, int]] = {}
    for card in cards:
        date = str(card.get("date", "") or "").strip()
        if date_filter and date != date_filter:
            continue
        item = counts.setdefault(date, {"cards": 0, "frozen": 0})
        item["cards"] += 1
        if card.get("frozen_bettable"):
            item["frozen"] += 1
    for date in sorted(counts):
        item = counts[date]
        print(f"{date}: cards={item['cards']} frozen_bettable={item['frozen']}")
    return 0


def main() -> int:
    if len(sys.argv) >= 3 and sys.argv[1] == "--materialize-stamp":
        return materialize_saved_snapshot(sys.argv[2])
    if len(sys.argv) >= 2 and sys.argv[1] == "--dashboard-bettable-counts":
        date_filter = sys.argv[2] if len(sys.argv) >= 3 else ""
        return dashboard_bettable_counts(date_filter)
    if len(sys.argv) >= 2 and sys.argv[1] == "--build-dashboard":
        script = Path(r"D:\codex\tools\build_football_dashboard.py")
        try:
            runpy.run_path(str(script), run_name="__main__")
        except SystemExit as exc:
            return int(exc.code or 0)
        return 0
    if len(sys.argv) >= 3 and sys.argv[1] == "--freeze-dashboard-bettable":
        script = Path(r"D:\codex\tools\freeze_today_bettable_events.py")
        sys.argv = [str(script), *sys.argv[2:]]
        try:
            runpy.run_path(str(script), run_name="__main__")
        except SystemExit as exc:
            return int(exc.code or 0)
        return 0
    if len(sys.argv) >= 3 and sys.argv[1] == "--restore-historical-bettable":
        rebuild_dashboard = "--rebuild-dashboard" in sys.argv
        dates = [arg for arg in sys.argv[2:] if not arg.startswith("--")]
        return restore_historical_bettable_freezes(dates, rebuild_dashboard=rebuild_dashboard)

    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = OUT_ROOT / stamp[:8]
    out_dir.mkdir(parents=True, exist_ok=True)

    future_count = 0
    future_added = 0
    try:
        # These three immutable public feeds are independent.  The schedule
        # is required; SB odds and change XML are supplements.  A supplement
        # failure must not discard the roster or prevent later strict market
        # fallbacks from running.
        with ThreadPoolExecutor(max_workers=3) as pool:
            feed_futures = {
                name: pool.submit(fetch, name, stamp, out_dir)
                for name in ("bfdata_ut.js", "sbOddsData.js", "ch_goalbf3.xml")
            }
            bf_path = feed_futures["bfdata_ut.js"].result()
            try:
                sb_path = feed_futures["sbOddsData.js"].result()
            except Exception as exc:
                sb_path = None
                print(f"sbodds_optional_fetch_failed: {exc}", file=sys.stderr)
            try:
                xml_path = feed_futures["ch_goalbf3.xml"].result()
            except Exception as exc:
                xml_path = None
                print(f"change_xml_optional_fetch_failed: {exc}", file=sys.stderr)
    except Exception as exc:
        print(f"fetch_failed: {exc}", file=sys.stderr)
        return 2

    # list_date is the immutable Titan/球探 roster key. Manual refreshes may
    # happen at any clock time, so read the requested list date explicitly.
    today = dt.date.fromisoformat(os.environ.get("FOOTBALL_LIST_DATE", dt.date.today().isoformat()))
    target_list_date = today.isoformat()
    ymd = today.strftime("%Y%m%d")
    roster = load_roster(today)
    global_roster = load_global_roster_index()

    schedule = parse_schedule(read_text(bf_path))
    for item in schedule.values():
        item["snapshot_stamp"] = stamp
    sbodds = parse_sbodds(read_text(sb_path)) if sb_path else {}
    changes = parse_change_xml(read_text(xml_path)) if xml_path else {}
    rows_by_id = {str(row["match_id"]): row for row in build_rows(schedule, sbodds, changes)}

    try:
        future_path, future_raw = fetch_url(
            f"{BF_BASE}/football/Next_{ymd}.htm",
            stamp,
            out_dir,
            f"Next_{ymd}.htm",
            referer=REFERER,
        )
        future_rows = parse_future_schedule(decode_text(future_raw))
        # The Next page contains several future list dates.  A daily refresh
        # must only materialize the requested list date; fetching later dates
        # wastes requests and can block the current day's publication when a
        # VIP endpoint is slow or unavailable.
        # One business slate runs Beijing 12:00 through next-day 11:59.
        # Keep the early next-day fixtures so 00:00-11:59 are not lost.
        next_day = today + dt.timedelta(days=1)
        target_mmdd = {today.strftime("%m-%d"), next_day.strftime("%m-%d")}
        future_rows = {
            match_id: item
            for match_id, item in future_rows.items()
            if any(str(item.get("bj_time", "")).strip().startswith(mmdd) for mmdd in target_mmdd)
        }
        for match_id, item in future_rows.items():
            item["snapshot_stamp"] = stamp
            apply_list_date_lock(match_id, item, target_list_date, f"Next_{ymd}", roster, global_roster)
        save_roster(today, roster)
        future_count = len(future_rows)
        # These are independent supplements after the Next page is parsed.
        # Run them concurrently; each source still has its own strict parser
        # and a failed optional source remains an explicit missing-data state.
        with ThreadPoolExecutor(max_workers=3) as pool:
            common_future = pool.submit(
                fetch_url,
                f"{BF_BASE}/CommonInterface.ashx?type=3&date={today.isoformat()}",
                stamp,
                out_dir,
                f"CommonInterface_type3_{ymd}.txt",
                str(future_path),
            )
            euro_future = pool.submit(
                fetch_url,
                EURO_INDEX,
                stamp,
                out_dir,
                f"index_vip_{ymd}.html",
                str(future_path),
            )
            five_future = pool.submit(load_fivehundred_odds, stamp, out_dir, target_list_date)
            common_lines = {}
            try:
                _common_path, common_raw = common_future.result()
                common_lines = parse_common_lines(decode_text(common_raw))
            except Exception as exc:
                # CommonInterface is an index hint, not the roster authority.
                print(f"common_interface_optional_fetch_failed: {exc}", file=sys.stderr)
            euro = {}
            try:
                _euro_path, euro_raw = euro_future.result()
                euro = parse_euro_index(decode_text(euro_raw))
            except Exception as exc:
                # Titan's aggregate Europe page is optional.  Its failure
                # cannot short-circuit the core Asian/total attempts.
                print(f"euro_optional_fetch_failed: {exc}", file=sys.stderr)
            fivehundred_fallback: dict[str, dict[str, object]] = {}
            try:
                five_feed = five_future.result()
                fivehundred_fallback = match_fivehundred_to_titan(future_rows, five_feed, stamp)
            except Exception as exc:
                # 500.com is a supplement.  A WAF/error page must be visible
                # in logs but can never make missing data look bettable.
                print(f"fivehundred_optional_fetch_failed: {exc}", file=sys.stderr)
        future_added = enrich_future_odds(
            rows_by_id,
            future_rows,
            common_lines,
            euro,
            stamp,
            out_dir,
            fivehundred=fivehundred_fallback,
        )
        # BetExplorer can carry major competitions that are absent from the
        # Titan Next page altogether (for example Championship/UCL fixtures).
        # Add those rows after Titan enrichment so their provider IDs never
        # enter the Titan VIP/mobile recovery queue.
        supplemental_rows = build_betexplorer_supplemental_rows(
            future_rows,
            euro,
            stamp,
            out_dir,
            target_list_date,
            existing_rows=rows_by_id,
        )
        for match_id, item in supplemental_rows.items():
            item["snapshot_stamp"] = stamp
            apply_list_date_lock(
                match_id,
                item,
                target_list_date,
                "BetExplorer_supplemental",
                roster,
                global_roster,
            )
            rows_by_id[match_id] = item
        future_added += len(supplemental_rows)

        # The Titan daily board contains official fixtures whose schedule row
        # exists but whose current AH transport is blank.  Those rows are not
        # in ``future_rows`` (the Next page is only a supplement), so give
        # BetExplorer a second filtered pass over the existing roster.
        # Merge only missing market fields; Titan/500 values remain preferred.
        def _complete_ah(item: dict[str, object]) -> bool:
            return all(str(item.get(k, "") or "").strip() for k in (
                "ah_full_current_home_or_over", "ah_full_current_line_or_draw", "ah_full_current_away_or_under"
            ))
        def _complete_euro(item: dict[str, object]) -> bool:
            return all(str(item.get(k, "") or "").strip() for k in (
                "euro_full_current_home_or_over", "euro_full_current_line_or_draw", "euro_full_current_away_or_under"
            ))
        coverage_targets = {
            match_id: row for match_id, row in rows_by_id.items()
            if str(row.get("state") or "").strip() in {"0", ""}
            and str(row.get("source_provider") or "") != "BetExplorer"
            and (not _complete_ah(row) or not _complete_euro(row))
            and str(row.get("home_en") or row.get("home_cn") or "").strip()
            and str(row.get("away_en") or row.get("away_cn") or "").strip()
        }
        if coverage_targets:
            try:
                existing_fallbacks = match_betexplorer_to_titan(
                    coverage_targets, {}, stamp, out_dir, target_list_date,
                )
                for match_id, fallback in existing_fallbacks.items():
                    target = rows_by_id.get(match_id)
                    if not target:
                        continue
                    for field, value in fallback.items():
                        if value is not None and str(value).strip() and not str(target.get(field) or "").strip():
                            target[field] = value
                print(
                    f"betexplorer_existing_targets={len(coverage_targets)} "
                    f"betexplorer_existing_mapped={len(existing_fallbacks)}",
                    file=sys.stderr,
                )
            except Exception as exc:
                print(f"betexplorer_existing_failed={exc}", file=sys.stderr)
    except Exception as exc:
        print(f"future_fetch_failed: {exc}", file=sys.stderr)

    for match_id, row in rows_by_id.items():
        row["snapshot_stamp"] = stamp
        locked = global_roster.get(match_id)
        if locked:
            row["list_date"] = locked.get("list_date", target_list_date)
            row["list_source"] = row.get("list_source") or locked.get("list_source", f"roster_{ymd}")
            row["list_lock_source"] = locked.get("_roster_file", "")
        elif match_id in roster:
            row["list_date"] = target_list_date
            row["list_source"] = row.get("list_source") or roster[match_id].get("list_source", f"roster_{ymd}")

    restored_count = restore_missing_roster_rows(rows_by_id, roster, stamp, target_list_date)
    roster_file = save_roster(today, roster)
    rows = list(rows_by_id.values())
    frozen_count = freeze_started_match_odds(rows, stamp)
    # A transient Titan refresh can omit a prematch quote even though the
    # same-list-date snapshot already had a complete quote.  Reuse that
    # immutable prematch quote for unstarted rows only; started rows remain
    # frozen and are never rewritten.
    reused_count = restore_missing_prematch_quotes(rows, stamp, target_list_date)

    # A previous refresh may have written a transport error before the mobile
    # fallback confirmed that the page was a valid HTTP 200 with no market row.
    # Do not carry that stale error into later snapshots.  Keep the missing
    # market explicit so downstream V3/V4 gates still reject it safely.
    for row in rows:
        for market in ("ah", "total"):
            status_key = f"future_{market}_market_status"
            mobile_error_key = f"future_{market}_mobile_browser_error"
            if row.get(mobile_error_key) == "mobile_empty_market_http_200":
                row[status_key] = "NOT_PUBLISHED"
                row.pop(mobile_error_key, None)
                row.pop(f"future_{market}_browser_error", None)
                row.pop(f"future_{market}_fetch_error", None)

    csv_path = out_dir / f"{stamp}_titan007_odds_snapshot.csv"
    fieldnames = sorted({key for row in rows for key in row.keys()})
    with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"raw_dir={out_dir}")
    print(f"csv={csv_path}")
    print(f"matches={len(rows)}")
    print(f"with_sbodds={sum(1 for k in schedule if k in sbodds)}")
    print(f"with_change_xml={sum(1 for k in schedule if k in changes)}")
    print(f"future_schedule={future_count}")
    print(f"future_added={future_added}")
    print(f"frozen_started_odds={frozen_count}")
    print(f"reused_same_list_date_odds={reused_count}")
    print(f"restored_roster_rows={restored_count}")
    print(f"roster={roster_file}")
    print(f"roster_matches={len(roster)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


