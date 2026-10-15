from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


STAGES = (
    "SCHEDULED",
    "DATA_UPDATED",
    "MODEL_COMPLETED",
    "PUBLISHED",
    "PAGE_VERIFIED",
    "FEISHU_SENT",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def record_stage(
    root: str | Path,
    stage: str,
    status: str,
    *,
    business_date: str = "",
    run_id: str = "",
    duration_seconds: float | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Append one auditable stage result and update the compact state file.

    This is deliberately independent of the pricing engine.  It records the
    delivery lifecycle without changing any model, ledger, or gate decision.
    """
    stage = str(stage).strip().upper()
    if stage not in STAGES:
        raise ValueError(f"unknown basketball stage: {stage}")
    root_path = Path(root).resolve()
    audit_dir = root_path / "audits"
    audit_dir.mkdir(parents=True, exist_ok=True)
    run_id = run_id or os.environ.get("GITHUB_RUN_ID", "local")
    entry: dict[str, Any] = {
        "schema_version": 1,
        "stage": stage,
        "status": str(status).upper(),
        "run_id": run_id,
        "business_date": business_date or os.environ.get("BASKETBALL_DATE", ""),
        "at": utc_now(),
        "duration_seconds": None if duration_seconds is None else round(float(duration_seconds), 3),
        "details": details or {},
    }
    events_path = audit_dir / "stage_status.jsonl"
    with events_path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False, separators=(",", ":")) + "\n")

    state_path = audit_dir / "stage_status.json"
    state: dict[str, Any] = {"schema_version": 1, "run_id": run_id, "business_date": entry["business_date"], "stages": {}, "updated_at": entry["at"]}
    if state_path.is_file():
        try:
            loaded = json.loads(state_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                state.update(loaded)
        except (OSError, ValueError):
            pass
    state["run_id"] = run_id
    state["business_date"] = entry["business_date"]
    state["updated_at"] = entry["at"]
    state.setdefault("stages", {})[stage] = entry
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    return entry


def main() -> int:
    ap = argparse.ArgumentParser(description="Record one basketball delivery lifecycle stage")
    ap.add_argument("--root", required=True)
    ap.add_argument("--stage", required=True, choices=STAGES)
    ap.add_argument("--status", default="SUCCESS")
    ap.add_argument("--business-date", default=os.environ.get("BASKETBALL_DATE", ""))
    ap.add_argument("--run-id", default=os.environ.get("GITHUB_RUN_ID", "local"))
    ap.add_argument("--duration-seconds", type=float, default=0.0)
    ap.add_argument("--detail", action="append", default=[])
    args = ap.parse_args()
    details: dict[str, str] = {}
    for item in args.detail:
        if "=" in item:
            key, value = item.split("=", 1)
            details[key] = value
    print(json.dumps(record_stage(args.root, args.stage, args.status, business_date=args.business_date, run_id=args.run_id, duration_seconds=args.duration_seconds, details=details), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
