from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

from stage_status import record_stage


def load(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def triggered(event: dict):
    execution = event.get("execution") or {}
    if execution.get("triggered") is not True:
        return []
    decisions = execution.get("market_decisions") or {}
    if not isinstance(decisions, dict):
        decisions = {}
    out = []
    for market, decision in decisions.items():
        if not isinstance(decision, dict) or decision.get("triggered") is not True:
            continue
        selected = decision.get("selected") or {}
        line = selected.get("line", selected.get("raw_line", ""))
        odds = selected.get("decimal_odds", selected.get("odds", ""))
        selection = selected.get("selection", "")
        out.append(f"{market} {selection} {line} @ {odds}")
    if not out and execution.get("selected"):
        selected = execution["selected"]
        out.append(f"{selected.get('market_type', '')} {selected.get('selection', '')} {selected.get('line', '')} @ {selected.get('decimal_odds', '')}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Send a compact basketball daily result to Feishu")
    ap.add_argument("--data", required=True)
    ap.add_argument("--status", default="success")
    ap.add_argument("--commit", default="")
    ap.add_argument("--deploy-status", default="not-run")
    ap.add_argument("--run-kind", default="")
    ap.add_argument("--run-url", default="")
    ap.add_argument("--business-date", default=os.environ.get("BASKETBALL_DATE", ""))
    ap.add_argument("--url", default="https://simondongxiao.github.io/odds/basketball-v2.html")
    ap.add_argument("--audit-root", default=os.environ.get("BASKETBALL_RUN_ROOT", ""))
    args = ap.parse_args()
    started = time.monotonic()
    audit_root = args.audit_root.strip()
    webhook = os.environ.get("FEISHU_WEBHOOK", "").strip()
    if not webhook:
        message = "FEISHU_WEBHOOK is not configured; notification was not attempted"
        if audit_root:
            record_stage(audit_root, "FEISHU_SENT", "FAILED", duration_seconds=time.monotonic() - started, details={"reason": "SECRET_MISSING"})
        print(message, file=os.sys.stderr)
        return 2
    if not webhook.startswith("https://open.feishu.cn/open-apis/bot/v2/hook/"):
        message = "FEISHU_WEBHOOK must be an open.feishu.cn bot webhook"
        if audit_root:
            record_stage(audit_root, "FEISHU_SENT", "FAILED", duration_seconds=time.monotonic() - started, details={"reason": "WEBHOOK_HOST_INVALID"})
        raise SystemExit(message)
    latest = load(Path(args.data))
    data_day = latest.get("date_bj") or latest.get("date") or "未知日期"
    requested_day = args.business_date.strip()
    day = requested_day or data_day
    data_matches_target = not requested_day or requested_day == data_day
    completed = (
        str(args.status).strip().lower() in {"success", "completed"}
        and str(args.deploy_status).strip().lower() == "success"
        and data_matches_target
    )
    funnel = latest.get("funnel") or {}
    lines = [
        f"篮球日更｜{day}",
        f"运行状态：{args.status}",
        f"数据快照：{data_day}" if data_matches_target else f"数据快照：未生成目标日（当前文件为 {data_day}）",
        f"赛事数：{len(latest.get('events') or [])}" if data_matches_target else "赛事数：—",
        f"纸面可投：{funnel.get('paper_bettable', '—')}" if data_matches_target else "纸面可投：—",
        f"Pages：{args.deploy_status}" if completed else "Pages：未完成发布",
    ]
    if args.run_kind:
        kind_label = {"TODAY_MORNING": "当天早间", "NEXT_DAY_EVENING": "次日晚间", "MANUAL_TARGET_DATE": "手动指定日期"}.get(args.run_kind, args.run_kind)
        lines.insert(1, f"运行类型：{kind_label}")
    picks = []
    for row in ((latest.get("events") or []) if data_matches_target and completed else []):
        picks.extend(triggered(row))
        if picks:
            event = row.get("event") or {}
            picks[-1] = f"{event.get('team1_name', '主队')} vs {event.get('team2_name', '客队')}｜{picks[-1]}"
    if picks:
        lines.append("纸面候选：")
        lines.extend(f"- {item}" for item in picks[:8])
    if completed:
        lines.append(f"页面：{args.url}")
    else:
        lines.append(f"页面：未发送成功链接；请查看 Actions：{args.run_url or '—'}")
    if completed and args.commit:
        lines.append(f"发布提交：{args.commit[:12]}")
    if args.run_url and completed:
        lines.append(f"Actions：{args.run_url}")
    payload = json.dumps({"msg_type": "text", "content": {"text": "\n".join(lines)}}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(webhook, data=payload, headers={"Content-Type": "application/json"}, method="POST")
    last_error = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                raw = response.read().decode("utf-8", errors="replace")
                body = json.loads(raw or "{}")
                http_status = response.status
            if not 200 <= http_status < 300:
                raise RuntimeError(f"Feishu HTTP status {http_status}")
            # Feishu bot HTTP 200 is not sufficient: code=0 is the business
            # acknowledgement.  Missing/unknown code is treated as failure.
            if not isinstance(body, dict) or body.get("code") != 0:
                raise RuntimeError(f"Feishu business response rejected: {body!r}")
            msg = str(body.get("msg", "")).strip().lower()
            if msg and msg not in {"success", "ok"}:
                raise RuntimeError(f"Feishu business message rejected: {body!r}")
            if audit_root:
                record_stage(audit_root, "FEISHU_SENT", "SUCCESS", business_date=day, duration_seconds=time.monotonic() - started, details={"http_status": str(http_status), "business_code": "0"})
            print(json.dumps({"sent": True, "status": http_status, "business_code": 0}, ensure_ascii=False))
            return 0
        except (OSError, ValueError, RuntimeError) as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(2 ** (attempt + 1))
    if audit_root:
        record_stage(audit_root, "FEISHU_SENT", "FAILED", business_date=day, duration_seconds=time.monotonic() - started, details={"reason": type(last_error).__name__, "error": str(last_error)})
    raise SystemExit(f"Feishu notification failed after 3 attempts: {last_error}")


if __name__ == "__main__":
    raise SystemExit(main())
