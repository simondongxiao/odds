from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve()
for candidate in (HERE.parents[1], HERE.parents[2]):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from football_update.independence_contract import write_analysis_bundle  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit V3/V4 shared-market and independent-analysis contract")
    parser.add_argument("--raw-csv", required=True, type=Path)
    parser.add_argument("--list-date", required=True)
    args = parser.parse_args()
    result = write_analysis_bundle(args.raw_csv, args.list_date)
    print(json.dumps({key: str(value) for key, value in result.items()}, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
