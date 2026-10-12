"""Read-only P0 structural audits for the existing Forward Native ledger.

This module never changes a frozen forecast, decision, quote, settlement, or
model parameter.  It creates append-only diagnostic output for direction bias,
margin compression, probability consistency, deep-spread concentration, and
market freshness.  Missing calibration layers remain explicit nulls.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import timedelta
from math import sqrt
from pathlib import Path

from .common import atomic, iso, load, stamp


BUCKETS = ((0, 5, "0-5"), (5, 10, "5.5-9.5"), (10, 15, "10-14.5"), (15, float("inf"), "15+"))
PREDICTED_BUCKETS = ((0, 3, "0-3"), (3, 6, "3-6"), (6, 9, "6-9"),
                     (9, 12, "9-12"), (12, 15, "12-15"), (15, 20, "15-20"),
                     (20, float("inf"), "20+"))


def _number(value):
    return float(value) if isinstance(value, (int, float)) else None


def _canonical_market_line(selected):
    """Return team1's market spread from the selected-side line."""
    line = _number((selected or {}).get("line"))
    if line is None:
        return None
    return line if selected.get("selection") == "TEAM1" else -line


def _first_write_records(root):
    root = Path(root)
    settlements = {p.stem: load(p, {}) for p in (root / "ledger" / "repair_v22_settlements").glob("*.json")}
    chosen = {}
    decisions_by_pid = {}
    for path in sorted((root / "ledger" / "repair_v22").glob("*/decision_*.json")):
        decision = load(path, {})
        if decision.get("archive_type") != "FORWARD_NATIVE":
            continue
        pid = decision.get("prediction_id")
        selected = decision.get("selected")
        if not pid or not selected or not decision.get("comparison_ready"):
            continue
        decisions_by_pid[pid] = decision
        inp = load(path.with_name("input_" + pid + ".json"), {})
        forecast = load(path.with_name("forecast_" + pid + ".json"), {})
        event = inp.get("event") or {}
        if not event.get("event_id") and not event.get("event_id"):
            continue
        key = (event.get("event_id"), selected.get("market_type"))
        row = {
            "prediction_id": pid,
            "event_id": event.get("event_id"),
            "first_write_at": decision.get("asof"),
            "tip_at": event.get("tip_at"),
            "bj_date": event.get("bj_date"),
            "league": event.get("league"),
            "league_family": event.get("league_family"),
            "league_tier": forecast.get("league_tier"),
            "team1": event.get("team1_name"),
            "team2": event.get("team2_name"),
            "market_type": selected.get("market_type"),
            "selection": selected.get("selection"),
            "line": _number(selected.get("line")),
            "market_spread": _canonical_market_line(selected) if selected.get("market_type") == "SPREAD" else None,
            "decimal_odds": _number(selected.get("decimal_odds")),
            "raw_margin": _number(forecast.get("mu_raw")),
            "raw_total": _number(forecast.get("total_raw")),
            "raw_probability": _number(selected.get("p_win")),
            "push_probability": _number(selected.get("p_push")),
            "loss_probability": _number(selected.get("p_loss")),
            "expected_value": _number(selected.get("ev")),
            "triggered": bool(decision.get("triggered")),
            "settlement": settlements.get(pid),
            "counterfactual": None,
            "pricing_decomposition": selected.get("pricing_decomposition") or forecast.get("fair_spread_decomposition"),
        }
        # The earliest decision is the immutable statistical record. Later
        # captures remain in the ledger but cannot create extra samples.
        old = chosen.get(key)
        if old is None or str(row.get("first_write_at") or "") < str(old.get("first_write_at") or ""):
            chosen[key] = row
    rows = list(chosen.values())
    for row in rows:
        if row["market_type"] != "SPREAD":
            continue
        d = decisions_by_pid.get(row["prediction_id"])
        if d:
            candidates = d.get("comparison_rows") or []
            others = [x for x in candidates if x.get("market_type") == "SPREAD"
                      and x.get("quote_id") == (d.get("selected") or {}).get("quote_id")
                      and x.get("selection") != row.get("selection")]
            if others:
                row["counterfactual"] = {
                    "selection": others[0].get("selection"),
                    "line": others[0].get("line"),
                    "cover_probability": others[0].get("p_win"),
                    "expected_value": others[0].get("ev"),
                    "decimal_odds": others[0].get("decimal_odds"),
                }
    return sorted(rows, key=lambda x: str(x.get("first_write_at") or ""))


def _direction_summary(rows):
    spread = [r for r in rows if r.get("market_type") == "SPREAD" and r.get("line") is not None]
    favorite = sum(r["line"] < 0 for r in spread)
    underdog = sum(r["line"] > 0 for r in spread)
    total = favorite + underdog
    return {
        "n": len(spread), "favorite_count": favorite, "underdog_count": underdog,
        "favorite_share": favorite / total if total else None,
        "underdog_share": underdog / total if total else None,
        "alerts": (["SEVERE_UNDERDOG_DIRECTION_BIAS"] if total >= 20 and underdog / total >= .95 else
                   ["UNDERDOG_DIRECTION_BIAS"] if total >= 20 and underdog / total >= .80 else []),
    }


def _regression(rows):
    pts = [(r["raw_margin"], (r["settlement"] or {}).get("score1"),
            (r["settlement"] or {}).get("score2")) for r in rows
           if r.get("market_type") == "SPREAD" and r.get("raw_margin") is not None
           and isinstance((r.get("settlement") or {}).get("score1"), (int, float))
           and isinstance((r.get("settlement") or {}).get("score2"), (int, float))]
    pts = [(float(x), float(a) - float(b)) for x, a, b in pts]
    if not pts:
        return {"n": 0, "intercept": None, "slope": None, "r2": None, "mae": None, "rmse": None, "mean_bias": None}
    if len(pts) == 1:
        xbar, ybar = pts[0]
        return {"n": 1, "intercept": ybar, "slope": None, "r2": None, "mae": 0.0, "rmse": 0.0, "mean_bias": 0.0}
    xbar = sum(x for x, _ in pts) / len(pts); ybar = sum(y for _, y in pts) / len(pts)
    sxx = sum((x - xbar) ** 2 for x, _ in pts)
    slope = sum((x - xbar) * (y - ybar) for x, y in pts) / sxx if sxx else None
    intercept = ybar - slope * xbar if slope is not None else ybar
    pred = [intercept + slope * x if slope is not None else ybar for x, _ in pts]
    errors = [y - p for (_, y), p in zip(pts, pred)]
    sse = sum(e * e for e in errors); sst = sum((y - ybar) ** 2 for _, y in pts)
    return {"n": len(pts), "intercept": intercept, "slope": slope,
            "r2": 1 - sse / sst if sst else None,
            "mae": sum(abs(e) for e in errors) / len(errors),
            "rmse": sqrt(sse / len(errors)), "mean_bias": sum(errors) / len(errors)}


def _bucket(value, spec):
    if value is None: return None
    for low, high, label in spec:
        if low <= abs(float(value)) < high:
            return label
    return None


def _bucket_stats(rows):
    out = {}
    for low, high, label in BUCKETS:
        group = [r for r in rows if r.get("market_type") == "SPREAD" and r.get("line") is not None
                 and low <= abs(r["line"]) < high]
        outcomes = Counter((r.get("settlement") or {}).get("outcome", "PENDING") for r in group)
        pnl = [float((r.get("settlement") or {}).get("paper_pnl")) for r in group
               if isinstance((r.get("settlement") or {}).get("paper_pnl"), (int, float))]
        errors = []
        for r in group:
            s = r.get("settlement") or {}
            if r.get("raw_margin") is not None and isinstance(s.get("score1"), (int, float)) and isinstance(s.get("score2"), (int, float)):
                errors.append((s["score1"] - s["score2"]) - r["raw_margin"])
        out[label] = {"n": len(group), "W": outcomes["WIN"], "L": outcomes["LOSS"], "P": outcomes["PUSH"],
                      "pending": outcomes["PENDING"], "pnl": sum(pnl),
                      "roi": sum(pnl) / len(pnl) if pnl else None,
                      "prediction_bias": sum(errors) / len(errors) if errors else None,
                      "mae": sum(abs(x) for x in errors) / len(errors) if errors else None,
                      "small_sample_outlier": len(group) < 20 and label == "15+"}
    return out


def _pnl_concentration(rows):
    settled = [r for r in rows if isinstance((r.get("settlement") or {}).get("paper_pnl"), (int, float))]
    settled.sort(key=lambda r: float(r["settlement"]["paper_pnl"]), reverse=True)
    total = sum(float(r["settlement"]["paper_pnl"]) for r in settled)
    def share(n): return sum(float(r["settlement"]["paper_pnl"]) for r in settled[:n]) / total if total else None
    deep = [r for r in settled if r.get("market_type") == "SPREAD" and r.get("line") is not None and abs(r["line"]) >= 10]
    wnba = [r for r in settled if "WNBA" in str(r.get("league_family") or r.get("league") or "").upper()]
    return {"settled_n": len(settled), "total_pnl": total, "top_3_contribution": share(3),
            "top_5_contribution": share(5), "deep_spread_contribution": sum(float(r["settlement"]["paper_pnl"]) for r in deep),
            "wnba_contribution": sum(float(r["settlement"]["paper_pnl"]) for r in wnba),
            "flag": "PNL_CONCENTRATION_HIGH" if total and (share(3) or 0) >= .75 else None}


def _probability_consistency(rows, root):
    checked = 0; failed = 0
    for r in rows:
        if r.get("market_type") != "SPREAD": continue
        a, b, p = r.get("raw_probability"), r.get("loss_probability"), r.get("push_probability")
        if None in (a, b, p): continue
        checked += 1
        if abs(float(a) + float(b) + float(p) - 1.0) > .01: failed += 1
    return {"checked": checked, "failed": failed, "status": "PASS" if failed == 0 else "FAIL", "tolerance": .01,
            "note": "概率只做一致性审计，不改变方向或门槛。"}


def _freshness(current_rows):
    grouped = defaultdict(lambda: {"market_found": 0, "fresh": 0, "ages": []})
    for row in current_rows or []:
        event = row.get("event") or {}; key = event.get("league_family") or event.get("league") or "UNKNOWN"
        quotes = (row.get("market") or {}).get("quotes") or []
        states = (row.get("market") or {}).get("quote_states") or []
        if not quotes: continue
        grouped[key]["market_found"] += 1
        if any(s.get("fresh_observation") for s in states): grouped[key]["fresh"] += 1
        grouped[key]["ages"].extend(float(s["age_seconds"]) / 60 for s in states if isinstance(s.get("age_seconds"), (int, float)))
    out = {}
    for league, v in grouped.items():
        ages = sorted(v["ages"])
        p90 = ages[min(len(ages) - 1, max(0, int(len(ages) * .9) - 1))] if ages else None
        out[league] = {"market_found": v["market_found"], "fresh": v["fresh"],
                       "fresh_rate": v["fresh"] / v["market_found"] if v["market_found"] else None,
                       "median_market_age_minutes": ages[len(ages) // 2] if ages else None,
                       "p90_market_age_minutes": p90,
                       "alert": "LEAGUE_MARKET_FRESHNESS_ANOMALY" if v["market_found"] >= 5 and v["fresh"] / v["market_found"] < .2 else None}
    return out


def build_p0_bias_audit(root, asof, day=None, current_rows=None):
    rows = _first_write_records(root)
    spread = [r for r in rows if r.get("market_type") == "SPREAD"]
    settled_spread = [r for r in spread if isinstance((r.get("settlement") or {}).get("score1"), (int, float))]
    windows = {}
    ordered = sorted(spread, key=lambda r: str(r.get("first_write_at") or ""), reverse=True)
    for name, subset in (("last_10", ordered[:10]), ("last_20", ordered[:20]), ("last_50", ordered[:50]), ("all_forward_native", spread)):
        windows[name] = _direction_summary(subset)
    cutoff = iso(asof)
    rolling = [r for r in spread if r.get("first_write_at") and cutoff - iso(r["first_write_at"]) <= timedelta(days=7)]
    windows["rolling_7d"] = _direction_summary(rolling)
    wnba = [r for r in spread if "WNBA" in str(r.get("league_family") or r.get("league") or "").upper()]
    groups = {
        "WNBA": wnba, "NBA": [r for r in spread if str(r.get("league_family") or r.get("league") or "").upper() == "NBA"],
        "TIER_1": [r for r in spread if r.get("league_tier") == "TIER_1"],
        "NORMAL_SPREAD": [r for r in spread if r.get("market_spread") is not None and abs(r["market_spread"]) < 10],
        "DEEP_SPREAD": [r for r in spread if r.get("market_spread") is not None and abs(r["market_spread"]) >= 10],
    }
    regression = {name: _regression(group) for name, group in groups.items()}
    regression["status"] = "MARGIN_COMPRESSION_DETECTED" if regression.get("DEEP_SPREAD", {}).get("slope") is not None and regression["DEEP_SPREAD"]["slope"] > 1.15 else "NOT_PROVEN"
    pred_buckets = {}
    for _, _, label in PREDICTED_BUCKETS:
        group = [r for r in settled_spread if r.get("raw_margin") is not None and _bucket(r["raw_margin"], PREDICTED_BUCKETS) == label]
        actual = [float(r["settlement"]["score1"]) - float(r["settlement"]["score2"]) for r in group]
        pred_buckets[label] = {"n": len(group), "predicted_margin": sum(r["raw_margin"] for r in group) / len(group) if group else None,
                               "actual_average_margin": sum(actual) / len(actual) if actual else None,
                               "bias": (sum(actual) / len(actual) - sum(r["raw_margin"] for r in group) / len(group)) if group else None,
                               "mae": sum(abs(a - r["raw_margin"]) for a, r in zip(actual, group)) / len(group) if group else None}
    result = {
        "schema_version": 1, "generated_at": stamp(), "asof": asof, "day_bj": day,
        "read_only": True, "real_execution_allowed": False,
        "sample_counts": {"all_first_write_event_markets": len(rows), "spread": len(spread), "settled_spread": len(settled_spread), "wnba_spread": len(wnba)},
        "direction_bias": {"all_forward_native": windows["all_forward_native"], "windows": windows,
                           "wnba": _direction_summary(wnba)},
        "margin_calibration": {"method": "FORWARD_NATIVE_DESCRIPTIVE_REGRESSION", "oos_walk_forward_status": "NOT_ENOUGH_SEPARATE_OOS_WINDOWS",
                                "groups": regression, "predicted_vs_actual_buckets": pred_buckets,
                                "center_bias_status": regression["status"],
                                "note": "仅审计 raw independent margin；未回写 Fair Spread、阈值、残差或 Champion。"},
        "deep_spread_audit": _bucket_stats(spread),
        "pnl_concentration": _pnl_concentration(rows),
        "probability_consistency": _probability_consistency(rows, root),
        "market_freshness": _freshness(current_rows),
        "ridge_audit": {"model_versions": sorted({(r.get("pricing_decomposition") or {}).get("model_version") for r in rows if (r.get("pricing_decomposition") or {}).get("model_version")}),
                        "regularization_audit_status": "REQUIRES_OOS_EXPERIMENT",
                        "center_bias_not_solved_by_residual_scale": True},
        "challengers": {"status": "NOT_PROMOTED", "required": ["MEAN_MARGIN_CALIBRATION", "DEEP_SPREAD_CALIBRATION", "RIDGE_REGULARIZATION", "MARKET_PRIOR_BLEND"],
                        "promotion_gate": "Separate OOS/prospective evaluation required; no automatic Champion change."},
        "records": rows,
    }
    out = Path(root) / "diagnostics"
    atomic(out / ("p0_bias_audit_" + str(day or "latest") + ".json"), result)
    lines = ["# P0 结构审计（只读）", "", f"- 生成时间：{result['generated_at']}", f"- Forward Native Spread 首写：{len(spread)}", f"- WNBA Spread 首写：{len(wnba)}", "- 真实执行：关闭", "", "## 方向偏置", ""]
    for name, value in windows.items(): lines.append(f"- {name}: N={value['n']}，Favorite={value['favorite_count']}，Underdog={value['underdog_count']}，Underdog Share={value['underdog_share']}")
    lines += ["", "## 校准审计", "", f"- 状态：{regression['status']}", f"- WNBA slope：{regression['WNBA'].get('slope')}", f"- Normal slope：{regression['NORMAL_SPREAD'].get('slope')}", f"- Deep slope：{regression['DEEP_SPREAD'].get('slope')}", "- 该文件只读，不修改历史预测、Fair Spread、阈值或 Champion。", ""]
    (out / ("p0_bias_audit_" + str(day or "latest") + ".md")).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return result
