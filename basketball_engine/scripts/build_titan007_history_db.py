"""Bootstrap or incrementally refresh the Titan007 basketball reference DB."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from providers.titan007_history_adapter import update_history_database


def _events(path):
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    return [(row.get("event") or row) for row in document.get("events", [])]


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--latest-json", default=r"D:\codex\outputs\basketball_odds_trader\dashboard_v2\data\latest.json")
    parser.add_argument("--output", default=r"D:\codex\outputs\basketball_odds_trader\reference_data\titan007_history")
    parser.add_argument("--years", default="")
    parser.add_argument("--boxscore-limit", type=int, default=10)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--limit-events", type=int, default=0)
    parser.add_argument(
        "--foundation-leagues", default="",
        help="Comma-separated complete league rosters: NBA,WNBA,EUROLEAGUE",
    )
    parser.add_argument(
        "--all-league-boxscores", action="store_true",
        help="Capture every finalized target-league box score before cutoff, not only the latest N per team",
    )
    args = parser.parse_args(argv)
    events = _events(args.latest_json)
    if args.limit_events:
        events = events[:args.limit_events]
    years = [int(x) for x in args.years.split(",") if x.strip()] or None
    foundation_leagues = [x.strip().upper() for x in args.foundation_leagues.split(",") if x.strip()]
    result = update_history_database(events, args.output, cutoff=datetime.now(timezone.utc), years=years,
                                     boxscore_limit=args.boxscore_limit, workers=args.workers,
                                     foundation_leagues=foundation_leagues,
                                     all_league_boxscores=args.all_league_boxscores)
    print(json.dumps({"database": result["database"], "audit_path": result["audit_path"],
                      **result["audit"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
