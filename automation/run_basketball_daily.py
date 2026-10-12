from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


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
    env = os.environ.copy()
    scripts = repo / "basketball_engine" / "scripts"
    env["PYTHONPATH"] = str(repo / "basketball_engine") + os.pathsep + str(scripts) + os.pathsep + env.get("PYTHONPATH", "")
    seed = [sys.executable, str(repo / "automation" / "seed_basketball_state.py"), "--public", str(public), "--root", str(root)]
    subprocess.run(seed, check=True, env=env)
    entry = scripts / "run_basketball_daily.py"
    cmd = [sys.executable, str(entry), "--root", str(root), "--date", args.date, "--live", "--timeout", "12", "--workers", "6"]
    completed = subprocess.run(cmd, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if completed.returncode:
        tail = (completed.stderr or completed.stdout)[-6000:]
        print(tail, file=sys.stderr)
        raise SystemExit(completed.returncode)
    # The engine emits a large audit JSON. Keep the Actions log compact while
    # retaining the full files under the run root and in the uploaded artifact.
    try:
        result = json.loads(completed.stdout)
        compact = {
            "run_id": result.get("run_id"),
            "date": result.get("day"),
            "update_status": result.get("update_status"),
            "source_http_attempts": result.get("source_http_attempts"),
            "source_http_successes": result.get("source_http_successes"),
            "paper_bettable": (result.get("summary") or {}).get("funnel", {}).get("paper_bettable"),
        }
    except (ValueError, TypeError):
        compact = {"engine_output_tail": completed.stdout[-3000:]}
    print(json.dumps(compact, ensure_ascii=False))
    publish = [sys.executable, str(repo / "automation" / "publish_basketball.py"), "--root", str(root), "--public", str(public)]
    subprocess.run(publish, check=True, env=env)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

