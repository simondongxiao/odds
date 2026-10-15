#!/usr/bin/env python3
"""Resolve a Beijing football business date from the workflow run's creation day."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo


BJ = ZoneInfo("Asia/Shanghai")


def run_created_at(repo: str, run_id: str, token: str) -> dt.datetime | None:
    if not repo or not run_id or not token:
        return None
    url = f"https://api.github.com/repos/{repo}/actions/runs/{run_id}"
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "Authorization": f"Bearer {token}", "User-Agent": "football-target-date/1"})
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            if response.status != 200:
                return None
            value = json.loads(response.read().decode("utf-8")).get("created_at")
        return dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("morning", "evening"), required=True)
    parser.add_argument("--event", default="manual")
    parser.add_argument("--schedule", default="")
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--run-id", default=os.environ.get("GITHUB_RUN_ID", ""))
    parser.add_argument("--token", default=os.environ.get("GITHUB_TOKEN", ""))
    parser.add_argument("--output", default="")
    args = parser.parse_args()
    now = dt.datetime.now(dt.timezone.utc)
    created = run_created_at(args.repo, args.run_id, args.token)
    if args.event == "schedule" and created is None:
        raise SystemExit("TARGET_DATE_RESOLUTION_FAILED: scheduled run creation time unavailable")
    anchor = (created or now).astimezone(BJ).date()
    target = anchor + dt.timedelta(days=1) if args.mode == "evening" else anchor
    values = {
        "list_date": target.isoformat(),
        "scheduled_at": args.schedule or "manual",
        "actual_started_at": now.isoformat().replace("+00:00", "Z"),
        "date_source": "github_run_created_at" if created else "runner_clock",
    }
    print(json.dumps(values, ensure_ascii=False))
    if args.output:
        path = Path(args.output)
        with path.open("a", encoding="utf-8") as handle:
            for key, value in values.items():
                handle.write(f"{key}={value}\n")
    return 0


if __name__ == "__main__":
    main()
