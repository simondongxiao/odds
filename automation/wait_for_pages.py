from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime

from stage_status import record_stage


def api_get(url: str, token: str) -> dict:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "basketball-daily-pages-waiter",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8", errors="replace") or "{}")


def current_branch_sha(repo: str, token: str) -> str:
    payload = api_get(f"https://api.github.com/repos/{repo}/git/ref/heads/gh-pages", token)
    return str(((payload.get("object") or {}).get("sha") or "")).strip()


def workflow_info(repo: str, workflow: str, token: str) -> dict:
    return api_get(f"https://api.github.com/repos/{repo}/actions/workflows/{workflow}", token)


def verify_pages_data(url: str, expected_date: str, expected_generated_at: str) -> dict:
    request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "basketball-daily-pages-verifier"})
    with urllib.request.urlopen(request, timeout=20) as response:
        if not 200 <= response.status < 300:
            raise RuntimeError(f"Pages data HTTP status {response.status}")
        payload = json.loads(response.read().decode("utf-8", errors="replace") or "{}")
    if not isinstance(payload, dict):
        raise RuntimeError("Pages latest payload is not a JSON object")
    actual_date = str(payload.get("date_bj") or payload.get("date") or "")
    if expected_date and actual_date != expected_date:
        raise RuntimeError(f"Pages date mismatch: {actual_date!r} != {expected_date!r}")
    actual_generated = str(payload.get("generated_at") or "")
    if expected_generated_at and actual_generated:
        try:
            if datetime.fromisoformat(actual_generated.replace("Z", "+00:00")) < datetime.fromisoformat(expected_generated_at.replace("Z", "+00:00")):
                raise RuntimeError(f"Pages payload is older than generated output: {actual_generated} < {expected_generated_at}")
        except ValueError:
            raise RuntimeError(f"Pages generated_at is not ISO-8601: {actual_generated!r}")
    if not payload.get("events"):
        raise RuntimeError("Pages latest payload contains no events")
    return {"date_bj": actual_date, "generated_at": actual_generated, "events": len(payload.get("events") or [])}


def main() -> int:
    ap = argparse.ArgumentParser(description="Wait for the GitHub Pages workflow for a published commit")
    ap.add_argument("--sha", required=True)
    ap.add_argument("--workflow", default=os.environ.get("PAGES_WORKFLOW_ID", "342557702"))
    ap.add_argument("--timeout", type=int, default=600)
    ap.add_argument("--interval", type=int, default=10)
    ap.add_argument("--pages-url", default=os.environ.get("PAGES_DATA_URL", ""))
    ap.add_argument("--expected-date", default=os.environ.get("BASKETBALL_DATE", ""))
    ap.add_argument("--expected-generated-at", default=os.environ.get("PAGES_EXPECTED_GENERATED_AT", ""))
    ap.add_argument("--audit-root", default=os.environ.get("BASKETBALL_RUN_ROOT", ""))
    ap.add_argument("--changed", choices=("true", "false"), default=os.environ.get("PUBLISH_CHANGED", "true"))
    args = ap.parse_args()
    started = time.monotonic()
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    if not token or not repo:
        raise SystemExit("GITHUB_TOKEN and GITHUB_REPOSITORY are required")
    try:
        info = workflow_info(repo, args.workflow, token)
    except (OSError, ValueError, urllib.error.HTTPError) as exc:
        if args.audit_root:
            record_stage(args.audit_root, "PAGE_VERIFIED", "FAILED", business_date=args.expected_date, duration_seconds=time.monotonic() - started, details={"reason": "PAGES_WORKFLOW_LOOKUP_FAILED", "error": str(exc)})
        raise SystemExit(f"Pages workflow lookup failed for {args.workflow}: {exc}")
    if not info.get("id") or info.get("state") != "active":
        if args.audit_root:
            record_stage(args.audit_root, "PAGE_VERIFIED", "FAILED", business_date=args.expected_date, duration_seconds=time.monotonic() - started, details={"reason": "PAGES_WORKFLOW_NOT_ACTIVE", "workflow": str(info.get("path") or args.workflow)})
        raise SystemExit(f"Pages workflow is not active: {json.dumps(info, ensure_ascii=False)}")
    endpoint = f"https://api.github.com/repos/{repo}/actions/workflows/{args.workflow}/runs?branch=gh-pages&per_page=20"
    if args.pages_url and not args.pages_url.endswith("latest.json"):
        args.pages_url = args.pages_url.rstrip("/") + "/basketball-data/latest.json"
    deadline = time.monotonic() + max(30, args.timeout)
    expected_sha = args.sha
    last = None
    while time.monotonic() < deadline:
        try:
            payload = api_get(endpoint, token)
            runs = payload.get("workflow_runs") or []
            matched = [row for row in runs if row.get("head_sha") == expected_sha]
            if matched:
                run = sorted(matched, key=lambda row: row.get("created_at", ""), reverse=True)[0]
                state = {"id": run.get("id"), "status": run.get("status"), "conclusion": run.get("conclusion"), "url": run.get("html_url")}
                if state != last:
                    print(json.dumps(state, ensure_ascii=False), flush=True)
                    last = state
                if run.get("status") == "completed":
                    if run.get("conclusion") == "success":
                        try:
                            page_state = verify_pages_data(args.pages_url, args.expected_date, args.expected_generated_at) if args.pages_url else {}
                        except (OSError, ValueError, RuntimeError, urllib.error.HTTPError) as exc:
                            print(json.dumps({"warning": f"Pages workflow succeeded but public payload is not ready: {exc}"}, ensure_ascii=False), flush=True)
                        else:
                            if args.audit_root:
                                record_stage(args.audit_root, "PAGE_VERIFIED", "SUCCESS", business_date=args.expected_date, duration_seconds=time.monotonic() - started, details={"workflow_id": str(run.get("id")), "head_sha": str(run.get("head_sha")), **{k: str(v) for k, v in page_state.items()}})
                            return 0
                    # A Pages run can be cancelled when football or a manual
                    # publisher advances gh-pages. Follow the newer branch
                    # head instead of treating that expected concurrency as a
                    # failed basketball deployment.
                    branch_sha = current_branch_sha(repo, token)
                    if branch_sha and branch_sha != expected_sha:
                        expected_sha = branch_sha
                        print(json.dumps({"superseded_by": expected_sha}, ensure_ascii=False), flush=True)
                    elif run.get("conclusion") not in {"cancelled", "skipped"}:
                        raise SystemExit(f"Pages workflow failed: {json.dumps(state, ensure_ascii=False)}")
            else:
                branch_sha = current_branch_sha(repo, token)
                if branch_sha and branch_sha != expected_sha:
                    expected_sha = branch_sha
                    print(json.dumps({"superseded_by": expected_sha}, ensure_ascii=False), flush=True)
                elif args.changed == "false" and args.pages_url:
                    try:
                        page_state = verify_pages_data(args.pages_url, args.expected_date, args.expected_generated_at)
                    except (OSError, ValueError, RuntimeError, urllib.error.HTTPError) as exc:
                        print(json.dumps({"warning": f"Existing gh-pages commit is not yet verified: {exc}"}, ensure_ascii=False), flush=True)
                    else:
                        if args.audit_root:
                            record_stage(args.audit_root, "PAGE_VERIFIED", "SUCCESS", business_date=args.expected_date, duration_seconds=time.monotonic() - started, details={"workflow_id": "already-current", **{k: str(v) for k, v in page_state.items()}})
                        return 0
        except (OSError, ValueError, urllib.error.HTTPError) as exc:
            print(json.dumps({"warning": str(exc)}, ensure_ascii=False), flush=True)
        time.sleep(max(2, args.interval))
    if args.audit_root:
        record_stage(args.audit_root, "PAGE_VERIFIED", "FAILED", business_date=args.expected_date, duration_seconds=time.monotonic() - started, details={"reason": "PAGES_VERIFICATION_TIMEOUT", "sha": args.sha})
    raise SystemExit(f"Timed out waiting for Pages workflow for {args.sha}")


if __name__ == "__main__":
    raise SystemExit(main())
