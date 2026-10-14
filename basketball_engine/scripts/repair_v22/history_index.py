"""Run-scoped canonical history index.

Every source row is canonicalized once.  Pricing then receives a small,
competition/team-connected in-memory slice instead of rescanning the complete
history list for every scheduled game.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from .common import attach_canonical_team_ids, durable_competition_key


class HistoryIndex:
    def __init__(self, rows):
        self.rows = []
        self.by_competition = defaultdict(list)
        self.by_team = defaultdict(list)
        self._candidate_cache = {}
        for raw in rows or []:
            row = dict(raw)
            attach_canonical_team_ids(row)
            for side in ("team1", "team2"):
                canonical = row.get(f"canonical_{side}_id")
                if canonical:
                    row.setdefault(f"{side}_legacy_id", row.get(f"{side}_id"))
                    row[f"{side}_id"] = canonical
            self.rows.append(row)
            gender = str(row.get("gender") or "").upper()
            comp = str(durable_competition_key(row) or "").upper()
            self.by_competition[(gender, comp)].append(row)
            for team_id in {row.get("team1_id"), row.get("team2_id")}:
                if team_id:
                    self.by_team[str(team_id)].append(row)
        for values in self.by_competition.values():
            values.sort(key=lambda item: str(item.get("tip_at") or ""))
        for values in self.by_team.values():
            values.sort(key=lambda item: str(item.get("tip_at") or ""))

    def canonical_event(self, raw: dict[str, Any]) -> dict[str, Any]:
        event = dict(raw or {})
        attach_canonical_team_ids(event)
        for side in ("team1", "team2"):
            canonical = event.get(f"canonical_{side}_id")
            if canonical:
                event.setdefault(f"{side}_legacy_id", event.get(f"{side}_id"))
                event[f"{side}_id"] = canonical
        return event

    def candidates(self, raw_event: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        event = self.canonical_event(raw_event)
        gender = str(event.get("gender") or "").upper()
        comp = str(durable_competition_key(event) or "").upper()
        key = (gender, comp, event.get("team1_id"), event.get("team2_id"))
        cached = self._candidate_cache.get(key)
        if cached is not None:
            return event, cached
        seen = set()
        selected = []
        pools = [self.by_competition.get((gender, comp), ())]
        pools.extend(self.by_team.get(str(team), ()) for team in (event.get("team1_id"), event.get("team2_id")) if team)
        for pool in pools:
            for row in pool:
                identity = (row.get("event_id"), row.get("team1_id"), row.get("team2_id"), row.get("tip_at"))
                if identity in seen:
                    continue
                seen.add(identity); selected.append(row)
        selected.sort(key=lambda item: str(item.get("tip_at") or ""))
        self._candidate_cache[key] = selected
        return event, selected

    def __len__(self):
        return len(self.rows)
