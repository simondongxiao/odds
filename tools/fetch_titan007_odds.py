from __future__ import annotations

import csv
from concurrent.futures import ThreadPoolExecutor, as_completed
import datetime as dt
import html
import json
import re
import runpy
import shutil
import subprocess
import sys
import time
import os
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path


BASE = "https://livestatic.titan007.com/vbsxml"
REFERER = "https://live.titan007.com/oldIndexall.aspx"
OUT_ROOT = Path(r"D:\codex\v3_legacy\outputs\football_odds_trader\raw\titan007")
BF_BASE = "https://bf.titan007.com"
VIP_BASE = "https://vip.titan007.com"
EURO_INDEX = "https://1x2.titan007.com/index_vip.aspx"
ROSTER_ROOT = OUT_ROOT.parents[1] / "ledger" / "slate_rosters"


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
    with urllib.request.urlopen(req, timeout=20) as resp:
        target.write_bytes(resp.read())
    return target


def fetch_url(url: str, stamp: str, out_dir: Path, label: str, referer: str = REFERER) -> tuple[Path, bytes]:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", label).strip("_")
    target = out_dir / f"{stamp}_{safe}"
    cache_key = f"r=007{int(time.time() * 1000)}"
    fresh_url = f"{url}&{cache_key}" if "?" in url else f"{url}?{cache_key}"
    urls = [fresh_url]
    if fresh_url.startswith("https://bf.titan007.com/"):
        urls.append("http://bf.titan007.com/" + fresh_url.removeprefix("https://bf.titan007.com/"))
    last_error: Exception | None = None
    raw = b""
    for candidate in urls:
        req = urllib.request.Request(
            candidate,
            headers={
                "Referer": referer,
                "User-Agent": "Mozilla/5.0",
                "Accept": "*/*",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=12) as resp:
                raw = resp.read()
            break
        except Exception as exc:
            last_error = exc
            curl = shutil.which("curl.exe") or shutil.which("curl")
            if curl:
                try:
                    completed = subprocess.run(
                        [
                            curl, "-sS", "-L", "--max-time", "20",
                            "-A", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36",
                            "-e", referer, "-H", "Accept: */*", candidate,
                        ],
                        check=True, capture_output=True, timeout=25,
                    )
                    if completed.stdout:
                        raw = completed.stdout
                        break
                except Exception as curl_exc:
                    last_error = curl_exc
    else:
        assert last_error is not None
        raise last_error
    target.write_bytes(raw)
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
            "initial_total_hint": row[43] if len(row) > 43 else "",
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
    root = ET.fromstring(text)
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
    preferences = ("Crow", "36", "澳", "易胜", "伟", "明", "10", "12", "利", "盈", "18")
    for pref in preferences:
        for cand in candidates:
            if pref in str(cand["company"]):
                return cand
    return candidates[0]


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


def enrich_future_odds(rows: dict[str, dict[str, object]], future_rows: dict[str, dict[str, str]], lines: dict[str, dict[str, str]], euro: dict[str, dict[str, float | str]], stamp: str, out_dir: Path) -> int:
    ids_to_fetch = [match_id for match_id in future_rows if match_id in lines]

    def fetch_one(match_id: str) -> tuple[str, dict[str, object], bool]:
        base_row = dict(rows.get(match_id) or future_rows[match_id])
        base_row.update(lines.get(match_id, {})); base_row.update(euro.get(match_id, {}))
        fetched_any = False
        try:
            _path, raw = fetch_url(f"{VIP_BASE}/AsianOdds_n.aspx?id={match_id}&l=0", stamp, out_dir, f"future_{match_id}_asian.html", referer=f"{BF_BASE}/football/Next_{stamp[:8]}.htm")
            ah = parse_primary_odds_triplet(decode_text(raw))
            if ah:
                base_row.update({"ah_full_open_home_or_over": ah["open_home"], "ah_full_open_line_or_draw": ah["open_line"], "ah_full_open_away_or_under": ah["open_away"], "ah_full_current_home_or_over": ah["current_home"], "ah_full_current_line_or_draw": ah["current_line"], "ah_full_current_away_or_under": ah["current_away"], "ah_full_company": ah["company"]})
                fetched_any = True
        except Exception as exc:
            base_row["future_ah_fetch_error"] = str(exc)
        try:
            _path, raw = fetch_url(f"{VIP_BASE}/OverDown_n.aspx?id={match_id}&l=0", stamp, out_dir, f"future_{match_id}_total.html", referer=f"{BF_BASE}/football/Next_{stamp[:8]}.htm")
            total = parse_primary_odds_triplet(decode_text(raw))
            if total:
                base_row.update({"total_full_open_home_or_over": total["open_home"], "total_full_open_line_or_draw": total["open_line"], "total_full_open_away_or_under": total["open_away"], "total_full_current_home_or_over": total["current_home"], "total_full_current_line_or_draw": total["current_line"], "total_full_current_away_or_under": total["away"], "total_full_company": total["company"]})
                # Retain the existing total alias fields used by the V3 parser.
                base_row["total_full_current_away_or_under"] = total["current_away"]
                fetched_any = True
        except Exception as exc:
            base_row["future_total_fetch_error"] = str(exc)
        return match_id, base_row, fetched_any

    added = 0
    # Bounded concurrency avoids a slow detail endpoint serially blocking the
    # whole slate while keeping the source load moderate.
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(fetch_one, match_id) for match_id in ids_to_fetch]
        completed: dict[str, tuple[dict[str, object], bool]] = {}
        for future in as_completed(futures):
            match_id, base_row, fetched_any = future.result()
            completed[match_id] = (base_row, fetched_any)
    for idx, match_id in enumerate(ids_to_fetch, 1):
        base_row, fetched_any = completed[match_id]
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


def load_prior_prematch_odds(current_stamp: str) -> dict[str, dict[str, str]]:
    prematch: dict[str, dict[str, str]] = {}
    for path in snapshot_csv_files():
        if path.name.startswith(current_stamp):
            continue
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as f:
                rows = list(csv.DictReader(f))
        except Exception:
            continue
        for row in rows:
            match_id = (row.get("match_id") or "").strip()
            if not match_id or (row.get("state") or "").strip() != "0":
                continue
            if any((row.get(key) or "").strip() for key in row if is_odds_key(key)):
                prematch[match_id] = row
    return prematch


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
            if is_odds_key(key):
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


def restore_missing_roster_rows(
    rows_by_id: dict[str, dict[str, object]],
    roster: dict[str, dict[str, str]],
    current_stamp: str,
    target_list_date: str,
) -> int:
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
        bf_path = fetch("bfdata_ut.js", stamp, out_dir)
        sb_path = fetch("sbOddsData.js", stamp, out_dir)
        xml_path = fetch("ch_goalbf3.xml", stamp, out_dir)
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
    sbodds = parse_sbodds(read_text(sb_path))
    changes = parse_change_xml(read_text(xml_path))
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
        for match_id, item in future_rows.items():
            if roster and match_id not in roster:
                continue
            item["snapshot_stamp"] = stamp
            apply_list_date_lock(match_id, item, target_list_date, f"Next_{ymd}", roster, global_roster)
        save_roster(today, roster)
        future_count = len(future_rows)
        common_path, common_raw = fetch_url(
            f"{BF_BASE}/CommonInterface.ashx?type=3&date={today.isoformat()}",
            stamp,
            out_dir,
            f"CommonInterface_type3_{ymd}.txt",
            referer=str(future_path),
        )
        common_lines = parse_common_lines(decode_text(common_raw))
        euro_path, euro_raw = fetch_url(
            EURO_INDEX,
            stamp,
            out_dir,
            f"index_vip_{ymd}.html",
            referer=str(future_path),
        )
        euro = parse_euro_index(decode_text(euro_raw))
        future_added = enrich_future_odds(rows_by_id, future_rows, common_lines, euro, stamp, out_dir)
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
    print(f"restored_roster_rows={restored_count}")
    print(f"roster={roster_file}")
    print(f"roster_matches={len(roster)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
