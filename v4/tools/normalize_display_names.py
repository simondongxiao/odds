"""Repair display names in already-generated V3/V4 JSON without touching decisions."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from display_names import localize_record


def normalize(path: Path) -> tuple[int, int]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("matches") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return 0, 0
    changed = 0
    for row in rows:
        before = json.dumps(row, ensure_ascii=False, sort_keys=True)
        localize_record(row)
        if json.dumps(row, ensure_ascii=False, sort_keys=True) != before:
            changed += 1
    if changed:
        temp = path.with_name(path.name + ".tmp")
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temp, path)
    return len(rows), changed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="+", type=Path)
    args = parser.parse_args()
    for path in args.paths:
        total, changed = normalize(path)
        print(f"{path}: rows={total} localized={changed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
