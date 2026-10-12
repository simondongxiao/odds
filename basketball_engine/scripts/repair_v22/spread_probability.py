"""Auditable spread uncertainty, residual and probability utilities.

This module is deliberately independent of market collection and model fitting.
It may read already-frozen OOS residuals, but it never feeds a market line back
into the independent fair-price calculation.
"""
from __future__ import annotations

import csv
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, median, pstdev
from .common import atomic


def _finite(value):
    return isinstance(value, (int, float)) and math.isfinite(float(value))


def quantile(values, probability):
    xs = sorted(float(v) for v in values if _finite(v))
    if not xs:
        return None
    if len(xs) == 1:
        return xs[0]
    p = min(1.0, max(0.0, float(probability)))
    pos = (len(xs) - 1) * p
    lo, hi = int(math.floor(pos)), int(math.ceil(pos))
    if lo == hi:
        return xs[lo]
    return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)


def interval_from_samples(values):
    xs = [float(v) for v in values if _finite(v)]
    if not xs:
        return {'sample_N': 0, 'standard_error': None, 'interval_80': None, 'interval_95': None}
    return {
        'sample_N': len(xs),
        'standard_error': pstdev(xs) if len(xs) > 1 else None,
        'interval_80': [quantile(xs, .10), quantile(xs, .90)],
        'interval_95': [quantile(xs, .025), quantile(xs, .975)],
    }


def block_bootstrap_predictions(games, predict_margin, reps=48, seed=20261004):
    """Resample complete time blocks and refit through ``predict_margin``.

    ``predict_margin(sample)`` must run the same pre-cutoff model fit as the
    Champion.  The function only controls the time-block resampling and never
    sees market lines.
    """
    rows = [g for g in games if isinstance(g, dict) and g.get('tip_at')]
    if len(rows) < 6:
        return []
    blocks = defaultdict(list)
    for row in rows:
        # Week blocks preserve same-day / short-window correlation better than
        # iid row bootstrap while remaining deterministic for audit replay.
        day = str(row.get('tip_at', ''))[:10]
        blocks[day[:8] + str((int(day[-2:]) if day[-2:].isdigit() else 1) // 7)].append(row)
    block_values = list(blocks.values())
    if len(block_values) < 2:
        return []
    state = int(seed) & 0x7fffffff
    predictions = []
    for _ in range(int(reps)):
        sample = []
        for _ in range(len(block_values)):
            state = (1103515245 * state + 12345) & 0x7fffffff
            sample.extend(block_values[state % len(block_values)])
        try:
            value = predict_margin(sample)
        except (KeyError, TypeError, ValueError, ZeroDivisionError):
            value = None
        if _finite(value):
            predictions.append(float(value))
    return predictions


def _log_student_t_pdf(x, df, scale):
    scale = max(float(scale), 1e-9)
    df = max(float(df), 2.01)
    return (math.lgamma((df + 1) / 2) - math.lgamma(df / 2)
            - .5 * math.log(df * math.pi) - math.log(scale)
            - ((df + 1) / 2) * math.log1p((x / scale) ** 2 / df))


def fit_student_t(residuals, min_n=8):
    """Robust grid MLE for a Student-t residual prior.

    The stored ``sd`` follows the existing t_cdf contract (standard
    deviation), while ``scale`` is the Student-t scale parameter.
    """
    xs = [float(v) for v in residuals if _finite(v)]
    if len(xs) < min_n:
        return {'fit_status': 'INSUFFICIENT_OOS', 'sample_N': len(xs), 'df': None,
                'scale': None, 'sd': None, 'median': median(xs) if xs else None,
                'mae': mean(abs(x) for x in xs) if xs else None,
                'rmse': math.sqrt(mean(x * x for x in xs)) if xs else None}
    center = median(xs)
    centered = [x - center for x in xs]
    mad = median(abs(x) for x in centered)
    robust_sd = max(1e-6, 1.4826 * mad)
    candidates = []
    for df in (3, 4, 5, 6, 7, 8, 10, 12, 15, 20, 30):
        # For t, variance = scale^2 * df/(df-2).  Use robust and empirical
        # scales, then select by likelihood; this is not a market-fitted prior.
        empirical_sd = math.sqrt(mean(x * x for x in centered))
        scale = max(1e-6, min(empirical_sd, robust_sd * 1.35) * math.sqrt((df - 2) / df))
        nll = -sum(_log_student_t_pdf(x, df, scale) for x in centered)
        candidates.append((nll, df, scale))
    _, df, scale = min(candidates, key=lambda item: item[0])
    sd = scale * math.sqrt(df / (df - 2))
    return {'fit_status': 'OOS_EMPIRICAL', 'sample_N': len(xs), 'df': float(df),
            'scale': float(scale), 'sd': float(sd), 'median': median(xs),
            'mae': mean(abs(x) for x in centered),
            'rmse': math.sqrt(mean(x * x for x in centered))}


def context_bucket(data_quality, context_quality=None):
    if context_quality in {'context_complete', 'context_partial', 'context_sparse'}:
        return context_quality
    return {'DATA_QUALITY_A': 'context_complete',
            'DATA_QUALITY_B': 'context_partial',
            'DATA_QUALITY_C': 'context_sparse',
            'DATA_QUALITY_D': 'context_sparse'}.get(data_quality, 'context_sparse')


def residual_profile(records, league=None, tier=None, season_regime=None,
                     pricing_mode=None, data_quality=None, context_quality=None, min_league=30,
                     min_global=60, prior_sd=None, prior_df=None):
    """Select empirical residuals with hierarchical shrinkage metadata."""
    def filt(**criteria):
        return [r for r in records if all(criteria[k] is None or r.get(k) == criteria[k] for k in criteria)
                and _finite(r.get('calibrated_residual', r.get('raw_residual')))]

    exact = filt(league=league, season_regime=season_regime, pricing_mode=pricing_mode,
                 data_quality=data_quality)
    league_rows = filt(league=league)
    tier_rows = filt(tier=tier)
    global_rows = filt()
    chosen, source = [], 'TIER_PRIOR'
    if len(league_rows) >= min_league:
        chosen, source = league_rows, 'LEAGUE_EMPIRICAL'
    elif len(global_rows) >= min_global:
        chosen, source = global_rows, 'GLOBAL_EMPIRICAL'
    elif len(tier_rows) >= min_league:
        chosen, source = tier_rows, 'TIER_EMPIRICAL'
    stats = fit_student_t([r.get('calibrated_residual', r.get('raw_residual')) for r in chosen])
    if stats.get('fit_status') != 'OOS_EMPIRICAL':
        stats.update({'df': prior_df, 'sd': prior_sd,
                      'scale': (prior_sd * math.sqrt((prior_df - 2) / prior_df)
                                if _finite(prior_sd) and _finite(prior_df) and prior_df > 2 else None)})
    context_rows = {bucket: fit_student_t([
        r.get('calibrated_residual', r.get('raw_residual')) for r in global_rows
        if context_bucket(r.get('data_quality'), r.get('context_quality')) == bucket])
                    for bucket in ('context_complete', 'context_partial', 'context_sparse')}
    base = context_rows.get('context_complete') or {}
    current = context_rows.get(context_bucket(data_quality)) or {}
    increment = None
    if _finite(current.get('mae')) and _finite(base.get('mae')):
        increment = max(0.0, float(current['mae']) - float(base['mae']))
    return {
        **stats, 'source': source, 'sample_N': int(stats.get('sample_N') or 0),
        'league_sample_N': len(league_rows), 'exact_sample_N': len(exact),
        'tier_sample_N': len(tier_rows), 'global_sample_N': len(global_rows),
        'context_uncertainty_increment': increment,
        'context_profiles': context_rows,
        'fallback_order': ['LEAGUE_EMPIRICAL', 'GLOBAL_EMPIRICAL', 'TIER_EMPIRICAL', 'TIER_PRIOR'],
    }


def market_gap_percentile(gaps, current_gap):
    xs = sorted(float(x) for x in gaps if _finite(x))
    if not _finite(current_gap) or not xs:
        return None
    return sum(x <= float(current_gap) for x in xs) / len(xs)


def information_risk(context_complete=False, fair_center_se=None,
                     disagreement_percentile=None, path_status=None,
                     source_quality=None):
    score = 0
    if not context_complete:
        score += 1
    if not _finite(fair_center_se):
        score += 1
    elif fair_center_se > 5:
        score += 2
    if _finite(disagreement_percentile) and (disagreement_percentile > .95 or disagreement_percentile < .05):
        score += 2
    if path_status == 'MARKET_DIVERGENCE':
        score += 1
    if source_quality in {'C', 'D', 'SOURCE_DEGRADED'}:
        score += 1
    return 'HIGH' if score >= 4 else 'MEDIUM' if score >= 2 else 'LOW'


def direction_robustness(fair_center_interval, market_threshold, selection):
    interval = fair_center_interval or []
    if len(interval) != 2 or not all(_finite(v) for v in interval) or not _finite(market_threshold):
        return None
    low, high = min(interval), max(interval)
    if selection == 'TEAM1':
        return low > float(market_threshold)
    if selection == 'TEAM2':
        return high < float(market_threshold)
    return None


def probability_fields(wpl, odds):
    d = float(odds)
    active = float(wpl.win + wpl.loss)
    conditional = wpl.win / active if active else None
    conditional_be = 1.0 / d
    unconditional_be = (1.0 - wpl.push) / d
    return {
        'p_win': float(wpl.win), 'p_push': float(wpl.push), 'p_loss': float(wpl.loss),
        'probability_sum': float(wpl.win + wpl.push + wpl.loss),
        'conditional_model_win_probability': conditional,
        'conditional_break_even_probability': conditional_be,
        'break_even_win_probability': unconditional_be,
        'probability_edge': (conditional - conditional_be) if conditional is not None else None,
        'ev': float(wpl.win * (d - 1.0) - wpl.loss),
    }


def student_t_quantile(probability, cdf):
    """Numerically invert an existing Student-t CDF without adding scipy."""
    p = min(1.0 - 1e-9, max(1e-9, float(probability)))
    lo, hi = -1000.0, 1000.0
    for _ in range(80):
        mid = (lo + hi) / 2.0
        if cdf(mid) < p:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def calibration_metrics(records):
    rows = [r for r in records if _finite(r.get('probability')) and r.get('outcome') in {'WIN', 'LOSS'}]
    buckets = [(0.50, .52), (.52, .54), (.54, .56), (.56, .58), (.58, .60), (.60, .65), (.65, 1.01)]
    reliability = []
    for lo, hi in buckets:
        part = [r for r in rows if lo <= r['probability'] < hi]
        if part:
            observed = sum(r['outcome'] == 'WIN' for r in part) / len(part)
            reliability.append({'bucket': f'{lo:.2f}-{min(1, hi):.2f}', 'N': len(part),
                                'mean_probability': mean(r['probability'] for r in part),
                                'observed_win_rate': observed})
    brier = mean((r['probability'] - (1 if r['outcome'] == 'WIN' else 0)) ** 2 for r in rows) if rows else None
    logloss = None
    if rows:
        vals = []
        for r in rows:
            p = min(1 - 1e-12, max(1e-12, r['probability']))
            vals.append(-math.log(p if r['outcome'] == 'WIN' else 1 - p))
        logloss = mean(vals)
    return {'N': len(rows), 'brier': brier, 'log_loss': logloss,
            'reliability_curve': reliability, 'ece': (
                sum(abs(x['mean_probability'] - x['observed_win_rate']) * x['N'] for x in reliability) / len(rows)
                if rows else None)}


def append_oos_residuals(path, records):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    existing = set()
    if path.exists():
        with path.open('r', encoding='utf-8') as f:
            for line in f:
                try:
                    row = json.loads(line)
                    existing.add(row.get('prediction_id'))
                except json.JSONDecodeError:
                    continue
    new_rows = [r for r in records if r.get('prediction_id') not in existing]
    if new_rows:
        with path.open('a', encoding='utf-8') as f:
            for row in new_rows:
                f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + '\n')
    return {'path': str(path), 'existing_N': len(existing), 'appended_N': len(new_rows),
            'total_N': len(existing) + len(new_rows), 'append_only': True}


def load_oos_residuals(path):
    path = Path(path)
    if not path.exists():
        return []
    rows = []
    with path.open('r', encoding='utf-8') as f:
        for line in f:
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if item.get('oos_flag') is True and _finite(item.get('raw_residual')):
                rows.append(item)
    return rows


def residual_rows_from_analytics(analytics):
    """Convert only settled Forward Native first-write records to OOS rows."""
    rows = []
    for item in (analytics or {}).get('records', []):
        if item.get('record_generation') != 'FORWARD_NATIVE_FIRST_WRITE':
            continue
        evaluation = item.get('evaluation') or {}
        if not _finite(evaluation.get('score1')) or not _finite(evaluation.get('score2')):
            continue
        predicted = item.get('fair_margin')
        if not _finite(predicted):
            continue
        actual = float(evaluation['score1']) - float(evaluation['score2'])
        rows.append({
            'prediction_id': item.get('prediction_id'), 'event_id': item.get('event_id'),
            'prediction_timestamp': item.get('first_write_at'), 'event_time': item.get('tip_at'),
            'model_version': item.get('model_version'), 'league': item.get('league'),
            'tier': item.get('tier'), 'season': str(item.get('tip_at') or '')[:4],
            'season_regime': item.get('season_regime') or 'REGULAR',
            'pricing_mode': item.get('pricing_mode') or item.get('model_family'),
            'data_quality': item.get('data_quality') or 'UNKNOWN',
            'context_quality': item.get('context_quality') or 'context_sparse',
            'raw_predicted_margin': float(predicted), 'calibrated_predicted_margin': item.get('calibrated_fair_spread'),
            'actual_margin': actual, 'raw_residual': actual - float(predicted),
            'calibrated_residual': (actual - float(item['calibrated_fair_spread'])
                                    if _finite(item.get('calibrated_fair_spread')) else actual - float(predicted)),
            'spread_bucket': 'DEEP_SPREAD' if abs(float(predicted)) >= 15 else 'NORMAL_SPREAD',
            'forward_native': True, 'oos_flag': True,
        })
    return rows


def build_spread_probability_audit(root, rows, residuals, asof, day):
    """Write read-only uncertainty/EV validation artifacts for the dashboard."""
    root=Path(root); cards=[]; comparable=[]
    for row in rows:
        event=row.get('event') or {}; pricing=row.get('pricing') or {}; execution=row.get('execution') or {}
        selected=execution.get('selected') or {}
        if not selected or selected.get('market_type') != 'SPREAD':
            continue
        decomposition=selected.get('pricing_decomposition') or {}
        card={
            'game_id': row.get('id'), 'league': event.get('league_family') or event.get('league'),
            'home_team': event.get('team1_name'), 'away_team': event.get('team2_name'),
            'start_time': event.get('tip_time_bj') or event.get('tip_at'),
            'raw_fair_spread': pricing.get('raw_fair_spread'),
            'calibrated_fair_spread': pricing.get('calibrated_fair_spread'),
            'fair_center_standard_error': pricing.get('fair_center_standard_error'),
            'fair_center_interval_80': pricing.get('fair_center_interval_80'),
            'fair_center_interval_95': pricing.get('fair_center_interval_95'),
            'game_outcome_prediction_interval_80': pricing.get('game_outcome_prediction_interval_80'),
            'game_outcome_prediction_interval_95': pricing.get('game_outcome_prediction_interval_95'),
            'market_spread': selected.get('line'), 'market_odds': selected.get('decimal_odds'),
            'line_edge_points': decomposition.get('model_market_gap'),
            'p_win': selected.get('p_win'), 'p_push': selected.get('p_push'), 'p_loss': selected.get('p_loss'),
            'break_even_win_probability': selected.get('break_even_win_probability'),
            'conditional_break_even_probability': selected.get('conditional_break_even_probability'),
            'probability_edge': selected.get('probability_edge'), 'ev': selected.get('ev'),
            'residual_source': pricing.get('residual_source'), 'residual_N': pricing.get('residual_oos_N'),
            'student_t_df': pricing.get('student_t_df'), 'student_t_scale': pricing.get('student_t_scale'),
            'direction_robust_80': selected.get('direction_robust_80'),
            'information_risk': selected.get('information_risk'),
            'market_path_status': selected.get('market_path_status'),
            'market_disagreement_percentile': selected.get('market_disagreement_percentile'),
            'decision': 'QUALIFIED' if execution.get('triggered') else ('NO_EDGE' if execution.get('model_state') == 'NO_EDGE' else 'PROVISIONAL'),
            'market_inputs_used_in_fair_price': False,
        }
        cards.append(card)
        comparable.append({
            'game_id': row.get('id'), 'league': card['league'], 'market_type':'SPREAD',
            'home_team':card['home_team'], 'away_team':card['away_team'], 'start_time':card['start_time'],
            'pricing_mode':pricing.get('pricing_state'), 'market_line':selected.get('line'),
            'raw_fair_line':pricing.get('raw_fair_spread'), 'raw_edge_points':decomposition.get('model_market_gap'),
            'raw_probability':selected.get('p_win'), 'calibrated_fair_line':pricing.get('calibrated_fair_spread'),
            'calibrated_edge_points':None, 'adjusted_probability':None, 'adjusted_EV':None,
            'residual_scale':pricing.get('residual_scale_breakdown',{}).get('final_spread'),
            'league_residual_multiplier':pricing.get('residual_scale_breakdown',{}).get('league'),
            'meta_confidence':pricing.get('spread_data_quality'), 'model_weight':1.0, 'market_weight':0.0,
            'data_quality':pricing.get('spread_data_quality'), 'evidence_status':execution.get('blockers'),
            'execution_score':selected.get('conditional_edge'), 'edge_retention_ratio':None,
            'primary_final_reason':None if execution.get('triggered') else (execution.get('blockers') or ['NO_EDGE'])[0],
            'secondary_warnings':pricing.get('model_warnings',[]),
        })
    summary={
        'schema_version':'spread-probability-ev-audit-1.0', 'asof':asof, 'date_bj':day,
        'fair_center_method':'BLOCK_BOOTSTRAP_TIME_BLOCK',
        'residual_method':'OOS_FORWARD_NATIVE_ONLY_STUDENT_T_HIERARCHICAL',
        'residual_records_N':len(residuals), 'cards_N':len(cards), 'decision_cards':cards,
        'calibration':calibration_metrics([]),
        'push_method':'DISCRETE_OOS_MARGIN_OR_STUDENT_T_HALF_POINT_LATTICE',
        'information_risk_definition':'context completeness + fair-center uncertainty + market gap percentile + market path + source quality',
        'market_inputs_used_in_fair_price':False, 'real_execution_allowed':False,
    }
    atomic(root/'diagnostics'/('uncertainty_audit_'+day.replace('-','')+'.json'),summary)
    write_comparable_csv(root/'diagnostics'/('comparable_edge_'+day+'.csv'),comparable)
    validation=(
        '# Spread Probability / EV Validation\n\n'
        f'- OOS residual ledger records: **{len(residuals)}**\n'
        f'- Decision cards generated: **{len(cards)}**\n'
        '- Fair center and game-outcome intervals are separate fields.\n'
        '- Residuals use `actual_margin - predicted_margin`; only Forward Native settled records enter the ledger.\n'
        '- Integer spreads use explicit W/P/L probabilities; push returns zero EV.\n'
        '- EV is `P(win) × (odds - 1) - P(loss)`; market data is read only after fair-price freeze.\n'
        '- Tier multipliers remain cold-start priors until the configured OOS sample threshold is met.\n'
        '- This report is diagnostic and does not lower Edge/EV gates or enable execution.\n'
    )
    (root/'diagnostics'/'spread_probability_ev_validation.md').write_text(validation,encoding='utf-8')
    return summary


def write_comparable_csv(path, rows):
    fields = ['game_id', 'league', 'market_type', 'home_team', 'away_team', 'start_time',
              'pricing_mode', 'market_line', 'raw_fair_line', 'raw_edge_points',
              'raw_probability', 'calibrated_fair_line', 'calibrated_edge_points',
              'adjusted_probability', 'adjusted_EV', 'residual_scale',
              'league_residual_multiplier', 'meta_confidence', 'model_weight',
              'market_weight', 'data_quality', 'evidence_status', 'execution_score',
              'edge_retention_ratio', 'primary_final_reason', 'secondary_warnings']
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore'); writer.writeheader()
        for row in rows:
            writer.writerow({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v
                             for k, v in row.items()})
    return {'path': str(path), 'rows': len(rows), 'fields': fields}
