"""Send the completed football daily run summary to a Feishu bot.

The webhook is read only from ``FEISHU_WEBHOOK_URL``.  It is deliberately not
stored in the repository or in the generated report files.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


CN_TZ = dt.timezone(dt.timedelta(hours=8))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None


def shanghai_today() -> str:
    return dt.datetime.now(CN_TZ).date().isoformat()


def date_payload(root: Path, list_date: str) -> dict[str, Any] | None:
    path = root / "dashboard" / "data" / "dates" / f"{list_date}.json"
    payload = read_json(path)
    return payload if isinstance(payload, dict) else None


def latest_history_alert(root: Path, list_date: str) -> dict[str, Any] | None:
    path = root / "reviews" / "league_history" / list_date / f"league_history_alert_{list_date}.json"
    payload = read_json(path)
    return payload if isinstance(payload, dict) else None


def build_summary(root: Path, list_date: str, status: str) -> str:
    current = read_json(root / "dashboard" / "data" / "current.json") or {}
    latest = read_json(root / "decision_versions" / list_date / "latest.json") or {}
    run = latest.get("run", {}) if isinstance(latest, dict) else {}
    metrics = run.get("v4", {}) if isinstance(run, dict) else {}
    if not metrics:
        metrics = current.get("v4", {}) if isinstance(current, dict) else {}
    v3 = run.get("v3", {}) if isinstance(run, dict) else {}
    if not v3:
        v3 = current.get("v3", {}) if isinstance(current, dict) else {}
    payload = date_payload(root, list_date)
    matches = payload.get("matches", []) if payload else []
    v4_rows = [m.get("v4_shadow", {}) for m in matches if isinstance(m, dict)]
    giving = sum(1 for row in v4_rows if row.get("side") == "giving")
    receiving = sum(1 for row in v4_rows if row.get("side") == "receiving")
    v4_bettable = giving + receiving
    v4_computed = sum(1 for row in v4_rows if row.get("status") == "EVALUATED")
    history = latest_history_alert(root, list_date)
    history_rows = len(history.get("rows", [])) if history else 0
    guard = ((run.get("steps", {}) if isinstance(run, dict) else {}).get("row_count_shrink_guard", {}) or {})
    guard_status = guard.get("status") or ("PASS" if guard.get("ok") else "UNKNOWN")
    run_id = (payload or {}).get("run_id") or run.get("run_id") or current.get("run_id") or "未找到运行编号"
    base_dashboard_url = os.environ.get("FOOTBALL_DASHBOARD_URL", "https://simondongxiao.github.io/odds/v4/").rstrip("/")
    dashboard_url = f"{base_dashboard_url}/?date={list_date}"
    roster_total = len(matches) or run.get("roster_total", current.get("total_matches", "未知"))
    v4_computed_display = v4_computed or metrics.get("v4_computed", metrics.get("computed_count", "未知"))
    v4_b_display = metrics.get("v4_B", metrics.get("B_count", "未知"))
    v4_c_display = metrics.get("v4_C", metrics.get("C_count", "未知"))

    lines = [
        "⚽ 足球 V3/V4 每日更新",
        f"状态：{status}",
        f"列表日：{list_date}",
        f"运行编号：{run_id}",
        f"赛事总数：{roster_total}",
        f"V3：计算 {v3.get('v3_computed', v3.get('computed_count', '未知'))} 场，可投 {v3.get('v3_bettable', v3.get('bettable_count', '未知'))} 场",
        f"V4：计算 {v4_computed_display} 场，BET可投 {v4_bettable} 场（让球 {giving} / 受让 {receiving}），B {v4_b_display}，C {v4_c_display}",
        f"缩表审计：{guard_status}",
        f"同赛事历史统计：{history_rows} 条",
        f"看板：{dashboard_url}",
    ]
    if status.lower() not in {"success", "succeeded", "completed"}:
        lines.insert(1, "⚠️ 本次更新未正常完成，请查看 GitHub Actions 日志。")
    return "\n".join(lines)


def send(webhook: str, text: str) -> None:
    body = json.dumps({"msg_type": "text", "content": {"text": text}}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        webhook,
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8", errors="replace") or "{}")
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Feishu webhook HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Feishu webhook network error: {exc.reason}") from exc
    if result.get("code", 0) not in (0, None):
        raise RuntimeError(f"Feishu webhook rejected message: code={result.get('code')}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Send the football daily run summary to Feishu.")
    parser.add_argument("--list-date", default="")
    parser.add_argument("--status", default="success")
    parser.add_argument("--root", default=os.environ.get("FOOTBALL_OUTPUT_ROOT", r"D:\codex\outputs\football_odds_trader"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    list_date = args.list_date or shanghai_today()
    text = build_summary(Path(args.root), list_date, args.status)
    if args.dry_run:
        print(text)
        return 0
    webhook = os.environ.get("FEISHU_WEBHOOK_URL", "").strip()
    if not webhook:
        raise SystemExit("FEISHU_WEBHOOK_URL is not set; add it as a GitHub Actions Secret")
    send(webhook, text)
    print("Feishu daily report sent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
