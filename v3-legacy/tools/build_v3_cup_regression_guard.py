"""Build immutable V3 cup baselines and post-change coverage-retention checks.

The guard is diagnostic only.  It never rewrites a frozen decision.  Baseline
candidate counts come from the frozen historical intent ledger; V3 bettable and
settlement figures come from the cumulative frozen bettable detail export.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import importlib.util
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


WORKSPACE = Path(r"D:\codex")
V3_ROOT = WORKSPACE / "v3_legacy" / "outputs" / "football_odds_trader"
SHARED_ROOT = WORKSPACE / "outputs" / "football_odds_trader"
OUT = SHARED_ROOT / "reviews" / "cup_regression_guard"
NORMALIZER_PATH = WORKSPACE / "tools" / "football_competition_normalizer.py"
SETTLED = {"红", "红半", "走水", "黑半", "黑"}


def load_normalizer():
    spec = importlib.util.spec_from_file_location("canonical_football_competition_normalizer", NORMALIZER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load canonical normalizer: {NORMALIZER_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


NORMALIZER = load_normalizer()
import v3_cup_match_state as cup_v3


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def latest(root: Path, pattern: str) -> Path:
    paths = sorted(root.glob(pattern), key=lambda path: path.stat().st_mtime, reverse=True)
    if not paths:
        raise FileNotFoundError(f"No {pattern} under {root}")
    return paths[0]


def is_cup(competition: str) -> bool:
    info = NORMALIZER.normalize(competition)
    return info.competition_type in {
        "杯赛", "洲际杯赛", "国家队正式赛", "国际综合运动会足球"
    } or info.competition_scope in {"国内杯赛", "洲际正式赛"}


def number(value: Any) -> float | None:
    try:
        text = str(value or "").strip().replace("%", "")
        return float(text) if text else None
    except ValueError:
        return None


def line_bucket(value: str) -> str:
    text = str(value or "").strip()
    return text or "MISSING"


def pnl_for(row: dict[str, str]) -> float | None:
    value = number(row.get("实际盈亏Unit"))
    if value is not None:
        return value
    label = row.get("结算标签", "")
    water = number(row.get("选中水位"))
    if label == "红" and water is not None:
        return water
    if label == "红半" and water is not None:
        return water / 2
    if label == "走水":
        return 0.0
    if label == "黑半":
        return -0.5
    if label == "黑":
        return -1.0
    return None


def freeze_hashes() -> dict[str, str]:
    result: dict[str, str] = {}
    for path in sorted((V3_ROOT / "ledger").glob("v3_legacy_decision_freeze_*.csv")):
        result[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def build_baseline() -> dict[str, Any]:
    history_path = latest(V3_ROOT / "ledger", "asian_intent_history_detail_*.csv")
    detail_path = latest(SHARED_ROOT / "ledger", "bettable_event_detail_*.csv")
    candidates = [row for row in read_csv(history_path) if is_cup(row.get("赛事", ""))]
    bettable = [row for row in read_csv(detail_path) if is_cup(row.get("赛事", ""))]

    by_comp: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "candidate_count": 0, "bettable_count": 0, "settled_count": 0,
        "红": 0, "红半": 0, "走水": 0, "黑半": 0, "黑": 0,
        "pnl": 0.0, "lines": defaultdict(int),
    })
    for row in candidates:
        comp = NORMALIZER.normalize(row.get("赛事", "")).competition_canonical or row.get("赛事", "")
        by_comp[comp]["candidate_count"] += 1
        by_comp[comp]["lines"][line_bucket(row.get("盘口档位", ""))] += 1
    for row in bettable:
        comp = NORMALIZER.normalize(row.get("赛事", "")).competition_canonical or row.get("赛事", "")
        cell = by_comp[comp]
        cell["bettable_count"] += 1
        label = row.get("结算标签", "")
        if label in SETTLED:
            cell["settled_count"] += 1
            cell[label] += 1
            value = pnl_for(row)
            if value is not None:
                cell["pnl"] += value

    rows: list[dict[str, Any]] = []
    for comp, cell in sorted(by_comp.items(), key=lambda item: (-item[1]["bettable_count"], item[0])):
        effective_n = cell["红"] + cell["红半"] + cell["黑半"] + cell["黑"]
        effective_wins = cell["红"] + 0.5 * cell["红半"]
        rows.append({
            "competition": comp,
            "candidate_count": cell["candidate_count"],
            "bettable_count": cell["bettable_count"],
            "settled_count": cell["settled_count"],
            "红": cell["红"], "红半": cell["红半"], "走水": cell["走水"],
            "黑半": cell["黑半"], "黑": cell["黑"],
            "effective_win_rate": round(effective_wins / effective_n, 6) if effective_n else None,
            "pnl": round(cell["pnl"], 4),
            "roi": round(cell["pnl"] / cell["settled_count"], 6) if cell["settled_count"] else None,
            "line_structure": json.dumps(dict(sorted(cell["lines"].items())), ensure_ascii=False),
        })
    generated_at = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    return {
        "generated_at": generated_at,
        "mode": "BEFORE_CHANGE_BASELINE",
        "history_source": str(history_path),
        "bettable_source": str(detail_path),
        "normalizer_source": str(NORMALIZER_PATH),
        "historical_freeze_hashes": freeze_hashes(),
        "rows": rows,
    }


def write_payload(payload: dict[str, Any], prefix: str) -> tuple[Path, Path, Path]:
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = OUT / f"{prefix}_{stamp}.json"
    csv_path = OUT / f"{prefix}_{stamp}.csv"
    md_path = OUT / f"{prefix}_{stamp}.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    rows = payload["rows"]
    fields = list(rows[0]) if rows else ["competition"]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    retention_mode = payload.get("mode") == "POST_CHANGE_COVERAGE_RETENTION"
    lines = [
        "# V3 杯赛 Coverage Retention" if retention_mode else "# V3 杯赛修改前基线",
        "",
        f"- 生成时间：{payload['generated_at']}",
        f"- 候选来源：`{payload['history_source']}`",
        f"- 可投/结算来源：`{payload['bettable_source']}`",
        f"- 历史冻结文件：{len(payload['historical_freeze_hashes'])} 个；仅计算哈希，未修改。",
    ]
    if retention_mode:
        lines.extend([
            f"- 历史冻结不可变校验：{'通过' if payload.get('historical_freeze_immutable') else '失败'}。",
            "- 该重放只评估分层贝叶斯收缩对既有可投覆盖的影响；历史赛果不用于重算当时方向，Fair Line 因历史证据不完整不参与重放。",
            "",
            "| 杯赛 | 候选基线 | 可投基线 | 保留 | 减少 | Coverage Retention | 缺概率/价格 | 警告 |",
            "|---|---:|---:|---:|---:|---:|---:|---|",
        ])
        for row in rows:
            retention = "待核" if row["coverage_retention"] is None else f"{row['coverage_retention']:.2%}"
            lines.append(
                f"| {row['competition']} | {row['candidate_baseline']} | {row['bettable_baseline']} | "
                f"{row['retained']} | {row['reduced']} | {retention} | {row['missing_rate_or_price']} | {row['warning'] or '—'} |"
            )
    else:
        lines.extend([
            "- 说明：候选数与可投数来源不同证据层，不能相除解释为实时转化率；该表只作为重构前覆盖和资产表现基线。",
            "",
            "| 杯赛 | 候选 | 可投 | 已结算 | 红/红半/走/黑半/黑 | 有效胜率 | PnL | ROI | 盘口结构 |",
            "|---|---:|---:|---:|---|---:|---:|---:|---|",
        ])
        for row in rows:
            rate = "待核" if row["effective_win_rate"] is None else f"{row['effective_win_rate']:.2%}"
            roi = "待核" if row["roi"] is None else f"{row['roi']:.2%}"
            lines.append(
                f"| {row['competition']} | {row['candidate_count']} | {row['bettable_count']} | {row['settled_count']} | "
                f"{row['红']}/{row['红半']}/{row['走水']}/{row['黑半']}/{row['黑']} | {rate} | "
                f"{row['pnl']:+.3f} | {roi} | `{row['line_structure']}` |"
            )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, csv_path, md_path


def build_retention(baseline_path: Path) -> dict[str, Any]:
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    detail_path = latest(SHARED_ROOT / "ledger", "bettable_event_detail_*.csv")
    rows = [row for row in read_csv(detail_path) if is_cup(row.get("赛事", ""))]
    model = cup_v3.model()
    by_comp: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "baseline_bettable": 0, "retained": 0, "reduced": 0,
        "missing_rate_or_price": 0, "reduction_reasons": defaultdict(int),
    })
    for row in rows:
        info = NORMALIZER.normalize(row.get("赛事", ""))
        comp = info.competition_canonical or row.get("赛事", "")
        cell = by_comp[comp]
        cell["baseline_bettable"] += 1
        base_rate = number(row.get("综合胜率"))
        threshold = number(row.get("通过阈值"))
        if base_rate is None or threshold is None:
            cell["missing_rate_or_price"] += 1
            cell["retained"] += 1
            continue
        posterior = model.posterior(row.get("赛事", ""), row.get("倾向意图", ""), "MISSING")
        weight = number(posterior.get("Cup_Bayes_Weight")) or 0.0
        post = number(posterior.get("Cup_Bayes_Posterior"))
        adjusted = base_rate if post is None or weight <= 0 else base_rate * (1 - weight) + post * weight
        if adjusted + 1e-12 >= threshold:
            cell["retained"] += 1
        else:
            cell["reduced"] += 1
            cell["reduction_reasons"]["HIERARCHICAL_SUPPORT_BELOW_PRICE"] += 1
    output_rows = []
    baseline_map = {row["competition"]: row for row in baseline.get("rows", [])}
    for comp in sorted(set(baseline_map) | set(by_comp)):
        cell = by_comp[comp]
        count = cell["baseline_bettable"]
        retention = cell["retained"] / count if count else None
        warning = ""
        if count >= 5 and retention is not None and retention < 0.70:
            warning = "COVERAGE_RETENTION_WARNING"
        output_rows.append({
            "competition": comp,
            "candidate_baseline": baseline_map.get(comp, {}).get("candidate_count", 0),
            "bettable_baseline": count,
            "retained": cell["retained"],
            "reduced": cell["reduced"],
            "coverage_retention": round(retention, 6) if retention is not None else None,
            "missing_rate_or_price": cell["missing_rate_or_price"],
            "warning": warning,
            "reduction_reasons": json.dumps(dict(cell["reduction_reasons"]), ensure_ascii=False),
        })
    current_hashes = freeze_hashes()
    old_hashes = baseline.get("historical_freeze_hashes", {})
    immutable = all(current_hashes.get(path) == digest for path, digest in old_hashes.items())
    return {
        "generated_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "mode": "POST_CHANGE_COVERAGE_RETENTION",
        "history_source": baseline.get("history_source", ""),
        "bettable_source": str(detail_path),
        "normalizer_source": str(NORMALIZER_PATH),
        "baseline_source": str(baseline_path),
        "historical_freeze_hashes": current_hashes,
        "historical_freeze_immutable": immutable,
        "rows": output_rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("baseline", "retention"), default="baseline")
    parser.add_argument("--baseline")
    args = parser.parse_args()
    if args.mode == "baseline":
        paths = write_payload(build_baseline(), "v3_cup_baseline")
        print(json.dumps({"json": str(paths[0]), "csv": str(paths[1]), "md": str(paths[2])}, ensure_ascii=False))
    else:
        baseline_path = Path(args.baseline) if args.baseline else latest(OUT, "v3_cup_baseline_*.json")
        payload = build_retention(baseline_path)
        paths = write_payload(payload, "v3_cup_coverage_retention")
        print(json.dumps({"json": str(paths[0]), "csv": str(paths[1]), "md": str(paths[2]), "historical_freeze_immutable": payload["historical_freeze_immutable"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
