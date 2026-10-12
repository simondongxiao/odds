"""Audited basketball reference core, v2.1.

Standard library only. This is a deterministic research/reference implementation,
not a live-site collector and not a calibrated betting model. Raw forecasts do
not accept market data. See SKILL.md for integration into the existing project.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path
from statistics import median
from typing import Any, Callable, Iterable, Mapping

VERSION = "basketball-reference-2.1.0"
BJ = timezone(timedelta(hours=8))
UTC = timezone.utc
MODES = {"FORWARD_NATIVE", "RECONSTRUCTED_BACKFILL", "SYNTHETIC_FIXTURE"}
RULES = {"INCLUDING_OT", "REGULATION_ONLY"}


class ContractError(ValueError):
    pass


def ts(value: str | datetime) -> datetime:
    out = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
    if out.tzinfo is None or out.utcoffset() is None:
        raise ContractError("Timestamp must include a timezone")
    return out.astimezone(UTC)


def finite(value: Any, name: str = "value") -> float:
    if isinstance(value, bool):
        raise ContractError(f"{name}: bool is not a number")
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise ContractError(f"{name}: missing/non-numeric") from exc
    if not math.isfinite(out):
        raise ContractError(f"{name}: must be finite")
    return out


def canonical_json(obj: Any) -> bytes:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(obj: Any) -> str:
    return hashlib.sha256(canonical_json(obj)).hexdigest()


def immutable_json(path: str | Path, obj: Any) -> bool:
    """Exclusive creation; identical retry is idempotent, changed content is rejected."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    content = canonical_json(obj) + b"\n"
    try:
        with path.open("xb") as f:
            f.write(content)
        return True
    except FileExistsError:
        if path.read_bytes() != content:
            raise ContractError(f"Immutable record conflict: {path}")
        return False


def verify_raw_reference(e: Mapping[str, Any], base_dir: Path) -> bool:
    """Check bytes, not a READY flag. Relative raw paths are input-file-relative."""
    raw_path, expected = e.get("raw_path"), e.get("raw_sha256")
    if not raw_path or not expected:
        return False
    p = Path(str(raw_path))
    if not p.is_absolute():
        p = base_dir / p
    try:
        return p.is_file() and hashlib.sha256(p.read_bytes()).hexdigest() == expected
    except OSError:
        return False


def validate_event(event: Mapping[str, Any]) -> None:
    for key in ("event_id", "team1_id", "team2_id", "team1_name", "team2_name", "competition_id", "gender", "age_group", "format_id", "tip_at"):
        if not event.get(key):
            raise ContractError(f"event missing {key}")
    if event["team1_id"] == event["team2_id"]:
        raise ContractError("Teams must differ")
    ts(event["tip_at"])
    if event.get("identity_verified") is not True:
        raise ContractError("Event identity must be evidenced, not inferred from numeric ID alone")


def evidence_eligible(e: Mapping[str, Any], asof: str | datetime, mode: str) -> tuple[bool, str]:
    """Publication time alone does NOT prove a mutable historical page's state."""
    if mode not in MODES:
        return False, "UNKNOWN_ARCHIVE_TYPE"
    if mode == "SYNTHETIC_FIXTURE":
        return (e.get("synthetic") is True, "SYNTHETIC_ONLY")
    if e.get("synthetic"):
        return False, "SYNTHETIC_IN_PRODUCTION"
    if e.get("quality") not in {"A", "B"}:
        return False, "UNSUPPORTED_EVIDENCE_QUALITY"
    if not e.get("source_url") or not e.get("raw_sha256"):
        return False, "PROVENANCE_MISSING"
    if e.get("raw_integrity_verified") is not True:
        return False, "RAW_BYTES_NOT_VERIFIED"
    cutoff = ts(asof)
    try:
        effective = ts(e["effective_at"])
        captured = ts(e["captured_at"])
    except (KeyError, ValueError):
        return False, "TIME_UNKNOWN"
    if effective > cutoff:
        return False, "EFFECTIVE_AFTER_CUTOFF"
    if mode == "FORWARD_NATIVE":
        return (captured <= cutoff, "OK" if captured <= cutoff else "CAPTURE_AFTER_CUTOFF")
    # Backfill: a verifiable archived version, or deterministic pre-cutoff fact reaggregation.
    if captured <= cutoff:
        return True, "OK_ORIGINAL_CAPTURE"
    if e.get("historical_version_verified") and e.get("version_asof"):
        if ts(e["version_asof"]) <= cutoff:
            return True, "OK_ARCHIVED_VERSION"
    if e.get("fact_type") == "PRIOR_COMPLETED_GAME" and e.get("historical_fact_verified"):
        if e.get("known_at") and ts(e["known_at"]) <= cutoff:
            return True, "OK_RECONSTRUCTED_FACT_NOT_NATIVE"
    return False, "MUTABLE_PAGE_NO_HISTORICAL_STATE"


def source_price(raw: Any, fmt: str) -> float:
    x = finite(raw, "raw_price")
    if fmt == "DECIMAL":
        d = x
    elif fmt == "HK" and x >= 0:
        d = 1 + x
    elif fmt == "AMERICAN" and abs(x) >= 100:
        d = 1 + (x / 100 if x > 0 else 100 / abs(x))
    elif fmt in {"MALAY", "INDO"} and x != 0:
        if fmt == "MALAY" and not (-1 <= x <= 1):
            raise ContractError("Malay odds outside [-1,1]")
        if fmt == "INDO" and abs(x) < 1:
            raise ContractError("Indonesian odds require abs(raw)>=1")
        d = 1 + (x if x > 0 else 1 / abs(x))
    else:
        raise ContractError("Unknown/invalid odds format; do not infer from numeric appearance")
    if d <= 1:
        raise ContractError("Decimal odds must exceed 1")
    return d


def main_line(value: Any) -> float:
    x = finite(value, "line")
    if Decimal(str(x)) * 2 != (Decimal(str(x)) * 2).to_integral_value():
        raise ContractError("This core accepts only integer or half-point lines; quarter lines need split settlement")
    return x


def display_handicap(team: str | None, handicap: float | None, verified: bool = True) -> str:
    if handicap is None:
        return "未获取"
    h = finite(handicap)
    if not team or not verified:
        return f"盘口方向待核验（幅度 {abs(h):g} 分）"
    if abs(h) < 1e-12:
        return f"{team} 平手（0分）"
    return f"{team} {'让' if h < 0 else '受让'} {abs(h):g} 分（{h:+g}）"


def display_fair_margin(event: Mapping[str, Any], mu_team1_minus_team2: float | None) -> str:
    if mu_team1_minus_team2 is None:
        return "未获取"
    m = finite(mu_team1_minus_team2)
    # Positive margin -> team1 is stronger -> fair handicap for team1 is negative.
    name = event.get("team1_name") if m >= 0 else event.get("team2_name")
    return display_handicap(name, -abs(m), bool(event.get("identity_verified")))


# Regularized incomplete beta, using a convergent continued fraction.
# Validated against scipy.special.betainc / scipy.stats.t in validation/.
def _betacf(a: float, b: float, x: float) -> float:
    qab, qap, qam = a + b, a + 1, a - 1
    tiny, eps = 1e-300, 3e-14
    c, d = 1.0, 1.0 - qab * x / qap
    if abs(d) < tiny:
        d = tiny
    d = 1 / d
    h = d
    for m in range(1, 401):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1 + aa * d
        if abs(d) < tiny:
            d = tiny
        c = 1 + aa / c
        if abs(c) < tiny:
            c = tiny
        d = 1 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1 + aa * d
        if abs(d) < tiny:
            d = tiny
        c = 1 + aa / c
        if abs(c) < tiny:
            c = tiny
        d = 1 / d
        delta = d * c
        h *= delta
        if abs(delta - 1) < eps:
            return h
    raise ContractError("Incomplete beta did not converge")


def reg_beta(x: float, a: float, b: float) -> float:
    if not (a > 0 and b > 0 and 0 <= x <= 1):
        raise ContractError("Invalid beta arguments")
    if x in (0, 1):
        return x
    bt = math.exp(math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log1p(-x))
    v = bt * _betacf(a, b, x) / a if x < (a + 1) / (a + b + 2) else 1 - bt * _betacf(b, a, 1 - x) / b
    return min(1.0, max(0.0, v))


def t_cdf(x: float, mean: float, sd: float, df: float) -> float:
    """sd is STANDARD DEVIATION, not scipy's scale. df > 2 required."""
    x, mean, sd, df = finite(x), finite(mean), finite(sd), finite(df)
    if sd <= 0 or df <= 2:
        raise ContractError("Student-t requires sd>0 and df>2")
    scale = sd * math.sqrt((df - 2) / df)
    z = (x - mean) / scale
    if z == 0:
        return 0.5
    v = 0.5 * reg_beta(df / (df + z * z), df / 2, 0.5)
    return v if z < 0 else 1 - v


@dataclass(frozen=True)
class WPL:
    win: float
    push: float
    loss: float

    def __post_init__(self) -> None:
        if any(not math.isfinite(v) or v < -1e-10 or v > 1 + 1e-10 for v in (self.win, self.push, self.loss)):
            raise ContractError("Invalid W/P/L probabilities")
        if abs(self.win + self.push + self.loss - 1) > 1e-8:
            raise ContractError("W/P/L must sum to one")


def threshold_probability(cdf: Callable[[float], float], threshold: float, side: str) -> WPL:
    t = main_line(threshold)
    if side not in {"OVER", "UNDER"}:
        raise ContractError("Threshold side must be OVER/UNDER")
    if t.is_integer():
        below, through = cdf(t - .5), cdf(t + .5)
        p = WPL(1 - through, through - below, below)
    else:
        f = cdf(t)
        p = WPL(1 - f, 0., f)
    return p if side == "OVER" else WPL(p.loss, p.push, p.win)


def margin_cdf(mu: float, sd: float, df: float, ot_rule: str) -> Callable[[float], float]:
    if ot_rule not in RULES:
        raise ContractError("Model settlement contract unknown")
    cdf = lambda x: t_cdf(x, mu, sd, df)
    if ot_rule == "REGULATION_ONLY":
        return cdf
    # Final full-game margin cannot equal zero. Discrete-lattice conditioning
    # removes zero probability. This is an explicit baseline approximation, not
    # a possession-level overtime simulator.
    neg, pos = cdf(-.5), cdf(.5)
    p0 = pos - neg
    def conditional(x: float) -> float:
        if x < -.5:
            return cdf(x) / (1 - p0)
        if x < .5:
            return neg / (1 - p0)
        return (cdf(x) - p0) / (1 - p0)
    return conditional


def total_cdf(mu: float, sd: float, df: float) -> Callable[[float], float]:
    c = lambda x: t_cdf(x, mu, sd, df)
    f0 = c(-.5)
    return lambda x: 0. if x <= -.5 else min(1., max(0., (c(x) - f0) / (1 - f0)))


def quote_probability(forecast: Mapping[str, Any], q: Mapping[str, Any]) -> WPL:
    if q.get("ot_rule") not in RULES or q.get("ot_rule") != forecast.get("ot_rule"):
        raise ContractError("No single probability/EV for mismatched or unknown OT contracts")
    if q.get("period") != "FULL_GAME":
        raise ContractError("Unsupported period")
    df = finite(forecast["df"])
    line = main_line(q["line"])
    if q["market_type"] == "SPREAD":
        s = q["selection"]
        if s not in {"TEAM1", "TEAM2"}:
            raise ContractError("Unknown spread selection")
        mu = finite(forecast["mu_margin"])
        if s == "TEAM2":
            mu = -mu
        return threshold_probability(margin_cdf(mu, forecast["sd_margin"], df, forecast["ot_rule"]), -line, "OVER")
    if q["market_type"] == "TOTAL":
        return threshold_probability(total_cdf(forecast["mu_total"], forecast["sd_total"], df), line, q["selection"])
    raise ContractError("Unsupported market: no silent conversion")


def ev_and_kelly(p: WPL, odds: float) -> dict[str, Any]:
    d = source_price(odds, "DECIMAL")
    active = p.win + p.loss
    ev = p.win * (d - 1) - p.loss
    conditional = None if active <= 1e-15 else p.win / active
    # General Kelly with a push returning the entire stake.
    f = 0. if active <= 1e-15 else max(0., min(1., ev / ((d - 1) * active)))
    return {"ev": ev, "p_win_conditional_nonpush": conditional,
            "conditional_breakeven": 1 / d,
            "unconditional_win_breakeven": (1 - p.push) / d,
            "min_break_even_decimal": None if p.win <= 0 else 1 + p.loss / p.win,
            "theoretical_kelly": f, "kelly_usable": False, "real_stake": 0.}


def settle(q: Mapping[str, Any], outcome: Mapping[str, Any]) -> dict[str, Any]:
    if outcome.get("status") in {"CANCELLED", "VOID"}:
        return {"status": "VOID", "pnl_units": 0.}
    if outcome.get("status") != "FINAL":
        return {"status": "PENDING", "pnl_units": None}
    if outcome.get("event_id") != q.get("event_id"):
        raise ContractError("Settlement event mismatch")
    if outcome.get("score_order") != "TEAM1_TEAM2":
        raise ContractError("Score order must be verified")
    rule = q.get("ot_rule")
    if rule not in RULES:
        return {"status": "UNSETTLED_UNKNOWN_RULE", "pnl_units": None}
    prefix = "final" if rule == "INCLUDING_OT" else "regulation"
    a, b = outcome.get(prefix + "_team1"), outcome.get(prefix + "_team2")
    if a is None or b is None:
        return {"status": "UNSETTLED_MISSING_SCORE", "pnl_units": None}
    a, b = finite(a), finite(b)
    if a < 0 or b < 0 or not a.is_integer() or not b.is_integer():
        raise ContractError("Final scores must be nonnegative integers")
    line, d = main_line(q["line"]), source_price(q["decimal_odds"], "DECIMAL")
    if q["market_type"] == "SPREAD":
        if q["selection"] not in {"TEAM1", "TEAM2"}:
            raise ContractError("Invalid spread selection")
        v = (a - b if q["selection"] == "TEAM1" else b - a) + line
    elif q["market_type"] == "TOTAL":
        if q["selection"] not in {"OVER", "UNDER"}:
            raise ContractError("Invalid total selection")
        v = a + b - line
        if q["selection"] == "UNDER":
            v = -v
    else:
        raise ContractError("Unsupported settlement market")
    return {"status": "WIN" if v > 0 else "LOSS" if v < 0 else "PUSH", "pnl_units": d - 1 if v > 0 else -1. if v < 0 else 0.}


def clv_points(entry: Mapping[str, Any], close: Mapping[str, Any]) -> float:
    for key in ("event_id", "market_type", "selection", "period", "ot_rule"):
        if entry.get(key) != close.get(key):
            raise ContractError("CLV requires the exact same contract and selection")
    if entry.get("ot_rule") not in RULES:
        raise ContractError("Unknown OT: CLV incomparable")
    if not close.get("is_valid_close"):
        raise ContractError("Close not validated")
    a, b = main_line(entry["line"]), main_line(close["line"])
    if entry["market_type"] == "SPREAD":
        return a - b
    if entry["market_type"] == "TOTAL":
        return b - a if entry["selection"] == "OVER" else a - b
    raise ContractError("Unsupported CLV")


def quote_blockers(q: Mapping[str, Any], event: Mapping[str, Any], asof: str, mode: str, ttl_seconds: int) -> list[str]:
    errors: list[str] = []
    t = ts(asof)
    if t >= ts(event["tip_at"]):
        errors.append("ALREADY_STARTED")
    if q.get("event_id") != event["event_id"] or not q.get("identity_verified"):
        errors.append("EVENT_IDENTITY_UNVERIFIED")
    if mode != "SYNTHETIC_FIXTURE" and q.get("synthetic"):
        errors.append("SYNTHETIC_IN_PRODUCTION")
    if q.get("status") != "OPEN":
        errors.append("MARKET_NOT_OPEN")
    if q.get("period") != "FULL_GAME":
        errors.append("PERIOD_UNSUPPORTED")
    if q.get("market_role") != "MAIN":
        errors.append("NON_MAIN_MARKET_UNSUPPORTED")
    if q.get("ot_rule") not in RULES:
        errors.append("UNKNOWN_OT_RULE")
    if not q.get("bookmaker_id") or not q.get("feed_provider"):
        errors.append("BOOK_OR_FEED_UNKNOWN")
    if not q.get("raw_sha256") or not q.get("source_url"):
        errors.append("RAW_EVIDENCE_MISSING")
    if mode != "SYNTHETIC_FIXTURE" and q.get("raw_integrity_verified") is not True:
        errors.append("RAW_BYTES_NOT_VERIFIED")
    if not q.get("quote_verified_for_paper"):
        errors.append("PAPER_PRICE_UNVERIFIED")
    if q.get("market_type") == "SPREAD" and not q.get("direction_verified"):
        errors.append("DIRECTION_UNKNOWN")
    try:
        main_line(q["line"])
        source_price(q["decimal_odds"], "DECIMAL")
    except (KeyError, ContractError):
        errors.append("LINE_OR_PRICE_INVALID")
    try:
        captured = ts(q.get("captured_at") or q.get("received_at"))
        semantics = str(q.get("source_timestamp_semantics") or "").upper()
        current_listing = (q.get("current_board_contract_verified") is True and
                           q.get("status") == "OPEN" and
                           semantics == "CURRENT_BOARD_CAPTURE_ONLY")
        updated = captured if current_listing else ts(q["source_quote_at"])
        if not current_listing and updated > captured:
            errors.append("QUOTE_TIME_CONFLICT")
        if updated > t:
            errors.append("QUOTE_TIME_CONFLICT")
        if mode != "RECONSTRUCTED_BACKFILL" and captured > t:
            errors.append("CAPTURE_AFTER_CUTOFF")
        if mode == "RECONSTRUCTED_BACKFILL" and captured > t and not q.get("historical_quote_verified"):
            errors.append("HISTORICAL_QUOTE_UNVERIFIED")
        if (t - updated).total_seconds() > ttl_seconds:
            errors.append("STALE_QUOTE")
    except (KeyError, ValueError):
        errors.append("SOURCE_QUOTE_TIME_UNKNOWN")
    return list(dict.fromkeys(errors))


def latest_market_rows(quotes: Iterable[Mapping[str, Any]], asof: str, mode: str) -> list[Mapping[str, Any]]:
    """Latest observed state per book/selection. A later suspension supersedes
    earlier open odds. Line is deliberately NOT a key for main-line movement.
    Availability is established independently for reconstructed quotes.
    """
    cutoff = ts(asof)
    groups: dict[tuple[Any, ...], Mapping[str, Any]] = {}
    rejected_time: list[Mapping[str, Any]] = []
    for q in quotes:
        try:
            capture = ts(q.get("captured_at") or q.get("received_at"))
            semantics = str(q.get("source_timestamp_semantics") or "").upper()
            current_listing = (q.get("current_board_contract_verified") is True and
                               q.get("status") == "OPEN" and
                               semantics == "CURRENT_BOARD_CAPTURE_ONLY")
            update = capture if current_listing else ts(q["source_quote_at"])
        except (KeyError, ValueError):
            rejected_time.append(q)
            continue
        if update > cutoff:
            rejected_time.append(q)
            continue
        if capture > cutoff and not (mode == "RECONSTRUCTED_BACKFILL" and q.get("historical_quote_verified")):
            rejected_time.append(q)
            continue
        key = tuple(q.get(k) for k in ("event_id", "bookmaker_id", "market_type", "period", "ot_rule", "selection", "market_role"))
        old = groups.get(key)
        # Source quote time determines the sequence; capture time breaks ties.
        old_capture = ts((old or {}).get("captured_at") or (old or {}).get("received_at")) if old else None
        old_semantics = str((old or {}).get("source_timestamp_semantics") or "").upper()
        old_current_listing = bool(old and old.get("current_board_contract_verified") is True and
                                   old.get("status") == "OPEN" and
                                   old_semantics == "CURRENT_BOARD_CAPTURE_ONLY")
        old_update = old_capture if old_current_listing else ts(old["source_quote_at"]) if old else None
        if old is None or (update, capture) > (old_update, old_capture):
            groups[key] = q
    return list(groups.values()) + rejected_time


def consensus(quotes: Iterable[Mapping[str, Any]], contract_key: tuple[str, ...]) -> dict[str, Any]:
    """Caller supplies time-eligible quotes; one quote per BOOK, not per feed."""
    rows = list(quotes)
    if not rows:
        return {"line": None, "bookmaker_count": 0, "feed_count": 0, "operator_groups_verified": 0, "executable": False}
    for q in rows:
        if tuple(str(q.get(k, "")) for k in ("event_id", "market_type", "period", "ot_rule", "selection")) != contract_key:
            raise ContractError("Mixed consensus contracts")
        if q.get("ot_rule") not in RULES:
            raise ContractError("Unknown-rule quotes stay in an observation quarantine, not consensus")
    latest: dict[str, Mapping[str, Any]] = {}
    for q in rows:
        if q.get("status") != "OPEN" or not q.get("bookmaker_id"):
            continue
        b = q["bookmaker_id"]
        semantics = str(q.get("source_timestamp_semantics") or "").upper()
        current_listing = (q.get("current_board_contract_verified") is True and
                           q.get("status") == "OPEN" and
                           semantics == "CURRENT_BOARD_CAPTURE_ONLY")
        quote_time = ts(q.get("captured_at") or q.get("received_at")) if current_listing else ts(q["source_quote_at"])
        if b not in latest:
            latest[b] = q
            continue
        prior = latest[b]
        prior_semantics = str(prior.get("source_timestamp_semantics") or "").upper()
        prior_current_listing = (prior.get("current_board_contract_verified") is True and
                                 prior.get("status") == "OPEN" and
                                 prior_semantics == "CURRENT_BOARD_CAPTURE_ONLY")
        prior_time = ts(prior.get("captured_at") or prior.get("received_at")) if prior_current_listing else ts(prior["source_quote_at"])
        if quote_time > prior_time:
            latest[b] = q
    chosen = list(latest.values())
    if not chosen:
        return {"line": None, "bookmaker_count": 0, "feed_count": 0, "operator_groups_verified": 0, "executable": False}
    lines = [main_line(q["line"]) for q in chosen]
    groups = {q.get("independent_operator_group") for q in chosen} - {None, "", "UNKNOWN"}
    return {"line": median(lines), "bookmaker_count": len(chosen),
            "feed_count": len({q["feed_provider"] for q in rows}), "operator_groups_verified": len(groups),
            "min_line": min(lines), "max_line": max(lines), "executable": False,
            "note": "Statistical benchmark only; never combine median line with another book's price"}


def _solve(a: list[list[float]], b: list[float]) -> list[float]:
    n = len(b)
    aug = [list(row) + [b[i]] for i, row in enumerate(a)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(aug[r][col]))
        if abs(aug[pivot][col]) < 1e-12:
            raise ContractError("Singular regularized regression")
        aug[col], aug[pivot] = aug[pivot], aug[col]
        z = aug[col][col]
        aug[col] = [v / z for v in aug[col]]
        for r in range(n):
            if r == col:
                continue
            z = aug[r][col]
            aug[r] = [aug[r][j] - z * aug[col][j] for j in range(n + 1)]
    return [row[-1] for row in aug]


def _ridge(samples: list[tuple[list[float], float, float]], penalty: float) -> list[float]:
    n = len(samples[0][0])
    a = [[penalty if i == j else 0. for j in range(n)] for i in range(n)]
    b = [0.] * n
    for x, y, w in samples:
        for i in range(n):
            b[i] += w * x[i] * y
            for j in range(n):
                a[i][j] += w * x[i] * x[j]
    return _solve(a, b)


def independent_forecast(item: Mapping[str, Any], policy: Mapping[str, Any]) -> dict[str, Any]:
    """Price-blind opponent-adjusted score baseline. No quotes argument allowed.

    Fallback is separately versioned; NOT a pace/efficiency/roster impact model.
    HIGH_UNCERTAINTY or national teams require documented current roster context.
    All numerical policy values are research priors, not fitted calibration.
    """
    if any(k in item for k in ("quotes", "market", "odds", "closing", "outcome", "result")):
        raise ContractError("Price-blind input contains market/evaluation fields")
    event = item["event"]
    validate_event(event)
    mode, cutoff = item["archive_type"], ts(item["asof"])
    family = item["model_family"]
    p = policy["families"][family]
    identity = {k: event[k] for k in ("event_id", "team1_id", "team2_id", "team1_name", "team2_name", "tip_at")}
    base: dict[str, Any] = {"version": VERSION, "archive_type": mode, "event": identity,
        "asof": item["asof"], "model_family": family, "pricing_status": "UNPRICEABLE",
        "mu_margin": None, "mu_total": None, "team1_points": None, "team2_points": None,
        "probability_calibration_status": "UNVALIDATED", "real_stake": 0., "real_execution_allowed": False}
    if cutoff >= ts(event["tip_at"]):
        return dict(base, blockers=["TARGET_ALREADY_STARTED"])
    if item.get("ot_rule") not in RULES:
        return dict(base, blockers=["MODEL_SCORE_CONTRACT_UNKNOWN"])
    if family in {"NATIONAL_TEAM", "HIGH_UNCERTAINTY"}:
        context = item.get("roster_context", {})
        good, reason = evidence_eligible(context, cutoff, mode)
        if not good or not context.get("current_roster_confirmed"):
            return dict(base, blockers=["CURRENT_ROSTER_CONTEXT_REQUIRED", reason])
    filtered: list[Mapping[str, Any]] = []
    exclusions: list[dict[str, str]] = []
    for g in item.get("history", []):
        reason = None
        if g.get("event_id") == event["event_id"]:
            reason = "TARGET_GAME_EXCLUDED"
        elif any(g.get(k) != event.get(k) for k in ("competition_id", "gender", "age_group", "format_id")):
            reason = "COHORT_MISMATCH"
        elif g.get("score_rule") != item["ot_rule"]:
            reason = "SCORE_CONTRACT_MISMATCH"
        elif g.get("status") != "FINAL" or not g.get("ended_at") or ts(g["ended_at"]) >= cutoff:
            reason = "NOT_COMPLETED_BEFORE_CUTOFF"
        else:
            ok, why = evidence_eligible(g.get("evidence", {}), cutoff, mode)
            if not ok:
                reason = why
        if reason:
            exclusions.append({"event_id": str(g.get("event_id")), "reason": reason})
        else:
            filtered.append(g)
    counts = {t: sum(g["team1_id"] == t or g["team2_id"] == t for g in filtered) for t in (event["team1_id"], event["team2_id"])}
    if not filtered or min(counts.values()) < int(p["min_team_games"]):
        return dict(base, blockers=["INSUFFICIENT_PRE_CUTOFF_TEAM_GAMES"], input_games=len(filtered), team_game_counts=counts, excluded=exclusions)
    teams = sorted({g[k] for g in filtered for k in ("team1_id", "team2_id")})
    ix, n = {t: i for i, t in enumerate(teams)}, len(teams)
    ms, totals = [], []
    weighted_total_sum = weight_sum = 0.
    for g in filtered:
        a, b = finite(g["score1"]), finite(g["score2"])
        if a < 0 or b < 0 or not a.is_integer() or not b.is_integer():
            raise ContractError("History scores invalid")
        age = (cutoff - ts(g["ended_at"])).total_seconds() / 86400
        w = 2 ** (-age / finite(p["half_life_days"]))
        overlap = finite(g.get("roster_overlap", 1.))
        if not 0 <= overlap <= 1:
            raise ContractError("roster_overlap outside [0,1]")
        w *= overlap
        if w == 0:
            continue
        x = [0.] * (n + 1)
        x[ix[g["team1_id"]]], x[ix[g["team2_id"]]] = 1., -1.
        x[-1] = finite(g.get("home_sign", 0))
        if x[-1] not in {-1., 0., 1.}:
            raise ContractError("home_sign must be -1,0,+1")
        ms.append((x, a - b, w))
        xt = [0.] * n
        xt[ix[g["team1_id"]]] = xt[ix[g["team2_id"]]] = 1.
        totals.append((xt, a + b, w))
        weighted_total_sum += w * (a + b)
        weight_sum += w
    if not ms or weight_sum <= 0:
        return dict(base, blockers=["NO_EFFECTIVE_HISTORY"])
    beta_m = _ridge(ms, finite(p["ridge_lambda"]))
    league_total = weighted_total_sum / weight_sum
    beta_t = _ridge([(x, y - league_total, w) for x, y, w in totals], finite(p["ridge_lambda"]))
    h = finite(event.get("home_sign", 0.))
    if h not in {-1., 0., 1.}:
        raise ContractError("Invalid target home_sign")
    mu = beta_m[ix[event["team1_id"]]] - beta_m[ix[event["team2_id"]]] + h * beta_m[-1]
    total = league_total + beta_t[ix[event["team1_id"]]] + beta_t[ix[event["team2_id"]]]
    pts1, pts2 = (total + mu) / 2, (total - mu) / 2
    if min(pts1, pts2) < 0:
        return dict(base, blockers=["INVALID_SCORE_MEANS"])
    # No arbitrary multiply-margin-by-quality. Uncertainty is represented
    # through separate mean-sensitivity / residual parameters.
    return dict(base, pricing_status="PRICED_LOW_CONFIDENCE", mu_margin=mu, mu_total=total,
        mu_raw=mu, mu_structural=mu, structural_method="REGULARIZED_BASELINE_NO_SECOND_SHRINK",
        team1_points=pts1, team2_points=pts2, input_games=len(filtered), team_game_counts=counts,
        strength_method="PRICE_BLIND_OPPONENT_ADJUSTED_SCORE_RIDGE", total_method="SCORE_TOTAL_RIDGE_NOT_PACE_MODEL",
        sd_margin=finite(p["sd_margin_prior"]), sd_total=finite(p["sd_total_prior"]),
        df=finite(p["df"]), mean_sensitivity_margin=finite(p["mean_sensitivity_margin"]),
        mean_sensitivity_total=finite(p["mean_sensitivity_total"]),
        ot_rule=item["ot_rule"], uncertainty_source="UNVALIDATED_PRIOR", excluded=exclusions,
        blockers=[], input_fingerprint=digest(item))


def shadow_decision(event: Mapping[str, Any], forecast: Mapping[str, Any], q: Mapping[str, Any] | None,
                    asof: str, mode: str, policy: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {"event_id": event["event_id"], "asof": asof, "archive_type": mode,
        "model_state": "UNPRICEABLE" if forecast.get("mu_margin") is None else "UNASSESSED",
        "shadow_action": "BLOCKED", "display_action": "不可投", "real_stake": 0.,
        "real_bet_flag": False, "kelly_usable": False, "model_validation_ready": False,
        "real_execution_allowed": False, "triggered": False, "blockers": []}
    if ts(asof) >= ts(event["tip_at"]):
        out["blockers"].append("ALREADY_STARTED")
    if forecast.get("pricing_status") == "UNPRICEABLE":
        out["blockers"].append("UNPRICEABLE")
    if q is None:
        out["blockers"].append("NO_MARKET")
        if out["blockers"] == ["NO_MARKET"]:
            out.update(shadow_action="WATCH", display_action="观察")
        return out
    out["quote_id"] = q.get("quote_id", digest(q))
    ttl = int(policy["quote_ttl_seconds"])
    out["blockers"] += quote_blockers(q, event, asof, mode, ttl)
    if forecast.get("ot_rule") and q.get("ot_rule") in RULES and forecast["ot_rule"] != q["ot_rule"]:
        out["blockers"].append("CONTRACT_MISMATCH")
    if out["blockers"]:
        out["blockers"] = list(dict.fromkeys(out["blockers"]))
        return out
    p = quote_probability(forecast, q)
    # A separately named adverse-mean scenario, not an invented confidence bound.
    adverse = dict(forecast)
    if q["market_type"] == "SPREAD":
        adverse["mu_margin"] += (-1 if q["selection"] == "TEAM1" else 1) * forecast["mean_sensitivity_margin"]
    else:
        adverse["mu_total"] += (-1 if q["selection"] == "OVER" else 1) * forecast["mean_sensitivity_total"]
    conservative = quote_probability(adverse, q)
    stats, guarded = ev_and_kelly(p, q["decimal_odds"]), ev_and_kelly(conservative, q["decimal_odds"])
    delta = guarded["p_win_conditional_nonpush"] - guarded["conditional_breakeven"]
    limit = finite(policy["families"][forecast["model_family"]]["conditional_probability_buffer"])
    passed = guarded["ev"] >= finite(policy["minimum_ev"]) and delta >= limit
    state = "EDGE" if passed else "LEAN" if stats["ev"] > 0 else "NO_EDGE"
    out.update(model_state=state, shadow_action="SHADOW_BET" if passed else "PASS",
        display_action="纸面可投" if passed else "不可投", triggered=passed,
        p=asdict(p), adverse_scenario_p=asdict(conservative), ev=stats["ev"], adverse_scenario_ev=guarded["ev"],
        probability_calibration_status="UNVALIDATED", conservative_method="ADVERSE_MEAN_SCENARIO_NOT_STATISTICAL_LOWER_BOUND",
        conditional_edge=delta, buffer=limit, buffer_source="RESEARCH_PRIOR",
        theoretical_kelly=guarded["theoretical_kelly"], quote=dict(q))
    return out


def counters(decisions: Iterable[Mapping[str, Any]], eligible_scope_events: int) -> dict[str, Any]:
    rows = list(decisions)
    compared = [r for r in rows if "ev" in r]
    return {"scope_event_count": eligible_scope_events,
        "decision_event_count": len({r["event_id"] for r in rows}),
        "compared_event_count": len({r["event_id"] for r in compared}),
        "paper_bet_count": None if not compared else sum(bool(r.get("triggered")) for r in rows),
        "judgment": "暂不可判断：暂无同场同规则有效比较" if not compared else "已筛选样本内的纸面结果，不代表全市场",
        "real_execution_allowed": False}
