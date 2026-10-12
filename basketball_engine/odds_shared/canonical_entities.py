"""One reviewed entity namespace shared by basketball and football.

Resolution is deliberately exact.  Unicode/punctuation normalization and
explicit aliases are accepted; edit-distance or substring guesses are not.
Unknown labels receive a deterministic label identity, so they remain usable
without being silently merged with a different club.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable


REGISTRY_PATH = Path(os.environ.get("CANONICAL_ENTITY_REGISTRY", Path(__file__).resolve().parents[1] / "config" / "canonical_entity_registry.json"))


def normalize_label(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = re.sub(r"\[[^\]]*\]|【[^】]*】", "", text)
    text = text.replace("(中)", "").replace("（中）", "").replace("(主)", "").replace("（主）", "")
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", text.casefold())


def _source_key(source: Any, source_id: Any) -> tuple[str, str]:
    return str(source or "").strip().upper(), str(source_id or "").strip()


@dataclass(frozen=True)
class Resolution:
    canonical_team_id: str
    method: str
    matched_alias: str | None
    ambiguous: bool = False


class EntityRegistry:
    def __init__(self, payload: dict[str, Any], path: Path | None = None):
        self.payload = payload
        self.path = path
        self.version = int(payload.get("version", 1))
        self.aliases: dict[str, dict[str, str]] = {}
        self.source_ids: dict[str, dict[tuple[str, str], str]] = {}
        self._build()

    @classmethod
    def load(cls, path: Path | str = REGISTRY_PATH) -> "EntityRegistry":
        path = Path(path)
        return cls(json.loads(path.read_text(encoding="utf-8")), path)

    def _build(self) -> None:
        for sport, spec in (self.payload.get("sports") or {}).items():
            sport_key = str(sport).lower()
            alias_index: dict[str, str] = {}
            source_index: dict[tuple[str, str], str] = {}
            for entity in spec.get("teams") or []:
                canonical = str(entity["canonical_team_id"])
                values = [entity.get("name"), *(entity.get("aliases") or [])]
                for source_aliases in (entity.get("source_aliases") or {}).values():
                    values.extend(source_aliases or [])
                for value in values:
                    token = normalize_label(value)
                    if not token:
                        continue
                    prior = alias_index.get(token)
                    if prior and prior != canonical:
                        raise ValueError(f"ambiguous registry alias {sport_key}:{token}: {prior} vs {canonical}")
                    alias_index[token] = canonical
                for source, ids in (entity.get("source_ids") or {}).items():
                    for source_id in ids or []:
                        key = _source_key(source, source_id)
                        prior = source_index.get(key)
                        if prior and prior != canonical:
                            raise ValueError(f"ambiguous registry source id {sport_key}:{key}")
                        source_index[key] = canonical
            self.aliases[sport_key] = alias_index
            self.source_ids[sport_key] = source_index

    def resolve(
        self,
        sport: str,
        name: Any,
        *,
        aliases: Iterable[Any] = (),
        source: Any = None,
        source_id: Any = None,
    ) -> Resolution:
        sport_key = str(sport).lower()
        by_id = self.source_ids.get(sport_key, {})
        if source and source_id not in (None, ""):
            canonical = by_id.get(_source_key(source, source_id))
            if canonical:
                return Resolution(canonical, "EXACT_SOURCE_ID", None)
        matches: dict[str, str] = {}
        for value in [name, *list(aliases or ())]:
            token = normalize_label(value)
            canonical = self.aliases.get(sport_key, {}).get(token)
            if canonical:
                matches[canonical] = token
        if len(matches) == 1:
            canonical, token = next(iter(matches.items()))
            return Resolution(canonical, "EXACT_REGISTERED_ALIAS", token)
        if len(matches) > 1:
            digest = hashlib.sha256("|".join(sorted(matches)).encode()).hexdigest()[:20]
            return Resolution(f"{sport_key}:ambiguous:{digest}", "AMBIGUOUS_REGISTERED_ALIASES", None, True)
        token = normalize_label(name) or next((normalize_label(x) for x in aliases if normalize_label(x)), "")
        if not token:
            return Resolution(f"{sport_key}:unknown:missing", "MISSING_NAME", None, True)
        return Resolution(f"{sport_key}:label:{token}", "EXACT_NORMALIZED_LABEL", token)


@lru_cache(maxsize=4)
def default_registry(path: str = str(REGISTRY_PATH)) -> EntityRegistry:
    return EntityRegistry.load(path)


def canonicalize_team_pair(event: dict[str, Any], sport: str, registry: EntityRegistry | None = None) -> tuple[Resolution, Resolution]:
    registry = registry or default_registry()
    source = event.get("source") or event.get("feed_provider")
    result = []
    for side in ("team1", "team2"):
        explicit = event.get(f"canonical_{side}_id") or event.get(
            "canonical_home_team_id" if side == "team1" else "canonical_away_team_id")
        if explicit:
            result.append(Resolution(str(explicit), "EXPLICIT_CANONICAL_ID", None))
            continue
        name = event.get(f"{side}_name") or event.get("home_cn" if side == "team1" else "away_cn") or event.get("home_team" if side == "team1" else "away_team")
        aliases = list(event.get(f"{side}_aliases") or [])
        alt = event.get("home_tw" if side == "team1" else "away_tw")
        if alt:
            aliases.append(alt)
        source_id = event.get(f"{side}_source_id")
        result.append(registry.resolve(sport, name, aliases=aliases, source=source, source_id=source_id))
    return result[0], result[1]


def canonicalize_event(event: dict[str, Any], sport: str, registry: EntityRegistry | None = None) -> dict[str, Any]:
    left, right = canonicalize_team_pair(event, sport, registry)
    event["canonical_team1_id"] = left.canonical_team_id
    event["canonical_team2_id"] = right.canonical_team_id
    event["canonical_team1_method"] = left.method
    event["canonical_team2_method"] = right.method
    event["canonical_identity_ambiguous"] = bool(left.ambiguous or right.ambiguous)
    return event


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def same_fixture(left: dict[str, Any], right: dict[str, Any], sport: str, tolerance_seconds: int = 300) -> bool:
    canonicalize_event(left, sport)
    canonicalize_event(right, sport)
    ordered_left = (left.get("canonical_team1_id"), left.get("canonical_team2_id"))
    ordered_right = (right.get("canonical_team1_id"), right.get("canonical_team2_id"))
    if ordered_left != ordered_right or any(not value for value in ordered_left):
        return False
    left_tip = _parse_time(left.get("tip_at") or left.get("kickoff_at") or left.get("bj_time"))
    right_tip = _parse_time(right.get("tip_at") or right.get("kickoff_at") or right.get("bj_time"))
    return bool(left_tip and right_tip and abs((left_tip - right_tip).total_seconds()) <= tolerance_seconds)


def canonical_event_id(event: dict[str, Any], sport: str, registry: EntityRegistry | None = None) -> str:
    canonicalize_event(event, sport, registry)
    tip = _parse_time(event.get("tip_at") or event.get("kickoff_at") or event.get("bj_time"))
    raw = "|".join((
        str(sport).lower(),
        str(event.get("canonical_team1_id") or ""),
        str(event.get("canonical_team2_id") or ""),
        tip.replace(second=0, microsecond=0).isoformat() if tip else str(event.get("tip_at") or event.get("kickoff_at") or event.get("bj_time") or ""),
    ))
    return f"{str(sport).lower()}:event:{hashlib.sha256(raw.encode()).hexdigest()[:24]}"
