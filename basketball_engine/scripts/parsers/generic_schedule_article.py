from __future__ import annotations
import re
from datetime import datetime

TEAM = r"[\u4e00-\u9fffA-Za-z][\u4e00-\u9fffA-Za-z·]{1,14}"
DATE_RE = re.compile(r"(?P<m>\d{1,2})\s*(?:月|/)\s*(?P<d>\d{1,2})\s*日?")
TIME_RE = re.compile(r"(?P<h>\d{1,2}):(?P<mi>\d{2})")
PAIR_RE = re.compile(rf"(?P<a>{TEAM})\s*(?:VS|vs|V|对阵|对)\s*(?P<b>{TEAM})")
SCORE_RE = re.compile(rf"(?P<a>{TEAM})\s*(?P<s1>\d{{2,3}})\s*[-:：]\s*(?P<s2>\d{{2,3}})\s*(?P<b>{TEAM})")
PLACEHOLDER_RE = re.compile(r"第[一二三四五六七八九十\d]+名")

def _stage(text: str) -> str | None:
    for key in ("决赛", "冠军赛", "季军赛", "三四名", "五六名", "七八名", "排位赛"):
        if key in text: return key
    return None

def parse_article(text: str, source_url: str = "", published_at: str | None = None, year: int = 2026):
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text))
    dates = list(DATE_RE.finditer(text))
    out = []
    for dm in dates:
        date = f"{year:04d}-{int(dm.group('m')):02d}-{int(dm.group('d')):02d}"
        window = text[dm.end(): min(len(text), dm.end()+1800)]
        next_date = DATE_RE.search(window)
        if next_date: window = window[:next_date.start()]
        for tm in TIME_RE.finditer(window):
            chunk = window[tm.end(): min(len(window), tm.end()+100)]
            pair = PAIR_RE.search(chunk) or SCORE_RE.search(chunk)
            if not pair:
                # Tournament schedules often publish only the slot label.
                if "决赛" in chunk or "决赛" in window:
                    out.append({"date": date, "time": tm.group(0), "team_1": "决赛", "team_2": "待定",
                                "stage": "决赛", "score_if_present": None, "source_url": source_url,
                                "article_published_at": published_at, "event_status": "bracket_placeholder",
                                "participant_resolution": "pending"})
                continue
            score = None
            if pair.re is SCORE_RE: score = [int(pair.group('s1')), int(pair.group('s2'))]
            a, b = pair.group('a').strip(), pair.group('b').strip()
            stage = _stage(chunk) or _stage(window)
            placeholder = bool(PLACEHOLDER_RE.search(a) or PLACEHOLDER_RE.search(b))
            out.append({"date": date, "time": tm.group(0), "team_1": a, "team_2": b,
                        "stage": stage, "score_if_present": score, "source_url": source_url,
                        "article_published_at": published_at, "event_status": "bracket_placeholder" if placeholder else "discovered",
                        "participant_resolution": "pending" if placeholder else "resolved"})
    # de-duplicate repeated text fragments while preserving article order
    seen, unique = set(), []
    for row in out:
        key = (row["date"], row["time"], row["team_1"], row["team_2"])
        if key not in seen: seen.add(key); unique.append(row)
    return unique
