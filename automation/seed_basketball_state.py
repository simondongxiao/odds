from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path


def load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def main() -> int:
    ap = argparse.ArgumentParser(description="Seed a bounded basketball state from the gh-pages snapshot")
    ap.add_argument("--public", required=True)
    ap.add_argument("--root", required=True)
    ap.add_argument("--days", type=int, default=14)
    args = ap.parse_args()
    public = Path(args.public).resolve()
    root = Path(args.root).resolve()
    src = public / "basketball-data"
    dst = root / "dashboard_v2" / "data"
    dst.mkdir(parents=True, exist_ok=True)
    copied = []
    for name in ("latest.json", "index.json"):
        path = src / name
        if path.is_file():
            shutil.copy2(path, dst / name)
            copied.append(name)
    dates = sorted((p for p in src.glob("20??-??-??.json") if p.is_file()), reverse=True)
    for path in dates[: max(1, args.days)]:
        shutil.copy2(path, dst / path.name)
        copied.append(path.name)
    print(json.dumps({"seeded_files": len(copied), "dates": copied}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
