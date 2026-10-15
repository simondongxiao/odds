from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from stage_status import record_stage


def main() -> int:
    ap = argparse.ArgumentParser(description="Run the production basketball engine in GitHub Actions")
    ap.add_argument("--date", default=os.environ.get("BASKETBALL_DATE") or "auto")
    ap.add_argument("--root", default=os.environ.get("BASKETBALL_RUN_ROOT"))
    ap.add_argument("--public", default=os.environ.get("BASKETBALL_PUBLIC_DIR"))
    args = ap.parse_args()
    repo = Path(__file__).resolve().parents[1]
    root = Path(args.root or repo / ".basketball-run").resolve()
    public = Path(args.public or repo / "public").resolve()
    root.mkdir(parents=True, exist_ok=True)
    target_day = args.date if args.date != "auto" else os.environ.get("BASKETBALL_DATE", "")
    started = time.monotonic()
    env = os.environ.copy()
    scripts = repo / "basketball_engine" / "scripts"
    env["PYTHONPATH"] = str(repo / "basketball_engine") + os.pathsep + str(scripts) + os.pathsep + env.get("PYTHONPATH", "")
    seed = [sys.executable, str(repo / "automation" / "seed_basketball_state.py"), "--public", str(public), "--root", str(root)]
    try:
        subprocess.run(seed, check=True, env=env)
    except Exception as exc:
        record_stage(root, "DATA_UPDATED", "FAILED", business_date=target_day, details={"reason": type(exc).__name__, "error": str(exc)})
        raise
    entry = scripts / "run_basketball_daily.py"
    cmd = [sys.executable, str(entry), "--root", str(root), "--date", args.date, "--live", "--timeout", "12", "--workers", "6"]
    engine_started = time.monotonic()
    completed = subprocess.run(cmd, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if completed.returncode:
        record_stage(root, "MODEL_COMPLETED", "FAILED", business_date=target_day, duration_seconds=time.monotonic() - engine_started, details={"returncode": str(completed.returncode)})
        tail = (completed.stderr or completed.stdout)[-6000:]
        print(tail, file=sys.stderr)
        raise SystemExit(completed.returncode)
    # The engine emits a large audit JSON. Keep the Actions log compact while
    # retaining the full files under the run root and in the uploaded artifact.
    try:
        result = json.loads(completed.stdout)
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        record_stage(root, "MODEL_COMPLETED", "FAILED", business_date=target_day, duration_seconds=time.monotonic() - engine_started, details={"reason": "ENGINE_OUTPUT_NOT_JSON", "error": str(exc)})
        raise SystemExit(f"basketball engine did not emit a JSON summary: {exc}")
    summary = result.get("summary") if isinstance(result.get("summary"), dict) else result
    day = str(summary.get("day") or result.get("day") or "")
    update_status = str(summary.get("update_status") or result.get("update_status") or "")
    target_path = root / "dashboard_v2" / "data" / f"{day}.json"
    latest_path = root / "dashboard_v2" / "data" / "latest.json"
    try:
        latest = json.loads(latest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        latest = {}
    if (target_day and target_day != "auto" and day != target_day) or not day:
        record_stage(root, "MODEL_COMPLETED", "FAILED", business_date=target_day, duration_seconds=time.monotonic() - engine_started, details={"reason": "TARGET_DATE_MISMATCH", "engine_day": day, "expected_day": target_day})
        raise SystemExit(f"basketball engine target date mismatch: {day!r} != {target_day!r}")
    if update_status == "FAILED" or not target_path.is_file() or latest.get("date_bj") != day or not latest.get("events"):
        details = {"reason": "STALE_OR_EMPTY_TARGET_PAYLOAD", "update_status": update_status, "events": str(len(latest.get("events") or []))}
        record_stage(root, "DATA_UPDATED", "FAILED", business_date=day, duration_seconds=time.monotonic() - engine_started, details=details)
        raise SystemExit("basketball engine did not produce a current non-empty target payload")
    record_stage(root, "DATA_UPDATED", "SUCCESS", business_date=day, duration_seconds=time.monotonic() - engine_started, details={"events": str(len(latest.get("events") or [])), "generated_at": str(latest.get("generated_at") or "")})
    record_stage(root, "MODEL_COMPLETED", "SUCCESS", business_date=day, duration_seconds=time.monotonic() - engine_started, details={"update_status": update_status, "run_id": str(summary.get("run_id") or result.get("run_id") or "")})
    compact = {
        "run_id": summary.get("run_id") or result.get("run_id"),
        "date": day,
        "update_status": update_status,
        "source_http_attempts": summary.get("source_http_attempts"),
        "source_http_successes": summary.get("source_http_successes"),
        "paper_bettable": (summary.get("funnel") or {}).get("paper_bettable"),
    }
    github_output = os.environ.get("GITHUB_OUTPUT", "")
    if github_output:
        with open(github_output, "a", encoding="utf-8") as fh:
            fh.write(f"date={day}\n")
            fh.write(f"generated_at={latest.get('generated_at') or ''}\n")
            fh.write(f"run_id={summary.get('run_id') or result.get('run_id') or ''}\n")
            fh.write(f"update_status={update_status}\n")
    print(json.dumps(compact, ensure_ascii=False))
    # Remote publication is deliberately owned by the following workflow step.
    # This wrapper only validates and prepares the payload; recording PUBLISHED
    # here would falsely claim that gh-pages was updated if the runner is
    # cancelled before the git push.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

