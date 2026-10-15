#!/usr/bin/env python3
"""Send a post-publish Feishu notification and persist a non-secret run manifest."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data" / "github_football" / "run_manifest.json"


def read_last_run() -> dict[str, Any]:
    path = ROOT / "data" / "github_football" / "last_run.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def parse_response(raw: str) -> tuple[str, str]:
    try:
        result = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Feishu returned non-JSON response") from exc
    code = result.get("code", result.get("StatusCode"))
    message = result.get("msg", result.get("StatusMessage", ""))
    if code not in (0, "0") or str(message).lower() not in {"", "success"}:
        raise RuntimeError(f"Feishu business failure code={code!r} message={message!r}")
    return str(code), str(message)


def write_manifest(data: dict[str, Any]) -> None:
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    tmp = MANIFEST.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(MANIFEST)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True)
    parser.add_argument("--status", choices=("SUCCESS", "FAILED"), required=True)
    parser.add_argument("--workflow", default="")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--event", default="")
    parser.add_argument("--scheduled-at", default="")
    parser.add_argument("--actual-started-at", default="")
    parser.add_argument("--pages-sha", default="")
    parser.add_argument("--pages-status", default="")
    parser.add_argument("--failure-stage", default="")
    parser.add_argument("--failure-reason", default="")
    args = parser.parse_args()
    last = read_last_run()
    counts = last.get("counts", {})
    status = args.status
    failure_reason = args.failure_reason if status == "FAILED" else ""
    failure_stage = args.failure_stage if status == "FAILED" else ""
    text = (
        f"GitHub 足球更新{status}｜日期 {args.date}\n"
        f"V3 可投 {counts.get('V3', '?')} 场｜V4 可投 {counts.get('V4', '?')} 场｜底稿 {counts.get('rows', '?')} 场\n"
        f"Pages: {args.pages_status or '未校验'} {args.pages_sha}\n"
        f"工作流 {args.workflow}｜Run {args.run_id}"
    )
    if failure_reason:
        text += f"\n失败阶段: {failure_stage or 'unknown'}\n原因: {failure_reason[:500]}"
    webhook = os.environ.get("FEISHU_WEBHOOK_URL", "").strip()
    manifest: dict[str, Any] = {
        "workflow": args.workflow,
        "run_id": args.run_id,
        "event": args.event,
        "scheduled_at": args.scheduled_at,
        "actual_started_at": args.actual_started_at,
        "ended_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "target_date": args.date,
        "source_counts": last.get("source_counts", {}),
        "counts": counts,
        "pages_sha": args.pages_sha,
        "pages_status": args.pages_status,
        "status": status,
        "failure_stage": failure_stage,
        "failure_reason": failure_reason,
        "feishu": {"configured": bool(webhook)},
    }
    if not webhook:
        manifest["feishu"].update({"http_status": None, "business_status": "missing_webhook"})
        write_manifest(manifest)
        print("FEISHU_WEBHOOK_CONFIGURED=false")
        raise SystemExit("FEISHU_WEBHOOK_URL is missing")
    body = json.dumps({"msg_type": "text", "content": {"text": text}}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(webhook, data=body, headers={"Content-Type": "application/json", "User-Agent": "football-update/1"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            raw = response.read().decode("utf-8", "replace")
            http_status = response.status
    except Exception as exc:
        manifest["feishu"].update({"http_status": None, "business_status": "transport_failure", "error": str(exc)})
        write_manifest(manifest)
        raise
    if http_status >= 300:
        manifest["feishu"].update({"http_status": http_status, "business_status": "http_failure"})
        write_manifest(manifest)
        raise SystemExit(f"Feishu HTTP {http_status}")
    try:
        code, message = parse_response(raw)
    except Exception as exc:
        manifest["feishu"].update({"http_status": http_status, "business_status": "business_failure", "error": str(exc)})
        write_manifest(manifest)
        raise
    manifest["feishu"].update({"http_status": http_status, "business_code": code, "business_message": message, "business_status": "success"})
    write_manifest(manifest)
    print(f"FEISHU_WEBHOOK_CONFIGURED=true feishu_business_status=success http={http_status}")
    return 0


if __name__ == "__main__":
    main()
