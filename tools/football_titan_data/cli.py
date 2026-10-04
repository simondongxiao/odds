from __future__ import annotations

import argparse
import json
from pathlib import Path

from .core import build_shared_snapshot


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the shared Titan007 AS-OF feature snapshot for V3 and V4.")
    parser.add_argument("--raw-csv", required=True)
    parser.add_argument("--list-date", required=True)
    args = parser.parse_args()
    result = build_shared_snapshot(Path(args.raw_csv), args.list_date)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
