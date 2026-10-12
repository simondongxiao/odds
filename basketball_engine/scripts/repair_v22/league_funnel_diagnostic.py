from __future__ import annotations

"""League-level, read-only diagnostics for the basketball pricing funnel.

This module deliberately reports emitted production fields only.  It never
changes a price, Fair line, threshold, residual multiplier, Champion value,
first-write ledger entry, or execution flag.
"""

import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


WINDOWS = ("today", "rolling_3d", "rolling_7d", "all_forward_native", "last_20_comparable", "last_50_comparable")
SUPPRESSION_REASONS = (
    "RESIDUAL_SCALE_SUPPRESSION", "MEAN_CALIBRATION_SUPPRESSION",
    "META_CALIBRATION_SUPPRESSION", "MARKET_WEIGHT_SUPPRESSION",
    "COLD_START_UNCERTAINTY", "PROBABILITY_THRESHOLD", "NEGATIVE_EV",
    "EVIDENCE_BLOCK", "EXECUTION_BLOCK", "PRICE_EXHAUSTED", "OTHER",
)
MIN_DIAGNOSTIC_SAMPLE = 10


def _num(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _date(value):
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        return None


def league_bucket(event: dict[str, Any]) -> str:
    raw = " ".join(str(event.get(k) or "") for k in ("league", "league_family", "competition_key", "region")).upper()
    if "WNBA" in raw or "WOMEN'S NATIONAL BASKETBALL ASSOCIATION" in raw:
        return "WNBA"
    if "EUROLEAGUE" in raw or "欧洲篮球联赛" in raw:
        return "EuroLeague"
    if "EUROCUP" in raw or "欧洲杯" in raw:
        return "EuroCup"
    if "NBL_AU" in raw or "AUSTRALIA" in raw or "澳大利亚" in raw:
        return "Australia NBL"
    if "B_LEAGUE" in raw or "JAPAN" in raw or "日本" in raw:
        return "Japan B League"
    if "KBL" in raw or "KOREA" in raw or "韩国" in raw:
        return "KBL"
    if "CBA" in raw or "CHINA" in raw or "中国" in raw:
        return "China"
    if "FIBA" in raw or "NATIONAL" in raw or "国家队" in raw:
        return "FIBA / National Team"
    if "LATIN" in raw or "AMERICAS" in raw or any(x in raw for x in ("CHILE", "MEXICO", "BRAZIL", "ARGENTINA", "智利", "墨西哥")):
        return "Latin America"
    if "EUROPE" in raw or "欧洲" in raw:
        return "European domestic"
    if "NBA" in raw:
        return "NBA"
    return str(event.get("league") or event.get("league_family") or "Other")


def _group(bucket: str) -> str:
    return "WNBA" if bucket == "WNBA" else "NON_WNBA"


def _explicit(pricing: dict[str, Any], names: tuple[str, ...]):
    for name in names:
        value = pricing.get(name)
        if _num(value) is not None:
            return float(value), name
    return None, "NOT_EMITTED"


def probability_waterfall(pricing: dict[str, Any], selected: dict[str, Any]) -> dict[str, Any]:
    aliases = {
        "raw_probability": ("raw_probability", "raw_cover_probability", "raw_win_probability"),
        "after_mean_calibration": ("after_mean_calibration", "mean_calibrated_probability", "mean_calibration_probability"),
        "after_residual_scale": ("after_residual_scale", "residual_scaled_probability", "residual_probability"),
        "after_league_calibration": ("after_league_calibration", "league_calibrated_probability", "league_calibration_probability"),
        "after_cold_start_adjustment": ("after_cold_start_adjustment", "cold_start_adjusted_probability"),
        "after_meta_calibration": ("after_meta_calibration", "meta_calibrated_probability", "meta_calibration_probability"),
    }
    result = {}
    emitted = {}
    missing = []
    for stage, names in aliases.items():
        value, source = _explicit(pricing, names)
        result[stage] = value
        emitted[stage] = source
        if value is None:
            missing.append(stage)
    # p_win is the production selected probability. It is intentionally used
    # only as the final probability; it is not relabeled as raw probability.
    result["final_probability"] = _num(selected.get("p_win"))
    emitted["final_probability"] = "selected.p_win" if result["final_probability"] is not None else "NOT_EMITTED"
    if result["final_probability"] is None:
        missing.append("final_probability")
    return {"values": result, "emitted_from": emitted, "missing_stages": missing,
            "status": "COMPLETE" if not missing else "PARTIAL_FIELDS"}


def _record_from_row(row, market, diagnose_market, comparable_fn):
    event = row.get("event") or {}
    pricing = row.get("pricing") or {}
    decision = ((row.get("execution") or {}).get("market_decisions") or {}).get(market) or {}
    diag = diagnose_market(row, market)
    rec = dict(diag)
    rec.update({
        "event_id": row.get("id") or event.get("event_id"),
        "canonical_event_id": event.get("canonical_event_id") or event.get("event_id"),
        "league": event.get("league"), "league_family": event.get("league_family"),
        "region": event.get("region"), "league_tier": pricing.get("league_tier") or event.get("league_tier"),
        "league_bucket": league_bucket(event), "league_group": _group(league_bucket(event)),
        "tip_time_bj": event.get("tip_time_bj") or event.get("tip_at"),
        "date_bj": event.get("bj_date") or str(event.get("tip_time_bj") or event.get("tip_at") or "")[:10],
        "team1": event.get("team1_name"), "team2": event.get("team2_name"),
        "archive_type": row.get("archive_type"),
        "first_write": bool((row.get("execution") or {}).get("signal_layer", {}).get("first_write")),
        "asof": (row.get("execution") or {}).get("asof") or pricing.get("asof"),
        "pricing_mode": (pricing.get("pricing_mode") or pricing.get("pricing_state") or
                         ("COLD_START" if pricing.get("cold_start_priceable") else "UNKNOWN")),
        "pricing_state": pricing.get("pricing_state"),
        "cold_start": bool(pricing.get("cold_start_priceable") or pricing.get("cold_start_residual_multiplier") not in (None, 1, 1.0)),
        "prior_only": bool(pricing.get("prior_only_price")),
        "native": bool(pricing.get("research_priceable") and not pricing.get("prior_only_price") and not pricing.get("cold_start_priceable")),
        "cold_start_residual_multiplier": pricing.get("cold_start_residual_multiplier"),
        "residual_scale_multiplier": pricing.get("residual_scale_multiplier"),
        "league_residual_multiplier": pricing.get("league_residual_multiplier"),
        "base_residual_scale": pricing.get("base_residual_scale") or pricing.get("base_residual_multiplier"),
        "tier_residual_scale": pricing.get("tier_residual_scale") or pricing.get("tier_residual_multiplier"),
        "market_weight": pricing.get("market_weight"), "model_weight": pricing.get("model_weight"),
        "probability_calibration_status": pricing.get("probability_calibration_status"),
        "pricing_blockers": list(pricing.get("blockers") or []),
        "evidence_blockers": list((pricing.get("total_diagnostic") or {}).get("hard_blockers") or []),
        "decision_blockers": list(decision.get("blockers") or diag.get("decision_blockers") or []),
        "waterfall": probability_waterfall(pricing, decision.get("selected") or {}),
        "comparable": comparable_fn(diag),
    })
    return rec


def _load_older_rows(root: Path, day: str):
    data_dir = root / "dashboard_v2" / "data"
    rows = []
    if not data_dir.exists():
        return rows
    for path in sorted(data_dir.glob("*.json")):
        if path.stem >= day or len(path.stem) != 10:
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for row in payload.get("events", []) if isinstance(payload, dict) else []:
            if isinstance(row, dict) and row.get("archive_type") == "FORWARD_NATIVE":
                rows.append(row)
    return rows


def _dedupe(records):
    selected = {}
    for record in records:
        key = (record.get("canonical_event_id") or record.get("event_id"), record.get("market_type"))
        if not key[0]:
            continue
        prior = selected.get(key)
        if prior is None or str(record.get("asof") or record.get("tip_time_bj") or "") < str(prior.get("asof") or prior.get("tip_time_bj") or ""):
            selected[key] = record
    return list(selected.values())


def _count_rate(numerator, denominator):
    return round(numerator / denominator, 4) if denominator else None


def _window_stats(records):
    stages = ("discovered", "market_found", "fresh_market", "research_priceable", "market_comparable", "raw_edge_found", "calibrated_edge_found", "evidence_pass", "execution_pass", "shadow_triggered")
    counts = {stage: 0 for stage in stages}
    for record in records:
        metrics = record.get("edge_metrics") or {}
        flags = {
            "discovered": True,
            "market_found": record.get("market_found", False),
            "fresh_market": record.get("fresh_market_found", False),
            "research_priceable": record.get("priceable", False),
            "market_comparable": record.get("comparable", False),
            "raw_edge_found": metrics.get("raw_edge_found", False),
            "calibrated_edge_found": metrics.get("calibrated_edge_found", False),
            "evidence_pass": metrics.get("evidence_pass", False),
            "execution_pass": metrics.get("execution_pass", False),
            "shadow_triggered": record.get("status") == "SHADOW_TRIGGERED",
        }
        for stage, passed in flags.items():
            counts[stage] += int(bool(passed))
    denominators = {
        "discovered": "discovered", "market_found": "discovered", "fresh_market": "market_found",
        "research_priceable": "fresh_market", "market_comparable": "research_priceable",
        "raw_edge_found": "market_comparable", "calibrated_edge_found": "raw_edge_found",
        "evidence_pass": "calibrated_edge_found", "execution_pass": "evidence_pass",
        "shadow_triggered": "execution_pass",
    }
    rates = {stage: _count_rate(counts[stage], counts[denominator]) for stage, denominator in denominators.items()}
    comparable = counts["market_comparable"]
    if not records:
        state = "INSUFFICIENT_SAMPLE"
    elif counts["market_found"] == 0:
        state = "NO_MARKET"
    elif counts["research_priceable"] == 0 or comparable == 0:
        state = "NOT_PRICEABLE"
    elif counts["shadow_triggered"]:
        state = "SHADOW_ACTIVE"
    elif counts["raw_edge_found"] == 0:
        state = "NO_RAW_EDGE"
    elif counts["calibrated_edge_found"] < counts["raw_edge_found"]:
        state = "CALIBRATION_SUPPRESSED"
    elif counts["evidence_pass"] < counts["calibrated_edge_found"]:
        state = "EVIDENCE_SUPPRESSED"
    elif counts["execution_pass"] < counts["evidence_pass"]:
        state = "EXECUTION_SUPPRESSED"
    else:
        state = "HEALTHY_NO_OPPORTUNITY"
    return {"sample_size": len(records), "comparable_sample": comparable, "counts": counts, "rates": rates,
            "main_state": state, "sample_sufficiency": "SUFFICIENT" if comparable >= MIN_DIAGNOSTIC_SAMPLE else "INSUFFICIENT_SAMPLE",
            "minimum_diagnostic_sample": MIN_DIAGNOSTIC_SAMPLE}


def _reason(record):
    metrics = record.get("edge_metrics") or {}
    if not metrics.get("raw_edge_found") or record.get("status") == "SHADOW_TRIGGERED":
        return None
    blockers = set(record.get("decision_blockers") or []) | set(record.get("pricing_blockers") or []) | set(record.get("evidence_blockers") or [])
    if any("COLD_START" in x or "PRIOR" in x or "UNCERTAINTY" in x for x in blockers) or record.get("cold_start") or record.get("prior_only"):
        return "COLD_START_UNCERTAINTY"
    if "PRICE_EXHAUSTED" in blockers:
        return "PRICE_EXHAUSTED"
    if not metrics.get("evidence_pass"):
        return "EVIDENCE_BLOCK"
    if not metrics.get("execution_pass"):
        if "EXECUTION" in " ".join(blockers) or "MARKET_MOVED" in blockers:
            return "EXECUTION_BLOCK"
    if metrics.get("adjusted_ev") is not None and metrics.get("adjusted_ev") <= 0:
        return "NEGATIVE_EV"
    if metrics.get("adjusted_probability") is not None and metrics.get("adjusted_probability") < 0.55:
        return "PROBABILITY_THRESHOLD"
    if metrics.get("calibrated_edge_found") is False and metrics.get("calibrated_fair_line") is not None:
        source = str(metrics.get("calibration_source") or "").lower()
        if "meta" in source:
            return "META_CALIBRATION_SUPPRESSION"
        if "league" in source:
            return "MEAN_CALIBRATION_SUPPRESSION"
        return "RESIDUAL_SCALE_SUPPRESSION"
    mw, modelw = _num(record.get("market_weight")), _num(record.get("model_weight"))
    if mw is not None and modelw is not None and mw > modelw:
        return "MARKET_WEIGHT_SUPPRESSION"
    return "OTHER"


def _attribution(records):
    counter = Counter()
    by_league = defaultdict(Counter)
    by_market = defaultdict(Counter)
    for record in records:
        reason = _reason(record)
        if not reason:
            continue
        counter[reason] += 1
        by_league[record.get("league_bucket", "Other")][reason] += 1
        by_market[record.get("market_type", "UNKNOWN")][reason] += 1
    return {"overall": {k: counter.get(k, 0) for k in SUPPRESSION_REASONS},
            "by_league": {k: {x: c.get(x, 0) for x in SUPPRESSION_REASONS} for k, c in sorted(by_league.items())},
            "by_market": {k: {x: c.get(x, 0) for x in SUPPRESSION_REASONS} for k, c in sorted(by_market.items())}}


def _group_comparison(records):
    result = {}
    for group in ("WNBA", "NON_WNBA"):
        result[group] = _window_stats([r for r in records if r.get("league_group") == group])
    return result


def _mean(values):
    return round(sum(values) / len(values), 6) if values else None


def _median(values):
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    value = ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2
    return round(value, 6)


def _mode_stats(records):
    result = {}
    for mode in ("NATIVE", "COLD_START", "PRIOR_ONLY", "UNKNOWN"):
        subset = [r for r in records if ("PRIOR_ONLY" if r.get("prior_only") else "COLD_START" if r.get("cold_start") else "NATIVE" if r.get("native") else "UNKNOWN") == mode]
        ratios = [(r.get("edge_metrics") or {}).get("edge_retention_ratio") for r in subset]
        ratios = [x for x in ratios if _num(x) is not None]
        result[mode] = {"sample_size": len(subset), "comparable": sum(r.get("comparable", False) for r in subset),
                        "raw_edge": sum((r.get("edge_metrics") or {}).get("raw_edge_found", False) for r in subset),
                        "shadow": sum(r.get("status") == "SHADOW_TRIGGERED" for r in subset),
                        "mean_edge_retention": _mean(ratios), "compression_observations": len(ratios)}
    return result


def _residual_breakdown(records):
    fields = ("base_residual_scale", "tier_residual_scale", "league_residual_multiplier", "cold_start_residual_multiplier", "residual_scale_multiplier")
    result = {}
    for field in fields:
        values = [_num(r.get(field)) for r in records]
        values = [x for x in values if x is not None]
        result[field] = {"sample_size": len(values), "mean": _mean(values), "median": _median(values) if values else None,
                         "emitted": bool(values)}
    ratios = [(r.get("edge_metrics") or {}).get("edge_retention_ratio") for r in records]
    ratios = [x for x in ratios if _num(x) is not None]
    result["compression_effect"] = {"sample_size": len(ratios), "mean_retention": _mean(ratios),
                                     "compressed_le_30pct": sum(x <= 0.3 for x in ratios),
                                     "note": "只统计生产显式输出的 Fair line retention；没有用市场融合值反推残差阶段。"}
    return result


def _market_pull(records):
    result = {}
    for group in ("WNBA", "NON_WNBA"):
        subset = [r for r in records if r.get("league_group") == group]
        weights = [_num(r.get("market_weight")) for r in subset if _num(r.get("market_weight")) is not None]
        retentions = [(r.get("edge_metrics") or {}).get("edge_retention_ratio") for r in subset]
        retentions = [x for x in retentions if _num(x) is not None]
        result[group] = {"sample_size": len(subset), "market_weight_emitted": len(weights), "mean_market_weight": _mean(weights),
                         "mean_edge_retention": _mean(retentions), "non_wna_high_market_pull": bool(group == "NON_WNBA" and weights and _mean(weights) >= 0.5),
                         "label_definition": "diagnostic-only: emitted mean market_weight >= 0.5"}
    return result


def _near_miss(records):
    rows = []
    for r in records:
        if r.get("league_group") != "NON_WNBA":
            continue
        m = r.get("edge_metrics") or {}
        if not m.get("raw_edge_found") or r.get("status") == "SHADOW_TRIGGERED":
            continue
        rows.append({"event_id": r.get("event_id"), "league": r.get("league"), "league_bucket": r.get("league_bucket"),
                     "market_type": r.get("market_type"), "teams": f"{r.get('team1')} vs {r.get('team2')}",
                     "raw_edge_points": m.get("raw_edge_points"), "calibrated_edge_points": m.get("calibrated_edge_points"),
                     "adjusted_probability": m.get("adjusted_probability"), "adjusted_EV": m.get("adjusted_ev"),
                     "suppression_reason": _reason(r), "pricing_mode": r.get("pricing_mode")})
    return sorted(rows, key=lambda x: abs(x.get("calibrated_edge_points") or x.get("raw_edge_points") or 0), reverse=True)[:10]


def _main_states_by_league(records):
    groups = defaultdict(list)
    for r in records:
        groups[r.get("league_bucket", "Other")].append(r)
    return {league: _window_stats(rows) for league, rows in sorted(groups.items())}


def _questions(summary):
    compare = summary.get("wnba_vs_non_wnba", {})
    non = compare.get("NON_WNBA", {}).get("counts", {})
    wna = compare.get("WNBA", {}).get("counts", {})
    return {
        "1_shadow_concentration": "按联赛、组别与市场拆分统计 Shadow，不改变任何门槛。",
        "2_wnba_vs_non_wnba": compare,
        "3_discovered_to_market": "见每个窗口的 discovered -> market_found 转化率。",
        "4_market_to_fresh": "见 fresh_market 的顺序转化率；过期盘口单独保留。",
        "5_fresh_to_priceable": "见 research_priceable；这是研究输入漏斗，不代表执行通过。",
        "6_priceable_to_comparable": "见 market_comparable；严格同市场、同规则比较。",
        "7_raw_edge": "raw_edge_found 只使用现有 Fair line 与盘口的诊断差异。",
        "8_calibrated_edge": "calibrated_edge_found 只使用生产显式校准 Fair line。",
        "9_evidence_pass": "按 evidence_pass 与 evidence blockers 分联赛统计。",
        "10_execution_pass": "按 execution_pass 统计，不把 paper Shadow 改成真实执行。",
        "11_suppression_attribution": "见 suppression_attribution；只对出现 raw edge 但未 Shadow 的记录归因。",
        "12_probability_waterfall": "中间概率未被生产显式输出时保留 null，不反推。",
        "13_cold_start_native_prior": "见 native_cold_start_prior；分组只做描述性比较。",
        "14_residual_scale": "见 residual_scale_breakdown；不改 base/tier/league/cold-start/final 任一倍率。",
        "15_market_pull": "见 market_pull；NON_WNBA_HIGH_MARKET_PULL 是诊断标签，不是新门槛。",
        "16_evidence_blockers_by_league": "见 evidence_blockers_by_league。",
        "17_mature_league_bias": "比较成熟联赛与其他联赛的 comparable、evidence、execution、Shadow 转化，样本不足则标记。",
        "18_near_miss": "见 non_wnba_near_miss_top10，并按 SPREAD/TOTAL 拆分。",
        "19_forward_native": "rolling 3d/7d/all_forward_native 只纳入首写前瞻样本，避免回测混入。",
        "20_sample_sufficiency": f"diagnostic minimum sample={MIN_DIAGNOSTIC_SAMPLE}，不足只显示 INSUFFICIENT_SAMPLE，不触发调参。",
        "21_main_state": "每个主要联赛给出一个 main_state。",
        "22_repair_scope": "只输出 P0/P1/P2 工程与证据链建议；不建议降低阈值、改 Fair line、改 Champion 或改残差尺度。",
        "current_wnba_counts": wna,
        "current_non_wnba_counts": non,
    }


def build_league_funnel_diagnostic(current_records, root, day, asof, diagnose_market, comparable_fn):
    root = Path(root)
    older_rows = _load_older_rows(root, day)
    records = list(current_records)
    for row in older_rows:
        for market in ("SPREAD", "TOTAL"):
            records.append(_record_from_row(row, market, diagnose_market, comparable_fn))
    records = _dedupe(records)
    current_date = _date(day) or datetime.now().date()
    for record in records:
        record["date_bj"] = record.get("date_bj") or str(_date(record.get("tip_time_bj")) or "")
    today = [r for r in records if r.get("date_bj") == day]
    def in_days(days):
        return [r for r in records if (_date(r.get("date_bj")) is not None and current_date - timedelta(days=days - 1) <= _date(r.get("date_bj")) <= current_date)]
    comparable_sorted = sorted([r for r in records if r.get("comparable")], key=lambda r: str(r.get("asof") or r.get("tip_time_bj") or ""))
    windows = {
        "today": today,
        "rolling_3d": in_days(3),
        "rolling_7d": in_days(7),
        "all_forward_native": records,
        "last_20_comparable": comparable_sorted[-20:],
        "last_50_comparable": comparable_sorted[-50:],
    }
    by_window = {}
    for name, subset in windows.items():
        leagues = _main_states_by_league(subset)
        groups = _group_comparison(subset)
        by_window[name] = {"sample_size": len(subset), "by_league": leagues, "groups": groups,
                           "split_by_market": {market: _group_comparison([r for r in subset if r.get("market_type") == market]) for market in ("SPREAD", "TOTAL")}}
    all_comparable = [r for r in records if r.get("comparable")]
    all_raw = [r for r in records if (r.get("edge_metrics") or {}).get("raw_edge_found")]
    summary = {
        "schema_version": "league-decision-funnel-diagnostic-1.0",
        "diagnostic_only": True, "real_execution_allowed": False, "date_bj": day, "asof": asof,
        "minimum_diagnostic_sample": MIN_DIAGNOSTIC_SAMPLE,
        "windows": by_window,
        "wnba_vs_non_wnba": _group_comparison(today),
        "suppression_attribution": _attribution(all_comparable),
        "probability_waterfall": {"sample_size": len(all_comparable), "rows": [{"event_id": r.get("event_id"), "league": r.get("league"), "league_bucket": r.get("league_bucket"), "market_type": r.get("market_type"), **r.get("waterfall", {})} for r in all_comparable], "note": "未显式输出的中间节点保留 null。"},
        "native_cold_start_prior": _mode_stats(all_comparable),
        "residual_scale_breakdown": _residual_breakdown(all_comparable),
        "market_pull": _market_pull(all_comparable),
        "evidence_blockers_by_league": {league: dict(Counter(x for r in all_comparable if r.get("league_bucket") == league for x in (r.get("evidence_blockers") or []) + (r.get("pricing_blockers") or []))) for league in sorted({r.get("league_bucket") for r in all_comparable})},
        "mature_league_bias": {"mature": _window_stats([r for r in all_comparable if str(r.get("league_tier") or "").upper() in {"TIER_1", "TIER_2"}]), "other": _window_stats([r for r in all_comparable if str(r.get("league_tier") or "").upper() not in {"TIER_1", "TIER_2"}]), "interpretation": "仅作结构性偏差诊断；任何一侧 comparable 样本不足时不下结论。"},
        "non_wnba_near_miss_top10": _near_miss(all_comparable),
        "market_split": {market: _window_stats([r for r in all_comparable if r.get("market_type") == market]) for market in ("SPREAD", "TOTAL")},
        "counts": {"forward_native_records": len(records), "comparable": len(all_comparable), "raw_edge": len(all_raw), "shadow": sum(r.get("status") == "SHADOW_TRIGGERED" for r in records)},
    }
    summary["questions"] = _questions(summary)
    p0 = sum(summary["suppression_attribution"]["overall"].values())
    summary["repair_suggestions"] = {
        "P0": "若 evidence blockers 或 source freshness 是主因，优先修复来源/证据链完整性；不改门槛。" if p0 else "持续记录并验证前瞻样本，暂不扩大模型动作。",
        "P1": "补齐按联赛与市场的显式概率瀑布、残差分解和市场拉力字段，避免把未发出的字段误判为校准抑制。",
        "P2": "当主要联赛达到足够原生前瞻样本后，再做分联赛偏差与校准回测；当前不平衡、不降阈值、不改 Fair line。",
    }
    return summary
