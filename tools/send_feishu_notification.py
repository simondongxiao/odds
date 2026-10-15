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
    parser.add_argument("--status", choices=("SUCCESS", "DIAGNOSTIC", "FAILED", "SKIPPED_DUPLICATE"), required=True)
    parser.add_argument("--workflow", default="")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--event", default="")
    parser.add_argument("--scheduled-at", default="")
    parser.add_argument("--planned-slot", default="")
    parser.add_argument("--planned-run-bjt", default="")
    parser.add_argument("--actual-run-bjt", default="")
    parser.add_argument("--target-list-date", default="")
    parser.add_argument("--trigger-source", default="")
    parser.add_argument("--run-key", default="")
    parser.add_argument("--actual-started-at", default="")
    parser.add_argument("--pages-sha", default="")
    parser.add_argument("--pages-status", default="")
    parser.add_argument("--failure-stage", default="")
    parser.add_argument("--failure-reason", default="")
    args = parser.parse_args()
    last = read_last_run()
    counts = last.get("counts", {})
    model_status = str(last.get("model_status") or "UNKNOWN")
    equivalence = str(last.get("formal_model_equivalence") or "NOT_VERIFIED")
    status = args.status
    failure_reason = args.failure_reason if status == "FAILED" else ""
    failure_stage = args.failure_stage if status == "FAILED" else ""
    ended_at = dt.datetime.now(dt.timezone.utc)
    webhook = os.environ.get("FEISHU_WEBHOOK_URL", "").strip()
    duration_seconds = None
    if args.actual_started_at:
        try:
            started_at = dt.datetime.fromisoformat(args.actual_started_at.replace("Z", "+00:00"))
            if started_at.tzinfo is None:
                started_at = started_at.replace(tzinfo=dt.timezone.utc)
            duration_seconds = round((ended_at - started_at).total_seconds(), 3)
        except ValueError:
            duration_seconds = None
    run_key = args.run_key or f"{args.date}|{args.planned_slot or 'manual'}"
    prior_manifest: dict[str, Any] = {}
    try:
        prior_manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        prior_manifest = {}
    if webhook and status in {"SUCCESS", "DIAGNOSTIC"} and prior_manifest.get("run_key") == run_key and prior_manifest.get("status") in {"SUCCESS", "DIAGNOSTIC", "SKIPPED_DUPLICATE"}:
        duplicate = dict(prior_manifest)
        duplicate.update({"status": "SKIPPED_DUPLICATE", "run_key": run_key, "duplicate_of_run_id": prior_manifest.get("run_id"), "ended_at": ended_at.isoformat()})
        duplicate["feishu"] = {"configured": bool(webhook), "business_status": "duplicate_suppressed"}
        write_manifest(duplicate)
        print(f"FEISHU_DUPLICATE_SUPPRESSED=true run_key={run_key}")
        return 0
    text = (
        f"GitHub 足球更新{status}｜日期 {args.date}\n"
        f"V3 可投 {counts.get('V3', '?')} 场｜V4 可投 {counts.get('V4', '?')} 场｜底稿 {counts.get('rows', '?')} 场\n"
        f"模型状态: {model_status}｜原版等价性: {equivalence}\n"
        f"业务时段: {args.planned_slot or 'manual'}｜计划 {args.planned_run_bjt or '未提供'}｜实际 {args.actual_run_bjt or '未提供'}\n"
        f"Pages: {args.pages_status or '未校验'} {args.pages_sha}\n"
        f"工作流 {args.workflow}｜Run {args.run_id}"
    )
    if failure_reason:
        text += f"\n失败阶段: {failure_stage or 'unknown'}\n原因: {failure_reason[:500]}"
    manifest: dict[str, Any] = {
        "workflow": args.workflow,
        "run_id": args.run_id,
        "event": args.event,
        "scheduled_at": args.scheduled_at,
        "planned_slot": args.planned_slot,
        "planned_run_bjt": args.planned_run_bjt,
        "actual_run_bjt": args.actual_run_bjt,
        "target_list_date": args.target_list_date or args.date,
        "trigger_source": args.trigger_source or args.event,
        "run_key": run_key,
        "actual_started_at": args.actual_started_at,
        "ended_at": ended_at.isoformat(),
        "duration_seconds": duration_seconds,
        "target_date": args.date,
        "source_counts": last.get("source_counts", {}),
        "counts": counts,
        "pages_sha": args.pages_sha,
        "pages_status": args.pages_status,
        "status": status,
        "model_status": model_status,
        "formal_model_equivalence": equivalence,
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
        manifest["feishu"].update({"http_status": None, "business_status": "UNKNOWN_DELIVERY", "error": str(exc)})
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
