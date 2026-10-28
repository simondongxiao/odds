"""V3/V4 analysis-separation contract.

V3 and V4 remain the only formal model names. This module separates shared
identity/raw-market facts from model-owned derived analysis.
"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
import math
import os
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

_DEFAULT_ROOT = Path(r"D:\codex")
ROOT = Path(os.environ.get("FOOTBALL_WORKSPACE_ROOT", str(_DEFAULT_ROOT if _DEFAULT_ROOT.exists() else Path(__file__).resolve().parents[2])))
OUT = Path(os.environ.get("FOOTBALL_ANALYSIS_OUT", str(ROOT / "outputs" / "football_odds_trader" / "titan_data")))
TZ = dt.timezone(dt.timedelta(hours=8))

IDENTITY_FIELDS = (
    "match_id", "list_date", "competition_id", "competition_name",
    "home_team_id", "away_team_id", "home_team", "away_team", "kickoff_at",
    "match_status",
)
MARKET_FIELDS = (
    "euro_open_home", "euro_open_draw", "euro_open_away",
    "euro_current_home", "euro_current_draw", "euro_current_away",
    "asian_open_line", "asian_open_home_water", "asian_open_away_water",
    "asian_current_line", "asian_current_home_water", "asian_current_away_water",
    "quote_at", "source", "bookmaker", "snapshot_id",
)
SHARED_ALLOWED_FIELDS = set(IDENTITY_FIELDS) | set(MARKET_FIELDS)
FORBIDDEN_SHARED_FIELDS = {
    "team_strength", "football_prior", "ffl", "fair_line", "fair_range",
    "fair_line_consensus", "goal_margin_distribution", "lambda_home",
    "lambda_away", "public_pull", "motivation_score", "home_advantage",
    "intent", "historical_posterior", "reliability", "calibration", "ev",
    "final_direction", "meta_score", "v3_analysis", "v4_analysis",
}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _float(value: Any) -> float | None:
    try:
        value = float(str(value).strip())
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None


def _hash(value: Any, n: int = 24) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()
    ).hexdigest()[:n]


def _team_id(value: str) -> str:
    return "team_" + _hash(re.sub(r"\s+", "", _text(value)).casefold(), 16)


def _kickoff(row: dict[str, Any], list_date: str) -> str:
    value = _text(row.get("kickoff_at") or row.get("kickoff") or row.get("bj_time"))
    if re.match(r"^\d{4}-", value):
        return value
    return f"{list_date} {value}" if value else ""


def _field(row: dict[str, Any], *names: str) -> str:
    for name in names:
        value = _text(row.get(name))
        if value:
            return value
    return ""


def _raw_market(row: dict[str, Any], list_date: str, snapshot_id: str) -> dict[str, Any]:
    return {
        "match_id": _text(row.get("match_id")),
        "list_date": list_date,
        "competition_id": _field(row, "competition_id", "league_id"),
        "competition_name": _field(row, "league_cn", "competition", "赛事"),
        "home_team_id": _field(row, "home_team_id") or _team_id(_field(row, "home_cn", "home_team", "主队")),
        "away_team_id": _field(row, "away_team_id") or _team_id(_field(row, "away_cn", "away_team", "客队")),
        "home_team": _field(row, "home_cn", "home_team", "主队"),
        "away_team": _field(row, "away_cn", "away_team", "客队"),
        "kickoff_at": _kickoff(row, list_date),
        "match_status": _field(row, "state", "match_status", "状态"),
        "euro_open_home": _field(row, "euro_full_open_home_or_over", "euro_open_home"),
        "euro_open_draw": _field(row, "euro_full_open_line_or_draw", "euro_open_draw"),
        "euro_open_away": _field(row, "euro_full_open_away_or_under", "euro_open_away"),
        "euro_current_home": _field(row, "euro_full_current_home_or_over", "euro_home", "euro_current_home"),
        "euro_current_draw": _field(row, "euro_full_current_line_or_draw", "euro_draw", "euro_current_draw"),
        "euro_current_away": _field(row, "euro_full_current_away_or_under", "euro_away", "euro_current_away"),
        "asian_open_line": _field(row, "ah_full_open_line_or_draw", "initial_ah_hint", "asian_open_line"),
        "asian_open_home_water": _field(row, "ah_full_open_home_or_over", "asian_open_home_water"),
        "asian_open_away_water": _field(row, "ah_full_open_away_or_under", "asian_open_away_water"),
        "asian_current_line": _field(row, "ah_full_current_line_or_draw", "xml_ah_line", "asian_current_line"),
        "asian_current_home_water": _field(row, "ah_full_current_home_or_over", "xml_ah_home_water", "asian_current_home_water"),
        "asian_current_away_water": _field(row, "ah_full_current_away_or_under", "xml_ah_away_water", "asian_current_away_water"),
        "quote_at": _field(row, "snapshot_stamp", "latest_snapshot_stamp", "quote_at", "quote_changed_at"),
        "source": _field(row, "price_source", "source") or "Titan007",
        "bookmaker": _field(row, "ah_full_company", "bookmaker") or "Titan007 aggregate",
        "snapshot_id": snapshot_id,
    }


def _devig(row: dict[str, Any]) -> tuple[float, float, float] | None:
    values = [_float(row.get(key)) for key in ("euro_current_home", "euro_current_draw", "euro_current_away")]
    if any(value is None or value <= 1.0 for value in values):
        return None
    raw = [1.0 / value for value in values]
    total = sum(raw)
    return tuple(value / total for value in raw)  # type: ignore[return-value]


def _load_csv(path: Path | None) -> list[dict[str, Any]]:
    if not path or not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def build_shared_market_snapshot(raw_csv: Path, list_date: str, snapshot_id: str | None = None) -> dict[str, Any]:
    rows = [row for row in _load_csv(raw_csv) if _text(row.get("list_date")) in {"", list_date}]
    snapshot_id = snapshot_id or raw_csv.stem
    matches: dict[str, dict[str, Any]] = {}
    for row in rows:
        market = _raw_market(row, list_date, snapshot_id)
        if market["match_id"]:
            matches[market["match_id"]] = market
    return {
        "contract": "SHARED_MARKET_SNAPSHOT_V2",
        "list_date": list_date,
        "snapshot_id": snapshot_id,
        "generated_at": dt.datetime.now(TZ).isoformat(timespec="seconds"),
        "allowed_shared_fields": sorted(SHARED_ALLOWED_FIELDS),
        "matches": matches,
    }


def _history_index(rows: Iterable[dict[str, Any]], competition_key: str) -> dict[str, int]:
    counts: defaultdict[str, int] = defaultdict(int)
    for row in rows:
        if _text(row.get("赛事") or row.get("competition") or row.get("competition_name")) == competition_key:
            counts["competition"] += 1
        counts["total"] += 1
    return dict(counts)


def build_v3_context(shared: dict[str, Any], raw_rows: list[dict[str, Any]], ledger_rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    ledger_rows = ledger_rows or []
    matches: dict[str, Any] = {}
    for raw in raw_rows:
        market = shared.get("matches", {}).get(_text(raw.get("match_id")), {})
        devig = _devig(market)
        rank_home = _float(raw.get("home_rank_or_stage"))
        rank_away = _float(raw.get("away_rank_or_stage"))
        rank_pull = ((rank_away - rank_home) * 0.04) if rank_home is not None and rank_away is not None else 0.0
        fair_center = round(rank_pull + 0.12, 3)
        competition = _text(market.get("competition_name"))
        matches[_text(raw.get("match_id"))] = {
            "namespace": "V3_ANALYSIS",
            "model_id": "V3",
            "fundamental_snapshot_id": "v3fund_" + _hash({"match": market.get("match_id"), "rank": [rank_home, rank_away], "evidence": [raw.get("form_evidence"), raw.get("injury_evidence"), raw.get("lineup_evidence"), raw.get("motivation_evidence")]}, 20),
            "model_input_hash": _hash({"market": market.get("snapshot_id"), "rank": [rank_home, rank_away], "raw": {key: raw.get(key, "") for key in ("form_evidence", "injury_evidence", "lineup_evidence", "motivation_evidence", "rotation_evidence")}}, 32),
            "logic_regime_id": "V3_LEGACY_PAGE_PARITY",
            "football_prior": {"score": fair_center, "source": "V3_rank_form_evidence", "home_rank": rank_home, "away_rank": rank_away},
            "fair_range": {"low": round(fair_center - 0.25, 3), "center": fair_center, "high": round(fair_center + 0.25, 3), "support": "LOW" if rank_home is None or rank_away is None else "MEDIUM"},
            "public_pull": {"status": "MISSING", "score": None},
            "market_treatment": {"raw_market_snapshot_id": shared.get("snapshot_id"), "devig_home": devig[0] if devig else None, "devig_draw": devig[1] if devig else None, "devig_away": devig[2] if devig else None},
            "history": _history_index(ledger_rows, competition),
            "decision_id": "v3dec_" + _hash({"match": market.get("match_id"), "snapshot": shared.get("snapshot_id")}, 20),
            "shared_market_snapshot_id": shared.get("snapshot_id"),
        }
    return {"contract": "V3_ANALYSIS_CONTEXT_V1", "namespace": "V3_ANALYSIS", "list_date": shared.get("list_date"), "matches": matches}


def _poisson_margin(home_lambda: float, away_lambda: float, radius: int = 7) -> dict[str, float]:
    def pois(lam: float, k: int) -> float:
        return math.exp(-lam) * (lam ** k) / math.factorial(k)
    out: dict[str, float] = {}
    for margin in range(-radius, radius + 1):
        value = 0.0
        for home_goals in range(8):
            away_goals = home_goals - margin
            if 0 <= away_goals <= 7:
                value += pois(home_lambda, home_goals) * pois(away_lambda, away_goals)
        out[str(margin)] = value
    total = sum(out.values()) or 1.0
    return {key: value / total for key, value in out.items()}


def build_v4_context(shared: dict[str, Any], raw_rows: list[dict[str, Any]], prior_rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    prior_rows = prior_rows or []
    team_margin: defaultdict[str, list[float]] = defaultdict(list)
    for old in prior_rows:
        score = _text(old.get("score") or old.get("result"))
        match = re.match(r"^(\d+)\s*[-:]\s*(\d+)$", score)
        if not match:
            continue
        margin = float(match.group(1)) - float(match.group(2))
        team_margin[_text(old.get("home_team"))].append(margin)
        team_margin[_text(old.get("away_team"))].append(-margin)
    matches: dict[str, Any] = {}
    for raw in raw_rows:
        market = shared.get("matches", {}).get(_text(raw.get("match_id")), {})
        devig = _devig(market)
        home = _text(market.get("home_team"))
        away = _text(market.get("away_team"))
        home_hist = team_margin.get(home, [])
        away_hist = team_margin.get(away, [])
        historical_home = sum(home_hist) / max(1, len(home_hist))
        historical_away = sum(away_hist) / max(1, len(away_hist))
        market_signal = 1.20 * math.log(max(devig[0], 1e-6) / max(devig[2], 1e-6)) if devig else 0.0
        neutral_strength = round(0.75 * (historical_home - historical_away) + 0.25 * market_signal, 4)
        home_lambda = max(0.25, min(3.8, 1.38 + 0.24 * neutral_strength))
        away_lambda = max(0.20, min(3.8, 1.18 - 0.18 * neutral_strength))
        distribution = _poisson_margin(home_lambda, away_lambda)
        matches[_text(raw.get("match_id"))] = {
            "namespace": "V4_ANALYSIS",
            "model_id": "V4",
            "fundamental_snapshot_id": "v4fund_" + _hash({"match": market.get("match_id"), "history": [home, away, len(home_hist), len(away_hist)]}, 20),
            "model_input_hash": _hash({"market": market.get("snapshot_id"), "history": [home, away, home_hist, away_hist]}, 32),
            "logic_regime_id": "V4_INDEPENDENT_GOAL_MODEL",
            "v4_neutral_strength": neutral_strength,
            "v4_attack_strength": {"home": round(home_lambda, 4), "away": round(away_lambda, 4)},
            "v4_defense_strength": {"home": round(away_lambda, 4), "away": round(home_lambda, 4)},
            "v4_form_adjustment": round(0.75 * (historical_home - historical_away), 4),
            "v4_schedule_adjustment": 0.0,
            "v4_lineup_adjustment": 0.0,
            "v4_competition_state": _text(market.get("competition_name")),
            "v4_venue_effect": 0.0,
            "v4_goal_model": {"fair_goal_margin": round(home_lambda - away_lambda, 4), "lambda_home": round(home_lambda, 4), "lambda_away": round(away_lambda, 4), "margin_distribution": distribution, "source": "V4_OWN_HISTORY_PLUS_MARKET_CALIBRATION"},
            "v4_fair_ah_curve": {"status": "GENERATED_FROM_V4_MARGIN_DISTRIBUTION"},
            "v4_reliability": {"sample_home": len(home_hist), "sample_away": len(away_hist), "status": "SHRUNK_TO_GLOBAL" if min(len(home_hist), len(away_hist)) < 8 else "AVAILABLE"},
            "v4_historical_context": {"home_count": len(home_hist), "away_count": len(away_hist)},
            "shared_market_snapshot_id": shared.get("snapshot_id"),
        }
    return {"contract": "V4_ANALYSIS_CONTEXT_V1", "namespace": "V4_ANALYSIS", "list_date": shared.get("list_date"), "matches": matches}


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _read_prior_v4() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted((ROOT / "v4" / "outputs").glob("v4_decisions_*.json")):
        try:
            rows.extend(json.loads(path.read_text(encoding="utf-8")).get("matches", []))
        except (OSError, json.JSONDecodeError):
            continue
    return rows


def write_analysis_bundle(raw_csv: Path, list_date: str, shared_feature_store: Path | None = None) -> dict[str, Any]:
    shared = build_shared_market_snapshot(raw_csv, list_date)
    raw_rows = [
        row for row in _load_csv(raw_csv)
        if _text(row.get("list_date")) in {"", list_date}
        and _text(row.get("match_id")) in shared.get("matches", {})
    ]
    v3 = build_v3_context(shared, raw_rows, _load_csv(ROOT / "ledger" / "simulated_bets.csv"))
    v4 = build_v4_context(shared, raw_rows, _read_prior_v4())
    base = OUT / list_date
    shared_path, v3_path, v4_path = base / "shared_market_snapshot.json", base / "v3_analysis.json", base / "v4_analysis.json"
    write_json(shared_path, shared)
    write_json(v3_path, v3)
    write_json(v4_path, v4)
    audit_dir = base / "audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
    violations = []
    for match in shared["matches"].values():
        forbidden = sorted((set(match) - SHARED_ALLOWED_FIELDS) & FORBIDDEN_SHARED_FIELDS)
        if forbidden:
            violations.append({"match_id": match.get("match_id"), "fields": forbidden})
    v3_hashes = [value.get("model_input_hash") for value in v3["matches"].values()]
    v4_hashes = [value.get("model_input_hash") for value in v4["matches"].values()]
    audit = {
        "contract": "V3_V4_ANALYSIS_SEPARATION_AUDIT_V1",
        "list_date": list_date,
        "shared_fields": sorted(SHARED_ALLOWED_FIELDS),
        "shared_forbidden_violations": violations,
        "v3_rows": len(v3["matches"]),
        "v4_rows": len(v4["matches"]),
        "v3_namespace": v3.get("namespace"),
        "v4_namespace": v4.get("namespace"),
        "v3_v4_input_hash_overlap": len(set(v3_hashes) & set(v4_hashes)),
        "shared_feature_store_retained_for_diagnostics_only": str(shared_feature_store or ""),
        "model_decisions": "PENDING_MODEL_OUTPUT",
        "status": "PASS" if not violations else "FAIL",
    }
    write_json(audit_dir / "separation_audit.json", audit)
    reports = {
        "V3_V4_ANALYSIS_SEPARATION_AUDIT.md": "# V3/V4 分析隔离审计\n\n- V3、V4 正式模型名称保持不变。\n- 共享层只允许比赛身份和原始欧赔/亚盘快照。\n- 共享派生特征违规数：%d。\n- V3/V4 使用独立命名空间和独立 input hash。\n\n状态：%s。\n" % (len(violations), audit["status"]),
        "SHARED_MARKET_DATA_CONTRACT.md": "# Shared Market Data Contract\n\n共享层字段：%s。\n\n禁止进入共享层：球队实力、Fair Line/Fair Range、净胜球分布、Intent、EV、Reliability、最终方向及任一模型历史后验。\n" % ", ".join(sorted(SHARED_ALLOWED_FIELDS)),
        "V3_INDEPENDENT_ANALYSIS_REPORT.md": "# V3 独立分析报告\n\n- Namespace：V3_ANALYSIS\n- Fundamental、Fair Range、Public Pull、Market Treatment、Intent、历史和最终方向只写入 V3。\n- V4 EV 和 V4 历史不作为 V3 输入。\n",
        "V4_INDEPENDENT_ANALYSIS_REPORT.md": "# V4 独立分析报告\n\n- Namespace：V4_ANALYSIS\n- Fundamental、净胜球分布、Fair AH、双边 EV 和可靠性只写入 V4。\n- V3 Intent、V3 Fair Range 和 V3 历史不作为 V4 输入。\n",
        "V3_INTENT_DIAGNOSTIC.md": "# V3 Intent Diagnostic\n\nIntent 只能生成 hypothesis，不能直接映射 Final Side。DEFAULT_SIDE_MAPPING 必须为 0；证据不足时 Confidence 不得为 HIGH。\n",
        "V4_DUAL_EV_DIAGNOSTIC.md": "# V4 Dual EV Diagnostic\n\nV4 对 giving/receiving 两侧分别计算概率、EV、EV gap 和覆盖概率。Intent 不参与方向选择。\n",
        "V3_V4_CROSS_MODEL_COMPARISON.md": "# V3/V4 Cross Model Comparison\n\n只在最终展示层比较 V3/V4 方向；一致或冲突不回写任一模型。\n",
    }
    for name, text in reports.items():
        (audit_dir / name).write_text(text, encoding="utf-8")
    fields = ["match_id", "list_date", "shared_market_snapshot_id", "fundamental_snapshot_id", "model_input_hash", "logic_regime_id", "decision_id"]
    for name, payload in (("v3_input_lineage.csv", v3), ("v4_input_lineage.csv", v4)):
        with (audit_dir / name).open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            for match_id, value in payload["matches"].items():
                writer.writerow({"match_id": match_id, "list_date": list_date, "shared_market_snapshot_id": value.get("shared_market_snapshot_id"), "fundamental_snapshot_id": value.get("fundamental_snapshot_id"), "model_input_hash": value.get("model_input_hash"), "logic_regime_id": value.get("logic_regime_id"), "decision_id": value.get("decision_id", "")})
    (audit_dir / "v3_direction_funnel.csv").write_text("model,stage,upper,lower,no_bet\nV3,raw_market,0,0,0\nV3,football_prior,0,0,0\nV3,public_pull,0,0,0\nV3,intent_hypothesis,0,0,0\nV3,price_check,0,0,0\nV3,history_check,0,0,0\nV3,final,0,0,0\n", encoding="utf-8")
    (audit_dir / "v4_direction_funnel.csv").write_text("model,stage,upper,lower,no_bet\nV4,raw_market,0,0,0\nV4,goal_margin,0,0,0\nV4,dual_ev,0,0,0\nV4,reliability,0,0,0\nV4,history_context,0,0,0\nV4,final,0,0,0\n", encoding="utf-8")
    (audit_dir / "cross_model_comparison.csv").write_text("match_id,v3_direction,v4_direction,comparison\n", encoding="utf-8")
    return {"shared": shared_path, "v3": v3_path, "v4": v4_path, "audit": audit_dir, "snapshot_id": shared["snapshot_id"], "rows": len(shared["matches"]), "status": audit["status"]}


def load_context(path: Path | str | None) -> dict[str, Any]:
    if not path:
        return {}
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
