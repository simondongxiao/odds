from __future__ import annotations
import math
import yaml
from collections import Counter, defaultdict
from datetime import timedelta
from pathlib import Path
from statistics import median
from .common import iso, stamp, fingerprint, competition_key, durable_competition_key, load
from .verified_core import _ridge, t_cdf, threshold_probability, ev_and_kelly, display_fair_margin, margin_cdf
from .tier_policy import tier_for, evaluation_channel
from .score_context import build_score_context
from .evidence_context import evaluate_tier3_roster_stability
from .pace_evidence import enrich_possessions_context
from .spread_probability import (block_bootstrap_predictions, interval_from_samples,
                                 probability_fields, residual_profile,
                                 direction_robustness, information_risk,
                                 quantile, student_t_quantile,
                                 market_gap_percentile)

MODEL_VERSION='score-ridge-production-2.4.0'
MARKET_INTEGRITY=load(Path(__file__).resolve().parents[2]/'config'/'market_integrity.json',{
 'minimum_fresh_main_quotes':2,'max_deviation_from_cross_book_median':{'SPREAD':4.0,'TOTAL':8.0}})
MARKET_CONTRACTS=load(Path(__file__).resolve().parents[2]/'config'/'repair_market_contracts.json',{})
FULL_GAME_CONTRACT=MARKET_CONTRACTS.get('global_full_game_contract') or {
    'overtime_rule':'INCLUDING_OT',
    'unknown_source_rule_handling':'ASSUME_INCLUDING_OT_WITH_AUDIT',
    'policy_evidence':'USER_CONFIRMED_GLOBAL_FULL_GAME_INCLUDING_OT_2026-10-08',
}
POLICY={
 'CLUB_MATURE':dict(min_games=3,max_days=550,half_life=90,ridge=8,sd_margin=13,sd_total=18,df=7,mean_margin=2,mean_total=3,buffer=.025),
 'NATIONAL_TEAM':dict(min_games=3,max_days=730,half_life=180,ridge=12,sd_margin=16,sd_total=20,df=6,mean_margin=3,mean_total=4,buffer=.045),
 'HIGH_UNCERTAINTY':dict(min_games=3,max_days=180,half_life=45,ridge=16,sd_margin=19,sd_total=25,df=5,mean_margin=4,mean_total=5,buffer=.08)}


def _cold_start_config():
    path = Path(__file__).resolve().parents[2] / 'config' / 'cold_start_pricing.yaml'
    try:
        return yaml.safe_load(path.read_text(encoding='utf-8')) or {}
    except (OSError, yaml.YAMLError):
        return {}


COLD_START = _cold_start_config()


def _total_evidence_policy():
    path = Path(__file__).resolve().parents[2] / 'config' / 'total_evidence_policy.yaml'
    try:
        return yaml.safe_load(path.read_text(encoding='utf-8')) or {}
    except (OSError, yaml.YAMLError):
        return {}


TOTAL_EVIDENCE_POLICY = _total_evidence_policy()
SHADOW_POLICY = load(Path(__file__).resolve().parents[2]/'config'/'shadow_learning_policy.json',{})
SPREAD_CONTEXT_POLICY = load(Path(__file__).resolve().parents[2]/'config'/'spread_context_uncertainty_policy.json',{})


def season_regime_for(event):
    """Classify the competition phase without inferring player availability."""
    text = ' '.join(str(event.get(key) or '') for key in
                    ('league', 'league_family', 'competition_key', 'model_family', 'season_phase')).upper()
    if any(token in text for token in ('SUMMER', '夏季', 'SUMMER_LEAGUE')):
        return 'SUMMER_LEAGUE'
    if any(token in text for token in ('PRESEASON', 'PRE-SEASON', '季前', '热身', 'WARMUP')):
        return 'PRESEASON'
    if any(token in text for token in ('PLAYOFF', '季后', '季後', '淘汰')):
        return 'PLAYOFF'
    # A season phase explicitly marked early is authoritative; otherwise the
    # competition remains regular season rather than guessing from the date.
    if any(token in text for token in ('EARLY_REGULAR', 'EARLY-REGULAR', '常规初期')):
        return 'EARLY_REGULAR'
    return 'REGULAR'

def paper_history_minimum(event):
    """Per-team history gate for verified compact preseason/KBL feeds."""
    return 4 if season_regime_for(event) == 'PRESEASON' or _competition_family(event) == 'KOREA_KBL' else 8


def _context_adjustment_layer(context):
    """Return explicit adjustment layers; missing is UNKNOWN, never zero."""
    aliases = {
        'PLAYER_AVAILABILITY_ADJUSTMENT': ('injury_adjustment_points', 'player_availability_adjustment_points', 'availability_adjustment_points'),
        'ROTATION_ADJUSTMENT': ('rotation_adjustment_points', 'rotation_expected_minutes_adjustment_points'),
        'CURRENT_TEAM_STRENGTH_ADJUSTMENT': ('current_team_strength_adjustment_points', 'net_rating_adjustment_points'),
    }
    layers = []
    for name, keys in aliases.items():
        value = next((context.get(key) for key in keys
                      if isinstance(context.get(key), (int, float)) and not isinstance(context.get(key), bool)), None)
        if value is not None:
            layers.append({'layer': name, 'value_points': float(value), 'adjustment_applied': True,
                           'status': 'AVAILABLE', 'reason': 'EXPLICIT_CUTOFF_ADJUSTMENT'})
            continue
        if name == 'PLAYER_AVAILABILITY_ADJUSTMENT' and str(context.get('injury_status') or '').upper() in ('KNOWN_NO_INJURY', 'NO_INJURY'):
            status, reason = 'KNOWN_NO_INJURY', 'KNOWN_NO_INJURY_NO_ADJUSTMENT'
        elif name == 'ROTATION_ADJUSTMENT' and context.get('rotation_continuity_verified'):
            status, reason = 'CONTINUITY_ONLY', 'ROTATION_CONTINUITY_WITHOUT_EXPECTED_MINUTES'
        elif name == 'CURRENT_TEAM_STRENGTH_ADJUSTMENT' and context.get('net_rating_context_verified'):
            status, reason = 'AVAILABLE_BASE_FEATURE', 'NET_RATING_USED_IN_BASE_MODEL'
        else:
            status, reason = 'UNKNOWN', 'DATA_UNAVAILABLE'
        layers.append({'layer': name, 'value_points': None, 'adjustment_applied': False,
                       'status': status, 'reason': reason})
    applied = sum(item['value_points'] for item in layers if item['adjustment_applied'])
    return {'layers': layers, 'total_adjustment_points': applied,
            'adjustment_applied': bool(any(item['adjustment_applied'] for item in layers)),
            'unknown_layers': [item['layer'] for item in layers if item['status'] == 'UNKNOWN']}


def _spread_uncertainty(context, season_regime):
    unknown = SPREAD_CONTEXT_POLICY.get('unknown_context') or {}
    regime = (SPREAD_CONTEXT_POLICY.get('season_regime') or {}).get(season_regime) or {}
    injury_known = bool(context.get('injury_verified')) or str(context.get('injury_status') or '').upper() in ('KNOWN_NO_INJURY', 'NO_INJURY')
    rotation_known = bool(context.get('rotation_or_expected_minutes_verified') or
                          context.get('rotation_verified') or context.get('roster_verified') or
                          context.get('rotation_continuity_verified'))
    injury_multiplier = 1.0 if injury_known else float(unknown.get('injury', 1.10))
    rotation_multiplier = 1.0 if rotation_known else float(unknown.get('rotation', 1.10))
    regime_multiplier = float(regime.get('residual_multiplier', 1.0))
    context_multiplier = max(injury_multiplier, rotation_multiplier, regime_multiplier)
    return {'injury_uncertainty_multiplier': injury_multiplier,
            'rotation_uncertainty_multiplier': rotation_multiplier,
            'season_regime_multiplier': regime_multiplier,
            'context_uncertainty_multiplier': context_multiplier,
            'combine_rule': SPREAD_CONTEXT_POLICY.get('combine_rule', 'MAX_OF_CONTEXT_PENALTIES'),
            'historical_weight_multiplier': float(regime.get('historical_weight_multiplier', 1.0)),
            'historical_weight_after_days': float(regime.get('historical_weight_after_days', 99999))}


def _spread_data_quality(context, counts, opponents, foundation):
    complete = all(bool(context.get(key)) for key in
                   ('injury_verified', 'rotation_or_expected_minutes_verified', 'net_rating_context_verified'))
    base_ready = min(counts.values(), default=0) >= 3 and min((len(value) for value in opponents.values()), default=0) >= 2
    if complete:
        return 'DATA_QUALITY_A'
    if base_ready:
        return 'DATA_QUALITY_B' if any(bool(context.get(key)) for key in
                                       ('injury_verified', 'rotation_or_expected_minutes_verified', 'net_rating_context_verified',
                                        'rotation_continuity_verified')) else 'DATA_QUALITY_C'
    return 'DATA_QUALITY_C' if base_ready else 'DATA_QUALITY_D'


def _challenger_outputs(foundation, ridge_margin=None, ridge_total=None):
    """Expose model-isolated fair prices without silently blending models."""
    foundation = dict(foundation or {})
    model_b = dict(foundation.get('model_b') or {})
    model_c = dict(foundation.get('model_c') or {})
    ensemble = dict(foundation.get('ensemble') or {})
    hybrid = None
    titan_total = foundation.get('technical_fair_total')
    if isinstance(ridge_margin, (int, float)) and isinstance(titan_total, (int, float)):
        hybrid = {
            'fair_margin': ridge_margin, 'fair_total': titan_total,
            'fair_team1_score': (titan_total + ridge_margin) / 2,
            'fair_team2_score': (titan_total - ridge_margin) / 2,
            'method': 'SCORE_RIDGE_MARGIN_PLUS_TITAN_PACE_TOTAL_NO_AVERAGING',
        }
    return {
        'RAW_SCORE_RIDGE': {'fair_margin': ridge_margin, 'fair_total': ridge_total,
                            'model_role': 'CHAMPION'},
        'A_SCORE_RIDGE_PLUS_TITAN_PACE': hybrid,
        'B_SCORE_RIDGE_PLUS_PACE_EFFICIENCY': model_b or None,
        'C_SCORE_RIDGE_PLUS_FOUR_FACTORS': ({'status': model_c.get('status'),
                                             'top_factors': foundation.get('top_factors')}
                                            if foundation.get('top_factors') else None),
        'D_SCORE_RIDGE_PLUS_MATCHUP_TACTICAL': model_c or None,
        'E_TITAN_POSSESSION_EFFICIENCY': model_b or None,
        'F_ENSEMBLE': ({**ensemble, 'promotion_eligible': False,
                        'weight_source': 'CAPABILITY_RULE_NOT_WALK_FORWARD',
                        'required_for_promotion': 'STRICT_FORWARD_NATIVE_WALK_FORWARD'}
                       if ensemble else None),
        'simple_average_used': False, 'market_inputs_used': False,
    }


def _bootstrap_match(event, game):
    """Return a conservative bootstrap relation, never a generic label match.

    H2H rows are deliberately excluded. Cross-season and cross-competition
    borrowing is restricted to TEAM_HISTORY rows with the same gender and a
    recognized competition family (or a national-team window).
    """
    if game.get('evidence_kind') != 'TEAM_HISTORY' or game.get('gender') != event.get('gender'):
        return None
    matched = competition_match(event, game)
    if matched:
        return matched
    family = str(event.get('model_family') or '')
    ekey = _competition_family(event)
    gkey = _competition_family(game)
    if family == 'NATIONAL_TEAM':
        return 'NATIONAL_WINDOW' if ekey or gkey else None
    professional = {
        'NBA', 'WNBA', 'EUROLEAGUE', 'EUROCUP', 'EUROLEAGUE_WOMEN',
        'EUROCUP_WOMEN', 'FIBA_EUROPE_CUP', 'ENBL', 'EUROPE_DOMESTIC',
        'AUSTRALIA_NBL', 'AUSTRALIA_WNBL', 'JAPAN_BLEAGUE', 'KOREA_KBL',
        'CBA_REGULAR', 'CBA_PLAYOFF', 'B_LEAGUE',
    }
    if family in ('CLUB_MATURE', 'HIGH_UNCERTAINTY') and ekey in professional and gkey in professional:
        return 'CROSS_COMPETITION_ADJUSTED'
    return None


def _competition_family(item):
    """Return a phase-independent competition family for safe bootstrap joins.

    A provider may label the same NBA team history as ``NBA`` while the target
    is labelled ``NBA季前``.  The phase is already handled separately by
    ``season_regime_for``; using the raw phase label here incorrectly turns a
    valid prior-season history join into a cold-start failure.
    """
    explicit = str(item.get('league_family') or '').upper().strip()
    text = ' '.join(str(item.get(key) or '') for key in
                    ('league_family', 'competition_key', 'league')).upper()
    if explicit in {'NBA', 'WNBA', 'EUROLEAGUE', 'EUROLEAGUE_WOMEN', 'EUROCUP',
                    'EUROCUP_WOMEN', 'FIBA_EUROPE_CUP', 'ENBL', 'AUSTRALIA_NBL',
                    'AUSTRALIA_WNBL', 'JAPAN_BLEAGUE', 'KOREA_KBL', 'B_LEAGUE',
                    'CBA_REGULAR', 'CBA_PLAYOFF'}:
        return explicit
    if 'WNBA' in text or '美国女子职业篮球' in text:
        return 'WNBA'
    if 'NBA' in text or '美国男子职业篮球' in text:
        return 'NBA'
    if 'EUROLEAGUE' in text or '欧洲篮球冠军联赛' in text:
        return 'EUROLEAGUE'
    if 'EUROCUP' in text or '欧洲篮球联盟杯' in text:
        return 'EUROCUP'
    if 'CBA' in text or '中国男子篮球职业联赛' in text:
        return 'CBA_PLAYOFF' if '季后' in text or 'PLAYOFF' in text else 'CBA_REGULAR'
    return str(item.get('competition_key') or competition_key(item.get('league'), item.get('gender')) or '').upper()


def _nba_cba_spread_context_is_soft(event):
    """NBA/CBA lineup context changes uncertainty, not spread existence.

    This also covers preseason labels.  Phase risk is already represented by
    ``season_regime_multiplier`` and must not be counted a second time as a
    roster-stability hard gate.
    """
    return _competition_family(event) in {'NBA', 'CBA_REGULAR', 'CBA_PLAYOFF'}


def _season_bucket(game, cutoff):
    age = max(0.0, (iso(cutoff) - iso(game['tip_at'])).total_seconds() / 86400.0)
    if age <= 180:
        return 'current_season'
    if age <= 450:
        return 'previous_season'
    return 'older_history'


def _competition_adjustment(relation, game):
    if relation == 'NATIONAL_WINDOW':
        key = 'NATIONAL_WINDOW'
    elif relation == 'CROSS_COMPETITION_ADJUSTED':
        label = str(game.get('competition_key') or game.get('league') or '').lower()
        key = 'CUP' if any(x in label for x in ('cup', '杯')) else 'TIER2_DOMESTIC'
    elif relation in ('NATIVE', 'CANONICAL_SOURCE_LABEL', 'CROSS_SOURCE_CANONICAL_LEAGUE', 'EXACT_SOURCE_ID'):
        key = 'SAME_COMPETITION'
    else:
        key = 'UNKNOWN'
    return key, float((COLD_START.get('competition_adjustments') or {}).get(key, 0.55))


def _bootstrap_history(event, history, cutoff, mode, native, rejections):
    """Add only time-valid TEAM_HISTORY facts for cold-start research."""
    c = iso(cutoff)
    p = POLICY[event['model_family']]
    max_age = float((COLD_START.get('thresholds') or {}).get('max_age_days', 730))
    added = []
    relations = {}
    native_ids = {g['event_id'] for g in native}
    for g in history:
        if g.get('event_id') in native_ids:
            relations[g['event_id']] = 'NATIVE'
            continue
        reason = None
        relation = _bootstrap_match(event, g)
        if g.get('event_id') == event.get('event_id'):
            reason = 'TARGET_GAME_EXCLUDED'
        elif not relation:
            reason = 'BOOTSTRAP_COMPETITION_MISMATCH'
        elif g.get('status') != 'FINAL':
            reason = 'NOT_CONFIRMED_FINAL'
        elif iso(g['tip_at']) >= c:
            reason = 'NOT_BEFORE_CUTOFF'
        elif (c - iso(g['tip_at'])).total_seconds() / 86400.0 > max_age:
            reason = 'BOOTSTRAP_HISTORY_TOO_OLD'
        elif mode == 'FORWARD_NATIVE' and (not g.get('known_final_at') or iso(g['known_final_at']) > c):
            reason = 'FINAL_NOT_OBSERVED_BY_CUTOFF'
        elif mode == 'RECONSTRUCTED_SCORE_ONLY' and iso(g['tip_at']) + timedelta(hours=24) > c:
            reason = 'RECONSTRUCTION_24H_AVAILABILITY_BUFFER'
        if reason:
            rejections[reason] = rejections.get(reason, 0) + 1
            continue
        relations[g['event_id']] = relation
        added.append(g)
    byid = {g['event_id']: g for g in native}
    for g in added:
        old = byid.get(g['event_id'])
        if old and any(old.get(k) != g.get(k) for k in ('team1_id', 'team2_id', 'score1_full', 'score2_full', 'tip_at')):
            rejections['CONFLICTING_SCORE_FACT'] += 1
            continue
        byid[g['event_id']] = g
    return sorted(byid.values(), key=lambda g: g['tip_at']), relations


def _history_weight_profile(games, targets, cutoff, policy, relations, bootstrap_used):
    """Calculate all history weights in one in-memory pass.

    No history file is opened here.  The caller supplies the already parsed
    game pool, preventing per-team/per-game JSON reads on large competitions.
    """
    if not bootstrap_used:
        weights = [2 ** (-max(0, (iso(cutoff) - iso(g['tip_at'])).total_seconds() / 86400) / policy['half_life']) for g in games]
    else:
        source_weights = COLD_START.get('source_weights') or {}
        weights = []
        for g in games:
            relation = relations.get(g['event_id'], 'UNKNOWN')
            season = _season_bucket(g, cutoff)
            _, competition_weight = _competition_adjustment(relation, g)
            age_weight = 2 ** (-max(0, (iso(cutoff) - iso(g['tip_at'])).total_seconds() / 86400) / policy['half_life'])
            weights.append(age_weight * float(source_weights.get(season, 0.3)) * competition_weight)
    statistical_by_team = {}; weighted_by_team = {}; diversity_by_team = {}
    for team in targets:
        pairs = [(w, g) for w, g in zip(weights, games) if team in (g['team1_id'], g['team2_id'])]
        ws = [w for w, _ in pairs]
        total = sum(ws)
        statistical_by_team[team] = (total * total / sum(w * w for w in ws)) if ws else 0.0
        weighted_by_team[team] = total
        opponent_weights = defaultdict(float)
        for weight, game in pairs:
            opponent = game['team2_id'] if game['team1_id'] == team else game['team1_id']
            opponent_weights[opponent] += weight
        opponent_total = sum(opponent_weights.values())
        diversity_by_team[team] = ((opponent_total * opponent_total) /
                                   sum(value * value for value in opponent_weights.values())) if opponent_weights else 0.0
    return {
        'weights': weights,
        'effective_sample_size': min(statistical_by_team.values(), default=0.0),
        'effective_sample_size_by_team': statistical_by_team,
        'history_ess': min(weighted_by_team.values(), default=0.0),
        'history_ess_by_team': weighted_by_team,
        'effective_opponent_diversity': min(diversity_by_team.values(), default=0.0),
        'effective_opponent_diversity_by_team': diversity_by_team,
    }


def _effective_sample_size(games, targets, cutoff, policy, relations, bootstrap_used):
    profile = _history_weight_profile(games, targets, cutoff, policy, relations, bootstrap_used)
    return profile['effective_sample_size'], profile['effective_sample_size_by_team'], profile['weights']


def _overtime_history_profile(event, games):
    """Build a cutoff-safe, team-specific overtime audit from final-score facts.

    ``price_event`` already fits its total target to ``score*_full``.  Those
    final scores include overtime, so a separately estimated OT expectation
    must not be added to the mean again.  This profile makes the embedded OT
    component observable and lets missing detail widen only the total outcome
    uncertainty.
    """
    targets = (event.get('team1_id'), event.get('team2_id'))
    by_team = {team: {'observations': 0, 'ot_games': 0, 'ot_points': []}
               for team in targets if team}
    seen = set()
    for game in games:
        game_id = game.get('event_id')
        # A source can provide a match through both teams' history pages.
        # Count the game once globally, while preserving each target's own
        # participation profile.
        identity = game_id or (game.get('tip_at'), game.get('team1_id'), game.get('team2_id'))
        if not identity or identity in seen:
            continue
        participants = set((game.get('team1_id'), game.get('team2_id')))
        involved = [team for team in by_team if team in participants]
        if not involved:
            continue
        full1, full2 = game.get('score1_full'), game.get('score2_full')
        try:
            full_total = float(full1) + float(full2)
        except (TypeError, ValueError):
            continue
        regulation_total = None
        try:
            regulation_total = float(game.get('score1_regulation')) + float(game.get('score2_regulation'))
        except (TypeError, ValueError):
            periods1, periods2 = game.get('period_points_team1'), game.get('period_points_team2')
            if (isinstance(periods1, list) and isinstance(periods2, list)
                    and len(periods1) >= 4 and len(periods2) >= 4):
                try:
                    regulation_total = sum(float(x) for x in periods1[:4]) + sum(float(x) for x in periods2[:4])
                except (TypeError, ValueError):
                    regulation_total = None
        if regulation_total is None:
            continue
        seen.add(identity)
        ot_points = full_total - regulation_total
        is_ot = ot_points > 0.0001
        for team in involved:
            profile = by_team[team]
            profile['observations'] += 1
            if is_ot:
                profile['ot_games'] += 1
                profile['ot_points'].append(ot_points)

    def summarize(profile):
        observations = profile['observations']
        ot_games = profile['ot_games']
        mean_points = (sum(profile['ot_points']) / ot_games) if ot_games else None
        probability = (ot_games / observations) if observations else None
        return {
            'observations': observations,
            'ot_games': ot_games,
            'ot_probability': probability,
            'mean_ot_points_when_occurred': mean_points,
            'expected_ot_points_per_game': (probability * mean_points
                                            if probability is not None and mean_points is not None else None),
        }

    team_profiles = {team: summarize(profile) for team, profile in by_team.items()}
    observations = sum(profile['observations'] for profile in by_team.values())
    ot_games = sum(profile['ot_games'] for profile in by_team.values())
    ot_points = [value for profile in by_team.values() for value in profile['ot_points']]
    probability = (ot_games / observations) if observations else None
    mean_points = (sum(ot_points) / len(ot_points)) if ot_points else None
    minimum = int((TOTAL_EVIDENCE_POLICY.get('overtime_history') or {}).get(
        'minimum_observations_for_stable_profile', 3))
    return {
        'method': 'PRE_CUTOFF_FINALS_WITH_REGULATION_OR_PERIOD_SPLIT',
        'baseline_integration': (TOTAL_EVIDENCE_POLICY.get('overtime_history') or {}).get(
            'full_score_baseline_contract', 'EMBEDDED_IN_HISTORICAL_FULL_TIME_TOTALS'),
        'team_profiles': team_profiles,
        'combined_observations': observations,
        'combined_ot_games': ot_games,
        'combined_ot_probability': probability,
        'mean_ot_points_when_occurred': mean_points,
        'expected_ot_points_per_game': (probability * mean_points
                                        if probability is not None and mean_points is not None else None),
        'minimum_observations_for_stable_profile': minimum,
        'data_status': ('UNAVAILABLE' if not observations else
                        'THIN_SAMPLE' if observations < minimum else 'OBSERVED'),
    }


def total_diagnostic(event,games,context,policy,predictive_spread=None,scale_multiplier=1.0):
    """Expose total evidence with hard blockers separated from soft missing data."""
    context=enrich_possessions_context(context)
    score_context = build_score_context(event, games, context.get('cutoff_at') or event.get('tip_at'))
    overtime_history = _overtime_history_profile(event, games)
    totals=[g['score1_full']+g['score2_full'] for g in games]
    target_ids={event.get('team1_id'),event.get('team2_id')}
    q4_close=[];q4_blowout=[]
    for g in games:
        if not target_ids.intersection((g.get('team1_id'),g.get('team2_id'))):continue
        p1,p2=g.get('period_points_team1'),g.get('period_points_team2')
        if not (isinstance(p1,list) and isinstance(p2,list) and len(p1)>=4 and len(p2)>=4):continue
        q4_total=p1[3]+p2[3];margin_before_q4=abs(sum(p1[:3])-sum(p2[:3]))
        if margin_before_q4<=8:q4_close.append(q4_total)
        elif margin_before_q4>=15:q4_blowout.append(q4_total)
    hard_blockers=[];soft_missing=[]
    if not event.get('game_minutes'):hard_blockers.append('GAME_RULE_UNKNOWN')
    evidence_level=str(context.get('possessions_level') or '')
    if not context.get('possessions_verified') and evidence_level not in ('LEVEL_A','LEVEL_B','LEVEL_C'):
        hard_blockers.append('POSSESSIONS_EVIDENCE_MISSING')
    if not context.get('basic_offense_verified') and not games:
        hard_blockers.append('BASIC_OFFENSE_EVIDENCE_MISSING')
    if not context.get('injury_verified'):soft_missing.append('INJURY_UNKNOWN')
    if not context.get('roster_verified'):soft_missing.append('ROTATION_UNKNOWN')
    if not context.get('three_point_verified'):soft_missing.append('THREE_POINT_PROFILE_UNKNOWN')
    if not context.get('late_foul_verified'):soft_missing.append('LATE_FOUL_ENVIRONMENT_UNKNOWN')
    if len(q4_close)<3:soft_missing.append('CLOSE_GAME_Q4_SAMPLE_INSUFFICIENT')
    if len(q4_blowout)<3:soft_missing.append('GARBAGE_TIME_Q4_SAMPLE_INSUFFICIENT')
    close_game_probability=None
    if predictive_spread is not None:
        adjusted_margin_sd=policy['sd_margin']*scale_multiplier
        close_game_probability=t_cdf(4.5,predictive_spread,adjusted_margin_sd,policy['df'])-t_cdf(-4.5,predictive_spread,adjusted_margin_sd,policy['df'])
    close_game_expected=bool(predictive_spread is not None and abs(float(predictive_spread))<=4.5)
    # Full-score training already contains historical OT points.  We surface
    # the team's observed OT profile for audit; missing detail adds uncertainty
    # but never acts as a total-execution veto.
    if overtime_history['data_status'] == 'UNAVAILABLE':
        soft_missing.append('OT_HISTORY_UNAVAILABLE')
    elif overtime_history['data_status'] == 'THIN_SAMPLE':
        soft_missing.append('OT_HISTORY_THIN_SAMPLE')
    execution_eligible=not hard_blockers
    total_adjustment = None
    if not close_game_expected:
        total_adjustment = 0.0
    elif context.get('late_foul_verified'):
        try:
            # The REGULATION_ONLY and INCLUDING_OT scenarios are fitted from
            # their respective historical score fields.  OT is therefore in
            # the latter scenario's target already; only a separately
            # evidenced late-foul component may be added here.
            total_adjustment = float(context['late_foul_premium'])
        except (KeyError, TypeError, ValueError):
            hard_blockers.append('CLOSE_GAME_PREMIUM_VALUE_INVALID')
            execution_eligible = False
    # No verified close-game premium is not a reason to erase a total signal.
    # In particular, do not add an OT premium here: it would double count the
    # overtime outcomes already present in the full-score training target.
    if total_adjustment is None and not hard_blockers:
        total_adjustment = 0.0
    soft_policy=TOTAL_EVIDENCE_POLICY.get('soft_missing_uncertainty') or {}
    per_item=float(soft_policy.get('per_item_multiplier',1.05))
    maximum=float(soft_policy.get('maximum_multiplier',1.25))
    soft_multiplier=min(maximum,per_item**len(set(soft_missing))) if soft_missing else 1.0
    diagnostic_sigma=policy['sd_total']*scale_multiplier*soft_multiplier
    return {'status':'EVIDENCE_GATED_TOTAL_DIAGNOSTIC','game_minutes':event.get('game_minutes'),
            'game_minutes_source':event.get('game_minutes_source','UNKNOWN_NO_MINUTES_ASSUMED'),
            'recent_total_mean':sum(totals)/len(totals) if totals else None,
            'recent_total_median':sorted(totals)[len(totals)//2] if totals else None,
            'recent_total_observations':len(totals),'pace_quality':'DIRECT_ONLY_NOT_IMPUTED',
            'close_game_q4_total_mean':sum(q4_close)/len(q4_close) if q4_close else None,
            'close_game_q4_observations':len(q4_close),
            'blowout_q4_total_mean':sum(q4_blowout)/len(q4_blowout) if q4_blowout else None,
            'blowout_q4_observations':len(q4_blowout),
            'garbage_time_proxy':'Q4_SCORE_BY_PRE_Q4_MARGIN',
            'source_context_variables':context.get('available_variables',[]),
            'recent_score_context':score_context,
            'score_context_status':score_context.get('status'),
            'score_context_method':score_context.get('method'),
            'score_context_warning':'比分与分节数据用于状态/波动诊断；未将比分反推为回合数、三分率或犯规率',
            'score_context_team_windows':{k:{'last_5':v['windows']['last_5'], 'last_10':v['windows']['last_10']}
                                         for k,v in score_context.get('team_context',{}).items()},
            'evidence_level':evidence_level or 'LEVEL_D','pace_source':context.get('pace_source','UNAVAILABLE'),
            'possessions_per_game':context.get('possessions_per_game'),
            'possession_missing_fields':context.get('missing_fields',[]),
            'predictive_spread':predictive_spread,'close_game_probability':close_game_probability,
            'close_game_expected':close_game_expected,
            'late_foul_premium':context.get('late_foul_premium') if context.get('late_foul_verified') else None,
            'ot_premium':overtime_history.get('expected_ot_points_per_game'),
            'overtime_history':overtime_history,
            'ot_mean_adjustment_contract':'ALREADY_EMBEDDED_IN_FULL_SCORE_BASELINE_NO_DOUBLE_COUNT',
            'close_game_total_adjustment':total_adjustment,
            'hard_blockers':list(dict.fromkeys(hard_blockers)),
            'soft_missing':list(dict.fromkeys(soft_missing)),
            'uncertainty_flags':list(dict.fromkeys(hard_blockers+soft_missing)),
            'diagnostic_sigma_total':diagnostic_sigma,
            'base_sigma_total':policy['sd_total']*scale_multiplier,
            'soft_missing_uncertainty_multiplier':soft_multiplier,
            'uncertainty_policy_source':'config/total_evidence_policy.yaml',
            'used_in_pricing':not hard_blockers,'used_in_execution':not hard_blockers,'used_in_kelly':not hard_blockers,
            'execution_eligible':execution_eligible,
            'execution_blockers':list(dict.fromkeys(hard_blockers)) if not execution_eligible else []}

def competition_match(event,g):
    """Match history by durable league identity before provider IDs.

    7M and Titan use independent competition-id namespaces.  An exact source
    id is the strongest relation, but a differing id must not veto a verified
    canonical league/gender match (especially NBA regular/preseason/playoff).
    """
    if g.get('evidence_kind')!='TEAM_HISTORY' or g.get('gender')!=event.get('gender'):
        return None
    eid=event.get('competition_id');gid=g.get('competition_id')
    if eid and gid and eid==gid:
        return 'EXACT_SOURCE_ID'
    ek=durable_competition_key(event)
    gk=durable_competition_key(g)
    if ek and gk and str(ek).upper()==str(gk).upper():
        return 'CROSS_SOURCE_CANONICAL_LEAGUE' if eid and gid and eid!=gid else 'CANONICAL_SOURCE_LABEL'
    # Defensive phase-independent fallback for rows captured before the
    # registry alias was normalized.  Restrict it to explicit mature leagues;
    # generic LABEL:* values must never be fuzzy-joined.
    ef=_competition_family(event)
    gf=_competition_family(g)
    allowed={'NBA','WNBA','EUROLEAGUE','EUROCUP','EUROLEAGUE_WOMEN','EUROCUP_WOMEN',
             'AUSTRALIA_NBL','AUSTRALIA_WNBL','JAPAN_BLEAGUE','KOREA_KBL',
             'CBA_REGULAR','CBA_PLAYOFF','B_LEAGUE'}
    if ef and ef==gf and ef in allowed:
        return 'CROSS_SOURCE_CANONICAL_LEAGUE'
    return None

def eligible_history(event,history,cutoff,mode):
    c=iso(cutoff);p=POLICY[event['model_family']];good=[];reject=Counter()
    for g in history:
        reason=None
        if g['event_id']==event['event_id']:reason='TARGET_GAME_EXCLUDED'
        elif g.get('gender')!=event.get('gender'):reason='GENDER_MISMATCH'
        elif not competition_match(event,g):reason='COMPETITION_MISMATCH'
        elif g.get('status')!='FINAL':reason='NOT_CONFIRMED_FINAL'
        elif iso(g['tip_at'])>=c:reason='NOT_BEFORE_CUTOFF'
        elif (c-iso(g['tip_at'])).total_seconds()/86400>p['max_days']:reason='HISTORY_TOO_OLD'
        elif mode=='FORWARD_NATIVE' and (not g.get('known_final_at') or iso(g['known_final_at'])>c):reason='FINAL_NOT_OBSERVED_BY_CUTOFF'
        elif mode=='RECONSTRUCTED_SCORE_ONLY' and iso(g['tip_at'])+timedelta(hours=24)>c:reason='RECONSTRUCTION_24H_AVAILABILITY_BUFFER'
        if reason:reject[reason]+=1
        else:good.append(g)
    # Deduplicate facts, do not let multiple mirrors multiply evidence.
    byid={};conflict=set()
    for g in good:
        old=byid.get(g['event_id'])
        if old and any(old.get(k)!=g.get(k) for k in ('team1_id','team2_id','score1_full','score2_full','tip_at')):conflict.add(g['event_id'])
        else:byid[g['event_id']]=g
    reject['CONFLICTING_SCORE_FACT']+=len(conflict)
    return sorted([g for k,g in byid.items() if k not in conflict],key=lambda g:g['tip_at']),dict(reject)

def price_event(event,history,cutoff,mode,context=None):
    """Actually called by the daily runner. Inputs contain only source score facts.

    This is an explicitly uncalibrated baseline with a cutoff-safe adjustment
    layer. Missing injury/rotation/Net Rating context widens Spread residual
    uncertainty; it does not by itself erase an independently formed fair line.
    """
    if hasattr(history,'candidates'):
        event,history=history.candidates(event)
    context=enrich_possessions_context(context);context.setdefault('cutoff_at',cutoff)
    foundation_pricing=dict(context.get('titan_foundation_pricing') or {})
    family=event['model_family'];p=POLICY[family]
    tier,tier_spec=tier_for(event);native_scale_multiplier=float(tier_spec.get('residual_scale_multiplier',1.45))
    season_regime=season_regime_for(event)
    phase_text=' '.join(str(event.get(key) or '') for key in ('season_phase','stage','season_regime','league_family','competition_key')).upper()
    season_regime_evidence='EXPLICIT_EVENT_PHASE' if any(token in phase_text for token in ('SUMMER','夏季','PRESEASON','PRE-SEASON','季前','PLAYOFF','季后','季後','淘汰','EARLY_REGULAR','常规初期')) else 'UNVERIFIED_DEFAULT'
    spread_uncertainty=_spread_uncertainty(context, season_regime)
    adjustment_layer=_context_adjustment_layer(context)
    roster_stability=evaluate_tier3_roster_stability(event,context,cutoff)
    if roster_stability.get('verified'):
        context['roster_stability_30d_verified']=True
        context['roster_stability_30d_evidence']=roster_stability
    cold_scale_multiplier=float((COLD_START.get('residual_scale') or {}).get('cold_start',1.25))
    evaluation,league_policy=evaluation_channel(event)
    base={'event_id':event['event_id'],'asof':cutoff,'archive_type':mode,'model_family':family,'model_version':MODEL_VERSION,
      'pricing_status':'UNPRICEABLE','mu_raw':None,'mu_structural':None,'mu_market':None,'mu_blended':None,
      'total_raw':None,'total_structural':None,'total_market':None,'total_blended':None,'pricing_data_quality':0,
      'model_source':'真实比分的正则化对手校正基线；非阵容/回合模型','probability_calibration_status':'UNVALIDATED',
      'real_execution_allowed':False,'paper_model_eligible':False,'uncertainty_source':'UNVALIDATED_RESEARCH_PRIOR',
      'roster_status':context.get('roster_status','UNKNOWN'),'injury_status':context.get('injury_status','UNKNOWN'),
      'total_model_status':'EVIDENCE_GATED_TOTAL_DIAGNOSTIC','league_tier':tier,
      'season_regime':season_regime,'season_regime_evidence':season_regime_evidence,'spread_data_quality':'DATA_QUALITY_D',
      'spread_context':{'injury_status':context.get('injury_status','UNKNOWN'),
                        'rotation_status':'KNOWN' if context.get('rotation_or_expected_minutes_verified') else
                                         'CONTINUITY_AVAILABLE' if context.get('rotation_continuity_verified') else 'UNKNOWN',
                        'net_rating_status':'KNOWN' if context.get('net_rating_context_verified') else 'UNKNOWN'},
      'adjustment_layer':adjustment_layer,
      'injury_uncertainty_multiplier':spread_uncertainty['injury_uncertainty_multiplier'],
      'rotation_uncertainty_multiplier':spread_uncertainty['rotation_uncertainty_multiplier'],
      'season_regime_multiplier':spread_uncertainty['season_regime_multiplier'],
      'context_uncertainty_multiplier':spread_uncertainty['context_uncertainty_multiplier'],
      'residual_scale_breakdown':{'base':None,'league':native_scale_multiplier,
                                  'context':spread_uncertainty['context_uncertainty_multiplier'],
                                  'final_spread':None,'combine_rule':spread_uncertainty['combine_rule']},
      'roster_stability_30d':roster_stability,
      'residual_scale_multiplier':native_scale_multiplier,'evaluation_channel':evaluation,
      'pricing_state':'UNPRICEABLE','research_priceable':False,'cold_start_priceable':False,
      'prior_only_price':False,'effective_sample_size':0.0,'effective_sample_size_by_team':{},
      'history_ess':0.0,'history_ess_by_team':{},'effective_opponent_diversity':0.0,
      'effective_opponent_diversity_by_team':{},
      'current_season_games':0,'previous_season_games':0,'older_history_games':0,
      'bootstrap_history_used':False,'competition_strength_adjustment':{},
      'cold_start_residual_multiplier':1.0,'shadow_eligible':False,'executable_eligible':False,
      'league_lifecycle_state':'DISCOVERY'}
    base['titan_foundation_pricing']=foundation_pricing
    base['pregame_evidence_bundle']=dict(context.get('pregame_evidence_bundle') or {})
    base['challenger_prices']=_challenger_outputs(foundation_pricing)
    # Keep score/period context visible even when pricing stops at an earlier
    # history or identity gate. This is diagnostic evidence, not a gate bypass.
    base['recent_score_context']=build_score_context(event, history, cutoff)
    if iso(cutoff)>=iso(event['tip_at']):return dict(base,blockers=['TARGET_ALREADY_STARTED'],input_games=0)
    if not event.get('identity_verified'):return dict(base,blockers=['IDENTITY_CONFLICT'],input_games=0)
    native_games,rejections=eligible_history(event,history,cutoff,mode)
    games=native_games
    relations={g['event_id']:'NATIVE' for g in native_games}
    targets=(event['team1_id'],event['team2_id']);counts={t:sum(t in (g['team1_id'],g['team2_id']) for g in games) for t in targets}
    bootstrap_used=False
    if min(counts.values(),default=0) < p['min_games']:
        games,relations=_bootstrap_history(event,history,cutoff,mode,native_games,rejections)
        bootstrap_used=any(relations.get(g['event_id']) not in (None,'NATIVE') for g in games)
        counts={t:sum(t in (g['team1_id'],g['team2_id']) for g in games) for t in targets}
    weight_profile=_history_weight_profile(games,targets,cutoff,p,relations,bootstrap_used)
    effective_ess=weight_profile['effective_sample_size'];ess_by_team=weight_profile['effective_sample_size_by_team']
    bootstrap_weights=weight_profile['weights']
    season_counts=Counter(_season_bucket(g,cutoff) for g in games
                          if any(t in (g['team1_id'],g['team2_id']) for t in targets)) if bootstrap_used else Counter()
    opponents={t:sorted({g['team2_id'] if g['team1_id']==t else g['team1_id'] for g in games if t in (g['team1_id'],g['team2_id'])}) for t in targets}
    match_methods=Counter(competition_match(event,g) for g in games)
    audit={'input_games':len(games),'team_game_counts':counts,'team_opponent_counts':{t:len(v) for t,v in opponents.items()},'history_exclusions':rejections,
      'competition_match_methods':{k:v for k,v in match_methods.items() if k},
      'used_history_ids':[g['event_id'] for g in games],'input_fingerprint':fingerprint({'event':event,'history':games,'cutoff':cutoff}),
      'last_game_at':{t:max((g['tip_at'] for g in games if t in (g['team1_id'],g['team2_id'])),default=None) for t in targets},
      'effective_sample_size':effective_ess,'effective_sample_size_by_team':ess_by_team,
      'history_ess':weight_profile['history_ess'],'history_ess_by_team':weight_profile['history_ess_by_team'],
      'effective_opponent_diversity':weight_profile['effective_opponent_diversity'],
      'effective_opponent_diversity_by_team':weight_profile['effective_opponent_diversity_by_team'],
      'current_season_games':season_counts.get('current_season',0),
      'previous_season_games':season_counts.get('previous_season',0),
      'older_history_games':season_counts.get('older_history',0),
      'bootstrap_history_used':bootstrap_used,
      'bootstrap_relations':{k:v for k,v in relations.items() if v!='NATIVE'}}
    research_min=float((COLD_START.get('thresholds') or {}).get('research_ess_min',3.0))
    cold_min=float((COLD_START.get('thresholds') or {}).get('cold_start_ess_min',6.0))
    if min(counts.values(),default=0)<p['min_games'] or (bootstrap_used and effective_ess<research_min):
        return dict(base,**audit,blockers=['INSUFFICIENT_PRE_CUTOFF_HISTORY'],
                    paper_evidence_blockers=['HISTORY_ESS_TOO_LOW','INSUFFICIENT_HISTORY'],
                    league_lifecycle_state='DISCOVERY')
    cold_state='NATIONAL_TEAM_BOOTSTRAP' if family=='NATIONAL_TEAM' and bootstrap_used else 'COLD_START_PRICEABLE' if bootstrap_used else 'NATIVE_PRICEABLE'
    scale_multiplier=native_scale_multiplier*(cold_scale_multiplier if bootstrap_used else 1.0)
    competition_adjustments=Counter()
    for g in games:
        relation=relations.get(g['event_id'],'UNKNOWN')
        if relation=='NATIVE':continue
        name,weight=_competition_adjustment(relation,g);competition_adjustments[name]+=weight
    # Only the connected component of the two targets; disjoint leagues cannot lend fake precision.
    component=set(targets)
    while True:
        nxt=component|{t for g in games if component.intersection((g['team1_id'],g['team2_id'])) for t in (g['team1_id'],g['team2_id'])}
        if nxt==component:break
        component=nxt
    games=[g for g in games if g['team1_id'] in component and g['team2_id'] in component][-800:]
    teams=sorted(component);ix={t:i for i,t in enumerate(teams)};n=len(teams)
    if n>180:return dict(base,**audit,blockers=['COHORT_TOO_LARGE_FOR_BASELINE'])
    weights=bootstrap_weights if bootstrap_used else [2**(-max(0,(iso(cutoff)-iso(g['tip_at'])).total_seconds()/86400)/p['half_life']) for g in games]
    # Preseason/Summer League may use prior history, but the policy explicitly
    # downweights older team strength instead of deleting the fair-price path.
    regime_after=spread_uncertainty['historical_weight_after_days']
    regime_weight=spread_uncertainty['historical_weight_multiplier']
    if regime_weight != 1.0:
        weights=[w * (regime_weight if (iso(cutoff)-iso(g['tip_at'])).total_seconds()/86400 > regime_after else 1.0)
                 for w,g in zip(weights,games)]
    eff={t:sum(w for w,g in zip(weights,games) if t in (g['team1_id'],g['team2_id'])) for t in targets}
    if min(eff.values())<.25:return dict(base,**audit,blockers=['NEGLIGIBLE_RECENT_HISTORY'],effective_weight=eff)
    scenarios={}
    for rule,suffix in [('REGULATION_ONLY','regulation'),('INCLUDING_OT','full')]:
        margins=[];totals=[]
        for g,w in zip(games,weights):
            x=[0.]*n;xt=[0.]*n;a=ix[g['team1_id']];b=ix[g['team2_id']];x[a]=1;x[b]=-1;xt[a]=xt[b]=1
            sa,sb=g['score1_'+suffix],g['score2_'+suffix]
            margins.append((x,sa-sb,w));totals.append((xt,sa+sb,w))
        center=sum(y*w for _,y,w in totals)/sum(weights)
        bm=_ridge(margins,p['ridge']);bt=_ridge([(x,y-center,w) for x,y,w in totals],p['ridge'])
        mu=bm[ix[targets[0]]]-bm[ix[targets[1]]];tot=center+bt[ix[targets[0]]]+bt[ix[targets[1]]]
        pts1,pts2=(tot+mu)/2,(tot-mu)/2
        if min(pts1,pts2)<0:return dict(base,**audit,blockers=['INVALID_MODEL_SCORE'])
        scenarios[rule]={'mu_margin':mu,'mu_total':tot,'team1_points':pts1,'team2_points':pts2,
          'raw_team_strength_team1':bm[ix[targets[0]]],'raw_team_strength_team2':bm[ix[targets[1]]],
          'sd_margin':p['sd_margin']*scale_multiplier,'sd_total':p['sd_total']*scale_multiplier,
          'base_sd_margin':p['sd_margin'],'base_sd_total':p['sd_total'],'residual_scale_multiplier':scale_multiplier,
          'df':p['df'],'score_rule':rule}
    base_fair_spread=scenarios['INCLUDING_OT']['mu_margin']

    def _bootstrap_fit(sample):
        usable = [g for g in sample if g.get('team1_id') in ix and g.get('team2_id') in ix
                  and isinstance(g.get('score1_full'), (int, float))
                  and isinstance(g.get('score2_full'), (int, float))]
        if len(usable) < 4:
            return None
        rows=[]
        for g in usable:
            x=[0.0]*n; a=ix[g['team1_id']]; b=ix[g['team2_id']]
            x[a]=1.0; x[b]=-1.0
            age=max(0.0,(iso(cutoff)-iso(g['tip_at'])).total_seconds()/86400)
            w=2**(-age/p['half_life'])
            rows.append((x,float(g['score1_full'])-float(g['score2_full']),w))
        try:
            fitted=_ridge(rows,p['ridge'])
            return float(fitted[ix[targets[0]]] - fitted[ix[targets[1]]])
        except (KeyError, TypeError, ValueError, ZeroDivisionError):
            return None

    fair_center_predictions = block_bootstrap_predictions(
        games, _bootstrap_fit, reps=24,
        seed=sum(ord(ch) for ch in str(event.get('event_id') or '')))
    fair_center_stats=interval_from_samples(fair_center_predictions)
    adjustment_points=float(adjustment_layer.get('total_adjustment_points') or 0.0)
    final_spread_scale=float(spread_uncertainty['context_uncertainty_multiplier'])
    for scenario in scenarios.values():
        scenario['base_fair_spread']=scenario['mu_margin']
        scenario['availability_adjustment_points']=adjustment_layer['layers'][0]['value_points']
        scenario['rotation_adjustment_points']=adjustment_layer['layers'][1]['value_points']
        scenario['current_team_strength_adjustment_points']=adjustment_layer['layers'][2]['value_points']
        scenario['adjustment_applied']=adjustment_layer['adjustment_applied']
        scenario['adjustment_unknown_layers']=adjustment_layer['unknown_layers']
        scenario['sd_margin_before_context']=scenario['sd_margin']
        scenario['sd_margin']*=final_spread_scale
        scenario['final_spread_residual_scale']=scenario['sd_margin']
        scenario['mu_margin']+=adjustment_points
        scenario['team1_points']=(scenario['mu_total']+scenario['mu_margin'])/2
        scenario['team2_points']=(scenario['mu_total']-scenario['mu_margin'])/2
        scenario['residual_scale_multiplier']=scale_multiplier*final_spread_scale
    residual_scale_breakdown={'base':p['sd_margin'],'league':native_scale_multiplier,
                              'cold_start':cold_scale_multiplier if bootstrap_used else 1.0,
                              'context':final_spread_scale,'final_spread':p['sd_margin']*scale_multiplier*final_spread_scale,
                              'combine_rule':spread_uncertainty['combine_rule']}
    full=scenarios['INCLUDING_OT'];warnings=['UNVALIDATED_SCORE_BASELINE']
    if any(len(v)<2 for v in opponents.values()):warnings.append('ONLY_H2H_OR_SINGLE_OPPONENT')
    history_minimum=paper_history_minimum(event)
    if min(counts.values())<8:warnings.append('SMALL_SAMPLE')
    if any(g['evidence_kind']=='H2H' for g in games) and not any(g['evidence_kind']=='TEAM_HISTORY' for g in games):warnings.append('TEAM_HISTORY_FEED_NOT_CAPTURED')
    nba_cba_soft_context=_nba_cba_spread_context_is_soft(event)
    if family!='CLUB_MATURE' and not context.get('roster_verified'):warnings.append('CURRENT_ROSTER_UNVERIFIED')
    if not context.get('injury_verified'):warnings.append('INJURY_UNKNOWN')
    paper_evidence_blockers=[]
    if min(counts.values(),default=0)<history_minimum:paper_evidence_blockers.extend(['HISTORY_ESS_TOO_LOW','INSUFFICIENT_HISTORY'])
    if any(len(v)<3 for v in opponents.values()):paper_evidence_blockers.extend(['OPPONENT_DIVERSITY_TOO_LOW','INSUFFICIENT_OPPONENT_DIVERSITY'])
    if not any(g['evidence_kind']=='TEAM_HISTORY' for g in games):paper_evidence_blockers.append('TEAM_HISTORY_FEED_NOT_CAPTURED')
    if family!='CLUB_MATURE' and not context.get('roster_verified',False) and not nba_cba_soft_context:
        paper_evidence_blockers.append('CURRENT_ROSTER_UNVERIFIED')
    eligible=not paper_evidence_blockers
    blockers=[]
    if tier=='TIER_3' and not context.get('roster_stability_30d_verified') and not nba_cba_soft_context:
        eligible=False
        paper_evidence_blockers.append('ROSTER_STABILITY_MISSING')
        blockers.append('ROSTER_STABILITY_MISSING')
    elif tier=='TIER_3' and not context.get('roster_stability_30d_verified'):
        warnings.append('ROSTER_STABILITY_UNKNOWN')
    context_keys={
        'injury_status': ('injury_status_verified', 'injury_verified'),
        'rotation_or_expected_minutes': ('rotation_or_expected_minutes_verified', 'rotation_verified', 'roster_verified'),
        'net_rating_context': ('net_rating_context_verified',),
    }
    # These are valuable context, not existence gates.  Filter them even if
    # an older league registry still contains the former v2.3 requirement;
    # missing context is represented by uncertainty multipliers above.
    spread_requires=[name for name in league_policy.get('spread_paper_entry_requires',[])
                     if name not in context_keys]
    missing_spread_context=[name for name in spread_requires if not any(context.get(key) for key in context_keys.get(name, (name+'_verified',)))]
    if missing_spread_context:
        blockers.append('SPREAD_CONTEXT_INCOMPLETE')
    quality=min(74,round(20+min(20,min(counts.values())*2)+min(20,min(len(v) for v in opponents.values())*4)+(14 if context.get('roster_verified') else 0)))
    spread_data_quality=_spread_data_quality(context, counts, opponents, foundation_pricing)
    residual_scale_breakdown['data_quality']=spread_data_quality
    oos_records=list(context.get('spread_oos_records') or [])
    league_key=event.get('league_family') or event.get('competition_key') or event.get('league')
    context_quality={'DATA_QUALITY_A':'context_complete','DATA_QUALITY_B':'context_partial',
                     'DATA_QUALITY_C':'context_sparse','DATA_QUALITY_D':'context_sparse'}.get(spread_data_quality)
    oos_profile=residual_profile(
        oos_records, league=league_key, tier=tier, season_regime=season_regime,
        data_quality=spread_data_quality, context_quality=context_quality,
        prior_sd=p['sd_margin']*native_scale_multiplier,
        prior_df=p['df'])
    empirical_residual=bool(oos_profile.get('fit_status') == 'OOS_EMPIRICAL'
                            and isinstance(oos_profile.get('sd'), (int, float)))
    if empirical_residual:
        # Empirical OOS replaces the tier scale; cold-start and context
        # multipliers remain explicit and are not silently folded into the fit.
        for scenario in scenarios.values():
            scenario['base_sd_margin']=float(oos_profile['sd'])
            scenario['sd_margin']=float(oos_profile['sd']) * (cold_scale_multiplier if bootstrap_used else 1.0) * final_spread_scale
            scenario['df']=float(oos_profile['df'])
            scenario['residual_source']=oos_profile.get('source')
        scale_multiplier=float(oos_profile['sd'])/max(float(p['sd_margin']), 1e-9) * (cold_scale_multiplier if bootstrap_used else 1.0)
        native_scale_multiplier=1.0
    center_increment=oos_profile.get('context_uncertainty_increment')
    center_se=fair_center_stats.get('standard_error')
    if isinstance(center_se, (int, float)) and isinstance(center_increment, (int, float)):
        center_se=math.sqrt(center_se*center_se + float(center_increment)*float(center_increment))
    final_center=base_fair_spread + adjustment_points
    center_interval_80=([final_center - 1.2815515655446*center_se,
                         final_center + 1.2815515655446*center_se]
                        if isinstance(center_se, (int, float)) else fair_center_stats.get('interval_80'))
    center_interval_95=([final_center - 1.95996398454005*center_se,
                         final_center + 1.95996398454005*center_se]
                        if isinstance(center_se, (int, float)) else fair_center_stats.get('interval_95'))
    if not isinstance(center_se, (int, float)) and adjustment_points and center_interval_80:
        center_interval_80=[float(x)+adjustment_points for x in center_interval_80]
    if not isinstance(center_se, (int, float)) and adjustment_points and center_interval_95:
        center_interval_95=[float(x)+adjustment_points for x in center_interval_95]
    fair_center_uncertainty={
        'method': 'BLOCK_BOOTSTRAP_TIME_BLOCK' if fair_center_predictions else 'INSUFFICIENT_HISTORY_FOR_BOOTSTRAP',
        'bootstrap_predictions': fair_center_predictions,
        'bootstrap_sample_N': len(fair_center_predictions),
        'fair_center_standard_error': center_se,
        'fair_center_interval_80': center_interval_80,
        'fair_center_interval_95': center_interval_95,
        'context_uncertainty_increment': center_increment,
        'context_quality': context_quality,
        'uncertainty_source': 'OOS_CONTEXT_RESIDUAL_PLUS_BLOCK_BOOTSTRAP' if center_increment is not None else 'BLOCK_BOOTSTRAP_OR_INSUFFICIENT_HISTORY',
    }
    residual_scale_breakdown['source']=oos_profile.get('source')
    residual_scale_breakdown['oos_sample_N']=oos_profile.get('sample_N', 0)
    residual_scale_breakdown['student_t_df']=oos_profile.get('df')
    residual_scale_breakdown['student_t_scale']=oos_profile.get('scale')
    if empirical_residual:
        residual_scale_breakdown.update({
            'base': float(oos_profile['sd']), 'league': 1.0,
            'cold_start': cold_scale_multiplier if bootstrap_used else 1.0,
            'final_spread': float(oos_profile['sd']) * (cold_scale_multiplier if bootstrap_used else 1.0) * final_spread_scale,
        })
    diagnostic=total_diagnostic(event,games,context,p,full['mu_margin'],scale_multiplier)
    # Soft-missing evidence widens only the total residual.  It never changes
    # the fair mean, the 8-game/3-opponent gate, or an edge threshold.
    total_uncertainty_multiplier=float(diagnostic.get('soft_missing_uncertainty_multiplier') or 1.0)
    for scenario in scenarios.values():
        scenario['sd_total_before_soft_missing']=scenario['sd_total']
        scenario['sd_total']*=total_uncertainty_multiplier
        scenario['total_soft_missing_uncertainty_multiplier']=total_uncertainty_multiplier
    # A close-game premium can only affect a total after both components are
    # independently evidenced. It is never imputed from the market or score mean.
    if diagnostic['close_game_total_adjustment'] is not None:
        for rule, scenario in scenarios.items():
            adjustment = diagnostic['close_game_total_adjustment']
            scenario['mu_total'] += adjustment
            scenario['team1_points'] = (scenario['mu_total'] + scenario['mu_margin']) / 2
            scenario['team2_points'] = (scenario['mu_total'] - scenario['mu_margin']) / 2
    full=scenarios['INCLUDING_OT']
    outcome_cdf=margin_cdf(full['mu_margin'], full['sd_margin'], full['df'], 'INCLUDING_OT')
    game_outcome_interval_80=[student_t_quantile(.10, outcome_cdf), student_t_quantile(.90, outcome_cdf)]
    game_outcome_interval_95=[student_t_quantile(.025, outcome_cdf), student_t_quantile(.975, outcome_cdf)]
    shadow_ess=float((COLD_START.get('thresholds') or {}).get('shadow_ess_min',8.0))
    current_min=int((COLD_START.get('thresholds') or {}).get('current_season_min_games_for_shadow',2))
    shadow_eligible=bool(eligible and (not bootstrap_used or (
        effective_ess>=shadow_ess and season_counts.get('current_season',0)>=current_min and
        (context.get('roster_stability_30d_verified') or nba_cba_soft_context))))
    if bootstrap_used and not shadow_eligible and 'COLD_START_SHADOW_GATE_NOT_MET' not in blockers:
        blockers.append('COLD_START_SHADOW_GATE_NOT_MET')
    lifecycle='SHADOW' if shadow_eligible else 'BOOTSTRAP' if bootstrap_used else 'PROVISIONAL'
    decomposition={
      'model_version':MODEL_VERSION,
      'raw_team_strength_home':full.get('raw_team_strength_team1'),
      'raw_team_strength_away':full.get('raw_team_strength_team2'),
      'base_fair_spread':base_fair_spread,
      'raw_expected_home_score':full.get('team1_points'),
      'raw_expected_away_score':full.get('team2_points'),
      'raw_independent_margin':base_fair_spread,
      'raw_fair_spread':base_fair_spread,
      'calibrated_fair_spread':None,
      'fair_center_standard_error':fair_center_uncertainty.get('fair_center_standard_error'),
      'fair_center_interval_80':fair_center_uncertainty.get('fair_center_interval_80'),
      'fair_center_interval_95':fair_center_uncertainty.get('fair_center_interval_95'),
      'residual_source':oos_profile.get('source'),
      'residual_oos_N':oos_profile.get('sample_N',0),
      'student_t_df':oos_profile.get('df'),
      'student_t_scale':oos_profile.get('scale'),
      'game_outcome_prediction_interval_80':game_outcome_interval_80,
      'game_outcome_prediction_interval_95':game_outcome_interval_95,
      'after_mean_calibration_margin':None,
      'after_deep_spread_calibration_margin':None,
      'market_spread':None,
      'model_market_gap':None,
      'betting_fair_spread':full.get('mu_margin'),
      'after_context_adjustment_margin':full.get('mu_margin'),
      'adjustment_layer':adjustment_layer,
      'spread_data_quality':spread_data_quality,
      'base_residual_scale':full.get('base_sd_margin'),
      'tier_residual_multiplier':native_scale_multiplier,
      'injury_uncertainty_multiplier':spread_uncertainty['injury_uncertainty_multiplier'],
      'rotation_uncertainty_multiplier':spread_uncertainty['rotation_uncertainty_multiplier'],
      'season_regime_multiplier':spread_uncertainty['season_regime_multiplier'],
      'context_uncertainty_multiplier':final_spread_scale,
      'final_spread_residual_scale':residual_scale_breakdown['final_spread'],
      'league_residual_multiplier':1.0,
      'deep_spread_residual_multiplier':None,
      'raw_cover_probability':None,
      'calibrated_cover_probability':None,
      'final_cover_probability':None,
      'expected_value':None,
      'selected_side':None,
      'calibration_status':'NOT_IMPLEMENTED_IN_PRODUCTION; NULLS_ARE_INTENTIONAL',
    }
    return dict(base,**audit,pricing_status='PRICED_LOW_CONFIDENCE',mu_raw=full['mu_margin'],mu_structural=full['mu_margin'],
      total_raw=full['mu_total'],total_structural=full['mu_total'],team1_points=full['team1_points'],team2_points=full['team2_points'],
      score_contract='INCLUDING_OT',scenarios=scenarios,pricing_data_quality=quality,effective_weight=eff,paper_model_eligible=bool(eligible),
      spread_data_quality=spread_data_quality,spread_context=base['spread_context'],adjustment_layer=adjustment_layer,
      base_fair_spread=base_fair_spread,final_fair_spread=full['mu_margin'],season_regime=season_regime,season_regime_evidence=season_regime_evidence,
      raw_fair_spread=base_fair_spread,calibrated_fair_spread=None,
      fair_center_standard_error=fair_center_uncertainty.get('fair_center_standard_error'),
      fair_center_interval_80=fair_center_uncertainty.get('fair_center_interval_80'),
      fair_center_interval_95=fair_center_uncertainty.get('fair_center_interval_95'),
      fair_center_uncertainty=fair_center_uncertainty,
      residual_profile=oos_profile,
      residual_source=oos_profile.get('source'),residual_oos_N=oos_profile.get('sample_N',0),
      student_t_df=oos_profile.get('df'),student_t_scale=oos_profile.get('scale'),
      game_outcome_prediction_interval_80=game_outcome_interval_80,
      game_outcome_prediction_interval_95=game_outcome_interval_95,
      injury_uncertainty_multiplier=spread_uncertainty['injury_uncertainty_multiplier'],
      rotation_uncertainty_multiplier=spread_uncertainty['rotation_uncertainty_multiplier'],
      season_regime_multiplier=spread_uncertainty['season_regime_multiplier'],
      context_uncertainty_multiplier=final_spread_scale,residual_scale_breakdown=residual_scale_breakdown,
      paper_evidence_blockers=list(dict.fromkeys(paper_evidence_blockers)),
      model_warnings=warnings,structured_method='SCORE_RIDGE_NO_QUALITY_MULTIPLIER',
      fair_spread_decomposition=decomposition,
      fair_spread_text=display_fair_margin(event,full['mu_margin']),
      total_diagnostic=diagnostic,total_execution_eligible=diagnostic['execution_eligible'],
      spread_execution_eligible=not missing_spread_context,
      spread_context_missing=missing_spread_context,
      pricing_state=cold_state,research_priceable=True,cold_start_priceable=bootstrap_used,
      cold_start_residual_multiplier=cold_scale_multiplier if bootstrap_used else 1.0,
      residual_scale_multiplier=scale_multiplier,
      competition_strength_adjustment=dict(competition_adjustments),
      challenger_prices=_challenger_outputs(foundation_pricing,full['mu_margin'],full['mu_total']),
      gate_challengers={
        'B_RAW_COUNT_TO_ESS':{'history_ess':weight_profile['history_ess'],'threshold':8.0,
                              'would_pass':weight_profile['history_ess']>=8.0,'champion_unchanged':True},
        'C_RAW_OPPONENTS_TO_WEIGHTED_DIVERSITY':{'effective_opponent_diversity':weight_profile['effective_opponent_diversity'],
                                                'threshold':3.0,'would_pass':weight_profile['effective_opponent_diversity']>=3.0,
                                                'champion_unchanged':True}},
      shadow_eligible=shadow_eligible,executable_eligible=False,
      league_lifecycle_state=lifecycle,blockers=blockers)

def apply_full_game_overtime_contract(q):
    """Apply the user's full-game including-OT comparison contract.

    A source omission remains visible as source metadata.  It is not evidence
    that a market is regulation-only.  A source that explicitly says
    regulation-only remains incompatible and is never silently relabelled.
    """
    # quote_state is intentionally called more than once (freshness, market
    # integrity, and per-market decision).  Preserve the original source
    # omission rather than relabelling a prior policy assumption as source
    # confirmation on the second pass.
    if q.get('ot_contract_status') == 'ASSUMED_INCLUDING_OT_FROM_GLOBAL_POLICY':
        return q
    source_rule = q.get('ot_rule') or 'UNKNOWN'
    if source_rule == 'REGULATION_ONLY':
        q['ot_contract_status'] = 'EXPLICIT_REGULATION_ONLY_CONFLICT'
        return q
    if source_rule != 'INCLUDING_OT':
        q.setdefault('source_ot_rule', source_rule)
        q.setdefault('source_rule_evidence', q.get('rule_evidence'))
        q['ot_rule'] = FULL_GAME_CONTRACT.get('overtime_rule', 'INCLUDING_OT')
        q['rule_evidence'] = FULL_GAME_CONTRACT.get(
            'policy_evidence', 'USER_CONFIRMED_GLOBAL_FULL_GAME_INCLUDING_OT_2026-10-08')
        q['ot_contract_status'] = 'ASSUMED_INCLUDING_OT_FROM_GLOBAL_POLICY'
    else:
        q['ot_contract_status'] = 'SOURCE_CONFIRMED_INCLUDING_OT'
    return q


def quote_state(q,event,asof):
    apply_full_game_overtime_contract(q)
    reasons=list(q.get('migration_blockers',[]));c=iso(asof)
    if not q.get('raw_verified'):reasons.append('RAW_QUOTE_NOT_VERIFIED')
    if not event.get('identity_verified'):reasons.append('EVENT_IDENTITY_UNVERIFIED')
    if q.get('event_id') != event.get('event_id'):reasons.append('QUOTE_EVENT_MISMATCH')
    if not q.get('bookmaker_id'):reasons.append('BOOKMAKER_UNKNOWN')
    if q.get('period') != 'FULL_GAME':reasons.append('PERIOD_UNVERIFIED_OR_UNSUPPORTED')
    if q.get('status') in ('SUSPENDED','CLOSED','STALE','UNAVAILABLE'):reasons.append('MARKET_NOT_OPEN')
    if q.get('status') != 'OPEN' and not q.get('current_board_contract_verified'):reasons.append('OPEN_STATUS_UNVERIFIED')
    if iso(event['tip_at'])<=c:reasons.append('EVENT_ALREADY_STARTED')
    rec=iso(q['received_at']) if q.get('received_at') else None
    qt=iso(q['source_quote_at']) if q.get('source_quote_at') else None
    if qt and qt>c+timedelta(seconds=5):reasons.append('QUOTE_TIME_IN_FUTURE')
    if rec and rec>c+timedelta(seconds=5):reasons.append('CAPTURE_AFTER_CUTOFF')
    minutes=(iso(event['tip_at'])-c).total_seconds()/60
    ttl=300 if minutes<=30 else 600 if minutes<=120 else 1800 if minutes<=360 else 3600
    # A verified current-board endpoint proves that the displayed line was
    # still listed when captured, even if it omits the line's last-change time.
    # This is current-listing freshness, not a fabricated source timestamp.
    semantics=str(q.get('source_timestamp_semantics') or '').upper()
    last_verified=iso(q['last_verified_at']) if q.get('last_verified_at') else None
    current_listing=(q.get('current_board_contract_verified') is True and q.get('status')=='OPEN' and
                     semantics == 'CURRENT_BOARD_CAPTURE_ONLY' and (last_verified is not None or rec is not None))
    basis=(last_verified or rec) if current_listing else qt
    freshness_basis='VERIFIED_CURRENT_BOARD_CAPTURE' if current_listing else 'SOURCE_QUOTE_TIME' if qt else 'UNKNOWN'
    age=(c-basis).total_seconds() if basis else None
    if age is None:reasons.append('QUOTE_TIME_UNKNOWN')
    elif age>ttl:reasons.append('STALE_QUOTE')
    if not q.get('price_format_verified'):reasons.append('PRICE_FORMAT_UNVERIFIED')
    if not q.get('direction_verified'):reasons.append('SELECTION_DIRECTION_UNVERIFIED')
    if q.get('ot_contract_status') == 'EXPLICIT_REGULATION_ONLY_CONFLICT':reasons.append('OT_POLICY_MISMATCH')
    elif q.get('ot_rule') != 'INCLUDING_OT' or not q.get('rule_evidence'):reasons.append('UNKNOWN_OT_RULE')
    if q.get('main_or_alt')!='MAIN':reasons.append('MAIN_MARKET_UNVERIFIED')
    return {'reasons':list(dict.fromkeys(reasons)),'age_seconds':age,'ttl_seconds':ttl,
      'freshness_basis':freshness_basis,
      'raw_observation':bool(q.get('raw_verified')),'fresh_observation':bool(q.get('raw_verified') and age is not None and 0<=age<=ttl and iso(event['tip_at'])>c),
      'paper_quote_eligible':not reasons}

def market_integrity(quotes,event,asof):
    """Quarantine divergent fresh MAIN quotes while preserving every raw observation."""
    grouped=defaultdict(list)
    for q in quotes:
        state=quote_state(q,event,asof)
        if not state['paper_quote_eligible'] or q.get('main_or_alt')!='MAIN':
            continue
        line=q.get('line_team1') if q.get('market_type')=='SPREAD' else q.get('raw_line')
        if not isinstance(line,(int,float)):
            continue
        key=(q.get('market_type'),q.get('period'),q.get('ot_rule'))
        grouped[key].append((q,float(line)))
    minimum=int(MARKET_INTEGRITY.get('minimum_fresh_main_quotes',2))
    limits=MARKET_INTEGRITY.get('max_deviation_from_cross_book_median',{})
    result={}
    for key,rows in grouped.items():
        if len(rows)<minimum:
            continue
        center=median([line for _,line in rows])
        limit=float(limits.get(key[0],float('inf')))
        for q,line in rows:
            deviation=abs(line-center)
            result[q['quote_id']]={'median_line':center,'line':line,'deviation':deviation,
                'max_allowed_deviation':limit,'outlier':deviation>limit,'quote_count':len(rows)}
    return result

def decide_market(event,forecast,quotes,cutoff,mode,market_gap_history=None):
    base={'event_id':event['event_id'],'asof':cutoff,'archive_type':mode,'model_state':'UNASSESSED','shadow_action':'BLOCKED',
          'display_action':'不可投','real_stake':0,'real_bet_flag':False,'kelly_usable':False,'triggered':False,'real_execution_allowed':False,
          'execution_mode':'MANUAL_LIVE' if mode=='FORWARD_NATIVE' else 'REPLAY_AUDIT',
          'automated_execution_allowed':False,'manual_order_required':True,'manual_execution_state':'NOT_ELIGIBLE',
          'blockers':[],'uncertainty_flags':[],'candidates':[],'ev':None,'comparison_ready':False}
    integrity=market_integrity(quotes,event,cutoff)
    base['market_integrity']=integrity
    if forecast['pricing_status']=='UNPRICEABLE':base['blockers']+=forecast.get('blockers',['UNPRICEABLE']);base['model_state']='UNPRICEABLE'
    if not quotes:
        base['blockers'].append('NO_MARKET')
        if forecast['pricing_status']!='UNPRICEABLE':base.update(shadow_action='WATCH',display_action='观察')
        return base
    if not forecast.get('paper_model_eligible'):
        evidence=list(forecast.get('paper_evidence_blockers') or [])
        if evidence:
            base['blockers']+=evidence
        elif not forecast.get('blockers'):
            base['blockers'].append('MODEL_CORE_INPUT_MISSING')
    valid=[];p=POLICY[event['model_family']]
    for q in quotes:
        qs=quote_state(q,event,cutoff);mi=integrity.get(q['quote_id'])
        item={'quote_id':q['quote_id'],'bookmaker':q.get('bookmaker'),'market_type':q['market_type'],'quote_state':qs,'market_integrity':mi}
        base['candidates'].append(item)
        if not qs['paper_quote_eligible']:
            base['blockers']+=qs['reasons'];continue
        if mi and mi['outlier']:
            base['blockers'].append('PROVIDER_DISAGREEMENT')
            continue
        if q['market_type']=='TOTAL' and not forecast.get('total_execution_eligible',False):
            hard=list((forecast.get('total_diagnostic') or {}).get('hard_blockers') or [])
            base['blockers']+=['TOTAL_CONTEXT_INCOMPLETE']+hard
            continue
        if q['market_type']=='TOTAL':
            base['uncertainty_flags']+=list((forecast.get('total_diagnostic') or {}).get('soft_missing') or [])
        if q['market_type']=='SPREAD' and not forecast.get('spread_execution_eligible',True):
            base['blockers'].append('SPREAD_CONTEXT_INCOMPLETE')
            continue
        s=forecast.get('scenarios',{}).get(q['ot_rule'])
        if not s:continue
        sides=('TEAM1','TEAM2') if q['market_type']=='SPREAD' else ('OVER','UNDER')
        prices=q.get('decimal_prices')
        if not prices or len(prices)!=2 or any(x is None or x<=1 for x in prices):continue
        for i,side in enumerate(sides):
            threshold=-q['line_team1'] if q['market_type']=='SPREAD' else q['raw_line']
            mu=s['mu_margin'] if q['market_type']=='SPREAD' else s['mu_total'];sd=s['sd_margin'] if q['market_type']=='SPREAD' else s['sd_total']
            direction='OVER' if side in ('TEAM1','OVER') else 'UNDER';shift=p['mean_margin'] if q['market_type']=='SPREAD' else p['mean_total']
            adverse=mu-shift if direction=='OVER' else mu+shift
            cdf_actual=margin_cdf(mu,sd,s['df'],q['ot_rule']) if q['market_type']=='SPREAD' else (lambda x:t_cdf(x,mu,sd,s['df']))
            cdf_adverse=margin_cdf(adverse,sd,s['df'],q['ot_rule']) if q['market_type']=='SPREAD' else (lambda x:t_cdf(x,adverse,sd,s['df']))
            wpl=threshold_probability(cdf_actual,threshold,direction)
            low=threshold_probability(cdf_adverse,threshold,direction)
            a=ev_and_kelly(wpl,prices[i]);b=ev_and_kelly(low,prices[i]);edge=b['p_win_conditional_nonpush']-1/prices[i]
            probability=probability_fields(wpl,prices[i])
            fair_margin=float(s['mu_margin']) if q['market_type']=='SPREAD' else None
            market_threshold=float(threshold) if q['market_type']=='SPREAD' else None
            raw_team1_gap=(fair_margin-market_threshold) if fair_margin is not None else None
            selected_side_edge=((fair_margin if side=='TEAM1' else -fair_margin) + float(q['line_team1'] if side=='TEAM1' else -q['line_team1'])) if fair_margin is not None else ((float(s['mu_total'])-float(q['raw_line'])) if side=='OVER' else (float(q['raw_line'])-float(s['mu_total'])))
            gap=selected_side_edge
            disagreement=market_gap_percentile(market_gap_history or [], abs(raw_team1_gap) if raw_team1_gap is not None else abs(selected_side_edge) if selected_side_edge is not None else None)
            path={'OPEN':q.get('open_at'),'FIRST_SEEN':q.get('first_seen_at'),
                  'SIGNAL':cutoff,'T-90':q.get('t90_at'),'T-30':q.get('t30_at'),
                  'T-10':q.get('t10_at'),'LAST_PREMATCH':q.get('source_quote_at'),'CLOSE':None}
            path_status='MARKET_PATH_COMPLETE' if all(path.get(k) for k in ('OPEN','FIRST_SEEN','SIGNAL','LAST_PREMATCH')) else 'MARKET_PATH_PARTIAL'
            robust=direction_robustness(forecast.get('fair_center_interval_80'),market_threshold,side) if q['market_type']=='SPREAD' else None
            risk=information_risk(
                context_complete=forecast.get('spread_data_quality') in ('DATA_QUALITY_A','DATA_QUALITY_B'),
                fair_center_se=forecast.get('fair_center_standard_error'),
                disagreement_percentile=disagreement,path_status=path_status,
                source_quality=forecast.get('spread_data_quality'))
            z={'quote_id':q['quote_id'],'bookmaker':q.get('bookmaker'),'selection':side,'market_type':q['market_type'],
               'line':(q['line_team1'] if i==0 else -q['line_team1']) if q['market_type']=='SPREAD' else q['raw_line'],
               'decimal_odds':prices[i],'ev':a['ev'],'adverse_ev':b['ev'],'conditional_edge':edge,
               'p_win':wpl.win,'p_push':wpl.push,'p_loss':wpl.loss,'ot_rule':q['ot_rule'],
               'research_edge_pass':b['ev']>=.025 and edge>=p['buffer'],
               'edge_gate':{'conservative_ev':b['ev'],'minimum_conservative_ev':.025,
                            'conditional_edge':edge,'minimum_conditional_edge':p['buffer'],
                            'conservative_ev_pass':b['ev']>=.025,
                            'conditional_edge_pass':edge>=p['buffer'],
                            'formal_edge_pass':b['ev']>=.025 and edge>=p['buffer']},
               **probability,
               'line_edge_points':gap,
               'selected_side_line_edge_points':selected_side_edge,
               'raw_team1_line_gap':raw_team1_gap,
               'model_market_gap_points':gap,
               'probability_source':'MODEL_RESIDUAL_STUDENT_T',
               'calibrated_probability':None,
               'residual_source':forecast.get('residual_source') or s.get('residual_source'),
               'residual_N':forecast.get('residual_oos_N') or s.get('residual_N'),
               'df':s.get('df'),
               'residual_scale':s.get('sd_margin') if q['market_type']=='SPREAD' else s.get('sd_total'),
               'direction_robust_80':robust,
               'market_disagreement_percentile':disagreement,
               'market_path':path,'market_path_status':path_status,
               'market_convergence_divergence':('MARKET_DIVERGENCE' if disagreement is not None and disagreement > .95 else
                                                'MARKET_CONVERGENCE' if disagreement is not None and disagreement < .10 else 'UNCONFIRMED'),
               'information_risk':risk}
            foundation=dict(forecast.get('titan_foundation_pricing') or {})
            if q['market_type']=='SPREAD' and isinstance(foundation.get('technical_fair_margin_neutral'),(int,float)):
                team1_edge=float(foundation['technical_fair_margin_neutral'])+float(q['line_team1'])
                foundation_edge=team1_edge if side=='TEAM1' else -team1_edge
                z.update(foundation_fair_line=foundation['technical_fair_margin_neutral'],
                         foundation_edge_points=foundation_edge,
                         foundation_line_basis='TEAM1_EXPECTED_MARGIN_NEUTRAL_COURT')
            elif q['market_type']=='TOTAL' and isinstance(foundation.get('technical_fair_total'),(int,float)):
                over_edge=float(foundation['technical_fair_total'])-float(q['raw_line'])
                foundation_edge=over_edge if side=='OVER' else -over_edge
                z.update(foundation_fair_line=foundation['technical_fair_total'],
                         foundation_edge_points=foundation_edge,
                         foundation_line_basis='EXPECTED_TOTAL_FROM_PACE_AND_PPP')
            if 'foundation_edge_points' in z:
                z['foundation_comparison_status']='SUPPORTS_SELECTION' if z['foundation_edge_points']>0 else \
                    'OPPOSES_SELECTION' if z['foundation_edge_points']<0 else 'NEUTRAL'
                z['foundation_market_inputs_used']=False
            if q['market_type']=='SPREAD':
                decomposition=dict(forecast.get('fair_spread_decomposition') or {})
                decomposition.update({
                    'market_spread':q.get('line_team1'),
                    'model_market_gap':(forecast.get('mu_raw') - q.get('line_team1')) if isinstance(forecast.get('mu_raw'), (int, float)) and q.get('line_team1') is not None else None,
                    'raw_cover_probability':wpl.win,
                    'p_win':wpl.win,'p_push':wpl.push,'p_loss':wpl.loss,
                    'conditional_break_even_probability':probability.get('conditional_break_even_probability'),
                    'break_even_win_probability':probability.get('break_even_win_probability'),
                    'probability_edge':probability.get('probability_edge'),
                    'line_edge_points':gap,
                    'selected_side_line_edge_points':selected_side_edge,
                    'raw_team1_line_gap':raw_team1_gap,
                    'calibrated_cover_probability':None,
                    'final_cover_probability':wpl.win,
                    'expected_value':a['ev'],
                    'selected_side':side,
                })
                z['pricing_decomposition']=decomposition
            valid.append(z)
    if valid:
        # Best single actual offered quote, never median line + another book's price.
        best=max(valid,key=lambda z:z['adverse_ev']);base.update(comparison_ready=True,comparison_rows=valid,selected=best,ev=best['ev'],
          model_state='EDGE' if best['research_edge_pass'] else 'LEAN' if best['ev']>0 else 'NO_EDGE')
        if best.get('pricing_decomposition'):
            base['fair_spread_decomposition']=best['pricing_decomposition']
        # Other invalid book quotes do not poison a valid book; retain them under candidates.
        persistent=set(forecast.get('blockers',[]))|set(forecast.get('paper_evidence_blockers',[]))
        if any(q.get('market_type')=='TOTAL' for q in quotes):
            persistent|=set((forecast.get('total_diagnostic') or {}).get('hard_blockers') or [])
            if not forecast.get('total_execution_eligible',False):persistent.add('TOTAL_CONTEXT_INCOMPLETE')
        if any(q.get('market_type')=='SPREAD' for q in quotes) and not forecast.get('spread_execution_eligible',True):
            persistent.add('SPREAD_CONTEXT_INCOMPLETE')
        persistent.add('PROVIDER_DISAGREEMENT')
        base['blockers']=[x for x in base['blockers'] if x in persistent]
        if not base['blockers']:
            passed=best['research_edge_pass']
            # Replay is computation audit, never a live paper fill.
            if mode=='FORWARD_NATIVE' and passed:base.update(shadow_action='SHADOW_BET',display_action='手动实盘候选',triggered=True,
                real_execution_allowed=True,automated_execution_allowed=False,manual_order_required=True,
                manual_execution_state='MANUAL_LIVE_CANDIDATE')
            else:base.update(shadow_action='PASS',display_action='不可投')
    base['blockers']=list(dict.fromkeys(base['blockers']))
    base['uncertainty_flags']=list(dict.fromkeys(base['uncertainty_flags']))
    return base


def decide_titan_market(event, forecast, quotes, cutoff, mode, market_type):
    """Evaluate the Titan technical challenger in an isolated provisional lane.

    It uses the same verified market contract and unchanged Champion EV/edge
    thresholds, but can never create a Qualified Paper entry by itself.
    """
    foundation = dict(forecast.get('titan_foundation_pricing') or {})
    bundle = dict(forecast.get('pregame_evidence_bundle') or {})
    data_quality = dict(bundle.get('DATA_QUALITY') or {})
    fair = (foundation.get('technical_fair_margin_neutral') if market_type == 'SPREAD'
            else foundation.get('technical_fair_total'))
    base = {
        'market_type': market_type, 'status': 'TITAN_RESEARCH_PRICE' if isinstance(fair, (int, float)) else 'UNAVAILABLE',
        'model_name': 'TITAN_TECHNICAL_CHALLENGER', 'fair_line': fair,
        'comparison_ready': False, 'edge': False, 'selected': None, 'comparison_rows': [],
        'hard_blockers': [], 'soft_missing': ['MODEL_NOT_YET_CHAMPION_VALIDATED'],
        'qualified_eligible': False, 'champion_eligible': False,
        'triggered': False, 'strategy_return_eligible': False, 'real_execution_allowed': False,
    }
    if not isinstance(fair, (int, float)):
        base['hard_blockers'].append('NO_INDEPENDENT_FAIR_PRICE')
        return base
    if not data_quality.get('history_ready'):
        base['hard_blockers'].append('INSUFFICIENT_HISTORY')
    if not data_quality.get('rule_ready'):
        base['hard_blockers'].append('GAME_RULE_UNKNOWN')
    tier, tier_spec = tier_for(event)
    if tier == 'TIER_3' and not data_quality.get('rotation_continuity_verified'):
        if market_type == 'SPREAD' and _nba_cba_spread_context_is_soft(event):
            base['soft_missing'].append('ROSTER_STABILITY_UNKNOWN')
        else:
            base['hard_blockers'].append('ROSTER_STABILITY_MISSING')
    if data_quality.get('current_availability') != 'KNOWN':
        base['soft_missing'].append('CURRENT_AVAILABILITY_UNKNOWN')
    if market_type == 'TOTAL':
        pace = ((bundle.get('PACE') or {}).get('pace_level') or {}).get('value')
        possessions = ((bundle.get('PACE') or {}).get('derived_possessions') or {}).get('value')
        if pace not in ('LEVEL_A', 'LEVEL_B') or not isinstance(possessions, (int, float)):
            base['hard_blockers'].append('POSSESSIONS_EVIDENCE_MISSING')
    if not quotes:
        base['hard_blockers'].append('NO_MARKET')
        return base
    integrity = market_integrity(quotes, event, cutoff)
    valid_quotes = []
    line_only = []
    for quote in quotes:
        state = quote_state(quote, event, cutoff)
        line = quote.get('line_team1') if market_type == 'SPREAD' else quote.get('raw_line')
        prices = quote.get('decimal_prices')
        if isinstance(line, (int, float)) and (not prices or len(prices) != 2 or any(
                value is None or value <= 1 for value in prices)):
            gap = (float(fair) + float(line)) if market_type == 'SPREAD' else float(fair) - float(line)
            line_only.append({'quote_id': quote.get('quote_id'), 'line': line, 'line_gap_team1_or_over': gap,
                              'status': 'LINE_EDGE_RESEARCH', 'bookmaker': quote.get('bookmaker')})
        if state.get('paper_quote_eligible') and not (integrity.get(quote.get('quote_id')) or {}).get('outlier'):
            valid_quotes.append(quote)
    base['line_only_research'] = line_only
    if not valid_quotes:
        base['hard_blockers'].append('MARKET_PRICE_MISSING' if line_only else 'NO_VERIFIED_MARKET_CONTRACT')
        base['status'] = 'LINE_EDGE_RESEARCH' if line_only else base['status']
        return base
    policy = POLICY[event['model_family']]
    residual = float(policy['sd_margin'] if market_type == 'SPREAD' else policy['sd_total'])
    residual *= float(tier_spec.get('residual_scale_multiplier', 1.45))
    provisional = SHADOW_POLICY.get('provisional') or {}
    per_soft = float(provisional.get('per_soft_reason_residual_multiplier_add', 0.08))
    maximum = float(provisional.get('maximum_residual_multiplier', 1.50))
    uncertainty_multiplier = min(maximum, 1.0 + per_soft * len(set(base['soft_missing'])))
    residual *= uncertainty_multiplier
    candidates = []
    for quote in valid_quotes:
        prices = quote.get('decimal_prices')
        sides = ('TEAM1', 'TEAM2') if market_type == 'SPREAD' else ('OVER', 'UNDER')
        threshold = -quote['line_team1'] if market_type == 'SPREAD' else quote['raw_line']
        for index, side in enumerate(sides):
            direction = 'OVER' if side in ('TEAM1', 'OVER') else 'UNDER'
            mean_shift = policy['mean_margin'] if market_type == 'SPREAD' else policy['mean_total']
            adverse = float(fair) - mean_shift if direction == 'OVER' else float(fair) + mean_shift
            cdf = (margin_cdf(float(fair), residual, policy['df'], quote['ot_rule']) if market_type == 'SPREAD'
                   else (lambda value, mu=float(fair): t_cdf(value, mu, residual, policy['df'])))
            adverse_cdf = (margin_cdf(adverse, residual, policy['df'], quote['ot_rule']) if market_type == 'SPREAD'
                           else (lambda value, mu=adverse: t_cdf(value, mu, residual, policy['df'])))
            actual = threshold_probability(cdf, threshold, direction)
            conservative = threshold_probability(adverse_cdf, threshold, direction)
            actual_ev = ev_and_kelly(actual, prices[index])
            conservative_ev = ev_and_kelly(conservative, prices[index])
            edge = conservative_ev['p_win_conditional_nonpush'] - 1 / prices[index]
            candidates.append({
                'quote_id': quote.get('quote_id'), 'bookmaker': quote.get('bookmaker'),
                'market_type': market_type, 'selection': side,
                'line': ((quote['line_team1'] if index == 0 else -quote['line_team1'])
                         if market_type == 'SPREAD' else quote['raw_line']),
                'decimal_odds': prices[index], 'ot_rule': quote.get('ot_rule'),
                'p_win': actual.win, 'p_push': actual.push, 'p_loss': actual.loss,
                'ev': actual_ev['ev'], 'adverse_ev': conservative_ev['ev'], 'conditional_edge': edge,
                'research_edge_pass': conservative_ev['ev'] >= .025 and edge >= policy['buffer'],
                'edge_gate': {'conservative_ev': conservative_ev['ev'], 'minimum_conservative_ev': .025,
                              'conditional_edge': edge, 'minimum_conditional_edge': policy['buffer'],
                              'conservative_ev_pass': conservative_ev['ev'] >= .025,
                              'conditional_edge_pass': edge >= policy['buffer'],
                              'formal_edge_pass': conservative_ev['ev'] >= .025 and edge >= policy['buffer']},
                'fair_line': fair, 'residual_scale': residual,
                'provisional_uncertainty_multiplier': uncertainty_multiplier,
            })
    best = max(candidates, key=lambda item: item['adverse_ev'], default=None)
    base.update(comparison_ready=bool(best), selected=best, comparison_rows=candidates,
                edge=bool(best and best.get('research_edge_pass')))
    if best and best.get('research_edge_pass') and not base['hard_blockers']:
        base['status'] = 'TITAN_PROVISIONAL_SHADOW'
    elif best:
        base['status'] = 'TITAN_RESEARCH_PRICE'
        if not best.get('research_edge_pass'):
            base['soft_missing'].append('NO_EDGE')
    base['hard_blockers'] = list(dict.fromkeys(base['hard_blockers']))
    base['soft_missing'] = list(dict.fromkeys(base['soft_missing']))
    return base

def decide(event,forecast,quotes,cutoff,mode,market_gap_history=None):
    """Decide each market independently; retain a legacy best-selection view."""
    market_decisions={}
    for market_type in ('SPREAD','TOTAL'):
        market_quotes=[q for q in quotes if q.get('market_type')==market_type]
        market_decisions[market_type]=decide_market(event,forecast,market_quotes,cutoff,mode,market_gap_history)
    comparable=[d for d in market_decisions.values() if d.get('comparison_ready') and d.get('selected')]
    selected=max((d['selected'] for d in comparable),key=lambda x:x.get('adverse_ev',float('-inf')),default=None)
    triggered=[d for d in market_decisions.values() if d.get('triggered')]
    base=market_decisions.get('SPREAD',{}).copy()
    if not comparable:
        base=market_decisions.get('TOTAL',base).copy()
    base['market_decisions']=market_decisions
    base['comparison_ready']=bool(comparable)
    base['selected']=selected
    base['ev']=selected.get('ev') if selected else None
    base['triggered']=bool(triggered)
    base['shadow_action']='SHADOW_BET' if triggered else base.get('shadow_action','BLOCKED')
    base['display_action']='手动实盘候选' if triggered else base.get('display_action','不可投')
    base['real_execution_allowed']=bool(triggered and mode=='FORWARD_NATIVE')
    base['automated_execution_allowed']=False
    base['manual_order_required']=bool(triggered and mode=='FORWARD_NATIVE')
    base['manual_execution_state']='MANUAL_LIVE_CANDIDATE' if base['real_execution_allowed'] else 'NOT_ELIGIBLE'
    base['market_types_with_comparison']=[m for m,d in market_decisions.items() if d.get('comparison_ready')]
    base['market_types_triggered']=[m for m,d in market_decisions.items() if d.get('triggered')]
    titan_market_decisions={market_type:decide_titan_market(
        event,forecast,[q for q in quotes if q.get('market_type')==market_type],cutoff,mode,market_type)
        for market_type in ('SPREAD','TOTAL')}
    titan_rank={'TITAN_PROVISIONAL_SHADOW':4,'TITAN_QUALIFIED_ELIGIBLE':3,
                'LINE_EDGE_RESEARCH':2,'TITAN_RESEARCH_PRICE':1,'UNAVAILABLE':0}
    titan_best=max(titan_market_decisions.values(),key=lambda item:titan_rank.get(item.get('status'),0))
    base['titan_market_decisions']=titan_market_decisions
    base['titan_provisional_status']=titan_best.get('status')
    base['titan_provisional_counted']=titan_best.get('status')=='TITAN_PROVISIONAL_SHADOW'
    blockers=[]
    for d in market_decisions.values(): blockers.extend(d.get('blockers',[]))
    base['blockers']=list(dict.fromkeys(blockers))
    return base
