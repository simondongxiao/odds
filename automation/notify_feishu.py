from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


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
    args = ap.parse_args()
    webhook = os.environ.get("FEISHU_WEBHOOK", "").strip()
    if not webhook:
        print("FEISHU_WEBHOOK is not configured; notification skipped")
        return 0
    if not webhook.startswith("https://open.feishu.cn/open-apis/bot/v2/hook/"):
        raise SystemExit("FEISHU_WEBHOOK must be an open.feishu.cn bot webhook")
    latest = load(Path(args.data))
    day = latest.get("date_bj") or latest.get("date") or "未知日期"
    funnel = latest.get("funnel") or {}
    lines = [f"篮球日更｜{day}", f"运行状态：{args.status}", f"赛事数：{len(latest.get('events') or [])}", f"纸面可投：{funnel.get('paper_bettable', '—')}"]
    picks = []
    for row in latest.get("events") or []:
        picks.extend(triggered(row))
        if picks:
            event = row.get("event") or {}
            picks[-1] = f"{event.get('team1_name', '主队')} vs {event.get('team2_name', '客队')}｜{picks[-1]}"
    if picks:
        lines.append("纸面候选：")
        lines.extend(f"- {item}" for item in picks[:8])
    lines.append("页面：https://simondongxiao.github.io/odds/basketball-v2.html")
    payload = json.dumps({"msg_type": "text", "content": {"text": "\n".join(lines)}}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(webhook, data=payload, headers={"Content-Type": "application/json"}, method="POST")
    last_error = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                body = json.loads(response.read().decode("utf-8", errors="replace") or "{}")
            if body.get("code", 0) not in (0, None):
                raise RuntimeError(f"Feishu returned code {body.get('code')}")
            print(json.dumps({"sent": True, "status": response.status}, ensure_ascii=False))
            return 0
        except (OSError, ValueError, RuntimeError) as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(2 ** (attempt + 1))
    raise SystemExit(f"Feishu notification failed after 3 attempts: {last_error}")


if __name__ == "__main__":
    raise SystemExit(main())
