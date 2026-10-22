"""Normalize continental competition labels and remove current provider duplicates.

This is a render/data-contract repair only.  It never changes odds, directions,
grades, scores, settlement or PnL.  Titan's numeric fixture is kept when the
same fixture also appears as a BetExplorer ``BE_`` supplement.
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import unicodedata
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import sys
sys.path.insert(0, str(Path(r"D:\codex\tools")))
from football_competition_normalizer import normalize  # noqa: E402


EUROPA_ALIASES = {"欧联", "欧联杯", "欧罗巴杯", "欧罗巴联赛", "欧洲联赛"}
TEAM_ALIASES = {
    "圣吉罗斯联合": "圣吉罗斯",
    "圣吉罗斯联": "圣吉罗斯",
    "贝尔谢巴工人": "贝尔谢巴夏普尔",
    "托伦斯": "杜连斯",
    "乔治罗尼亚": "比亚韦斯托克雅盖隆",
    "萨尔茨堡红牛": "萨尔茨堡",
}


def canonical_competition(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return text
    info = normalize(text)
    # Keep youth/women variants separate.  Only the senior Europa aliases are
    # collapsed; 欧冠 and 欧协联 remain independent scopes.
    if text in EUROPA_ALIASES or "欧罗巴" in text or "UEFA Europa League" in text or text.casefold() == "europa league":
        if re.search(r"女|women|woman|girls|female", text, re.I):
            return "欧联女足"
        if re.search(r"U\s*\d+|青年|youth", text, re.I):
            return "欧青联"
        return "欧联"
    return info.competition_canonical or text


def canonical_competition_for_match(value: Any, match: Any = "") -> str:
    """Use team markers to disambiguate a provider's generic league label."""
    text = f"{value or ''} {match or ''}"
    label = canonical_competition(value)
    if re.search(r"(女足|女子|女联|women|woman|girls|female|\bW\b)", text, re.I):
        if label == "欧联":
            return "欧联女足"
        if label == "欧冠":
            return "欧冠女足"
        if label == "欧协联":
            return "欧协联女足"
    if re.search(r"(U\s*19|U\s*21|青年|youth)", text, re.I) and label in {"欧联", "欧冠", "欧协联"}:
        return "欧青联"
    return label


def normalize_labels(value: Any, key: str = "") -> Any:
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if k in {"competition", "competition_cn", "league", "league_cn", "赛事类型", "联赛/杯赛"} and isinstance(v, str):
                out[k] = canonical_competition_for_match(v, value.get("match", ""))
            elif k in {"canonical_competition_id", "canonical_competition_name"} and isinstance(v, str):
                out[k] = canonical_competition(v)
            else:
                out[k] = normalize_labels(v, k)
        return out
    if isinstance(value, list):
        return [normalize_labels(item, key) for item in value]
    return value


def _team(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    text = re.sub(r"[（(][^）)]*[）)]", "", text)
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"[^0-9A-Za-z\u3400-\u9fff]+", "", text).casefold()
    for source, target in TEAM_ALIASES.items():
        text = text.replace(source.casefold(), target.casefold())
    return text


def _teams(row: dict[str, Any]) -> tuple[str, str]:
    market = row.get("market") if isinstance(row.get("market"), dict) else {}
    identity = row.get("identity") if isinstance(row.get("identity"), dict) else {}
    home = market.get("home_team") or row.get("home_team") or identity.get("home")
    away = market.get("away_team") or row.get("away_team") or identity.get("away")
    if (not home or not away) and isinstance(row.get("match"), str):
        parts = re.split(r"\s+vs\s+", row["match"], maxsplit=1, flags=re.I)
        if len(parts) == 2:
            home, away = parts
    return _team(home), _team(away)


def _kickoff(row: dict[str, Any]) -> datetime | None:
    value = row.get("kickoff_at") or row.get("kickoff")
    identity = row.get("identity") if isinstance(row.get("identity"), dict) else {}
    if not value:
        value = identity.get("kickoff")
    try:
        text = str(value or "").replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
        return parsed.replace(tzinfo=None)
    except (TypeError, ValueError):
        match = re.search(r"(?:(\d{4})-)?(\d{1,2})-(\d{1,2})\s+(\d{1,2}):(\d{2})", str(value or ""))
        if not match:
            return None
        year = int(match.group(1) or str(identity.get("list_date") or row.get("list_date") or "2000")[:4])
        try:
            return datetime(year, int(match.group(2)), int(match.group(3)), int(match.group(4)), int(match.group(5)))
        except ValueError:
            return None


def _match_id(row: dict[str, Any]) -> str:
    return str(row.get("match_id") or (row.get("identity") or {}).get("match_id") or "").strip()


def _competition(row: dict[str, Any]) -> str:
    return canonical_competition(str(row.get("competition") or (row.get("identity") or {}).get("competition") or ""))


def dedupe_rows(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Drop BE_ rows that duplicate a Titan numeric fixture in one slate."""
    primary = [r for r in rows if not _match_id(r).startswith("BE_")]
    supplements = [r for r in rows if _match_id(r).startswith("BE_")]
    removed: list[dict[str, str]] = []
    keep = list(primary)
    for row in supplements:
        comp = _competition(row)
        home, away = _teams(row)
        when = _kickoff(row)
        duplicate = None
        if comp == "欧联" and home and away and when:
            for candidate in primary:
                if _competition(candidate) != "欧联":
                    continue
                ch, ca = _teams(candidate)
                cw = _kickoff(candidate)
                if not ch or not ca or not cw or abs((when - cw).total_seconds()) > 90 * 60:
                    continue
                score = (SequenceMatcher(None, home, ch).ratio() + SequenceMatcher(None, away, ca).ratio()) / 2
                if score >= 0.78:
                    duplicate = candidate
                    break
        if duplicate is None:
            keep.append(row)
        else:
            removed.append({"duplicate_match_id": _match_id(row), "kept_match_id": _match_id(duplicate), "competition": "欧联"})
    return keep, removed


def repair_file(path: Path, dedupe_current: bool = False) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload = normalize_labels(payload)
    removed: list[dict[str, str]] = []
    if dedupe_current and isinstance(payload, dict) and isinstance(payload.get("matches"), list):
        payload["matches"], removed = dedupe_rows(payload["matches"])
        if removed:
            payload["display_dedupe"] = {"status": "PASS", "removed_count": len(removed), "rows": removed, "rule": "Titan numeric fixture wins over BE_ supplement"}
            summary = payload.get("summary")
            if isinstance(summary, dict):
                summary["total"] = len(payload["matches"])
    temporary = path.with_name(f".{path.name}.competition.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    return {"path": str(path), "rows_removed": len(removed), "total": len(payload.get("matches", [])) if isinstance(payload, dict) else None}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--current", required=True, nargs="+")
    parser.add_argument("--labels", nargs="*", default=[])
    args = parser.parse_args()
    results = [repair_file(Path(p), dedupe_current=True) for p in args.current]
    results.extend(repair_file(Path(p), dedupe_current=False) for p in args.labels)
    print(json.dumps({"status": "PASS", "results": results}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
