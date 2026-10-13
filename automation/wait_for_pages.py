from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.request


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


def main() -> int:
    ap = argparse.ArgumentParser(description="Wait for the GitHub Pages workflow for a published commit")
    ap.add_argument("--sha", required=True)
    ap.add_argument("--workflow", default=os.environ.get("PAGES_WORKFLOW_ID", "342557702"))
    ap.add_argument("--timeout", type=int, default=600)
    ap.add_argument("--interval", type=int, default=10)
    args = ap.parse_args()
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    if not token or not repo:
        raise SystemExit("GITHUB_TOKEN and GITHUB_REPOSITORY are required")
    endpoint = f"https://api.github.com/repos/{repo}/actions/workflows/{args.workflow}/runs?branch=gh-pages&per_page=20"
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
        except (OSError, ValueError, urllib.error.HTTPError) as exc:
            print(json.dumps({"warning": str(exc)}, ensure_ascii=False), flush=True)
        time.sleep(max(2, args.interval))
    raise SystemExit(f"Timed out waiting for Pages workflow for {args.sha}")


if __name__ == "__main__":
    raise SystemExit(main())
