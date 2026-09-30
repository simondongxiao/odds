"""Raw market adapter for the single official V4 runtime.

This module only exports source fields.  It never creates a direction,
probability, grade, decision or stake.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(r"D:\codex")
LEGACY_HTML = ROOT / "v3_legacy" / "dashboard" / "index.html"


def _split_match(value: str) -> tuple[str, str]:
    parts = re.split(r"\s+vs\s+", str(value or ""), maxsplit=1, flags=re.I)
    return (parts[0].strip(), parts[1].strip()) if len(parts) == 2 else (str(value or "").strip(), "")


def _euro_prices(value: str) -> tuple[str, str, str]:
    numbers = re.findall(r"\d+(?:\.\d+)?", str(value or ""))
    return tuple(numbers[:3]) if len(numbers) >= 3 else ("", "", "")


def load_raw(list_date: str) -> list[dict[str, Any]]:
    """Fallback export from the V3 page when no Titan CSV is supplied."""
    text = LEGACY_HTML.read_text(encoding="utf-8")
    match = re.search(r"const cardsData = (.*?);\s*\n", text, re.S)
    if not match:
        raise RuntimeError("cardsData not found")
    cards = json.loads(match.group(1).rstrip(";"))
    rows: list[dict[str, Any]] = []
    for card in cards:
        if card.get("date") != list_date:
            continue
        home, away = _split_match(card.get("match", ""))
        euro_home, euro_draw, euro_away = _euro_prices(card.get("euro", ""))
        rows.append({
            "match_id": str(card.get("match_id", "")),
            "list_date": list_date,
            "competition": card.get("league", ""),
            "match": card.get("match", ""),
            "kickoff": card.get("time", ""),
            "state": card.get("state", ""),
            "home_team": home,
            "away_team": away,
            "asian_raw": card.get("ah", ""),
            "euro_raw": card.get("euro", ""),
            "euro_home": euro_home,
            "euro_draw": euro_draw,
            "euro_away": euro_away,
            "totals_raw": card.get("total", ""),
            "ah_ok": bool(card.get("ah_ok")),
            "euro_ok": bool(card.get("euro_ok")),
            "totals_ok": bool(card.get("total_ok")),
            "price_source": card.get("price_source", ""),
            "quote_at": card.get("quote_at", ""),
            "last_confirmed_at": card.get("last_confirmed_at", ""),
            "form_evidence": card.get("form_source", ""),
            "h2h_evidence": card.get("h2h_source", ""),
            "injury_evidence": card.get("injury", ""),
            "lineup_evidence": card.get("lineup", ""),
            "motivation_evidence": card.get("motivation_source", ""),
        })
    return rows


def write_raw(rows: list[dict[str, Any]], list_date: str) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = ROOT / "raw" / "shared" / list_date / stamp / "snapshot.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "list_date": list_date,
        "snapshot_id": stamp,
        "source": "V4_RAW_FIELD_EXPORT",
        "rows": rows,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
