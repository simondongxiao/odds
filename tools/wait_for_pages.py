#!/usr/bin/env python3
"""Poll the public GitHub Pages payload until a requested update is visible."""
from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from typing import Any


def fetch_json(url: str) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": "football-pages-verify/1"})
    with urllib.request.urlopen(req, timeout=20) as response:
        if response.status != 200:
            raise RuntimeError(f"HTTP {response.status}")
        return json.loads(response.read().decode("utf-8"))


def fetch_status(url: str) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "football-pages-verify/1"})
    with urllib.request.urlopen(req, timeout=20) as response:
        if response.status != 200:
            raise RuntimeError(f"HTTP {response.status}")


def verify_once(base_url: str, date: str, expected_v3: str | None, expected_v4: str | None, path_prefix: str = "") -> dict[str, Any]:
    stamp = str(time.time_ns())
    root = base_url.rstrip("/")
    prefix = path_prefix.strip("/")
    results: dict[str, Any] = {}
    for version, expected in (("v3", expected_v3), ("v4", expected_v4)):
        version_root = f"{root}/{prefix}/{version}" if prefix else f"{root}/{version}"
        fetch_status(f"{version_root}/index.html?verify={stamp}")
        index = fetch_json(f"{version_root}/data/index.json?verify={stamp}")
        if date not in index:
            raise RuntimeError(f"{version} index missing {date}")
        payload = fetch_json(f"{version_root}/data/{date}.json?verify={stamp}")
        if payload.get("list_date") != date:
            raise RuntimeError(f"{version} payload list_date={payload.get('list_date')!r}")
        matches = payload.get("matches")
        if not isinstance(matches, list) or not matches:
            raise RuntimeError(f"{version} payload has no matches")
        generated = str(payload.get("generated_at", ""))
        if expected and generated != expected:
            raise RuntimeError(f"{version} generated_at stale: {generated!r} != {expected!r}")
        history = fetch_json(f"{version_root}/data/{version}_competition_history_{date}.json?verify={stamp}")
        if history.get("list_date") != date:
            raise RuntimeError(f"{version} history list_date={history.get('list_date')!r}")
        history_rows = history.get("rows")
        if not isinstance(history_rows, list) or not history_rows:
            raise RuntimeError(f"{version} history payload has no rows")
        results[version] = {
            "matches": len(matches), "generated_at": generated,
            "history_rows": len(history_rows), "history_source_rows": history.get("source_detail_rows", 0),
        }
    return results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True)
    parser.add_argument("--base-url", default="https://simondongxiao.github.io/odds")
    parser.add_argument("--expected-v3")
    parser.add_argument("--expected-v4")
    parser.add_argument("--sha", default="")
    parser.add_argument("--path-prefix", default="", help="Optional path below the Pages base URL, e.g. diagnostic/cloud")
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--interval", type=int, default=10)
    args = parser.parse_args()
    deadline = time.monotonic() + max(1, args.timeout)
    last_error = "unknown"
    while time.monotonic() < deadline:
        try:
            result = verify_once(args.base_url, args.date, args.expected_v3, args.expected_v4, args.path_prefix)
            print(f"pages_verify=success sha={args.sha} v3_matches={result['v3']['matches']} v4_matches={result['v4']['matches']} v3_history_rows={result['v3']['history_rows']} v4_history_rows={result['v4']['history_rows']}")
            return 0
        except (OSError, ValueError, RuntimeError, urllib.error.URLError) as exc:
            last_error = str(exc)
            time.sleep(max(1, args.interval))
    raise SystemExit(f"pages_verify=failed date={args.date} error={last_error}")


if __name__ == "__main__":
    main()
