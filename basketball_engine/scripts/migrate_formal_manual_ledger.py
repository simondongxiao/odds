"""Build the user-authorized historical unified manual-live ledger."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from repair_v22.common import stamp
from repair_v22.manual_live_ledger import (attach_formal_manual_ledger_to_dashboard,
                                           build_formal_manual_live_ledger)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=r"D:\codex\outputs\basketball_odds_trader")
    args = parser.parse_args()
    root = Path(args.root)
    ledger = build_formal_manual_live_ledger(root, stamp())
    dashboard = attach_formal_manual_ledger_to_dashboard(root, ledger)
    print(json.dumps({"summary": ledger["summary"], "by_layer": ledger["by_layer"],
                      "dedupe_excluded": len(ledger["dedupe"]["excluded"]), **dashboard},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
