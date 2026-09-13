from __future__ import annotations

import argparse
import csv
import datetime as dt
import importlib.util
from pathlib import Path


ROOT = Path(r"D:\codex\outputs\football_odds_trader")
DASHBOARD_TOOL = Path(r"D:\codex\tools\build_football_dashboard.py")
OUT_DIR = ROOT / "backtests" / "sequential_asian"


def load_dashboard_module():
    spec = importlib.util.spec_from_file_location("football_dashboard", DASHBOARD_TOOL)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot import dashboard builder from {DASHBOARD_TOOL}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def useful_intent(tag: object, asian_intent: object) -> bool:
    text = f"{tag or ''} {asian_intent or ''}".strip()
    if not text:
        return False
    blocked = ("平衡盘", "等待临场", "不计", "无方向", "缺候选标签", "盘口缺失")
    return not any(word in text for word in blocked)


def main() -> int:
    parser = argparse.ArgumentParser(description="Export current dashboard rows with usable Asian intent tags.")
    parser.add_argument("--date", default=dt.date.today().isoformat(), help="Dashboard list date, e.g. 2026-09-01")
    args = parser.parse_args()

    module = load_dashboard_module()
    cards, _meta = module.build_rows()
    rows = []
    for card in cards:
        if str(card.get("date", "")) != args.date:
            continue
        if not useful_intent(card.get("intent_tag"), card.get("asian_intent")):
            continue
        rows.append(
            {
                "日期": card.get("date", ""),
                "北京时间": card.get("display_time", "") or card.get("time", ""),
                "赛事": card.get("league", ""),
                "比赛": card.get("display_match", "") or card.get("match", ""),
                "状态": card.get("display_status", "") or card.get("state_label", ""),
                "比分": card.get("display_score", "") or card.get("score", ""),
                "盘口档位": card.get("intent_line_bucket", ""),
                "候选标签": card.get("intent_tag", ""),
                "正向球队": card.get("intent_forward_team", ""),
                "反向球队": card.get("intent_reverse_team", ""),
                "上盘球队": card.get("intent_upper_team", ""),
                "下盘球队": card.get("intent_lower_team", ""),
                "正向水位": card.get("intent_forward_water", ""),
                "反向水位": card.get("intent_reverse_water", ""),
                "亚盘": card.get("ah", ""),
                "欧赔": card.get("euro", ""),
                "大小球": card.get("total", ""),
                "微观板块": card.get("micro_region", ""),
                "亚盘已读": card.get("ah_ok", ""),
                "欧赔已读": card.get("euro_ok", ""),
                "大小球已读": card.get("total_ok", ""),
                "最终动作": card.get("final_action", ""),
            }
        )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    out = OUT_DIR / f"current_intent_matches_{args.date}_{stamp}.csv"
    fields = [
        "日期",
        "北京时间",
        "赛事",
        "比赛",
        "状态",
        "比分",
        "盘口档位",
        "候选标签",
        "正向球队",
        "反向球队",
        "上盘球队",
        "下盘球队",
        "正向水位",
        "反向水位",
        "亚盘",
        "欧赔",
        "大小球",
        "微观板块",
        "亚盘已读",
        "欧赔已读",
        "大小球已读",
        "最终动作",
    ]
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    print(f"exported={len(rows)}")
    print(out)
    for row in rows[:40]:
        print(
            f"{row['北京时间']} | {row['赛事']} | {row['比赛']} | {row['盘口档位']} | "
            f"{row['候选标签']} | 正向:{row['正向球队']} | 反向:{row['反向球队']} | {row['亚盘']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
