#!/usr/bin/env python3
"""Resolve a Beijing business date from a scheduled slot, not arrival day."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

BJ = ZoneInfo("Asia/Shanghai")
UTC = dt.timezone.utc
SLOT_TIMES = {"morning": (5, 7), "evening": (20, 7)}


def run_created_at(repo: str, run_id: str, token: str) -> dt.datetime | None:
    if not repo or not run_id or not token:
        return None
    url = f"https://api.github.com/repos/{repo}/actions/runs/{run_id}"
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "Authorization": f"Bearer {token}", "User-Agent": "football-target-date/2"})
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            if response.status != 200:
                return None
            value = json.loads(response.read().decode("utf-8")).get("created_at")
        return dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None


def parse_iso(value: str | None, timezone: dt.tzinfo = UTC) -> dt.datetime | None:
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return (parsed.replace(tzinfo=timezone) if parsed.tzinfo is None else parsed).astimezone(timezone)


def infer_slot(mode: str, schedule: str) -> str:
    if mode in SLOT_TIMES:
        return mode
    return "evening" if schedule.strip().split()[:2] == ["7", "12"] else "morning"


def planned_run_bjt(actual_bjt: dt.datetime, mode: str, schedule: str) -> dt.datetime:
    slot = infer_slot(mode, schedule)
    hour, minute = SLOT_TIMES[slot]
    candidate = actual_bjt.replace(hour=hour, minute=minute, second=0, microsecond=0)
    # If a scheduled run is created after midnight, it still belongs to the
    # previous evening slot. The same boundary rule protects morning replays.
    if actual_bjt < candidate:
        candidate -= dt.timedelta(days=1)
    return candidate


def resolve_target(*, mode: str, event: str, schedule: str, actual_started: dt.datetime,
                   run_created: dt.datetime | None, explicit_target: str = "",
                   explicit_planned_bjt: str = "", max_lateness_minutes: int = 720) -> dict[str, str]:
    actual_bjt = actual_started.astimezone(BJ)
    slot = infer_slot(mode, schedule)
    planned = parse_iso(explicit_planned_bjt, BJ) if explicit_planned_bjt else None
    if planned is None:
        anchor = (run_created or actual_started).astimezone(BJ)
        planned = planned_run_bjt(anchor, slot, schedule)
    lateness = (actual_bjt - planned).total_seconds() / 60.0
    if event == "schedule" and lateness < -5:
        raise ValueError(f"SCHEDULED_SLOT_NOT_REACHED planned={planned.isoformat()} actual={actual_bjt.isoformat()}")
    if event == "schedule" and lateness > max_lateness_minutes:
        raise ValueError(f"STALE_SCHEDULED_RUN planned={planned.isoformat()} actual={actual_bjt.isoformat()} lateness_minutes={lateness:.0f}")
    target = dt.date.fromisoformat(explicit_target) if explicit_target else (
        planned.date() + dt.timedelta(days=1) if slot == "evening" else planned.date()
    )
    return {
        "list_date": target.isoformat(),
        "target_list_date": target.isoformat(),
        "planned_slot": slot,
        "planned_run_bjt": planned.isoformat(),
        "actual_run_bjt": actual_bjt.isoformat(),
        "actual_started_at": actual_started.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "scheduled_at": schedule or "manual",
        "trigger_source": event or "manual",
        "date_source": "explicit_target_date" if explicit_target else ("github_run_created_at" if run_created else "runner_clock"),
        "lateness_minutes": str(round(max(0.0, lateness), 3)),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=tuple(SLOT_TIMES), required=True)
    parser.add_argument("--event", default="manual")
    parser.add_argument("--schedule", default="")
    parser.add_argument("--target-date", default="")
    parser.add_argument("--planned-run-bjt", default="")
    parser.add_argument("--max-lateness-minutes", type=int, default=720)
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--run-id", default=os.environ.get("GITHUB_RUN_ID", ""))
    parser.add_argument("--token", default=os.environ.get("GITHUB_TOKEN", ""))
    parser.add_argument("--output", default="")
    parser.add_argument("--now", default="", help="test-only ISO timestamp")
    args = parser.parse_args()
    now = parse_iso(args.now, UTC) or dt.datetime.now(UTC)
    created = run_created_at(args.repo, args.run_id, args.token)
    if args.event == "schedule" and created is None and not args.planned_run_bjt:
        raise SystemExit("TARGET_DATE_RESOLUTION_FAILED: scheduled run creation time unavailable")
    try:
        values = resolve_target(mode=args.mode, event=args.event, schedule=args.schedule,
                                actual_started=now, run_created=created,
                                explicit_target=args.target_date,
                                explicit_planned_bjt=args.planned_run_bjt,
                                max_lateness_minutes=args.max_lateness_minutes)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps(values, ensure_ascii=False))
    if args.output:
        path = Path(args.output)
        with path.open("a", encoding="utf-8") as handle:
            for key, value in values.items():
                handle.write(f"{key}={value}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
