from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path


def load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def main() -> int:
    ap = argparse.ArgumentParser(description="Publish the bounded basketball daily output to gh-pages")
    ap.add_argument("--root", required=True)
    ap.add_argument("--public", required=True)
    args = ap.parse_args()
    root = Path(args.root).resolve()
    public = Path(args.public).resolve()
    src_data = root / "dashboard_v2" / "data"
    dst_data = public / "basketball-data"
    dst_data.mkdir(parents=True, exist_ok=True)
    latest = load(src_data / "latest.json", {})
    day = str(latest.get("date_bj") or latest.get("date") or "")
    if not day:
        raise SystemExit("basketball daily output has no date_bj")
    current = src_data / f"{day}.json"
    if not current.is_file():
        raise SystemExit(f"missing daily JSON: {current}")
    for path in (current, src_data / "latest.json"):
        shutil.copy2(path, dst_data / path.name)
    health = root / "dashboard_v2" / "sources" / "health.json"
    if health.is_file():
        target = public / "basketball-sources" / "health.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(health, target)
    for name in ("basketball-v2.html", "basketball.html"):
        path = root / "dashboard_v2" / name
        if path.is_file():
            shutil.copy2(path, public / name)
    index = load(dst_data / "index.json", {})
    entries = {}
    for row in index.get("dates", []) if isinstance(index, dict) else []:
        if isinstance(row, str):
            entries[row] = {"date": row, "file": f"{row}.json"}
        elif isinstance(row, dict) and row.get("date"):
            entries[str(row["date"])] = dict(row)
    entries[day] = {
        "date": day,
        "file": f"{day}.json",
        "event_count": len(latest.get("events") or []),
        "archive_type": latest.get("archive_type", "FORWARD_NATIVE"),
    }
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dates": [entries[key] for key in sorted(entries, reverse=True)],
    }
    (dst_data / "index.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = {
        "date_bj": day,
        "paper_bettable": (latest.get("funnel") or {}).get("paper_bettable"),
        "events": len(latest.get("events") or []),
        "published_data": str(dst_data / f"{day}.json"),
    }
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
