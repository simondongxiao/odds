"""Recent score and period context for the total-market evidence layer.

This derives only from final, pre-cutoff games. It never infers pace,
possessions, three-point rate, foul rate, travel, injuries, or rotations.
"""
from datetime import timedelta
from statistics import mean, median, pstdev

from .common import iso


def _num(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _summary(values):
    if not values:
        return {'observations': 0, 'mean': None, 'median': None, 'stdev': None,
                'min': None, 'max': None}
    return {'observations': len(values), 'mean': round(mean(values), 4),
            'median': round(median(values), 4),
            'stdev': round(pstdev(values), 4) if len(values) > 1 else 0.0,
            'min': min(values), 'max': max(values)}


def _period_summary(rows):
    result = {}
    for label, index in (('Q1', 0), ('Q2', 1), ('Q3', 2), ('Q4', 3), ('OT', 4)):
        values = [row['team_periods'][index] + row['opponent_periods'][index]
                  for row in rows if len(row['team_periods']) > index
                  and len(row['opponent_periods']) > index]
        result[label] = _summary(values)
    return result


def _team_games(games, cutoff, team_id):
    rows = []
    for game in games:
        if game.get('status') != 'FINAL' or team_id not in (game.get('team1_id'), game.get('team2_id')):
            continue
        if not game.get('tip_at') or iso(game['tip_at']) >= iso(cutoff):
            continue
        if not (_num(game.get('score1_full')) and _num(game.get('score2_full'))):
            continue
        p1, p2 = game.get('period_points_team1'), game.get('period_points_team2')
        if not (isinstance(p1, list) and isinstance(p2, list) and len(p1) >= 4 and len(p2) >= 4):
            p1 = p2 = None
        team1 = game.get('team1_id') == team_id
        team_score = game['score1_full'] if team1 else game['score2_full']
        opponent_score = game['score2_full'] if team1 else game['score1_full']
        team_periods = list(p1 if team1 else p2) if p1 is not None else []
        opponent_periods = list(p2 if team1 else p1) if p2 is not None else []
        pre_q4_margin = None
        q4_total = None
        if len(team_periods) >= 4 and len(opponent_periods) >= 4:
            pre_q4_margin = sum(team_periods[:3]) - sum(opponent_periods[:3])
            q4_total = team_periods[3] + opponent_periods[3]
        rows.append({'event_id': game.get('event_id'), 'tip_at': game['tip_at'],
                     'team_id': team_id,
                     'team_name': game.get('team1_name') if team1 else game.get('team2_name'),
                     'opponent_name': game.get('team2_name') if team1 else game.get('team1_name'),
                     'team_points': team_score, 'opponent_points': opponent_score,
                     'total_points': team_score + opponent_score, 'margin': team_score - opponent_score,
                     'team_periods': team_periods, 'opponent_periods': opponent_periods,
                     'pre_q4_margin': pre_q4_margin, 'q4_total': q4_total,
                     'close_before_q4': abs(pre_q4_margin) <= 8 if pre_q4_margin is not None else None,
                     'blowout_before_q4': abs(pre_q4_margin) >= 15 if pre_q4_margin is not None else None,
                     'final_close': abs(team_score - opponent_score) <= 8})
    return sorted(rows, key=lambda row: row['tip_at'], reverse=True)


def _window(rows, n):
    chosen = rows[:n]
    totals = [row['total_points'] for row in chosen]
    team_points = [row['team_points'] for row in chosen]
    opponent_points = [row['opponent_points'] for row in chosen]
    q4_close = [row['q4_total'] for row in chosen if row['close_before_q4'] and row['q4_total'] is not None]
    q4_blowout = [row['q4_total'] for row in chosen if row['blowout_before_q4'] and row['q4_total'] is not None]
    rest_days = []
    for current, previous in zip(chosen, chosen[1:]):
        delta = (iso(current['tip_at']) - iso(previous['tip_at'])).total_seconds() / 86400
        rest_days.append(round(max(0.0, delta), 4))
    last_tip = iso(chosen[0]['tip_at']) if chosen else None
    cutoff_14d = iso(last_tip) - timedelta(days=14) if last_tip else None
    density_14d = sum(1 for row in chosen if cutoff_14d and iso(row['tip_at']) >= cutoff_14d)
    margins = [row['margin'] for row in chosen]
    return {'games': len(chosen), 'event_ids': [row['event_id'] for row in chosen],
            'total_points': _summary(totals), 'team_points': _summary(team_points),
            'opponent_points': _summary(opponent_points), 'period_total_points': _period_summary(chosen),
            'close_before_q4': {'games': sum(row['close_before_q4'] is True for row in chosen), 'q4_total': _summary(q4_close)},
            'blowout_before_q4': {'games': sum(row['blowout_before_q4'] is True for row in chosen), 'q4_total': _summary(q4_blowout)},
            'final_close_games': sum(row['final_close'] for row in chosen),
            'rest_days': _summary(rest_days), 'games_in_14_days': density_14d,
            'score_volatility': {'total_stdev': _summary(totals)['stdev'],
                                 'team_stdev': _summary(team_points)['stdev'],
                                 'margin_stdev': _summary(margins)['stdev']},
            'rows': chosen}


def build_score_context(event, games, cutoff):
    """Return auditable 5/10-game context for both teams and the matchup."""
    team_context = {}
    all_rows = []
    for team_id in (event.get('team1_id'), event.get('team2_id')):
        rows = _team_games(games, cutoff, team_id)
        all_rows.extend(rows)
        team_context[team_id] = {'team_name': next((r['team_name'] for r in rows if r.get('team_name')), team_id),
                                 'windows': {'last_5': _window(rows, 5), 'last_10': _window(rows, 10)},
                                 'period_data_coverage': sum(bool(r['team_periods']) for r in rows[:10])}
    return {'status': 'READY' if all(v['windows']['last_5']['games'] >= 5 for v in team_context.values()) else 'PARTIAL',
            'cutoff': cutoff, 'method': 'FINAL_SCORE_AND_PERIODS_ONLY', 'team_context': team_context,
            'matchup_recent_total': _summary([r['total_points'] for r in all_rows[:10]]),
            'period_evidence': 'VERIFIED_WHEN_SOURCE_PERIOD_ARRAY_PRESENT',
            'close_game_definition': 'absolute_margin_before_Q4 <= 8 points',
            'blowout_definition': 'absolute_margin_before_Q4 >= 15 points',
            'schedule_context': 'rest intervals and 14-day density only; travel is not inferred',
            'missing_not_inferred': ['possessions', 'pace', 'three_point_rate', 'foul_rate', 'injury', 'rotation', 'travel'],
            'source_event_ids': sorted({r['event_id'] for r in all_rows if r.get('event_id')})}
