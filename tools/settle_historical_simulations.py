from __future__ import annotations

import csv
import math
import re
import unicodedata
from collections import Counter
from datetime import date, datetime
from html import unescape
from pathlib import Path


ROOT = Path(r"D:\codex\outputs\football_odds_trader")
LEDGER = ROOT / "ledger" / "simulated_bets.csv"
ESPN_RAW = ROOT / "raw" / "espn_scores"
TITAN_RAW = ROOT / "raw" / "titan007"
TODAY = datetime.now().date()


TEAM_ALIASES = {
    "大田市民": "daejeon hana citizen",
    "光州FC": "gwangju fc",
    "光州": "gwangju fc",
    "首尔FC": "fc seoul",
    "全北现代": "jeonbuk hyundai motors",
    "蔚山HD": "ulsan hd",
    "浦项制铁": "pohang steelers",
    "济州联": "jeju united",
    "仁川联": "incheon united",
    "江原FC": "gangwon fc",
    "安养FC": "fc anyang",
    "金泉尚武": "gimcheon sangmu",
    "水原FC": "suwon fc",
    "悉尼奥林匹克": "sydney olympic",
    "布里斯班狮吼": "brisbane roar",
    "马可尼": "marconi stallions",
    "悉尼联盟": "sydney united",
    "莱卡特老虎": "leichhardt tigers",
    "卧龙岗狼队": "wollongong wolves",
    "西悉尼流浪者青年队": "western sydney wanderers youth",
}

ABNORMAL_TITAN_STATUSES = ("推迟", "取消", "延期", "腰斩", "中断")


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def norm(text: str) -> str:
    raw = TEAM_ALIASES.get((text or "").strip(), text or "")
    ascii_text = unicodedata.normalize("NFKD", raw).encode("ascii", "ignore").decode("ascii")
    ascii_text = ascii_text.lower()
    ascii_text = re.sub(r"\b(fc|sc|cf|afc|club|the)\b", " ", ascii_text)
    ascii_text = re.sub(r"[^a-z0-9]+", " ", ascii_text)
    ascii_text = re.sub(r"\s+", " ", ascii_text).strip()
    if ascii_text:
        return ascii_text
    zh_text = re.sub(r"\[[^\]]+\]", " ", raw.lower())
    zh_text = re.sub(r"[^\w\u4e00-\u9fff]+", " ", zh_text)
    return re.sub(r"\s+", " ", zh_text).strip()


def split_match(match: str) -> tuple[str, str] | None:
    if " vs " not in match:
        return None
    home, away = match.split(" vs ", 1)
    return home.strip(), away.strip()


def latest_espn_rows() -> list[dict[str, str]]:
    files = sorted(ESPN_RAW.glob("espn_events_*.csv"), key=lambda p: p.stat().st_mtime)
    rows: list[dict[str, str]] = []
    for path in files:
        rows.extend(read_csv(path))
    return rows


def titan_rows() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for path in sorted(TITAN_RAW.glob("**/*_titan007_odds_snapshot.csv")):
        for row in read_csv(path):
            row = dict(row)
            row["_source_file"] = str(path)
            rows.append(row)
    return rows


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
    value = unescape(value).replace("\xa0", " ")
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


def page_date_from_over_path(path: Path) -> date | None:
    m = re.search(r"Over_(\d{8})", path.name)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%Y%m%d").date()
    except ValueError:
        return None


def actual_date_from_time(page_date: date, time_text: str) -> date:
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
        return date(year, month, day)
    except ValueError:
        return page_date


def titan_over_score_rows() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for path in sorted(TITAN_RAW.glob("**/*Over_*.htm")):
        page_date = page_date_from_over_path(path)
        if not page_date:
            continue
        text = read_text_auto(path)
        for tr in re.finditer(r"<tr\b[^>]*\bsId=['\"]?(\d{6,})['\"]?[^>]*>(.*?)</tr>", text, re.S | re.I):
            match_id = tr.group(1)
            cells = re.findall(r"<td\b[^>]*>(.*?)</td>", tr.group(2), re.S | re.I)
            if len(cells) < 6:
                continue
            league = strip_html(cells[0])
            time_text = strip_html(cells[1])
            status = strip_html(cells[2])
            home = clean_team(cells[3])
            score_text = strip_html(cells[4])
            away = clean_team(cells[5])
            score_match = re.search(r"(\d+)\s*-\s*(\d+)", score_text)
            is_abnormal = any(term in status for term in ABNORMAL_TITAN_STATUSES)
            if not home or not away:
                continue
            if ("完" not in status or not score_match) and not is_abnormal:
                continue
            actual_date = actual_date_from_time(page_date, time_text)
            rows.append(
                {
                    "match_id": match_id,
                    "list_date": page_date.isoformat(),
                    "actual_date": actual_date.isoformat(),
                    "league": league,
                    "home": home,
                    "away": away,
                    "home_score": score_match.group(1) if score_match else "",
                    "away_score": score_match.group(2) if score_match else "",
                    "status": status,
                    "abnormal": "1" if is_abnormal else "",
                    "source": f"Titan007完场页:{path.name}",
                }
            )
    return rows


def load_scores() -> dict[tuple[str, str, str], dict[str, str]]:
    scores: dict[tuple[str, str, str], dict[str, str]] = {}
    for row in latest_espn_rows():
        if str(row.get("completed", "")).lower() != "true":
            continue
        d = row.get("bjt_date") or ""
        home = row.get("home", "")
        away = row.get("away", "")
        if not d or not home or not away:
            continue
        payload = {
            "home": home,
            "away": away,
            "home_score": row.get("home_score", ""),
            "away_score": row.get("away_score", ""),
            "status": row.get("status_detail", "Final"),
            "source": row.get("source_url", "ESPN"),
        }
        scores[(d, norm(home), norm(away))] = payload
    for row in titan_rows():
        state = row.get("state", "")
        if state != "-1":
            continue
        bj = row.get("bj_time", "")
        m = re.match(r"(\d{1,2}-\d{1,2})\s+", bj)
        if not m:
            continue
        d = f"2026-{m.group(1)}"
        try:
            d = datetime.strptime(d, "%Y-%m-%d").date().isoformat()
        except ValueError:
            continue
        home = row.get("home_cn", "")
        away = row.get("away_cn", "")
        if not home or not away:
            continue
        payload = {
            "home": home,
            "away": away,
            "home_score": row.get("home_score", ""),
            "away_score": row.get("away_score", ""),
            "status": "Final",
            "source": "Titan007快照",
        }
        scores[(d, norm(home), norm(away))] = payload
        match_id = match_id_from_row(row)
        if match_id:
            scores[("match_id", match_id, "")] = payload
    for row in titan_over_score_rows():
        home = row.get("home", "")
        away = row.get("away", "")
        if not home or not away:
            continue
        payload = {
            "home": home,
            "away": away,
            "home_score": row.get("home_score", ""),
            "away_score": row.get("away_score", ""),
            "status": row.get("status", "完"),
            "abnormal": row.get("abnormal", ""),
            "source": row.get("source", "Titan007完场页"),
        }
        for d in {row.get("list_date", ""), row.get("actual_date", "")}:
            if d:
                scores[(d, norm(home), norm(away))] = payload
        match_id = row.get("match_id", "")
        if match_id:
            scores[("match_id", match_id, "")] = payload
    return scores


def find_score(row: dict[str, str], scores: dict[tuple[str, str, str], dict[str, str]]) -> dict[str, str] | None:
    match_id = match_id_from_row(row)
    if match_id:
        direct_id = scores.get(("match_id", match_id, ""))
        if direct_id:
            return direct_id
    match = split_match(row.get("比赛", ""))
    if not match:
        return None
    d = row.get("日期", "")
    home, away = match
    direct = scores.get((d, norm(home), norm(away)))
    if direct:
        return direct
    nh, na = norm(home), norm(away)
    best = None
    best_score = 0
    for (sd, sh, sa), score in scores.items():
        if sd != d:
            continue
        points = 0
        if nh and (nh in sh or sh in nh):
            points += 2
        if na and (na in sa or sa in na):
            points += 2
        if nh and nh in sa:
            points -= 2
        if na and na in sh:
            points -= 2
        if points > best_score:
            best_score = points
            best = score
    return best if best_score >= 4 else None


def extract_decimal(text: str) -> float | None:
    text = text or ""
    for pat in (r"十进制([0-9.]+)", r"@\s*HK\s*([0-9.]+)", r"\b(?:ML|Draw)\s*([0-9.]+)", r">=\s*([0-9.]+)", r"<=\s*([0-9.]+)", r"\b([12]\.[0-9]{2})\b"):
        m = re.search(pat, text, re.I)
        if not m:
            continue
        v = float(m.group(1))
        if "HK" in pat:
            return 1.0 + v
        return v
    return None


def extract_line(text: str) -> float | None:
    m = re.search(r"([+-]?\d+(?:\.\d+)?)", text or "")
    return float(m.group(1)) if m else None


def stake(row: dict[str, str]) -> float:
    try:
        return float((row.get("虚拟仓位单位") or "0.25").replace("+", ""))
    except ValueError:
        return 0.25


def asian_factor(value: float) -> float:
    eps = 1e-9
    if value > eps:
        return 1.0
    if value < -eps:
        return -1.0
    return 0.0


def quarter_factor(value: float) -> float:
    frac = abs(value - math.trunc(value))
    if abs(frac - 0.25) < 1e-9:
        low = math.floor(value * 2) / 2
        high = low + 0.5
        return (asian_factor(low) + asian_factor(high)) / 2
    if abs(frac - 0.75) < 1e-9:
        low = math.floor(value * 2) / 2
        high = low + 0.5
        return (asian_factor(low) + asian_factor(high)) / 2
    return asian_factor(value)


def pnl_from_factor(factor: float, row: dict[str, str]) -> str:
    st = stake(row)
    dec = extract_decimal(row.get("模拟盘口/价格", "")) or 2.0
    if factor > 0:
        return f"+{st * (dec - 1) * factor:.2f}"
    if factor < 0:
        return f"{st * factor:.2f}"
    return "0"


def selected_side(row: dict[str, str], home: str, away: str) -> str | None:
    pick = row.get("模拟方向", "")
    if "平局" in pick or pick.lower().startswith("draw"):
        return "draw"
    hp, ap = norm(home), norm(away)
    npick = norm(pick)
    if hp and (hp in npick or npick in hp):
        return "home"
    if ap and (ap in npick or npick in ap):
        return "away"
    return None


def settle(row: dict[str, str], score: dict[str, str]) -> tuple[str, str, str, str]:
    if score.get("abnormal") == "1":
        status = score.get("status", "异常")
        return f"取消/延期（{status}）", "不计", "NA", "取消/延期/不计"

    hs, away_s = int(score["home_score"]), int(score["away_score"])
    home, away = row.get("比赛", "").split(" vs ", 1)
    total = hs + away_s
    market = row.get("市场框架", "")
    pick = row.get("模拟方向", "")
    price = row.get("模拟盘口/价格", "")
    side = selected_side(row, home, away)
    home_margin = hs - away_s
    result = f"{home}{hs}-{away_s}{away}"

    factor = None
    if "BTTS" in market or "双方进球" in market or "双方进球" in pick:
        yes = hs > 0 and away_s > 0
        factor = 1.0 if yes else -1.0
    elif "进球" in market or "大小" in market or pick.startswith(("大", "小")) or "U" in price or "O" in price or "Over" in price or "Under" in price:
        line = extract_line(price) or extract_line(pick) or 2.5
        if "小" in pick or "U" in price or "Under" in price:
            factor = quarter_factor(line - total)
        else:
            factor = quarter_factor(total - line)
    elif "DNB" in market or "DNB" in pick or "DNB" in price:
        if side == "home":
            factor = asian_factor(home_margin)
        elif side == "away":
            factor = asian_factor(-home_margin)
    elif "亚盘" in market or "让" in market or re.search(r"[+-]\d", pick + price):
        line = extract_line(pick) if re.search(r"[+-]\d", pick) else extract_line(price)
        if line is not None and side == "home":
            factor = quarter_factor(home_margin + line)
        elif line is not None and side == "away":
            factor = quarter_factor(-home_margin + line)
    else:
        if side == "draw":
            factor = 1.0 if hs == away_s else -1.0
        elif side == "home":
            factor = 1.0 if hs > away_s else -1.0
        elif side == "away":
            factor = 1.0 if away_s > hs else -1.0

    if factor is None:
        return result, "不计", "NA", "比分已回补/盘口方向无法机械结算"
    if factor > 0:
        return result, pnl_from_factor(factor, row), "B", "自动回补-方向赢"
    if factor < 0:
        return result, pnl_from_factor(factor, row), "D", "自动回补-方向输"
    return result, "0", "走", "自动回补-走水"


def main() -> int:
    rows = read_csv(LEDGER)
    if not rows:
        print("no ledger")
        return 2
    fieldnames = list(rows[0].keys())
    scores = load_scores()
    counts = Counter()
    audit: list[dict[str, str]] = []

    for row in rows:
        row_date = datetime.strptime(row["日期"], "%Y-%m-%d").date()
        if row_date >= TODAY:
            continue
        if row.get("赛果") not in {"", "待赛", "待填", "赛果未匹配待人工核验"}:
            continue
        score = find_score(row, scores)
        if score:
            result, pnl, grade, error = settle(row, score)
            row["赛果"] = result
            row["模拟盈亏单位"] = pnl
            row["过程评级"] = grade
            row["错误类型"] = error
            row["模型更新"] = f"历史比分自动回补；来源={score['source']}；仍需人工复盘盘口路径"
            counts["settled"] += 1
            audit.append({"date": row["日期"], "match": row["比赛"], "result": result, "pnl": pnl, "source": score["source"]})
        else:
            row["赛果"] = "赛果未匹配待人工核验"
            row["模拟盈亏单位"] = "不计"
            row["过程评级"] = "NA"
            row["错误类型"] = "比分源未匹配/不计胜率"
            row["模型更新"] = "过期待赛已清理；需补充Flashscore/球探历史或人工核验"
            counts["unmatched"] += 1
            audit.append({"date": row["日期"], "match": row["比赛"], "result": row["赛果"], "pnl": "不计", "source": "missing"})

    write_csv(LEDGER, rows, fieldnames)
    audit_path = ROOT / "ledger" / f"historical_settlement_audit_{TODAY.strftime('%Y%m%d')}.csv"
    write_csv(audit_path, audit, ["date", "match", "result", "pnl", "source"])
    print(f"settled={counts['settled']}")
    print(f"unmatched={counts['unmatched']}")
    print(f"audit={audit_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
