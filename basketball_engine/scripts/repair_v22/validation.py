"""Read-only probability, residual, and empirical-return validation.

This module deliberately operates on derived analytics rows.  It never edits
the first-write decision, quote, forecast, or settlement records.
"""
from __future__ import annotations

import csv
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path

from .common import atomic, stamp


GOVERNANCE = ((20, "EARLY_EMPIRICAL"), (50, "PROVISIONAL_EMPIRICAL"), (100, "EMPIRICAL_ESTIMATE"))


def governance(n):
    n = int(n or 0)
    if n < 20:
        return "MODEL_ONLY"
    if n < 50:
        return "EARLY_EMPIRICAL"
    if n < 100:
        return "PROVISIONAL_EMPIRICAL"
    return "EMPIRICAL_ESTIMATE"


def probability_bucket(p):
    if p is None:
        return "UNKNOWN"
    p = float(p)
    if p < .50:
        return "<50%"
    if p >= .70:
        return "70%+"
    lo = int(math.floor(p * 100 / 2) * 2)
    return f"{lo}-{lo + 2}%"


def edge_bucket(edge):
    if edge is None:
        return "UNKNOWN"
    edge = abs(float(edge))
    if edge < 2:
        return "0-2"
    if edge < 5:
        return "2-5"
    if edge < 10:
        return "5-10"
    if edge < 20:
        return "10-20"
    return "20+"


def selected_side_edge(record):
    """Positive always means favorable to the selected side."""
    market = record.get("market_type")
    line = record.get("line")
    if line is None:
        return None
    if market == "SPREAD" and record.get("fair_margin") is not None:
        selected_margin = float(record["fair_margin"]) if record.get("selection") == "TEAM1" else -float(record["fair_margin"])
        return selected_margin + float(line)
    if market == "TOTAL" and record.get("fair_total") is not None:
        fair, line = float(record["fair_total"]), float(line)
        return fair - line if record.get("selection") == "OVER" else line - fair
    return None


def residual(record):
    ev = record.get("evaluation") or {}
    if record.get("market_type") == "SPREAD" and ev.get("actual_margin") is not None and record.get("fair_margin") is not None:
        return float(ev["actual_margin"]) - float(record["fair_margin"])
    if record.get("market_type") == "TOTAL" and ev.get("actual_total") is not None and record.get("fair_total") is not None:
        return float(ev["actual_total"]) - float(record["fair_total"])
    return None


def _mean(values):
    return sum(values) / len(values) if values else None


def _rmse(values):
    return math.sqrt(_mean([x * x for x in values])) if values else None


def _bootstrap_mean(values, seed=17, rounds=1000):
    if not values:
        return None
    # Deterministic LCG avoids importing a mutable/global random stream.
    state = seed
    means = []
    for _ in range(rounds):
        sample = []
        for _ in values:
            state = (1103515245 * state + 12345) % (2 ** 31)
            sample.append(values[state % len(values)])
        means.append(_mean(sample))
    means.sort()
    return {"low_95": means[int(.025 * len(means))], "high_95": means[int(.975 * len(means)) - 1]}


def _drawdown(returns):
    equity = peak = 0.0
    worst = 0.0
    for value in returns:
        equity += float(value or 0)
        peak = max(peak, equity)
        worst = min(worst, equity - peak)
    return worst


def return_summary(rows):
    settled = [r for r in rows if (r.get("evaluation") or {}).get("outcome") in ("WIN", "LOSS", "PUSH")]
    returns = [float((r.get("evaluation") or {}).get("paper_pnl") or (1 if (r.get("evaluation") or {}).get("outcome") == "WIN" else -1 if (r.get("evaluation") or {}).get("outcome") == "LOSS" else 0)) for r in settled]
    if not settled:
        return {"available": False, "sample_N": 0, "status": "MODEL_ONLY", "mean_return": None}
    wins = sum((r.get("evaluation") or {}).get("outcome") == "WIN" for r in settled)
    losses = sum((r.get("evaluation") or {}).get("outcome") == "LOSS" for r in settled)
    pushes = sum((r.get("evaluation") or {}).get("outcome") == "PUSH" for r in settled)
    n = len(settled)
    return {"available": n >= 20, "sample_N": n, "status": governance(n),
            "mean_return": _mean(returns) if n >= 20 else None,
            "median_return": statistics.median(returns) if n >= 20 else None,
            "bootstrap_ci_95": _bootstrap_mean(returns) if n >= 20 else None,
            "max_drawdown": _drawdown(returns) if n >= 20 else None,
            "wins": wins, "losses": losses, "pushes": pushes,
            "hit_rate_ex_push": wins / (wins + losses) if wins + losses else None,
            "source": "SAME_TYPE_FORWARD_NATIVE_OOS_ONLY" if n >= 20 else "NO_EMPIRICAL_ESTIMATE_N_LT_20"}


def _empirical_pool(records, record):
    # A signal's own settlement is never allowed to train its empirical
    # expected-return annotation.
    records = [r for r in records if r.get("prediction_id") != record.get("prediction_id")]
    market = record.get("market_type")
    league = record.get("league")
    regime = record.get("season_regime") or "REGIME_UNKNOWN"
    exact = [r for r in records if r.get("market_type") == market and r.get("league") == league and (r.get("season_regime") or "REGIME_UNKNOWN") == regime]
    if len(exact) >= 20:
        return exact, "EXACT_MATCH"
    same_market_regime = [r for r in records if r.get("market_type") == market and (r.get("season_regime") or "REGIME_UNKNOWN") == regime]
    if len(same_market_regime) >= 20:
        return same_market_regime, "FALLBACK_MARKET_REGIME"
    same_market = [r for r in records if r.get("market_type") == market]
    if len(same_market) >= 20:
        return same_market, "FALLBACK_MARKET_ONLY"
    return exact, "EXACT_MATCH_INSUFFICIENT"


def _calibration(rows):
    buckets = defaultdict(list)
    for row in rows:
        ev = row.get("evaluation") or {}
        if ev.get("outcome") not in ("WIN", "LOSS"):
            continue
        p = row.get("p_win")
        push = row.get("p_push") or 0
        if p is None:
            continue
        p = float(p) / max(1e-12, 1 - float(push))
        buckets[probability_bucket(p)].append((p, 1.0 if ev["outcome"] == "WIN" else 0.0))
    output = {}
    for bucket, vals in sorted(buckets.items()):
        n = len(vals); avg_p = _mean([x[0] for x in vals]); avg_y = _mean([x[1] for x in vals])
        brier = _mean([(x - y) ** 2 for x, y in vals])
        logloss = _mean([-math.log(min(max(x, 1e-12), 1 - 1e-12)) if y else -math.log(min(max(1 - x, 1e-12), 1 - 1e-12)) for x, y in vals])
        output[bucket] = {"N": n, "predicted": avg_p, "actual": avg_y, "calibration_gap": avg_p - avg_y,
                          "brier": brier, "log_loss": logloss, "overconfidence": bool(n >= 20 and avg_p - avg_y >= .05)}
    eligible = [v for v in output.values() if v["N"]]
    total = sum(v["N"] for v in eligible)
    ece = sum(v["N"] * abs(v["calibration_gap"]) for v in eligible) / total if total else None
    return {"status": "VALIDATED" if total >= 100 else "PROVISIONAL" if total >= 20 else "UNVALIDATED",
            "N": total, "buckets": output, "Brier": _mean([v["brier"] for v in eligible]) if eligible else None,
            "LogLoss": _mean([v["log_loss"] for v in eligible]) if eligible else None, "ECE": ece,
            "overconfidence_flag": any(v["overconfidence"] for v in eligible)}


def comparable_edge_row(record, annotation=None):
    edge = selected_side_edge(record)
    ann = annotation or {}
    return {"game_id": record.get("event_id"), "league": record.get("league"), "market_type": record.get("market_type"),
            "home_team": record.get("team1"), "away_team": record.get("team2"), "start_time": record.get("tip_at"),
            "pricing_mode": "MODEL_IMPLIED", "market_line": record.get("line"),
            "raw_fair_line": record.get("fair_margin") if record.get("market_type") == "SPREAD" else record.get("fair_total"),
            "raw_edge_points": edge, "calibrated_fair_line": None, "calibrated_edge_points": None,
            "adjusted_probability": ann.get("calibrated_probability"), "adjusted_EV": record.get("entry_ev"),
            "residual_scale": record.get("residual_scale"), "league_residual_multiplier": 1.0,
            "meta_confidence": record.get("data_quality"), "model_weight": None, "market_weight": None,
            "data_quality": record.get("data_quality"), "evidence_status": record.get("probability_status"),
            "execution_score": record.get("entry_ev"), "edge_retention_ratio": None,
            "primary_final_reason": record.get("execution_action"), "secondary_warnings": record.get("warnings", []),
            "selected_side_line_edge_points": edge, "raw_team1_line_gap": record.get("raw_team1_line_gap")}


def build_validation(records):
    settled = [r for r in records if r.get("execution_triggered") and (r.get("evaluation") or {}).get("outcome") in ("WIN", "LOSS", "PUSH")]
    annotations = {}
    for record in records:
        pool, source = _empirical_pool(settled, record)
        summary = return_summary(pool)
        edge = selected_side_edge(record)
        ann = {"model_implied_ev": record.get("entry_ev"), "model_ev_status": "MODEL_IMPLIED_EV_ONLY",
               "empirical_expected_return": summary, "empirical_source": source,
               "selected_side_line_edge_points": edge, "raw_team1_line_gap": record.get("raw_team1_line_gap"),
               "probability_source": record.get("probability_source"), "p_win": record.get("p_win"),
               "p_push": record.get("p_push"), "p_loss": record.get("p_loss"),
               "residual_source": record.get("residual_source"), "residual_N": record.get("residual_N"),
               "df": record.get("df"), "scale": record.get("residual_scale"),
               "residual_fit_status": governance(record.get("residual_N") or 0),
               "fair_center_uncertainty": record.get("fair_center_uncertainty"),
               "outcome_residual": residual(record),
               "home_court_status": "HOME_COURT_NOT_MODELLED"}
        annotations[record.get("prediction_id")] = ann
    residual_groups = defaultdict(list)
    for r in settled:
        x = residual(r)
        if x is not None:
            residual_groups[(r.get("market_type"), r.get("league"), r.get("season_regime") or "REGIME_UNKNOWN")].append(x)
    residual_diag = {}
    for key, vals in sorted(residual_groups.items(), key=lambda x: str(x[0])):
        residual_diag["|".join(map(str, key))] = {"market_type": key[0], "league": key[1], "season_regime": key[2],
            "N": len(vals), "source": "FORWARD_NATIVE_OOS_RESIDUALS", "mean_bias": _mean(vals),
            "MAE": _mean([abs(x) for x in vals]), "RMSE": _rmse(vals), "governance": governance(len(vals)),
            "note": "Descriptive only; no automatic tuning."}
    return_groups = defaultdict(list)
    for r in settled:
        key = (r.get("market_type"), r.get("league"), r.get("season_regime") or "REGIME_UNKNOWN",
               r.get("selection"), ("FAVORITE" if float(r.get("line")) < 0 else "UNDERDOG") if r.get("market_type") == "SPREAD" and r.get("line") is not None else "NOT_APPLICABLE",
               ("DEEP_SPREAD" if abs(float(r.get("line"))) >= 15 else "NORMAL_SPREAD") if r.get("market_type") == "SPREAD" and r.get("line") is not None else "NOT_APPLICABLE",
               probability_bucket(r.get("p_win")), edge_bucket(selected_side_edge(r)))
        return_groups[key].append(r)
    return_group_diag = {}
    for key, vals in sorted(return_groups.items(), key=lambda x: str(x[0])):
        return_group_diag["|".join(map(str, key))] = dict(return_summary(vals),
            market_type=key[0], league=key[1], season_regime=key[2], direction=key[3],
            favorite_underdog=key[4], spread_depth=key[5], probability_bucket=key[6], edge_bucket=key[7])
    calibration = {k: _calibration([r for r in settled if r.get("market_type") == k]) for k in ("SPREAD", "TOTAL")}
    return {"schema_version": 1, "generated_at": stamp(), "sample_scope": "TRIGGERED_FORWARD_NATIVE_FIRST_WRITE_OOS_ONLY",
            "sample_N": len(settled), "governance": governance(len(settled)), "record_annotations": annotations,
            "residual_diagnostics": residual_diag, "return_group_diagnostics": return_group_diag,
            "probability_calibration": calibration,
            "model_implied_ev": {"definition": "p_win*(decimal_odds-1)-p_loss; push is zero", "count": len(records)},
            "empirical_expected_return": {"definition": "same-type OOS realized return; never inferred from recent W/L", "sample_N": len(settled), "governance": governance(len(settled))},
            "rules": ["N<20 is MODEL_ONLY and empirical return is unavailable.", "Fallbacks disclose source and sample N.", "No parameter tuning or historical first-write mutation.", "Fair-center uncertainty is separate from outcome residual uncertainty."]}


def write_validation_artifacts(root, asof, payload, records):
    root = Path(root); diag = root / "diagnostics"; diag.mkdir(parents=True, exist_ok=True)
    atomic(diag / "probability_ev_empirical_validation.json", payload)
    rows = [comparable_edge_row(r, (payload.get("record_annotations") or {}).get(r.get("prediction_id"))) for r in records]
    csv_path = diag / f"comparable_edge_{str(asof)[:10]}.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["game_id"])
        writer.writeheader()
        for row in rows:
            writer.writerow({k: ";".join(map(str, v)) if isinstance(v, list) else v for k, v in row.items()})
    md = ["# Probability / EV / Empirical Validation", "", f"生成时间：{payload.get('generated_at')}",
          "", "## 结论", "", f"- 样本范围：{payload.get('sample_scope')}", f"- 触发且已结算样本：{payload.get('sample_N', 0)}",
          f"- 经验收益治理：`{payload.get('governance')}`；N<20 时不提供经验收益点估计。",
          "- 模型隐含 EV 与经验实现收益严格分栏；本报告不改变首写账本、不自动调参。", "",
          "## 残差与概率健康", "", "```json", __import__('json').dumps({"residual_diagnostics": payload.get("residual_diagnostics"), "probability_calibration": payload.get("probability_calibration")}, ensure_ascii=False, indent=2), "```", "",
          "## 逐场字段", "", "每场记录同时保留 raw_team1_line_gap 与 selected_side_line_edge_points；后者大于 0 才表示对所选方向有利。Fair Center 不确定性不等同于比赛结果残差。", "",
          "## 文件", "", f"- [Comparable Edge CSV]({csv_path})", "- `probability_ev_empirical_validation.json`", "- `uncertainty_audit_YYYYMMDD.json`"]
    (diag / "probability_ev_empirical_validation.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    (diag / "spread_probability_ev_validation.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    atomic(diag / f"uncertainty_audit_{str(asof)[:10].replace('-', '')}.json", {"generated_at": stamp(), "asof": asof,
        "fair_center_vs_outcome_residual": "SEPARATE", "home_court": "HOME_COURT_NOT_MODELLED",
        "residual_diagnostics": payload.get("residual_diagnostics", {}), "no_auto_tuning": True})
    return rows
