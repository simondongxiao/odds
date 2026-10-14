from __future__ import annotations
import json, shutil, subprocess, sys, uuid, time
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path
from . import VERSION
from .common import *
from .source import collect_live, replay_bundle
from .model import price_event, decide, quote_state
from .history_index import HistoryIndex
from .prior_forward_index import load_prior_forward_records
from .report import (write_dashboard, project_row, csvwrite, funnel, cold_start_summary,
                      HTML, standalone_preview, coalesce_duplicate_display_rows)
from .pricing_funnel_diagnostic import build_pricing_funnel_diagnostic
from .total_market_pipeline_diagnostic import build_total_market_pipeline_diagnostic
from .history_readiness_diagnostic import build_history_readiness_diagnostic
from .analytics import append_lifecycle_revision, build_analytics, lifecycle_config, _phase
from .p0_bias_audit import build_p0_bias_audit
from .unified_evidence_audit import build_unified_evidence_audit
from .shadow_learning import (annotate_decision, freeze_learning_records,
                              freeze_titan_provisional_records,
                              settle_learning_records, build_shadow_learning_analytics,
                              daily_paper_funnel)
from .manual_live_ledger import build_formal_manual_live_ledger
from .spread_probability import (load_oos_residuals, append_oos_residuals,
                                 residual_rows_from_analytics,
                                 build_spread_probability_audit)
from coverage_funnel import build as build_coverage
from providers.titan007_feature_store import freeze_pregame_snapshot, store_market_observations
from titan007_evidence_bridge import attach_market_evidence

DEFAULT_CONTRACTS={'schema_version':1,'companies':{},'note':'Company rules must be evidenced; empty config means observation-only, not false executable success.'}


def event_continuity_key(event):
    """Return the durable identity for a scheduled fixture.

    Provider event IDs (and, unusually, provider team IDs) may be regenerated
    during a board refresh.  A normalized unordered team-name pair plus the
    scheduled tip is therefore the only identity suitable for *continuity*.
    This helper is deliberately not a market/signal matcher.
    """
    event = event or {}
    attach_canonical_team_ids(event)
    def side_token(side):
        canonical=event.get('canonical_'+side+'_id')
        if canonical:return canonical
        values=[event.get(side+'_name')]+list(event.get(side+'_aliases') or [])
        tokens={canonical_team_token(value) for value in values if canonical_team_token(value)}
        cba_tokens=sorted(token for token in tokens if token.startswith('cba:'))
        if cba_tokens:
            return cba_tokens[0]
        # Prefer the provider's primary display name over an optional Latin
        # alias.  Titan often supplies both a Chinese display name and an
        # English alias while 7M supplies only the Chinese name; choosing the
        # Latin alias here made the two providers receive different
        # continuity keys and rendered one fixture twice.  Cross-language
        # reconciliation belongs in the source merge layer, not this key.
        primary=canonical_team_token(event.get(side+'_name'))
        return primary or (sorted(tokens)[0] if tokens else '')

    names = tuple(sorted(filter(None, (side_token('team1'), side_token('team2')))))
    ids = tuple(sorted(filter(None, (str(event.get('team1_id') or ''), str(event.get('team2_id') or '')))))
    teams = names if len(names) == 2 else ids
    tip = event.get('tip_at') or event.get('tip_time_bj')
    if not teams or not tip:
        return ('EVENT_ID', str(event.get('event_id') or ''))
    try:
        tip_key = iso(tip).replace(second=0, microsecond=0).isoformat()
    except (TypeError, ValueError):
        tip_key = str(tip)[:19]
    return ('TEAM_PAIR_AND_TIP_TIME', teams, tip_key)


def _inventory_team_tokens(event, side):
    values = [event.get(side + '_name')] + list(event.get(side + '_aliases') or [])
    return {token for value in values
            for token in (canonical_team_token(value),)
            if token}


def _inventory_competition_family(event):
    text = ' '.join(str(event.get(key) or '') for key in
                    ('competition_key', 'league', 'league_family')).upper()
    if 'WNBA' in text or '美国女子' in text:
        return 'WNBA'
    if 'NBA' in text:
        return 'NBA'
    if 'CBA' in text or '中国男子' in text:
        return 'CBA'
    return text.replace('季前', '').replace('季后', '').replace('常规赛', '').strip()


def _same_inventory_fixture(left, right, tolerance_minutes=5):
    """Match source inventory rows despite small provider tip-time drift.

    Some boards publish the same fixture at 02:00 and 02:04. Exact timestamp
    keys therefore split one game into two rows. Only the same unordered team
    pair, compatible competition family, and a bounded time window qualify;
    this is not a general fuzzy market matcher.
    """
    attach_canonical_team_ids(left);attach_canonical_team_ids(right)
    left_pair=(left.get('canonical_team1_id'),left.get('canonical_team2_id'))
    right_pair=(right.get('canonical_team1_id'),right.get('canonical_team2_id'))
    if not all(left_pair) or not all(right_pair):
        return False
    if left_pair != right_pair:
        return False
    left_family = _inventory_competition_family(left)
    right_family = _inventory_competition_family(right)
    if left_family and right_family and left_family != right_family:
        return False
    try:
        left_tip = iso(left.get('tip_at') or left.get('tip_time_bj'))
        right_tip = iso(right.get('tip_at') or right.get('tip_time_bj'))
    except (TypeError, ValueError):
        return False
    return abs((left_tip - right_tip).total_seconds()) <= tolerance_minutes * 60


def _load_titan_provisional_continuity(root, asof):
    """Load immutable Titan first-writes keyed independently of provider IDs.

    This is only used to preserve a pre-existing provisional card when a
    source reissues the same fixture under a fresh event ID.  It never turns a
    historic selection into a new quote, signal, paper entry, or execution.
    """
    first_by_market = {}
    for path in (Path(root) / 'ledger' / 'titan_provisional').glob('*/*.json'):
        record = load(path, {})
        event = record.get('event') or {}
        if (record.get('archive_type') != 'FORWARD_NATIVE' or
                record.get('shadow_level') != 'TITAN_PROVISIONAL_SHADOW' or
                not isinstance(event, dict) or not event.get('event_id')):
            continue
        first_write_at = str(record.get('first_write_at') or '')
        if first_write_at and first_write_at > str(asof):
            continue
        key = event_continuity_key(event)
        market_type = str(record.get('market_type') or 'UNKNOWN')
        slot = (key, market_type)
        prior = first_by_market.get(slot)
        if prior is None or (first_write_at, str(record.get('record_id') or path)) < (
                str(prior.get('first_write_at') or ''), str(prior.get('record_id') or '')):
            first_by_market[slot] = record

    aliases = {}
    for (key, _), record in first_by_market.items():
        aliases.setdefault(key, []).append(record)
    for records in aliases.values():
        records.sort(key=lambda x: (str(x.get('first_write_at') or ''), str(x.get('market_type') or '')))
    return aliases


def apply_titan_provisional_continuity(event, decision, aliases):
    """Retain an old Titan provisional card across an ID-only source reissue.

    The current run's decision remains intact and is exposed as a recheck
    status.  The retained selection is immutable historical evidence, not a
    fresh recommendation or a replacement for the current market decision.
    """
    records = list((aliases or {}).get(event_continuity_key(event), []))
    if not records:
        return False
    current_event_id = str(event.get('event_id') or '')
    records = [r for r in records if str(r.get('event_id') or '') != current_event_id]
    if not records or decision.get('titan_provisional_status') == 'TITAN_PROVISIONAL_SHADOW':
        return False
    selected_record = records[0]
    selected = {
        'selection': selected_record.get('selected_side'),
        'market_type': selected_record.get('market_type'),
        'line': selected_record.get('market_line'),
        'decimal_odds': selected_record.get('decimal_odds'),
        'bookmaker': selected_record.get('bookmaker'),
        'ot_rule': selected_record.get('ot_rule'),
    }
    current_status = decision.get('titan_provisional_status') or 'UNAVAILABLE'
    decision['titan_provisional_continuity'] = {
        'status': 'HISTORICAL_FIRST_WRITE_RETAINED',
        'reason': 'PROVIDER_EVENT_ID_REISSUED',
        'immutable_first_write': True,
        'new_signal_created': False,
        'paper_entry_created': False,
        'real_execution_allowed': False,
        'source_event_ids': sorted({str(r.get('event_id')) for r in records}),
        'current_event_id': current_event_id,
        'first_write_at': selected_record.get('first_write_at'),
        'selected': selected,
        'first_write_records': [{
            'event_id': r.get('event_id'), 'record_id': r.get('record_id'),
            'first_write_at': r.get('first_write_at'), 'market_type': r.get('market_type'),
            'selected_side': r.get('selected_side'), 'market_line': r.get('market_line'),
            'decimal_odds': r.get('decimal_odds'), 'bookmaker': r.get('bookmaker'),
            'ot_rule': r.get('ot_rule'),
        } for r in records],
        'current_revalidation_status': current_status,
        'current_revalidation_blockers': list(decision.get('blockers') or []),
    }
    decision['titan_provisional_current_status'] = current_status
    decision['titan_provisional_status'] = 'TITAN_PROVISIONAL_SHADOW'
    return True


def _load_market_gap_history(root):
    """Load historical model-vs-market gaps once for a diagnostic percentile.

    This is decision metadata only; the independent model is already frozen
    before the function is called and never receives the market line.
    """
    path=Path(root)/'calibration'/'spread_execution_total_analytics.json'
    payload=load(path,{})
    gaps=[]
    for item in payload.get('records',[]):
        if item.get('market_type')!='SPREAD':
            continue
        fair=item.get('fair_margin');line=item.get('line')
        if isinstance(fair,(int,float)) and isinstance(line,(int,float)):
            gaps.append(abs(float(fair)-(-float(line))))
    return gaps


def preserve_daily_event_inventory(cap, root, day):
    """Union today's current discovery with append-only intraday snapshots.

    Current-board sources legitimately remove fixtures after tip-off.  A later
    run must not make a previously evidenced same-day game disappear.  The
    inventory stores source events only; missing fixtures return as diagnostic
    rows with no fabricated current quote.
    """
    inventory_dir = Path(root) / 'ledger' / 'event_inventory' / day.replace('-', '')
    inventory_dir.mkdir(parents=True, exist_ok=True)
    current_day = [e for e in cap.get('events', []) if e.get('bj_date') == day]
    # The evening next-day run publishes a forward inventory before the source
    # rolls its date file at midnight. Seed that published target-day view back
    # into continuity matching so the morning run cannot lose fixtures merely
    # because the current board moved to the following date.
    baseline_path = Path(root) / 'dashboard_v2' / 'data' / (day + '.json')
    baseline_document = load(baseline_path, {})
    baseline_events = []
    for item in baseline_document.get('events', []) if isinstance(baseline_document, dict) else []:
        event = item.get('event') if isinstance(item, dict) and isinstance(item.get('event'), dict) else item
        if isinstance(event, dict) and event.get('bj_date') == day and event.get('event_id'):
            baseline_events.append(dict(event))
    snapshot = {
        'schema_version': 'daily-event-inventory-1.0', 'day': day,
        'run_id': cap.get('run_id'), 'captured_at': cap.get('capture_finished_at'),
        'events': current_day, 'immutable': True,
    }
    exclusive(inventory_dir / (str(cap.get('run_id')) + '.json'), snapshot)
    # First collapse provider-ID repeats, then run a bounded cross-source
    # reconciliation. The latter is needed for rows such as 02:00 Titan and
    # 02:04 7M, which are the same fixture but cannot share an exact key.
    inventory_events = {}
    source_snapshots = []
    current_ids = {str(e.get('event_id') or '') for e in current_day if e.get('event_id')}
    for path in sorted(inventory_dir.glob('*.json')):
        payload = load(path, {})
        source_snapshots.append(path.name)
        for item in payload.get('events', []):
            event = item.get('event') if isinstance(item, dict) and isinstance(item.get('event'), dict) else item
            if not isinstance(event, dict) or event.get('bj_date') != day or not event.get('event_id'):
                continue
            candidate = dict(event)
            event_id = str(candidate.get('event_id'))
            prior = inventory_events.get(event_id)
            if prior is None:
                inventory_events[event_id] = candidate
            elif event_id in current_ids:
                inventory_events[event_id] = candidate
    for event in current_day:
        if event.get('event_id'):
            inventory_events[str(event['event_id'])] = event
    for event in baseline_events:
        event_id = str(event.get('event_id'))
        if event_id not in inventory_events:
            inventory_events[event_id] = event

    ids = list(inventory_events)
    parent = {event_id: event_id for event_id in ids}

    def find(event_id):
        while parent[event_id] != event_id:
            parent[event_id] = parent[parent[event_id]]
            event_id = parent[event_id]
        return event_id

    def union(left_id, right_id):
        left_root, right_root = find(left_id), find(right_id)
        if left_root != right_root:
            parent[right_root] = left_root

    for index, left_id in enumerate(ids):
        for right_id in ids[index + 1:]:
            if _same_inventory_fixture(inventory_events[left_id], inventory_events[right_id]):
                union(left_id, right_id)

    groups = defaultdict(list)
    for event_id in ids:
        groups[find(event_id)].append(event_id)

    merged = {}
    redirects = {}
    fuzzy_merges = []
    current_canonical_ids = set()
    for group_ids in groups.values():
        def rank(event_id):
            event = inventory_events[event_id]
            return (
                event_id in current_ids,
                not bool(event.get('inventory_preserved_from_prior_snapshot')),
                bool(event.get('observed_at')),
                str(event.get('observed_at') or ''),
                str(event_id),
            )

        canonical_id = max(group_ids, key=rank)
        canonical = inventory_events[canonical_id]
        if canonical_id in current_ids:
            current_canonical_ids.add(canonical_id)
        source_ids = sorted(set(group_ids))
        for source_id in source_ids:
            if source_id != canonical_id:
                redirects[source_id] = canonical_id
        if len(source_ids) > 1:
            canonical['continuity_source_event_ids'] = source_ids
            canonical['event_identity_continuity_method'] = 'CANONICAL_TEAM_PAIR_AND_TIP_TIME_TOLERANCE'
            discoveries = list(canonical.get('discovery_sources') or [])
            for source_id in source_ids:
                item = inventory_events[source_id]
                candidate = {'source': item.get('source'), 'source_url': item.get('source_url'),
                             'source_event_id': item.get('source_event_id'),
                             'event_id': source_id, 'match_method': 'INTRADAY_TEAM_PAIR_AND_TIP_TIME_TOLERANCE'}
                if candidate not in discoveries:
                    discoveries.append(candidate)
            canonical['discovery_sources'] = discoveries
            fuzzy_merges.append({'canonical_event_id': canonical_id,
                                 'source_event_ids': source_ids,
                                 'tip_times': sorted(str(inventory_events[event_id].get('tip_at') or '')
                                                      for event_id in source_ids)})
        merged[event_continuity_key(canonical)] = canonical
    remapped_quotes = 0
    for quote in cap.get('quotes', []):
        old_id = str(quote.get('event_id') or '')
        new_id = redirects.get(old_id)
        if not new_id:
            continue
        quote.setdefault('continuity_original_event_id', old_id)
        quote['event_id'] = new_id
        quote['canonical_event_id'] = new_id
        quote['event_match_method'] = 'INTRADAY_CONTINUITY_TEAM_PAIR_AND_TIP_TIME'
        remapped_quotes += 1
    contexts = cap.get('total_context') or {}
    for old_id, new_id in redirects.items():
        old = contexts.get(old_id)
        if not isinstance(old, dict):
            continue
        current = contexts.setdefault(new_id, {})
        for name, value in old.items():
            if name not in current or current[name] in (None, '', [], {}):
                current[name] = value
            elif isinstance(value, bool):
                current[name] = bool(current[name] or value)
            elif isinstance(value, list) and isinstance(current[name], list):
                current[name] = current[name] + [item for item in value if item not in current[name]]
    for key, event in merged.items():
        if str(event.get('event_id') or '') not in current_canonical_ids:
            event['inventory_preserved_from_prior_snapshot'] = True
            event['current_source_observation_status'] = 'NOT_ON_CURRENT_BOARD'
    other_dates = [e for e in cap.get('events', []) if e.get('bj_date') != day]
    combined = other_dates + list(merged.values())
    # A provider event id is unique even when an older snapshot carried a
    # corrected team label or time/date bucket.  De-duplicate it explicitly so
    # continuity aliases cannot leave two pricing rows with one canonical id.
    by_event_id = {}
    duplicate_event_ids = []
    for event in combined:
        event_id = str(event.get('event_id') or '')
        if not event_id:
            continue
        prior = by_event_id.get(event_id)
        if prior is None:
            by_event_id[event_id] = event
            continue
        duplicate_event_ids.append(event_id)
        prior_score = (prior.get('bj_date') == day,
                       not prior.get('inventory_preserved_from_prior_snapshot'),
                       bool(prior.get('observed_at')))
        current_score = (event.get('bj_date') == day,
                         not event.get('inventory_preserved_from_prior_snapshot'),
                         bool(event.get('observed_at')))
        if current_score >= prior_score:
            by_event_id[event_id] = event
    cap['events'] = list(by_event_id.values())
    cap['daily_event_inventory_audit'] = {
        'day': day, 'current_discovered': len(current_day), 'stable_inventory': len(merged),
        'preserved_missing_current_board': sum(
            1 for event in merged.values()
            if str(event.get('event_id') or '') not in current_canonical_ids),
        'snapshot_files': source_snapshots,
        'published_baseline_file': str(baseline_path) if baseline_events else None,
        'published_baseline_events': len(baseline_events), 'quotes_fabricated': 0,
        'event_id_redirects': redirects, 'quotes_remapped_to_current_identity': remapped_quotes,
        'fuzzy_time_tolerance_minutes': 45, 'fuzzy_merges': fuzzy_merges,
        'duplicate_event_ids_removed': sorted(set(duplicate_event_ids)),
    }
    return cap

def _movement_direction(delta, positive_is_favorable):
    """Classify a same-selection price move without guessing a side."""
    if delta is None:
        return 'UNKNOWN'
    if abs(delta) < 1e-9:
        return 'UNCHANGED'
    return 'FAVORABLE' if (delta > 0) == positive_is_favorable else 'ADVERSE'


def _line_move_direction(market_type, selection, delta):
    # Quotes are normalized to the selected side. More points are better for a
    # spread selection; for totals, Over benefits from a lower number and
    # Under benefits from a higher number.
    if market_type == 'SPREAD':
        return _movement_direction(delta, True)
    if market_type == 'TOTAL':
        if selection == 'OVER':
            return _movement_direction(delta, False)
        if selection == 'UNDER':
            return _movement_direction(delta, True)
    return 'UNKNOWN'


def paper_market_revalidation(event, decision, asof, original_selected=None):
    """State whether this run would still pass the unchanged paper gate.

    The result is an observation of the current feed, not a replacement for a
    first-write paper decision or its later settlement.
    """
    base = {'checked_at': asof, 'event_id': event['event_id'],
            'current_selected': decision.get('selected'),
            'original_selection': original_selected,
            'comparison_ready': bool(decision.get('comparison_ready')),
            'blockers': list(decision.get('blockers', [])),
            'real_execution_allowed': False}
    if iso(event['tip_at']) <= iso(asof):
        return dict(base, status='EVENT_STARTED', display='比赛已开始，首写纸面单进入结算跟踪')
    if original_selected:
        scoped = (decision.get('market_decisions') or {}).get(original_selected.get('market_type')) or decision
        base['comparison_ready'] = bool(scoped.get('comparison_ready'))
        base['blockers'] = list(scoped.get('blockers', []))
        same_contract = [candidate for candidate in scoped.get('comparison_rows', [])
                         if candidate.get('bookmaker') == original_selected.get('bookmaker')
                         and candidate.get('market_type') == original_selected.get('market_type')
                         and candidate.get('selection') == original_selected.get('selection')
                         and candidate.get('ot_rule') == original_selected.get('ot_rule')]
        if not same_contract:
            return dict(base, status='REVALIDATION_UNAVAILABLE',
                        display='本轮未取得原纸面方向的同公司、同规则新鲜报价')
        candidate = max(same_contract, key=lambda item: item['adverse_ev'])
        base['current_selected'] = candidate
        cfg=lifecycle_config().get('revalidation_drift_limits',{}).get(original_selected.get('market_type'),{})
        old_line, new_line=original_selected.get('line'),candidate.get('line')
        old_odds, new_odds=original_selected.get('decimal_odds'),candidate.get('decimal_odds')
        line_delta=(float(new_line)-float(old_line)) if old_line is not None and new_line is not None else None
        odds_delta=(float(new_odds)-float(old_odds)) if old_odds is not None and new_odds is not None else None
        line_limit=cfg.get('max_line_change_points');odds_limit=cfg.get('max_decimal_odds_deterioration')
        material=(line_delta is not None and line_limit is not None and abs(line_delta)>float(line_limit)) or (odds_delta is not None and odds_limit is not None and odds_delta < -float(odds_limit))
        line_direction = _line_move_direction(original_selected.get('market_type'), original_selected.get('selection'), line_delta)
        odds_direction = _movement_direction(odds_delta, True)
        adverse_material = ((line_direction == 'ADVERSE' and line_delta is not None and line_limit is not None and abs(line_delta) > float(line_limit))
                            or (odds_direction == 'ADVERSE' and odds_delta is not None and odds_limit is not None and abs(odds_delta) > float(odds_limit)))
        base['market_difference']={'original_line':old_line,'current_line':new_line,'line_delta':line_delta,
                                   'original_decimal_odds':old_odds,'current_decimal_odds':new_odds,'odds_delta':odds_delta,
                                   'line_limit':line_limit,'odds_deterioration_limit':odds_limit,'material':material,
                                   'line_direction':line_direction,'odds_direction':odds_direction,
                                   'adverse_material':adverse_material,'requires_explicit_recheck':material}
        if candidate.get('research_edge_pass') and not scoped.get('blockers'):
            if line_direction == 'FAVORABLE' or odds_direction == 'FAVORABLE':
                display = '当前同规则盘口或赔率对原纸面方向更有利；已按本轮报价重新审核，仍符合纸面条件'
            elif adverse_material:
                display = '盘口或赔率对原纸面方向不利，但已按本轮同规则报价重新审核，仍符合纸面条件'
            else:
                display = '原纸面方向按本轮同公司、同规则报价仍符合纸面条件'
            return dict(base, status='STILL_QUALIFIES',
                        display=display)
        display = ('真实盘口差异过大，经重新审核后本轮不投注；仅保留首写记录与后续结算跟踪'
                   if adverse_material else '原纸面方向已按本轮同公司、同规则报价重新比较，但未通过纸面条件')
        return dict(base, status='NO_LONGER_QUALIFIES',
                    display=display)
    if decision.get('triggered'):
        return dict(base, status='STILL_QUALIFIES', display='按本轮新鲜同规则盘口，仍符合纸面条件')
    if decision.get('comparison_ready'):
        return dict(base, status='NO_LONGER_QUALIFIES', display='本轮已重新比较，但未通过纸面条件')
    return dict(base, status='REVALIDATION_UNAVAILABLE', display='缺少本轮新鲜、同规则的可比较盘口')


def paper_market_revalidation_tracking(root, document, asof):
    """Audit fresh rechecks for immutable paper entries shown in this document."""
    records = []
    for row in document.get('events', []):
        original = row.get('execution') or {}
        if not original.get('triggered'):
            continue
        current = (row.get('current_snapshot') or {}).get('execution') or original
        review = current.get('market_revalidation')
        if not review:
            event = row.get('event') or {}
            if event.get('tip_at') and iso(event['tip_at']) <= iso(asof):
                review = {'status': 'EVENT_STARTED', 'checked_at': asof,
                          'display': '比赛已开始，停止赛前盘口复核，进入赛果结算跟踪'}
            else:
                review = {'status': 'REVALIDATION_UNAVAILABLE', 'checked_at': asof,
                          'display': '本轮未观察到该未开赛赛事，无法取得同公司、同规则的新鲜报价复核'}
        records.append({'event_id': row.get('id'), 'teams': [row.get('event', {}).get('team1_name'),
                        row.get('event', {}).get('team2_name')], 'first_write_prediction_id': original.get('prediction_id'),
                        'first_write_selection': original.get('selected'), 'revalidation': review})
    result = {'checked_at': asof, 'archive_type': 'FORWARD_NATIVE', 'records': records,
              'counts': dict(Counter(x['revalidation']['status'] for x in records)),
              'first_write_preserved': True, 'real_execution_allowed': False}
    atomic(Path(root)/'audits'/'paper_market_revalidation.json', result)
    return result

def settle_existing(root,history,asof,settlement_facts=None):
    root=Path(root)
    facts={g['event_id']:g for g in history if g.get('status')=='FINAL'}
    # Daily event-result snapshots are settlement-only evidence. They are
    # merged after pricing and never enter the frozen pregame history pool.
    items=(settlement_facts or {}).values() if isinstance(settlement_facts,dict) else (settlement_facts or [])
    for item in items:
        if item.get('event_id') and item.get('status')=='FINAL':
            facts[item['event_id']]=item
    count=0
    for f in (root/'ledger'/'repair_v22').glob('*/decision_*.json'):
        d=load(f,{})
        if d.get('archive_type')!='FORWARD_NATIVE' or not d.get('triggered') or d.get('real_bet_flag'):continue
        original=load(f.with_name('input_'+d['prediction_id']+'.json'),{}).get('event',{})
        ids=(original.get('team1_id'),original.get('team2_id'))
        market_decisions=d.get('market_decisions') or {}
        if market_decisions:
            entries=[(market, item) for market, item in market_decisions.items()
                     if isinstance(item, dict) and item.get('triggered') and item.get('selected')]
        else:
            entries=[((d.get('selected') or {}).get('market_type'), d)] if d.get('selected') else []
        for market_type, market_decision in entries:
            g=facts.get(d.get('event_id')); s=market_decision.get('selected') or {}
            if not g or not s:continue
            if not g.get('known_final_at') or iso(g['known_final_at'])>iso(asof):continue
            suffix='regulation' if s['ot_rule']=='REGULATION_ONLY' else 'full'
            gid=(g.get('team1_id'),g.get('team2_id'))
            if None in ids or set(ids)!=set(gid):continue
            a,b=g['score1_'+suffix],g['score2_'+suffix]
            if ids==gid[::-1]:a,b=b,a
            if s['market_type']=='SPREAD':delta=(a-b if s['selection']=='TEAM1' else b-a)+s['line']
            else:delta=(a+b-s['line'])*(1 if s['selection']=='OVER' else -1)
            result='WIN' if delta>0 else 'LOSS' if delta<0 else 'PUSH'
            market_pid=f"{d['prediction_id']}__{market_type}"
            out={'prediction_id':d['prediction_id'],'market_record_id':market_pid,'event_id':d['event_id'],
                 'market_type':market_type,'archive_type':'FORWARD_NATIVE','settled_at':asof,'outcome':result,
                 'score1':a,'score2':b,'score_rule':s['ot_rule'],'paper_units':1,
                 'paper_pnl':s['decimal_odds']-1 if delta>0 else -1 if delta<0 else 0,
                 'outcome_raw_sha256':g.get('raw_sha256'),'close':None,'clv':None,
                 'close_reason':'NO_VERIFIED_CLOSE_SNAPSHOT','real_stake':0,'real_execution_allowed':False}
            if g.get('raw_path'): out['result_source_ref']=g.get('raw_path')
            if g.get('source_url'): out['result_source_url']=g.get('source_url')
            if g.get('evidence_kind'): out['result_evidence_kind']=g.get('evidence_kind')
            path=root/'ledger'/'repair_v22_settlements'/(market_pid+'.json')
            legacy_path=root/'ledger'/'repair_v22_settlements'/(d['prediction_id']+'.json')
            if not path.exists() and not (not market_decisions and legacy_path.exists()):
                exclusive(path if market_decisions else legacy_path,out);count+=1
    return count


def _final_fact_index(root, current_history):
    """Read immutable final-score facts without treating a later page as pregame input."""
    facts = {g.get('event_id'): g for g in current_history if g.get('status') == 'FINAL' and g.get('event_id')}
    for capture_path in (Path(root) / 'raw' / 'repair_v22').glob('*/capture.json'):
        capture = load(capture_path, {})
        for game in capture.get('history', []):
            if game.get('status') == 'FINAL' and game.get('event_id'):
                facts.setdefault(game['event_id'], game)
    return facts


def _aligned_periods(event, fact):
    """Return period scores in the frozen event's team order, or no result on identity conflict."""
    p1, p2 = fact.get('period_points_team1'), fact.get('period_points_team2')
    original_ids = (event.get('team1_id'), event.get('team2_id'))
    fact_ids = (fact.get('team1_id'), fact.get('team2_id'))
    if not (isinstance(p1, list) and isinstance(p2, list) and len(p1) >= 4 and len(p2) >= 4):
        return None
    if None in original_ids or set(original_ids) != set(fact_ids):
        return None
    return (p2, p1) if original_ids == fact_ids[::-1] else (p1, p2)


def failure_audit_settlements(root, current_history, asof):
    """Append deterministic post-mortems for LOSS settlements; never revise first writes."""
    root = Path(root)
    path = root / 'audits' / 'post_mortem.json'
    previous = load(path, {'schema_version': 1, 'records': []})
    records = list(previous.get('records', []))
    known = {key for row in records for key in
             (row.get('audit_id'), row.get('market_record_id'), row.get('prediction_id')) if key}
    facts = _final_fact_index(root, current_history)
    created = []
    for settlement_path in sorted((root / 'ledger' / 'repair_v22_settlements').glob('*.json')):
        settlement = load(settlement_path, {})
        pid = settlement.get('prediction_id')
        market_record_id = settlement.get('market_record_id') or settlement_path.stem
        if not pid or market_record_id in known or settlement.get('outcome') != 'LOSS':
            continue
        matches = list((root / 'ledger' / 'repair_v22').glob('*/decision_' + pid + '.json'))
        if not matches:
            continue
        decision = load(matches[0], {})
        frozen = load(matches[0].with_name('input_' + pid + '.json'), {})
        forecast = load(matches[0].with_name('forecast_' + pid + '.json'), {})
        event = frozen.get('event', {})
        selected = decision.get('selected') or {}
        market_type = settlement.get('market_type')
        if market_type and isinstance(decision.get('market_decisions'), dict):
            selected = (decision['market_decisions'].get(market_type) or {}).get('selected') or selected
        fact = facts.get(settlement.get('event_id'))
        missing = ['VERIFIED_FINAL_FACT_MISSING'] if not fact else []
        label = 'CAUSE_UNKNOWN_INSUFFICIENT_DATA'
        passed = False
        evidence = {'metric_name': 'required_failure_evidence', 'metric_value': None,
                    'threshold_triggered': 'not evaluable', 'source_ref': None}
        reasoning = ''
        periods = _aligned_periods(event, fact) if fact else None
        if selected.get('market_type') == 'SPREAD':
            if periods is None:
                missing.append('QUARTER_SCORES_MISSING_OR_TEAM_ORDER_CONFLICT')
            else:
                selected_index = 0 if selected.get('selection') == 'TEAM1' else 1
                other_index = 1 - selected_index
                selected_q3 = sum(periods[selected_index][:3])
                other_q3 = sum(periods[other_index][:3])
                q4_margin = periods[selected_index][3] - periods[other_index][3]
                line = selected.get('line')
                covering_at_q3 = line is not None and selected_q3 - other_q3 + float(line) > 0
                if covering_at_q3 and q4_margin <= -8:
                    label = 'GARBAGE_TIME_COVER'; passed = True
                    evidence = {'metric_name': 'Q4_margin', 'metric_value': q4_margin,
                                'threshold_triggered': '<= -8', 'source_ref': fact.get('raw_path')}
                    reasoning = ('按冻结让分合同，所选方向在第三节结束时仍覆盖；第四节净负%s分，'
                                 '最终让分结算为LOSS，满足量化末节吞噬定义。' % abs(q4_margin))
                else:
                    missing.append('GARBAGE_TIME_COVER_THRESHOLD_NOT_MET')
        elif selected.get('market_type') == 'TOTAL':
            missing.append('REGULATION_FINAL_120_SECONDS_SCORING_MISSING')
        # The current production source does not supply a verified frozen 3P
        # distribution or player-minute feed. Explicitly surface that absence.
        missing.extend(['FROZEN_SAME_COMPETITION_3P_BASELINE_MISSING',
                        'FINAL_3P_MAKES_ATTEMPTS_MISSING',
                        'FROZEN_EXPECTED_MINUTES_MISSING', 'ACTUAL_PLAYER_MINUTES_MISSING'])
        if not passed:
            reasoning = '无法对特定错因作出审计结论；缺少或未满足的证据：' + '；'.join(dict.fromkeys(missing))
        record = {
            'schema_version': 1, 'audit_id': market_record_id + ':v1', 'prediction_id': pid,
            'market_record_id': market_record_id,
            'event_id': settlement.get('event_id'), 'settlement_id': settlement_path.stem,
            'audit_at': asof, 'market_type': market_type or selected.get('market_type'),
            'frozen_selection': selected, 'frozen_forecast_fingerprint': decision.get('forecast_fingerprint'),
            'failure_label': label, 'hard_evidence': evidence, 'audit_passed': passed,
            'reasoning_chain': reasoning, 'missing_evidence': list(dict.fromkeys(missing)),
            'result_source_ref': fact.get('raw_path') if fact else None,
            'result_raw_sha256': fact.get('raw_sha256') if fact else None,
            'real_execution_allowed': False,
        }
        records.append(record); created.append(record); known.add(market_record_id)
    result = {'schema_version': 1, 'generated_at': asof, 'append_only': True,
              'records': records, 'counts': dict(Counter(x.get('failure_label') for x in records)),
              'new_records': len(created), 'real_execution_allowed': False}
    atomic(path, result)
    return result


def sync_paper_settlements(root, asof):
    """Join immutable settlements to every dated page and latest.

    The append-only decision ledger is the source of truth for the first-write
    paper set. A live board may remove a started event, so a page row missing
    from a later refresh is restored from its immutable input/forecast/decision
    artifacts before settlement is joined. This is additive only: it never
    replaces a frozen row or invents a quote.
    """
    root = Path(root)
    settlements = {p.stem: load(p, {}) for p in (root/'ledger'/'repair_v22_settlements').glob('*.json')}
    ledger_rows = {}
    for path in sorted((root/'ledger'/'repair_v22').glob('*/decision_*.json')):
        decision = load(path, {})
        if (decision.get('archive_type') != 'FORWARD_NATIVE' or
                decision.get('triggered') is not True or not decision.get('prediction_id')):
            continue
        pid = decision['prediction_id']
        input_doc = load(path.with_name('input_'+pid+'.json'), {})
        event = input_doc.get('event') or {}
        if not event.get('event_id') or not event.get('bj_date'):
            continue
        ledger_rows[pid] = {
            'id': event['event_id'], 'event': event,
            'pricing': load(path.with_name('forecast_'+pid+'.json'), {}),
            'market': {'quotes': [], 'quote_states': []},
            'execution': decision, 'generation': 'REPAIR_V22',
            'archive_type': 'FORWARD_NATIVE',
            'display': {'status': decision.get('display_action'), 'reasons': [], 'warnings': []},
            'immutable_ledger_restore': True,
        }
    records = {}
    for path in sorted((root/'dashboard_v2'/'data').glob('*.json')):
        if path.name != 'latest.json' and not (len(path.stem) == 10 and path.stem[:4].isdigit()):
            continue
        doc = load(path, {})
        changed = False
        expected_day = doc.get('date_bj')
        existing_pids = {((row.get('execution') or {}).get('prediction_id'))
                         for row in doc.get('events', [])}
        for pid, restored in ledger_rows.items():
            if restored['event'].get('bj_date') != expected_day or pid in existing_pids:
                continue
            doc.setdefault('events', []).append(restored)
            existing_pids.add(pid)
            changed = True
        if changed and doc.get('events'):
            doc['events'].sort(key=lambda row: ((row.get('event') or {}).get('tip_at',''), row.get('id','')))
            doc['funnel'] = funnel(doc['events'])
        for row in doc.get('events', []):
            decision = row.get('execution') or {}
            pid = decision.get('prediction_id')
            if not pid or not decision.get('triggered') or decision.get('archive_type') != 'FORWARD_NATIVE':
                continue
            market_decisions = decision.get('market_decisions') or {}
            if market_decisions:
                entries = [(market, item) for market, item in market_decisions.items()
                           if isinstance(item, dict) and item.get('triggered') and item.get('selected')]
            else:
                selected = decision.get('selected') or {}
                # Very old rows may omit market_type; their only historical
                # line field was a spread line, so keep the compatibility
                # interpretation without rewriting that row.
                entries = [((selected.get('market_type') or 'SPREAD'), decision)] if selected else []
            settlements_by_market = dict(row.get('settlements_by_market') or {})
            for market_type, market_decision in entries:
                if not market_type or not market_decision.get('selected'):
                    continue
                market_pid = f'{pid}__{market_type}' if market_decisions else pid
                settlement = settlements.get(market_pid)
                if settlement is None and not market_decisions:
                    settlement = settlements.get(pid)
                if settlement and settlement.get('event_id') == row.get('id'):
                    if market_decisions:
                        if settlements_by_market.get(market_type) != settlement:
                            settlements_by_market[market_type] = settlement; changed = True
                    elif row.get('settlement') != settlement:
                        row['settlement'] = settlement; changed = True
                else:
                    settlement = None
                record_key = market_pid
                records[record_key] = {'prediction_id': pid, 'market_record_id': market_pid,
                    'market_type': market_type, 'event_id': row.get('id'),
                    'date_bj': row.get('event', {}).get('bj_date'),
                    'selection': market_decision.get('selected'), 'first_write_at': market_decision.get('asof') or decision.get('asof'),
                    'outcome': settlement.get('outcome') if settlement else 'PENDING',
                    'settlement': settlement}
            if settlements_by_market and row.get('settlements_by_market') != settlements_by_market:
                row['settlements_by_market'] = settlements_by_market; changed = True
        if changed:
            atomic(path, doc)
    result = {'checked_at': asof, 'archive_type': 'FORWARD_NATIVE',
              'records': list(records.values()), 'counts': dict(Counter(x['outcome'] for x in records.values()))}
    atomic(root/'audits'/'paper_settlement_tracking.json', result)
    return result


def review_previous_day(root, day, asof):
    """Review the prior Beijing day without changing its first-write decision."""
    root=Path(root);previous=(date.fromisoformat(day)-timedelta(days=1)).isoformat()
    data_path=root/'dashboard_v2'/'data'/(previous+'.json');document=load(data_path,{})
    settlement_dir=root/'ledger'/'repair_v22_settlements';settlements={}
    for f in settlement_dir.glob('*.json'):
        item=load(f,{})
        if item.get('event_id') and item.get('prediction_id'):
            settlements[f.stem]=item
            settlements.setdefault(item['prediction_id'], item)
    reviewed=[];changed=False
    for row in document.get('events',[]):
        decision=row.get('execution') or {};pid=decision.get('prediction_id')
        if not (decision.get('triggered') is True):continue
        market_decisions=decision.get('market_decisions') or {}
        entries=[(market,item) for market,item in market_decisions.items()
                 if isinstance(item,dict) and item.get('triggered') and item.get('selected')]
        if not entries:
            selected = decision.get('selected') or {}
            entries=[((selected.get('market_type') or 'SPREAD'), decision)] if selected else []
        settlements_by_market=dict(row.get('settlements_by_market') or {})
        for market_type, market_decision in entries:
            market_pid=f'{pid}__{market_type}' if market_decisions else pid
            item=settlements.get(market_pid) or (settlements.get(pid) if not market_decisions else None)
            if item:
                if market_decisions:
                    if settlements_by_market.get(market_type)!=item:
                        settlements_by_market[market_type]=item;changed=True
                elif row.get('settlement')!=item:
                    row['settlement']=item;changed=True
            reviewed.append({'event_id':row.get('id'),'team1':row.get('event',{}).get('team1_name'),
                             'team2':row.get('event',{}).get('team2_name'),'prediction_id':pid,
                             'market_record_id':market_pid,'market_type':market_type,
                             'paper_selection':market_decision.get('selected'),
                             'outcome':item.get('outcome') if item else 'PENDING',
                             'score1':item.get('score1') if item else None,'score2':item.get('score2') if item else None,
                             'settlement_available':bool(item)})
        if settlements_by_market and row.get('settlements_by_market')!=settlements_by_market:
            row['settlements_by_market']=settlements_by_market;changed=True
    # Settlement review must not bypass the same fixture-family coalescing used
    # by the forward dashboard writer.  Otherwise a later prior-day review can
    # reintroduce sponsor/phase aliases (or opposite market rows) that the
    # current-day writer already merged.  This only changes the derived public
    # view; first-write ledger files remain immutable.
    coalesced_events = coalesce_duplicate_display_rows(document.get('events', []))
    if coalesced_events != document.get('events', []):
        document['events'] = coalesced_events
        changed = True
    if changed:atomic(data_path,document)
    report={'date_bj':previous,'reviewed_at':asof,'paper_event_count':len(reviewed),
            'settled_count':sum(x['settlement_available'] for x in reviewed),'events':reviewed,
            'first_write_preserved':True,'real_execution_allowed':False}
    atomic(root/'audits'/('paper_review_'+previous+'.json'),report)
    return report


def _decision_has_triggered_market(decision):
    """Return whether a forward decision contains a locked market signal."""
    decision = decision or {}
    if decision.get('triggered') is True:
        return True
    return any(isinstance(item, dict) and item.get('triggered') is True
               for item in (decision.get('market_decisions') or {}).values())


def _continuity_pair(event):
    key = event_continuity_key(event)
    if key and key[0] == 'TEAM_PAIR_AND_TIP_TIME':
        return key[1]
    return None


def _merge_prior_forward_decisions(records):
    """Merge immutable first-writes without allowing a later refresh to win.

    A provider can emit a fresh event ID, or a second immutable decision file
    can exist after a prior refresh.  The earliest triggered decision for each
    market is the lock; later records are retained in the ledger but are not
    allowed to change its direction, line, or odds.
    """
    ordered = sorted(records, key=lambda item: (
        str(item.get('decision', {}).get('asof') or ''),
        str(item.get('decision', {}).get('prediction_id') or ''),
    ))
    merged = dict(ordered[0].get('decision') or {}) if ordered else {}
    market_decisions = {}
    for item in ordered:
        decision = item.get('decision') or {}
        source_markets = decision.get('market_decisions') or {}
        if source_markets:
            for market_name, market_decision in source_markets.items():
                if (market_name not in market_decisions and
                        isinstance(market_decision, dict) and
                        market_decision.get('triggered') is True):
                    market_decisions[market_name] = market_decision
        elif decision.get('triggered') is True and decision.get('selected'):
            market_name = decision.get('selected', {}).get('market_type') or 'SPREAD'
            market_decisions.setdefault(market_name, decision)
    if market_decisions:
        merged['market_decisions'] = market_decisions
        merged['market_types_triggered'] = sorted(market_decisions)
        merged['triggered'] = True
        merged['selected'] = next(
            (item.get('selected') for item in market_decisions.values()
             if isinstance(item, dict) and item.get('selected')),
            merged.get('selected'))
    return merged


def _matching_prior_forward_records(event, by_key, by_pair):
    """Find locked first-writes across source-ID and small tip-time changes."""
    exact = list(by_key.get(event_continuity_key(event), []))
    if exact:
        return exact
    pair = _continuity_pair(event)
    if not pair:
        return []
    return [item for item in by_pair.get(pair, [])
            if _same_inventory_fixture(event, item.get('event') or {})]


def run_capture(cap,output_root,day,context_map=None):
    root=Path(output_root);mode=cap['mode'];asof=cap['capture_finished_at'];run_id=cap['run_id'];contexts=context_map or {}
    baseline_document=load(root/'dashboard_v2'/'data'/(day+'.json'),{}) if mode=='FORWARD_NATIVE' else {}
    if mode == 'FORWARD_NATIVE':
        cap = preserve_daily_event_inventory(cap, root, day)
    # All artifacts for an audit are intentionally separate from the operational ledger.
    ledger=root/'ledger'/'repair_v22'/run_id;ledger.mkdir(parents=True,exist_ok=True)
    history_index_started=time.perf_counter()
    history_index=HistoryIndex(cap.get('history') or [])
    history_index_build_ms=round((time.perf_counter()-history_index_started)*1000,3)
    groups=defaultdict(list)
    for q in cap['quotes']:groups[q['event_id']].append(q)
    rows=[];audit=[];calls=[]; prior_entries=defaultdict(set); prior_market_entries=defaultdict(set)
    prior_decisions={}; prior_events={}; current_decisions={}
    prior_forward_records=[]; prior_by_key=defaultdict(list); prior_by_pair=defaultdict(list)
    prior_forward_index_audit={}
    # Load the append-only OOS residual ledger once per run.  Per-event pricing
    # reuses this in-memory list and never rereads historical JSON/JS files.
    oos_residual_path=root/'calibration'/'oos_spread_residuals.jsonl'
    spread_oos_records=load_oos_residuals(oos_residual_path)
    market_gap_history=_load_market_gap_history(root)
    if mode=='FORWARD_NATIVE':
        prior_forward_records, prior_forward_index_audit = load_prior_forward_records(root, run_id)
        for record in prior_forward_records:
            d=record.get('decision') or {}
            input_event=record.get('event') or {}
            if input_event:
                prior_by_key[event_continuity_key(input_event)].append(record)
                pair = _continuity_pair(input_event)
                if pair:
                    prior_by_pair[pair].append(record)
            # Keep the source-ID index as a fast fallback for legacy records
            # whose immutable input file is unavailable.
            event_id=d.get('event_id')
            if event_id:
                prior_entries[event_id].add(d.get('prediction_id'))
                prior_markets = d.get('market_decisions') or {}
                if prior_markets:
                    for market_name, market_decision in prior_markets.items():
                        if isinstance(market_decision, dict) and market_decision.get('triggered'):
                            prior_market_entries[event_id].add(market_name)
                else:
                    market_name = (d.get('selected') or {}).get('market_type')
                    if market_name:
                        prior_market_entries[event_id].add(market_name)
                prior_decisions.setdefault(event_id, d)
                prior_events.setdefault(event_id, input_event)
    titan_provisional_aliases = _load_titan_provisional_continuity(root, asof) if mode == 'FORWARD_NATIVE' else {}
    for e in sorted(cap['events'],key=lambda x:(x['tip_at'],x['event_id'])):
        try:
            calls.append({'stage':'price_event','event_id':e['event_id'],'history_candidates':len(cap['history'])})
            # A price-blind dictionary is saved before decision code sees any quote.
            total_context=dict(cap.get('total_context',{}).get(e['event_id'],{}))
            total_context.update(contexts.get(e['event_id']) or {})
            total_context['spread_oos_records']=spread_oos_records
            pricing=price_event(e,history_index,asof,mode,total_context)
            snapshot_db=root/'reference_data'/'titan007_history'/'titan007_history.sqlite'
            if snapshot_db.exists() and pricing.get('titan_foundation_pricing'):
                pricing['pregame_snapshot_id']=freeze_pregame_snapshot(snapshot_db,e,pricing,asof)
            pid=fingerprint({'event_id':e['event_id'],'input':pricing.get('input_fingerprint'),'asof':asof,'mode':mode,'version':VERSION})[:28]
            evidence_ids=set(pricing.get('used_history_ids',[]))
            inp={'event':e,'asof':asof,'archive_type':mode,'history':[g for g in cap['history'] if g['event_id'] in evidence_ids],
                 'history_pool_fingerprint':fingerprint(cap['history']),'model_version':pricing['model_version']}
            exclusive(ledger/('input_'+pid+'.json'),inp)
            exclusive(ledger/('forecast_'+pid+'.json'),pricing)
            # Collection may already have observed markets; the raw model has no market feature access.
            qs=groups.get(e['event_id'],[]);states=[quote_state(q,e,asof) for q in qs]
            if snapshot_db.exists():
                store_market_observations(snapshot_db,e,qs)
            decision=decide(e,pricing,qs,asof,mode,market_gap_history);decision['prediction_id']=pid
            apply_titan_provisional_continuity(e, decision, titan_provisional_aliases)
            decision['pregame_evidence_bundle']=attach_market_evidence(
                pricing.get('pregame_evidence_bundle'),qs,states,asof)
            # Capture the current gate result before duplicate protection turns a
            # second would-be entry into WATCH.
            matched_prior = _matching_prior_forward_records(e, prior_by_key, prior_by_pair)
            if matched_prior:
                original_decision = _merge_prior_forward_decisions(matched_prior)
                # Re-key the lock by the current provider event ID so the
                # existing market-scoped duplicate protection also applies
                # when 7M/Titan reissues the fixture under a new ID.
                prior_decisions[e['event_id']] = original_decision
                prior_events[e['event_id']] = matched_prior[0].get('event') or e
                for item in matched_prior:
                    prior = item.get('decision') or {}
                    prior_entries[e['event_id']].add(prior.get('prediction_id'))
                    prior_markets = prior.get('market_decisions') or {}
                    if prior_markets:
                        prior_market_entries[e['event_id']].update(
                            market_name for market_name, market_decision in prior_markets.items()
                            if isinstance(market_decision, dict) and market_decision.get('triggered'))
                    elif prior.get('selected'):
                        prior_market_entries[e['event_id']].add(
                            prior.get('selected', {}).get('market_type') or 'SPREAD')
            else:
                original_decision = prior_decisions.get(e['event_id'], {})
            original = original_decision.get('selected')
            decision['market_revalidation']=paper_market_revalidation(e,decision,asof,original)
            # Duplicate protection is market-scoped.  A prior SPREAD signal
            # must not suppress a newly qualified TOTAL signal for the same
            # fixture, and vice versa.
            market_revalidations = {}
            original_markets = original_decision.get('market_decisions') or {}
            for market_name, market_decision in (decision.get('market_decisions') or {}).items():
                if not isinstance(market_decision, dict):
                    continue
                old_selected = (original_markets.get(market_name) or {}).get('selected')
                if old_selected is None and isinstance(original, dict) and original.get('market_type') == market_name:
                    old_selected = original
                market_revalidations[market_name] = paper_market_revalidation(
                    e, market_decision, asof, old_selected)
                if market_decision.get('triggered') and market_name in prior_market_entries[e['event_id']]:
                    market_decision.update(triggered=False, shadow_action='WATCH', display_action='观察',
                                           real_execution_allowed=False, manual_execution_state='DUPLICATE_BLOCKED',
                                           manual_order_required=False)
                    market_decision.setdefault('blockers', []).append('EXISTING_PAPER_ENTRY_NO_DUPLICATE')
                    market_decision['prior_entry_ids'] = sorted(prior_entries[e['event_id']])
            if market_revalidations:
                decision['market_revalidation_by_market'] = market_revalidations
            decision['market_types_triggered'] = [m for m, d in (decision.get('market_decisions') or {}).items()
                                                   if d.get('triggered')]
            decision['triggered'] = bool(decision['market_types_triggered'])
            active_selected = [d.get('selected') for d in (decision.get('market_decisions') or {}).values()
                               if d.get('selected') and (d.get('triggered') or d.get('comparison_ready'))]
            decision['selected'] = max(active_selected, key=lambda item: item.get('adverse_ev', float('-inf')),
                                       default=None)
            decision['comparison_ready'] = any(d.get('comparison_ready') for d in
                                               (decision.get('market_decisions') or {}).values())
            decision['ev'] = decision['selected'].get('ev') if decision.get('selected') else None
            decision['shadow_action'] = 'SHADOW_BET' if decision['triggered'] else decision.get('shadow_action', 'BLOCKED')
            decision['display_action'] = '手动实盘候选' if decision['triggered'] else decision.get('display_action', '不可投')
            if not decision['triggered'] and any('EXISTING_PAPER_ENTRY_NO_DUPLICATE' in (d.get('blockers') or [])
                                                 for d in (decision.get('market_decisions') or {}).values()):
                decision['shadow_action'] = 'WATCH'; decision['display_action'] = '观察'
            decision['real_execution_allowed'] = bool(decision['triggered'] and mode == 'FORWARD_NATIVE')
            decision['manual_order_required'] = bool(decision['triggered'] and mode == 'FORWARD_NATIVE')
            decision['manual_execution_state'] = 'MANUAL_LIVE_CANDIDATE' if decision['real_execution_allowed'] else 'NOT_ELIGIBLE'
            decision['blockers'] = list(dict.fromkeys(
                list(decision.get('blockers') or []) +
                [reason for market_decision in (decision.get('market_decisions') or {}).values()
                 for reason in (market_decision.get('blockers') or [])]))
            if decision.get('triggered'):
                prior_entries[e['event_id']].add(pid)
                prior_market_entries[e['event_id']].update(decision['market_types_triggered'])
            if decision.get('triggered'):
                phase, minutes = _phase(asof, e['tip_at'], lifecycle_config())
                decision['execution_lifecycle']={'entry_phase':phase,'minutes_before_tip_at_entry':minutes,
                    'threshold_source':lifecycle_config().get('early_entry',{}).get('threshold_source','INITIAL_PRIOR'),
                    'late_recheck_required_at_minutes':lifecycle_config().get('late_recheck_minutes_before_tip',[30,10,5]),
                    'real_execution_allowed':True,'execution_mode':'MANUAL_LIVE',
                    'automated_execution_allowed':False,'manual_order_required':True}
            decision['signal_layer']={'first_write':True,'pre_tip':True,
                'market_type':(decision.get('selected') or {}).get('market_type'),
                'selection':(decision.get('selected') or {}).get('selection'),
                'classification':'VALID_PRETIP_DIRECTION' if decision.get('comparison_ready') else 'NO_VALID_DIRECTION',
                'markets':{k:{'market_type':k,'selection':(v.get('selected') or {}).get('selection'),
                    'triggered':bool(v.get('triggered')),'comparison_ready':bool(v.get('comparison_ready')),
                    'model_state':v.get('model_state'),'blockers':v.get('blockers',[])}
                    for k,v in (decision.get('market_decisions') or {}).items()}}
            decision['forecast_fingerprint']=fingerprint(pricing);decision['price_blind_input_fingerprint']=fingerprint(inp)
            decision['feature_isolation_verified']=True
            annotate_decision(e,pricing,decision)
            freeze_learning_records(root,run_id,e,pricing,decision)
            freeze_titan_provisional_records(root,run_id,e,pricing,decision)
            exclusive(ledger/('decision_'+pid+'.json'),decision)
            current_decisions[e['event_id']]=decision
            rows.append(project_row(e,pricing,qs,decision,states,mode))
            audit.append({'event_id':e['event_id'],'league':e['league'],'team1':e['team1_name'],'team2':e['team2_name'],'tip_bj':e['tip_time_bj'],
              'historical_candidates':len(history_index),'indexed_candidates':len(history_index.candidates(e)[1]),
              'history_index_build_ms':history_index_build_ms,'history_used':pricing.get('input_games',0),'history_team_counts':pricing.get('team_game_counts',{}),
              'history_opponent_counts':pricing.get('team_opponent_counts',{}),'history_exclusions':pricing.get('history_exclusions',{}),
              'competition_match_methods':pricing.get('competition_match_methods',{}),'paper_model_eligible':pricing.get('paper_model_eligible',False),
              'pricing_status':pricing['pricing_status'],'raw_margin':pricing.get('mu_raw'),'raw_total':pricing.get('total_raw'),
              'raw_quote_rows':len(qs),'raw_verified':sum(x['raw_observation'] for x in states),'fresh_quotes':sum(x['fresh_observation'] for x in states),
              'action':decision['shadow_action'],'blockers':decision.get('blockers'),
              'model_warnings':pricing.get('model_warnings',[]),'feature_fingerprint':pricing.get('input_fingerprint'),'pricing_called':True})
        except Exception as exc:
            p={'pricing_status':'UNPRICEABLE','mu_raw':None,'total_raw':None,'pricing_data_quality':0,'blockers':['PIPELINE_EXCEPTION'], 'error':str(exc)}
            d={'shadow_action':'BLOCKED','display_action':'不可投','blockers':['PIPELINE_EXCEPTION: '+str(exc)],'real_stake':0,'real_execution_allowed':False}
            rows.append(project_row(e,p,groups.get(e['event_id'],[]),d,[],mode));audit.append({'event_id':e['event_id'],'pricing_called':True,'blockers':d['blockers']})
    # Later observations are append-only revisions. They never replace the
    # original selection, line, price, probability, or settlement evidence.
    if mode == 'FORWARD_NATIVE':
        current_events={e['event_id']:e for e in cap['events']}
        # A reissued fixture can be present under both its old provider ID and
        # its current provider ID.  Both entries may point to the same frozen
        # first-write prediction.  Lifecycle revisions are keyed by
        # (prediction_id, run_id), so writing both would either create a
        # conflicting immutable record or make the same observation count
        # twice.  Collapse this run to one deterministic candidate per
        # prediction, preferring the current event snapshot.
        revision_candidates={}
        for event_id, original in prior_decisions.items():
            pid=original.get('prediction_id')
            event=current_events.get(event_id) or prior_events.get(event_id)
            if not pid or not event or not original.get('triggered'):
                continue
            rank=(0 if event_id in current_events else 1, str(event_id))
            existing=revision_candidates.get(pid)
            if existing is None or rank < existing[0]:
                revision_candidates[pid]=(rank,event_id,event,original)
        for pid in sorted(revision_candidates):
            _, event_id, event, original=revision_candidates[pid]
            if event_id in current_events:
                current=current_decisions.get(event_id)
            elif event.get('tip_at') and iso(event['tip_at']) <= iso(asof):
                current={'market_revalidation': paper_market_revalidation(event, {}, asof, original.get('selected'))}
            else:
                current=None
            append_lifecycle_revision(root,event,original,current,asof,run_id)
    current=[r for r in rows if r['event']['bj_date']==day]
    native=mode=='FORWARD_NATIVE';message=('实时运行；低置信度研究定价不等于可投。' if native else '包内离线核查；非当时实际发布的前向预测，不计入实盘或纸面业绩。')
    settled=settle_existing(root,cap['history'],asof,cap.get('settlement_facts')) if native else 0
    learning_settled=settle_learning_records(root,cap['history'],asof) if native else {}
    formal_manual_ledger=build_formal_manual_live_ledger(root,asof) if native else None
    failure_audit=failure_audit_settlements(root,cap['history'],asof) if native else None
    settlement_tracking=sync_paper_settlements(root,asof) if native else None
    analytics=build_analytics(root,asof) if native else None
    oos_ledger_result=None; all_spread_residuals=spread_oos_records
    if native:
        oos_rows=residual_rows_from_analytics(analytics)
        oos_ledger_result=append_oos_residuals(oos_residual_path,oos_rows)
        all_spread_residuals=load_oos_residuals(oos_residual_path)
    shadow_learning=build_shadow_learning_analytics(root,asof,analytics) if native else None
    paper_funnel=daily_paper_funnel(current,day)
    coverage=build_coverage(current,cap.get('source_health',[]))
    history_readiness_diagnostic=build_history_readiness_diagnostic(current,cap,root,asof,mode)
    pricing_funnel_diagnostic=build_pricing_funnel_diagnostic(current,root,day,asof,cap.get('source_health',[]),history_readiness_diagnostic)
    total_market_pipeline_diagnostic=build_total_market_pipeline_diagnostic(current,root,day,asof)
    p0_bias_audit=build_p0_bias_audit(root,asof,day,current)
    paper_ledger_history=load(root/'paper_ledger_history.json',{})
    document=write_dashboard(root,rows,day,asof,mode,message,analytics=analytics,live_funnel=funnel(current),coverage=coverage,pricing_funnel_diagnostic=pricing_funnel_diagnostic,history_readiness_diagnostic=history_readiness_diagnostic,total_market_pipeline_diagnostic=total_market_pipeline_diagnostic,p0_bias_audit=p0_bias_audit,shadow_learning=shadow_learning,daily_paper_funnel=paper_funnel,formal_manual_ledger=formal_manual_ledger,paper_ledger_history=paper_ledger_history)
    # First-write preservation can add an immutable paper row to the written
    # current-day view. Recompute read-only diagnostics on exactly that final
    # row set so the manifest, JSON, and page cannot drift apart.
    written_rows=document.get('events',[])
    unified_evidence_audit=build_unified_evidence_audit(
        root,written_rows,day,asof,baseline_document,
        cap.get('unified_evidence_audit'))
    history_readiness_diagnostic=build_history_readiness_diagnostic(written_rows,cap,root,asof,mode)
    pricing_funnel_diagnostic=build_pricing_funnel_diagnostic(written_rows,root,day,asof,cap.get('source_health',[]),history_readiness_diagnostic)
    total_market_pipeline_diagnostic=build_total_market_pipeline_diagnostic(written_rows,root,day,asof)
    scope=pricing_funnel_diagnostic.get('scope_invariant') or {}
    if (pricing_funnel_diagnostic.get('date_bj')!=day or
        pricing_funnel_diagnostic.get('events')!=len(written_rows) or
        not scope.get('date_scope_match') or not scope.get('event_count_match')):
        raise AssertionError('DASHBOARD_PRICING_FUNNEL_SCOPE_ERROR')
    document['history_readiness_diagnostic']=history_readiness_diagnostic
    document['pricing_funnel_diagnostic']=pricing_funnel_diagnostic
    document['total_market_pipeline_diagnostic']=total_market_pipeline_diagnostic
    document['p0_bias_audit']=p0_bias_audit
    document['shadow_learning']=shadow_learning
    document['daily_paper_funnel']=daily_paper_funnel(written_rows,day)
    document['formal_manual_ledger']=formal_manual_ledger
    document['unified_evidence_audit']=unified_evidence_audit
    spread_probability_audit=build_spread_probability_audit(root,written_rows,all_spread_residuals,asof,day)
    document['spread_probability_audit']=spread_probability_audit
    document['oos_spread_residual_ledger']=oos_ledger_result or {
        'path':str(oos_residual_path),'total_N':len(all_spread_residuals),'append_only':True}
    atomic(root/'dashboard_v2'/'data'/(day+'.json'),document)
    atomic(root/'dashboard_v2'/'data'/'latest.json',document)
    revalidation_tracking=paper_market_revalidation_tracking(root,document,asof) if native else None
    prior_review=review_previous_day(root,day,asof) if native else None
    summary={'version':VERSION,'run_id':run_id,'archive_type':mode,'asof':asof,'day':day,'all_source_identities':len(rows),
      'source_history_facts':len(cap['history']),'source_quote_rows':len(cap['quotes']),'source_errors':cap.get('errors',[]),
      'stage_timings':cap.get('stage_timings',{}),
      'titan007_audit':cap.get('titan007_audit'),
      'titan007_history_audit':cap.get('titan007_history_audit'),
      'daily_event_inventory_audit':cap.get('daily_event_inventory_audit'),
      'team_histories_attempted':cap.get('histories_attempted',0),'team_histories_parsed':cap.get('histories_parsed',0),
      'team_history_games_parsed':cap.get('team_history_games_parsed',0),'history_page_audit':cap.get('history_page_audit',[]),
      'scope_funnel':funnel(rows),'today_funnel':funnel(written_rows),'cold_start_summary':cold_start_summary(written_rows),'priced_scope_events':[r['id'] for r in rows if r['pricing'].get('mu_raw') is not None],
      'pricing_call_count':len(calls),'settlements_appended':settled,'previous_day_paper_review':prior_review,
      'learning_settlements_appended':learning_settled,
      'paper_settlement_tracking':settlement_tracking,
      'failure_audit':failure_audit,
      'paper_market_revalidation':revalidation_tracking,'coverage':coverage,'coverage_all_events':build_coverage(rows,cap.get('source_health',[])),
      'spread_execution_total_analytics':analytics,
      'shadow_learning_analytics':shadow_learning,
      'formal_manual_ledger':formal_manual_ledger,
      'daily_paper_funnel':document.get('daily_paper_funnel'),
      'pricing_funnel_diagnostic':pricing_funnel_diagnostic,
      'total_market_pipeline_diagnostic':total_market_pipeline_diagnostic,
      'history_readiness_diagnostic':history_readiness_diagnostic,
      'p0_bias_audit':p0_bias_audit,
      'prior_forward_index':prior_forward_index_audit,
      'unified_evidence_audit':unified_evidence_audit,
      'spread_probability_audit':spread_probability_audit,
      'oos_spread_residual_ledger':oos_ledger_result or {'path':str(oos_residual_path),'total_N':len(all_spread_residuals),'append_only':True},
      'real_execution_allowed':False,
      'update_status':'PARTIAL' if cap.get('errors') or not any(r['execution'].get('comparison_ready') for r in rows) else 'COMPLETE',
      'source_http_attempts':len(cap.get('source_health',[])),'source_http_successes':sum(bool(x.get('ok')) for x in cap.get('source_health',[])),
      'missing_raw_files':cap.get('missing_raw_files',[]),'limitations':cap.get('limitations',[])}
    atomic(root/'manifests'/'repair_v22_latest.json',summary)
    atomic(root/'manifests'/(run_id+'_calls.json'),calls)
    atomic(root/'audits'/'current_event_pricing_audit.json',audit)
    fields=['event_id','league','team1','team2','tip_bj','historical_candidates','history_used','history_team_counts','history_opponent_counts','history_exclusions','competition_match_methods','paper_model_eligible','pricing_status','raw_margin','raw_total','raw_quote_rows','raw_verified','fresh_quotes','action','blockers','model_warnings','feature_fingerprint','pricing_called']
    csvwrite(root/'audits'/'current_event_pricing_audit.csv',audit,fields)
    atomic(root/'dashboard_v2'/'sources'/'health.json',cap.get('source_health',[]))
    # Counts explicitly distinguish samples from market-quote rows.
    analytics_summary = None
    if analytics:
        analytics_summary = {'spread_signal_layer': analytics.get('spread_signal_layer'),
                             'spread_execution_layer': analytics.get('spread_execution_layer'),
                             'price_exhaustion_layer': {k: analytics.get('price_exhaustion_layer', {}).get(k) for k in ('count', 'note')},
                             'total_diagnostic_layer': {k: analytics.get('total_diagnostic_layer', {}).get(k) for k in ('status', 'settled_total_observations', 'bias_conclusion')},
                             'migration': analytics.get('migration'),
                             'model_validation': analytics.get('model_validation')}
    atomic(root/'dashboard_v2'/'calibration'/'summary.json',{'archive_type':mode,'last_run_funnel':funnel(rows),'probability_calibration':'UNVALIDATED','ROI':None,'hit_rate':None,'spread_execution_total':analytics_summary,'real_execution_allowed':False})
    return {'summary':summary,'rows':rows,'document':document}

def reconstructed_score_backtest(cap,root,day,n):
    """Sequential score-only check. Never invent historical prices/entries or ROI.

    Historical final-score facts fetched later are reconstructed evidence. A
    conservative 24h availability lag is explicitly disclosed, not a claimed
    archive timestamp. This is distinct from strict original-snapshot replay.
    """
    # A tomorrow-slate refresh must not label the still-running capture day
    # as a complete backtest day. Anchor to the actual capture date as well.
    capture_day=iso(cap.get('capture_finished_at') or stamp()).astimezone(BJ).date().isoformat()
    dates=recent_complete_days(min(day,capture_day),n);history=cap['history'];targets=[g for g in history if iso(g['tip_at']).astimezone(BJ).date().isoformat() in dates]
    rows=[];excluded=[];dest=Path(root)/'calibration'/'repair_v22_score_reconstruction';dest.mkdir(parents=True,exist_ok=True)
    for g in sorted(targets,key=lambda x:x['tip_at']):
        e={k:g[k] for k in ('event_id','team1_id','team2_id','team1_name','team2_name','competition_id','gender','format_id','tip_at','league')}
        e['competition_key']=g.get('competition_key') or competition_key(g.get('league'),g.get('gender'))
        from .source import family
        e.update(model_family=family(g['league']),identity_verified=True,source_event_id=g['source_event_id'],age_group='UNVERIFIED',home_sign=0,
                 tip_time_bj=iso(g['tip_at']).astimezone(BJ).isoformat(),bj_date=iso(g['tip_at']).astimezone(BJ).date().isoformat())
        cutoff=stamp(iso(g['tip_at'])-timedelta(hours=1));mode='RECONSTRUCTED_SCORE_ONLY'
        # Outcome scores are not in event and target row is absent from history passed to model.
        input_history=[h for h in history if h['event_id']!=g['event_id']]
        p=price_event(e,input_history,cutoff,mode);pid=fingerprint({'event':e,'forecast':p})[:28]
        exclusive(dest/('forecast_'+pid+'.json'),p)
        if p['pricing_status']=='UNPRICEABLE':excluded.append({'event_id':g['event_id'],'day':e['bj_date'],'reason':p.get('blockers')});continue
        # Only now read the held-out target outcome.
        margin=g['score1_full']-g['score2_full'];total=g['score1_full']+g['score2_full']
        rows.append({'event_id':g['event_id'],'day':e['bj_date'],'league':e['league'],'model_family':e['model_family'],
          'team1':e['team1_name'],'team2':e['team2_name'],'cutoff':cutoff,'history_used':p['input_games'],
          'mu_margin':p['mu_raw'],'mu_total':p['total_raw'],'actual_margin':margin,'actual_total':total,
          'abs_margin_error':abs(margin-p['mu_raw']),'abs_total_error':abs(total-p['total_raw']),
          'archive_type':mode,'forecast_id':pid,'quote':None,'paper_pnl':None})
    def mae(key,arr):return sum(r[key] for r in arr)/len(arr) if arr else None
    daily=[{'date':d,'candidate_games':sum(iso(g['tip_at']).astimezone(BJ).date().isoformat()==d for g in targets),
            'priced_games':sum(r['day']==d for r in rows),'margin_MAE':mae('abs_margin_error',[r for r in rows if r['day']==d]),
            'total_MAE':mae('abs_total_error',[r for r in rows if r['day']==d])} for d in dates]
    summary={'requested_dates':dates,'candidate_games':len(targets),'priced_games':len(rows),'excluded_games':len(excluded),
       'archive_type':'RECONSTRUCTED_SCORE_ONLY','margin_MAE':mae('abs_margin_error',rows),'total_MAE':mae('abs_total_error',rows),
       'ROI':None,'hit_rate':None,'CLV':None,'strict_original_snapshot_replay_count':0,
       'assumptions':['Final-score facts reaggregated from later source snapshots; not an exact historical page-state replay.',
                      'A prior game must have started at least 24 hours before cutoff, be marked FINAL in the captured source, and not be the target.',
                      'No archived pregame quote means no entry, no PnL, no ROI. No model tuning on these outcomes.'],
       'daily':daily,'exclusions':excluded}
    atomic(dest/'summary.json',summary);atomic(Path(root)/'audits'/'recent6_backtest_audit.json',summary)
    csvwrite(dest/'replay_games.csv',rows,['event_id','day','league','model_family','team1','team2','cutoff','history_used','mu_margin','mu_total','actual_margin','actual_total','abs_margin_error','abs_total_error','archive_type','forecast_id','quote','paper_pnl'])
    csvwrite(dest/'daily_summary.csv',daily,['date','candidate_games','priced_games','margin_MAE','total_MAE'])
    return summary

def _public_recent_score_context(context):
    """Keep the score-context aggregates rendered by the public page."""
    if not isinstance(context, dict):
        return context
    public = {k: context.get(k) for k in (
        'status', 'method', 'schedule_context', 'cutoff', 'period_evidence',
        'close_game_definition', 'blowout_definition', 'missing_not_inferred',
        'matchup_recent_total') if k in context}
    public_teams = {}
    for team_id, team in (context.get('team_context') or {}).items():
        if not isinstance(team, dict):
            continue
        public_windows = {}
        for name in ('last_5', 'last_10'):
            window = (team.get('windows') or {}).get(name)
            if not isinstance(window, dict):
                continue
            period_totals = window.get('period_total_points') or {}
            public_windows[name] = {
                'games': window.get('games'),
                'games_in_14_days': window.get('games_in_14_days'),
                'total_points': {
                    'mean': (window.get('total_points') or {}).get('mean')},
                'period_total_points': {
                    period: {'mean': (period_totals.get(period) or {}).get('mean')}
                    for period in ('Q1', 'Q2', 'Q3', 'Q4')},
                'score_volatility': {
                    'total_stdev': (window.get('score_volatility') or {}).get(
                        'total_stdev')},
            }
        public_teams[team_id] = {
            'team_name': team.get('team_name'),
            'period_data_coverage': team.get('period_data_coverage'),
            'windows': public_windows,
        }
    public['team_context'] = public_teams
    return public


def _public_evidence_field(field):
    if not isinstance(field, dict):
        return field
    return {k: field.get(k) for k in ('value', 'quality', 'source', 'cutoff_valid')
            if k in field}


def _public_evidence_bundle(bundle):
    """Retain decision evidence without publishing repeated raw-file payloads."""
    if not isinstance(bundle, dict):
        return bundle
    public = {k: bundle.get(k) for k in ('schema_version', 'canonical_event_id')
              if k in bundle}
    public['DATA_QUALITY'] = dict(bundle.get('DATA_QUALITY') or {})
    history = bundle.get('HISTORY') or {}
    public['HISTORY'] = {
        key: _public_evidence_field(history.get(key))
        for key in (
            'home_same_comp_games', 'away_same_comp_games',
            'home_unique_opponents', 'away_unique_opponents',
            'effective_opponent_diversity', 'history_ess',
            'history_source_quality', 'history_sources')
        if key in history
    }
    pace = bundle.get('PACE') or {}
    public['PACE'] = {
        key: _public_evidence_field(pace.get(key))
        for key in ('pace_level', 'derived_possessions', 'direct_pace')
        if key in pace
    }
    rule = bundle.get('RULE') or {}
    public['RULE'] = {
        key: _public_evidence_field(rule.get(key))
        for key in ('regulation_minutes', 'period_count', 'period_minutes',
                    'overtime_minutes')
        if key in rule
    }
    return public


def _public_total_diagnostic(diagnostic):
    if not isinstance(diagnostic, dict):
        return diagnostic
    public = {k: v for k, v in diagnostic.items()
              if k != 'score_context_team_windows'}
    if 'recent_score_context' in public:
        public['recent_score_context'] = _public_recent_score_context(
            public['recent_score_context'])
    return public


def _public_pricing(pricing):
    if not isinstance(pricing, dict):
        return pricing
    kept = {
        'archive_type', 'asof', 'event_id', 'model_family', 'model_source',
        'model_version', 'pricing_status', 'pricing_state',
        'pricing_data_quality', 'blockers', 'model_warnings', 'input_games',
        'current_season_games', 'previous_season_games', 'older_history_games',
        'effective_sample_size', 'effective_sample_size_by_team',
        'effective_opponent_diversity', 'effective_opponent_diversity_by_team',
        'history_ess', 'history_ess_by_team', 'paper_model_eligible',
        'research_priceable', 'cold_start_priceable', 'shadow_eligible',
        'executable_eligible', 'prior_only_price', 'evaluation_channel',
        'league_lifecycle_state', 'league_tier', 'season_regime',
        'mu_raw', 'mu_structural', 'mu_market', 'mu_blended', 'total_raw',
        'total_structural', 'total_market', 'total_blended',
        'total_model_status', 'spread_data_quality', 'spread_context',
        'probability_calibration_status', 'uncertainty_source',
        'residual_scale_multiplier', 'residual_scale_breakdown',
        'adjustment_layer', 'titan_foundation_pricing', 'challenger_prices',
        'pregame_evidence_bundle', 'recent_score_context', 'total_diagnostic',
        'real_execution_allowed',
    }
    public = {k: v for k, v in pricing.items() if k in kept}
    if 'recent_score_context' in public:
        public['recent_score_context'] = _public_recent_score_context(
            public['recent_score_context'])
    if 'total_diagnostic' in public:
        public['total_diagnostic'] = _public_total_diagnostic(
            public['total_diagnostic'])
        if isinstance(public['total_diagnostic'], dict) and \
                'recent_score_context' in public['total_diagnostic']:
            # The renderer reads the diagnostic copy first.
            public.pop('recent_score_context', None)
    if 'pregame_evidence_bundle' in public:
        public['pregame_evidence_bundle'] = _public_evidence_bundle(
            public['pregame_evidence_bundle'])
    return public


def _public_execution(execution):
    if not isinstance(execution, dict):
        return execution
    omitted = {'candidates', 'learning_classification', 'signal_layer',
               'comparison_rows', 'fair_spread_decomposition'}
    public = {k: v for k, v in execution.items() if k not in omitted}
    for decision_group in ('market_decisions', 'titan_market_decisions'):
        decisions = public.get(decision_group)
        if isinstance(decisions, dict):
            public[decision_group] = {
                market: ({k: v for k, v in decision.items()
                          if k not in {'candidates', 'comparison_rows'}}
                         if isinstance(decision, dict) else decision)
                for market, decision in decisions.items()
            }
    if 'pregame_evidence_bundle' in public:
        public['pregame_evidence_bundle'] = _public_evidence_bundle(
            public['pregame_evidence_bundle'])
    return public


def _public_current_snapshot(snapshot):
    if not isinstance(snapshot, dict):
        return snapshot
    pricing = snapshot.get('pricing') or {}
    compact_pricing = {
        k: pricing.get(k) for k in (
            'pricing_status', 'total_diagnostic', 'recent_score_context')
        if k in pricing
    }
    if 'total_diagnostic' in compact_pricing:
        compact_pricing['total_diagnostic'] = _public_total_diagnostic(
            compact_pricing['total_diagnostic'])
    if 'recent_score_context' in compact_pricing:
        compact_pricing['recent_score_context'] = _public_recent_score_context(
            compact_pricing['recent_score_context'])
    execution = snapshot.get('execution') or {}
    compact_execution = {
        k: execution.get(k) for k in (
            'market_revalidation', 'shadow_action', 'comparison_ready',
            'triggered', 'display_action', 'selected', 'blockers',
            'uncertainty_flags', 'model_state', 'ev') if k in execution
    }
    if isinstance(execution.get('market_decisions'), dict):
        compact_execution['market_decisions'] = {
            market: {
                k: decision.get(k) for k in (
                    'selected', 'shadow_action', 'comparison_ready',
                    'triggered', 'display_action', 'model_state', 'ev',
                    'blockers', 'uncertainty_flags') if k in decision
            }
            for market, decision in execution['market_decisions'].items()
            if isinstance(decision, dict)
        }
    return {
        k: v for k, v in {
            'asof': snapshot.get('asof'),
            'refresh_status': snapshot.get('refresh_status'),
            'event': snapshot.get('event'),
            'market': snapshot.get('market'),
            'pricing': compact_pricing,
            'execution': compact_execution,
        }.items() if v is not None
    }


def public_dashboard_projection(document):
    """Return the compact, read-only document used by GitHub Pages.

    The local dashboard JSON remains the complete audit artifact.  The public
    page does not render several large append-only collections, and analytics
    records historically repeated the same checkpoint revision payload in
    every row.  Publishing those copies made a single date tens of megabytes
    without adding information to the page.  This projection removes only
    unrendered/redundant detail; event rows, decisions, settlements, source
    status and all summaries used by the HTML remain unchanged.
    """
    if not isinstance(document, dict) or 'events' not in document:
        return document
    public = dict(document)
    public_events = []
    for row in document.get('events') or []:
        if not isinstance(row, dict):
            public_events.append(row)
            continue
        projected = dict(row)
        if 'pricing' in projected:
            projected['pricing'] = _public_pricing(projected['pricing'])
        if 'execution' in projected:
            projected['execution'] = _public_execution(projected['execution'])
        if (isinstance(projected.get('pricing'), dict) and
                isinstance(projected.get('execution'), dict) and
                'pregame_evidence_bundle' in projected['execution']):
            # The event panel reads the execution copy first.
            projected['pricing'].pop('pregame_evidence_bundle', None)
        if 'current_snapshot' in projected:
            projected['current_snapshot'] = _public_current_snapshot(
                projected['current_snapshot'])
        if 'display_pricing' in projected:
            projected['display_pricing'] = _public_pricing(projected['display_pricing'])
        if 'display_execution' in projected:
            projected['display_execution'] = _public_execution(projected['display_execution'])
        if 'display_market' in projected and isinstance(projected['display_market'], dict):
            projected['display_market'] = {
                'quotes': projected['display_market'].get('quotes') or [],
                'quote_states': projected['display_market'].get('quote_states') or [],
            }
        public_events.append(projected)
    public['events'] = public_events

    analytics = document.get('analytics')
    if isinstance(analytics, dict):
        public_analytics = {k: v for k, v in analytics.items()
                            if k != 'execution_records'}
        records = analytics.get('records')
        if isinstance(records, list):
            public_analytics['records'] = [
                {k: v for k, v in row.items()
                 if k in {'prediction_id', 'entry_phase', 'threshold_source'}}
                if isinstance(row, dict) else row
                for row in records
            ]
        public['analytics'] = public_analytics

    p0 = document.get('p0_bias_audit')
    if isinstance(p0, dict):
        public['p0_bias_audit'] = {k: v for k, v in p0.items()
                                   if k != 'records'}

    formal = document.get('formal_manual_ledger')
    if isinstance(formal, dict):
        public['formal_manual_ledger'] = {
            k: v for k, v in formal.items() if k not in {'records', 'dedupe'}
        }
        day = str(document.get('date_bj') or '')
        day_records = []
        for record in formal.get('records') or []:
            if not isinstance(record, dict):
                continue
            event = record.get('event') or {}
            if str(event.get('bj_date') or '') != day:
                continue
            settlement = record.get('settlement') or {}
            day_records.append({
                'formal_record_id': record.get('formal_record_id'),
                'event_id': record.get('event_id'),
                'league': event.get('league'),
                'competition_key': event.get('competition_key'),
                'team1_name': event.get('team1_name'),
                'team2_name': event.get('team2_name'),
                'tip_time_bj': event.get('tip_time_bj') or event.get('tip_at'),
                'market_type': record.get('market_type'),
                'selection': record.get('selection'),
                'line': record.get('line'),
                'decimal_odds': record.get('decimal_odds'),
                'bookmaker': record.get('bookmaker'),
                'source_layer': record.get('source_layer'),
                'first_write_at': record.get('first_write_at'),
                'outcome': settlement.get('outcome'),
                'formal_manual_pnl': settlement.get('formal_manual_pnl'),
            })
        if day_records:
            public['formal_manual_ledger']['records'] = day_records

    pricing = document.get('pricing_funnel_diagnostic')
    if isinstance(pricing, dict):
        # The same history-readiness object already exists at the dashboard
        # top level and is rendered from there.  Keep one public copy.
        public_pricing = {
            k: v for k, v in pricing.items()
            if k not in {'history_readiness', 'league_decision_funnel'}
        }
        if isinstance(pricing.get('records'), list):
            public_pricing['records'] = [
                {k: v for k, v in row.items()
                 if k not in {'history_readiness', 'spread', 'total'}}
                if isinstance(row, dict) else row
                for row in pricing['records']
            ]
        public['pricing_funnel_diagnostic'] = public_pricing

    coverage = document.get('coverage')
    if isinstance(coverage, dict):
        # Source request logs have their own public health artifact and are not
        # read by the coverage widget.
        public['coverage'] = {k: v for k, v in coverage.items()
                              if k != 'source_health'}

    history = document.get('history_readiness_diagnostic')
    if isinstance(history, dict):
        # The HTML deliberately renders only the first 80 teams.  Preserve the
        # complete local diagnostic while publishing exactly that visible set.
        public_history = dict(history)
        if isinstance(history.get('teams'), list):
            visible_team_fields = {
                'canonical_team_id', 'raw_team_name', 'league', 'source',
                'raw_games_found', 'games_after_league_filter',
                'games_before_cutoff', 'usable_history_games',
                'minimum_required_games', 'primary_history_failure',
                'history_ready', 'paper_history_ready',
                'research_history_ready', 'effective_sample_size',
                'effective_opponent_diversity',
            }
            public_history['teams'] = [
                {k: v for k, v in team.items() if k in visible_team_fields}
                if isinstance(team, dict) else team
                for team in history['teams'][:80]
            ]
            public_history['public_team_rows'] = len(public_history['teams'])
        if isinstance(history.get('events'), list):
            event_team_fields = {
                'canonical_team_id', 'raw_team_name', 'league', 'source',
                'raw_games_found', 'games_after_league_filter',
                'games_before_cutoff', 'usable_history_games',
                'minimum_required_games', 'primary_history_failure',
                'history_ready', 'paper_history_ready',
                'research_history_ready', 'effective_sample_size',
                'effective_opponent_diversity',
            }
            public_history['events'] = []
            for event in history['events']:
                if not isinstance(event, dict):
                    public_history['events'].append(event)
                    continue
                public_event = {
                    k: event.get(k) for k in ('canonical_event_id', 'event_id')
                    if k in event}
                for side in ('team1', 'team2'):
                    team = event.get(side)
                    public_event[side] = (
                        {k: v for k, v in team.items()
                         if k in event_team_fields}
                        if isinstance(team, dict) else team)
                public_history['events'].append(public_event)
        public['history_readiness_diagnostic'] = public_history

    unified = document.get('unified_evidence_audit')
    if isinstance(unified, dict) and isinstance(unified.get('records'), list):
        public_unified = dict(unified)
        public_unified['records'] = [
            {k: v for k, v in row.items()
             if k not in {'history', 'pace', 'rotation', 'rule', 'teams'}}
            if isinstance(row, dict) else row
            for row in unified['records']
        ]
        public['unified_evidence_audit'] = public_unified

    public['public_projection'] = {
        'schema_version': 'basketball-public-projection-1.1',
        'full_audit_retained_locally': True,
        'events_preserved': len(document.get('events') or []),
    }
    return public


def publish(root,repo,push=False):
    root=Path(root);repo=Path(repo).resolve()
    if repo.name=='basketball-data':repo=repo.parent
    if not repo.is_dir():raise ValueError('publish directory does not exist')
    web=root/'dashboard_v2';target=repo/'basketball-data';target.mkdir(exist_ok=True)
    copied=[]
    for p in (web/'data').glob('*.json'):
        document=load(p,{})
        public_document=public_dashboard_projection(document)
        (target/p.name).write_text(
            json.dumps(public_document,ensure_ascii=False,sort_keys=True,
                       separators=(',',':'),allow_nan=False),
            encoding='utf-8')
        copied.append('basketball-data/'+p.name)
    (repo/'basketball-v2.html').write_text(HTML,encoding='utf-8');copied.append('basketball-v2.html')
    for folder,src in [('basketball-sources',web/'sources'/'health.json'),('basketball-calibration',web/'calibration'/'summary.json')]:
        (repo/folder).mkdir(exist_ok=True);shutil.copy2(src,repo/folder/src.name);copied.append(folder+'/'+src.name)
    result={'files_copied':copied,'old_basketball_html_modified':False,'git_push_requested':push,'public_verified':False}
    if push:
        def git(*args):return subprocess.run(['git','-C',str(repo),*args],capture_output=True,text=True,encoding='utf-8',errors='replace',check=True).stdout.strip()
        allowed=set(copied);staged=git('diff','--cached','--name-only').splitlines()
        if any(p not in allowed for p in staged):raise ValueError('other staged files exist; refusing mixed commit')
        git('add','--',*copied)
        if git('diff','--cached','--name-only'):git('commit','-m','fix basketball actual pricing pipeline and per-event data')
        result['commit']=git('rev-parse','HEAD')
        # The local release branch is intentionally versioned while GitHub
        # Pages is served from gh-pages.  Push the checked commit explicitly;
        # plain ``git push`` fails under push.default=simple when names differ.
        git('-c','http.version=HTTP/1.1','push','origin','HEAD:gh-pages');result['git_pushed']=True
        result['public_note']='Push success is not Pages-render validation; check the actual Pages deployment.'
    return result

def execute(root,day,live=False,bundle=None,session_id=None,backtest_n=0,publish_dir=None,push=False,timeout=12,workers=6):
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    if bundle:
        cap=replay_bundle(bundle,session_id)
        if not day or day=='auto':day=cap['requested_day']
    else:
        if not live:raise ValueError('Use --live for a new capture or --replay-bundle for explicitly separated offline audit')
        day=now().astimezone(BJ).date().isoformat() if not day or day=='auto' else day
        if day<now().astimezone(BJ).date().isoformat():raise ValueError('Past dates cannot become forward-native. Use --backtest-recent.')
        config=load(Path(__file__).resolve().parents[2]/'config'/'repair_market_contracts.json',DEFAULT_CONTRACTS)
        cap=collect_live(root,day,config,timeout,workers)
    if not cap['events']:
        failure={'version':VERSION,'run_id':cap['run_id'],'update_status':'FAILED','reason':'NO_CANONICAL_EVENTS_FROM_THIS_CAPTURE',
                 'source_health':cap.get('source_health',[]),'parse_errors':cap.get('errors',[]),'real_execution_allowed':False}
        atomic(root/'manifests'/'repair_v22_latest.json',failure)
        # Preserve last known data as stale, not as a fresh empty success.
        p=root/'dashboard_v2'/'data'/'latest.json';old=load(p)
        if old:
            old['update_status']='FAILED';old['last_failed_attempt_at']=stamp();old['message']='本轮采集失败；以下为历史最后记录，不是当前盘口。'
            old['current_quotes_usable']=False;atomic(p,old)
        atomic(root/'dashboard_v2'/'sources'/'health.json',cap.get('source_health',[]))
        if publish_dir and old:
            failure['publish']=publish(root,publish_dir,push)
        return failure
    result=run_capture(cap,root,day)
    if backtest_n:result['summary']['backtest']=reconstructed_score_backtest(cap,root,day,backtest_n)
    if bundle:
        preview=dict(result['document']);preview['events']=result['rows'];preview['funnel']=funnel(result['rows'])
        standalone_preview(root/'核查预览.html',preview)
    if publish_dir:
        if bundle:raise ValueError('Offline audit must not be published as current live data')
        try:
            result['summary']['publish']=publish(root,publish_dir,push)
        except Exception as exc:
            # Publication transport is external to a completed immutable data
            # run. Keep the run auditable and report the exact publish failure.
            result['summary']['publish']={'status':'PUBLISH_FAILED_AFTER_LOCAL_COMPLETION',
                                          'error_type':type(exc).__name__,'error':str(exc),
                                          'git_push_requested':push,'real_execution_allowed':False}
            result['summary']['update_status']='PARTIAL'
    atomic(root/'audits'/'repair_v22_run_report.json',result['summary'])
    return result['summary']
