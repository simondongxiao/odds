from __future__ import annotations
import json, re, urllib.request, urllib.error, uuid, math, time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, date
from pathlib import Path
from urllib.parse import urljoin, urlparse, urlencode
from html import unescape
try:
    from curl_cffi import requests as curl_requests
except Exception:
    curl_requests = None
try:
    import requests as std_requests
except Exception:
    std_requests = None
from .common import *
from odds_shared.http_retry import RetryPolicy, request_with_retry
from odds_shared.market_schedule import market_inventory_state
from global_discovery import discover as discover_global, merge_with_primary, classify as classify_global
from odds_discovery import route as route_odds
from providers.titan007_adapter import parse_schedule_xml as parse_titan_schedule_xml, parse_odds_xml as parse_titan_odds_xml
from providers.titan007_history_adapter import (
    update_history_database, merge_reference_history, load_event_foundation_contexts,
)
from providers.espn_history_adapter import collect_espn_history
from titan007_evidence_bridge import (
    load_normalized_history_store, build_pregame_evidence_bundles,
)

# These five selector mappings are evidenced in the supplied source audit.
COMPANIES={'0':('澳','0'),'1':('S2','4'),'2':('易','2'),'3':('12','3'),'4':('威','1')}
ALLOWED_HOSTS={'basket.7m.com.cn','js-basket.7m.com.cn','bdata.7m.com.cn','bdata-js.7m.com.cn','bodds.7m.com.cn','lq.7m.com.cn','lq3.titan007.com','www.betmonitor.com','betmonitor.com','www.cloudbet.com','cloudbet.com'}
JAPAN_B_LEAGUE_TOKENS=('JAPAN_BLEAGUE','B.LEAGUE','日本B联赛','日本男子B联赛','日B1','日B2','日B3','JAPANB1','JAPANB2','JAPANB3')
BETMONITOR_JAPAN_LEAGUE_URL='https://www.betmonitor.com/odds-comparison/basketball/japan-b-league-1/10007979'
BETMONITOR_TEAM_ALIASES={
    'Fukuoka':'福冈雷风神','Tokyo Excellence':'橫濱卓越',
    'Fukui Blowinds':'福井吹风','Yamagata Wyverns':'山形飞龙',
    'Gifu Swoops':'岐阜猛扑','Saitama':'琦玉野马',
    'Otsuka Alphas':'越谷阿尔法','Nagoya':'名古屋战鹰',
    'Kagoshima Rebnise':'鹿儿岛列布尼斯','Aomori Wats':'青森热力',
    'Bambitious Nara':'奈良雄心','Niigata Albirex':'新泻天鹅',
    'Veltex Shizuoka':'静冈顶峰','Tokushima Gambarous':'德岛甘巴鲁斯',
    'Tokyo Hachioji Trains':'东京八王子彩虹','Kumamoto Volters':'熊本火山',
    'Iwate Big Bulls':'岩手大公牛','Earth Friends Tokyo Z':'东京地球之友',
    'Okayama Tryhoop':'冈山尝试箍','Kagawa Five Arrows':'香川五箭',
    'Ehime Orange Vikings':'爱媛维京人','Kanazawa':'石川金泽武士',
}
CLOUDBET_KBL_URL='https://www.cloudbet.com/en/sports/basketball/south-korea-kbl'
# Cloudbet uses sponsor-free English labels while 7M's KBL schedule uses the
# Korean/Chinese display names.  These are explicit aliases only; matching is
# still done through the canonical registry token and the +/-5 minute tip key.
CLOUDBET_KBL_TEAM_ALIASES={
    'Samsung Thunders':'首尔三星雷电',
    'Seoul Samsung Thunders':'首尔三星雷电',
    'LG Sakers':'昌原LG猎隼',
    'Changwon LG Sakers':'昌原LG猎隼',
    'SK Knights':'首尔SK骑士',
    'Seoul SK Knights':'首尔SK骑士',
    'KCC Egis':'釜山KCC宙斯盾',
    'Busan KCC Egis':'釜山KCC宙斯盾',
    'KT Sonicboom':'水原KT音速弹',
    'Suwon KT Sonicboom':'水原KT音速弹',
    'DB Promy':'原州DB新世代',
    'Wonju DB Promy':'原州DB新世代',
    'Korea Gas Corporation':'大邱韩国燃气公社',
    'Daegu KOGAS Pegasus':'大邱韩国燃气公社',
    'Mobis Phoebus':'蔚山现代모비스피버스',
    'Ulsan Hyundai Mobis Phoebus':'蔚山现代모비스피버스',
    'Anyang KGC':'安养正官庄',
    'Anyang Jung Kwan Jang Red Boosters':'安养正官庄',
}

def apply_canonical_display_names(event):
    """Replace source display labels with the reviewed registry names.

    Some 7M payloads arrive with a lossy legacy encoding even though their
    identity IDs are still resolvable.  The canonical ID is the stable join;
    once it is attached, the registry name is the only safe UI label.  Keep
    the raw source label in an audit field and never use this display rewrite
    for matching or pricing.
    """
    registry = default_registry()
    by_id = {}
    for entity in (registry.payload.get('sports', {}).get('basketball', {}).get('teams', []) or []):
        cid = str(entity.get('canonical_team_id') or '')
        name = str(entity.get('name') or '')
        if cid and name:
            by_id[cid] = name
    for side in ('team1', 'team2'):
        cid = str(event.get('canonical_' + side + '_id') or '')
        display = by_id.get(cid)
        if display and event.get(side + '_name') != display:
            event.setdefault(side + '_source_name', event.get(side + '_name'))
            event[side + '_name'] = display
    if is_japan_b_league_event(event):
        event.setdefault('league_source_name', event.get('league'))
        event['league_display'] = '日本B联赛'
    return event

def is_japan_b_league_event(event):
    """Identify Japan B.League rows across 7M's 日B1/2/3 labels.

    The event inventory and the odds board use different competition labels.
    Keep this predicate in the collection layer so a delayed board quote does
    not prevent the Japanese fixture from being pre-warmed and retried.
    """
    event=event or {}
    key=str(event.get('competition_key') or '').upper()
    text=' '.join(str(event.get(name) or '') for name in ('league','league_family','competition_key','league_display')).upper()
    return key=='JAPAN_BLEAGUE' or any(token.upper() in text for token in JAPAN_B_LEAGUE_TOKENS)


def is_korea_kbl_event(event):
    """Recognize KBL before the later global classifier has run."""
    event = event or {}
    key = str(event.get('competition_key') or '').upper()
    text = ' '.join(str(event.get(name) or '') for name in
                    ('league', 'league_family', 'competition', 'competition_key', 'league_display')).upper()
    return key == 'KOREA_KBL' or any(token in text for token in
                                     ('KBL', '韩篮甲', '韓籃甲', '韩国篮球', '韓國籃球', '韩国KBL'))

def _canonical_team_token(value):
    # Titan's board appends live ranking markers such as ``[8]`` while the
    # 7M identity endpoint does not.  Only remove display-only markers; never
    # use fuzzy edit distance to force two different teams together.
    return canonical_team_token(value)

def _team_tokens(event, side):
    values=[event.get(side+'_name')]+list(event.get(side+'_aliases') or [])
    return {canonical_team_token(value) for value in values if canonical_team_token(value)}


def _cross_source_target_index(events):
    """Return the exact team namespace needed by Titan-led target events.

    A capture can contain both a 7M-led fixture and a Titan-led fixture for
    the same club.  Only the latter needs a 7M -> Titan history bridge.  Keep
    this index shared by the bridge and the append-only archive loader so the
    two paths cannot silently disagree about which teams are in scope.
    """
    targets = {}
    ambiguous = set()
    for event in events or []:
        attach_canonical_team_ids(event)
        if str(event.get('source') or '').upper() not in ('TITAN007', '') and not any(
                str(event.get(side + '_id') or '').startswith('titan-team:')
                for side in ('team1', 'team2')):
            continue
        scope = str(event.get('competition_key') or event.get('league_family') or '').upper()
        gender_value = str(event.get('gender') or '').upper()
        if not scope or not gender_value:
            continue
        for side in ('team1', 'team2'):
            canonical = str(event.get(side + '_id') or '')
            if not canonical:
                continue
            aliases = [event.get(side + '_name')] + list(event.get(side + '_aliases') or [])
            for alias in aliases:
                token = _canonical_team_token(alias)
                if not token:
                    continue
                key = (scope, gender_value, token)
                prior = targets.setdefault(key, set())
                prior.add(canonical)
                if len(prior) > 1:
                    ambiguous.add(key)
    return targets, ambiguous

def resolve_reused_7m_team_ids(events, history_rows):
    """Disambiguate a 7M numeric team id only when the capture proves reuse.

    The schedule endpoints use compact numeric ids, but those ids are not a
    globally stable team primary key.  A single live capture can, for example,
    label both Orlando and Cleveland as ``7m-team:6``.  Retaining that value as
    a canonical id joins unrelated histories and can poison Titan's exact-name
    bridge.  We preserve the compact id for source fetch/audit purposes, and
    give only proven collisions a league/gender/name-scoped canonical id.

    Non-colliding legacy ids remain unchanged for compatibility with existing
    ledgers and historical first writes.
    """
    rows=list(events or [])+list(history_rows or [])
    names_by_legacy={}
    for row in rows:
        for side in ('team1','team2'):
            legacy=str(row.get(side+'_id') or '')
            name=_canonical_team_token(row.get(side+'_name'))
            if re.fullmatch(r'7m-team:\d+',legacy) and name:
                names_by_legacy.setdefault(legacy,set()).add(name)
    collisions={legacy:names for legacy,names in names_by_legacy.items() if len(names)>1}
    changed=[]
    for row in rows:
        for side in ('team1','team2'):
            legacy=str(row.get(side+'_id') or '')
            if legacy not in collisions:
                continue
            token=_canonical_team_token(row.get(side+'_name'))
            if not token:
                continue
            # competition_key is the durable cross-source league label.  The
            # raw competition id is absent in 7M team-history pages, so using
            # it here would break the schedule/history join we are protecting.
            scope=str(durable_competition_key(row) or row.get('league') or 'UNKNOWN').upper()
            scoped='7m-team-name:'+scope+':'+str(row.get('gender') or 'UNKNOWN').upper()+':'+token
            row.setdefault(side+'_legacy_id',legacy)
            row[side+'_id']=scoped
            row[side+'_identity_method']='NAME_SCOPED_SOURCE_ID_COLLISION'
            changed.append({'event_id':row.get('event_id'),'side':side,
                            'legacy_team_id':legacy,'canonical_team_id':scoped,
                            'team_name':row.get(side+'_name')})
    return {'status':'OK','legacy_ids_observed':len(names_by_legacy),
            'colliding_legacy_ids':{key:sorted(value) for key,value in sorted(collisions.items())},
            'rewritten_team_references':len(changed),'rewrites':changed}


def bridge_cross_source_team_history_ids(history_rows, events):
    """Bridge exact 7M team-history IDs onto a Titan-led target event.

    7M and Titan007 publish the same club with different numeric namespaces
    (for example ``7m-team:2`` versus ``titan-team:14`` for Chicago).  The
    history facts are still valid, but the pricing layer cannot use them when
    the target event was discovered from Titan and its canonical team IDs are
    therefore Titan IDs.  Build a deliberately conservative name/league/
    gender bridge for target teams observed in this capture.

    Only exact normalized aliases are accepted and only a unique canonical
    target is rewritten.  The original provider IDs are preserved for audit;
    no fuzzy name matching or competition relaxation occurs here.
    """
    rows = list(history_rows or [])
    targets, ambiguous = _cross_source_target_index(events)
    target_registry_ids = {}
    for event in events or []:
        attach_canonical_team_ids(event)
        for side in ('team1','team2'):
            if event.get(side+'_id') and event.get('canonical_'+side+'_id'):
                target_registry_ids[str(event[side+'_id'])]=event['canonical_'+side+'_id']

    rewrites = []
    skipped_ambiguous = 0
    for row in rows:
        row_scope = str(durable_competition_key(row) or row.get('league_family') or '').upper()
        row_gender = str(row.get('gender') or '').upper()
        if not row_scope or not row_gender:
            continue
        for side in ('team1', 'team2'):
            old_id = str(row.get(side + '_id') or '')
            if not old_id.startswith('7m-team:'):
                continue
            token = _canonical_team_token(row.get(side + '_name'))
            key = (row_scope, row_gender, token)
            candidates = targets.get(key) or set()
            if key in ambiguous:
                skipped_ambiguous += 1
                continue
            if len(candidates) != 1:
                continue
            new_id = next(iter(candidates))
            if new_id == old_id:
                continue
            row.setdefault(side + '_legacy_id', old_id)
            row[side + '_id'] = new_id
            attach_canonical_team_ids(row)
            canonical_field='canonical_'+side+'_id'
            if target_registry_ids.get(new_id):
                row[canonical_field]=target_registry_ids[new_id]
            row.setdefault('cross_source_identity_bridge', {
                'method': 'EXACT_TEAM_ALIAS_COMPETITION_GENDER',
                'source_team_ids': {},
            })
            bridge = row['cross_source_identity_bridge']
            bridge.setdefault('source_team_ids', {})[side] = old_id
            bridge.setdefault('canonical_team_ids', {})[side] = new_id
            bridge.setdefault('registry_canonical_team_ids', {})[side] = row.get(canonical_field)
            bridge['status'] = 'BRIDGED_CROSS_SOURCE_TEAM_NAME'
            rewrites.append({
                'event_id': row.get('event_id'), 'side': side,
                'team_name': row.get(side + '_name'), 'scope': row_scope,
                'gender': row_gender, 'source_team_id': old_id,
                'canonical_team_id': new_id,
            })
    return {
        'status': 'OK',
        'candidate_team_keys': len(targets),
        'ambiguous_team_keys': len(ambiguous),
        'skipped_ambiguous_references': skipped_ambiguous,
        'rewritten_team_references': len(rewrites),
        'rewrites': rewrites,
    }


def _history_game_fingerprint(row):
    """Build a source-independent fingerprint for one completed game."""
    scope = str(durable_competition_key(row) or row.get('league_family') or '').upper()
    gender = str(row.get('gender') or '').upper()
    tip = source_time(row.get('tip_at'))
    pair = []
    for side in ('team1', 'team2'):
        token = _canonical_team_token(row.get(side + '_name'))
        score = row.get('score' + str(1 if side == 'team1' else 2) + '_full')
        if token:
            pair.append((token, str(score)))
    if len(pair) != 2 or tip is None:
        return None
    return (scope, gender, tuple(sorted(pair)), tip.isoformat())


def load_prior_capture_history(output_root, events, cutoff, current_session=None,
                               max_capture_days=3):
    """Load immutable prior capture facts for a Titan-led target.

    The live collector is intentionally market-first.  That is correct for
    discovery, but it also means a provider switch can make today's Titan
    fixture see only today's small 7M history crawl.  Prior captures already
    contain completed team-history facts, so reuse them incrementally rather
    than treating the provider switch as a new team with zero history.

    Selection is bounded to the newest capture per UTC run date and uses only
    exact normalized team name + competition + gender matches.  Every row is
    still subject to the normal final/cutoff checks downstream; this function
    additionally rejects future or not-yet-final rows before they enter the
    merged history pool.
    """
    root = Path(output_root)
    raw_root = root / 'raw' / 'repair_v22'
    targets, ambiguous = _cross_source_target_index(events)
    audit = {
        'status': 'NOT_NEEDED' if not targets else 'OK',
        'max_capture_days': max_capture_days,
        'candidate_team_keys': len(targets),
        'ambiguous_team_keys': len(ambiguous),
        'capture_files_considered': 0,
        'capture_files_read': 0,
        'capture_run_dates': [],
        'rows_seen': 0,
        'rows_matching_target': 0,
        'rows_added': 0,
        'rows_rejected_future_or_unfinal': 0,
        'rows_deduplicated': 0,
        'rows_skipped_event_id_conflict': 0,
    }
    if not targets or not raw_root.is_dir():
        return [], audit

    current_name = Path(current_session).name if current_session else ''
    candidates = sorted(raw_root.glob('*/capture.json'), key=lambda p: p.parent.name, reverse=True)
    audit['capture_files_considered'] = len(candidates)
    selected = []
    selected_days = set()
    for path in candidates:
        run_name = path.parent.name
        if current_name and run_name >= current_name:
            continue
        match = re.match(r'^(\d{8})T', run_name)
        if not match:
            continue
        run_day = match.group(1)
        if run_day in selected_days:
            continue
        selected.append(path)
        selected_days.add(run_day)
        if len(selected) >= max_capture_days:
            break

    cutoff_dt = source_time(cutoff)
    if cutoff_dt is None:
        cutoff_dt = now()
    rows = []
    for path in selected:
        try:
            capture = load(path, {}) or {}
            audit['capture_files_read'] += 1
            run_day = path.parent.name[:8]
            audit['capture_run_dates'].append(run_day)
        except Exception:
            continue
        for row in capture.get('history') or []:
            audit['rows_seen'] += 1
            if not isinstance(row, dict):
                continue
            scope = str(durable_competition_key(row) or row.get('league_family') or '').upper()
            gender = str(row.get('gender') or '').upper()
            matched = False
            for side in ('team1', 'team2'):
                token = _canonical_team_token(row.get(side + '_name'))
                if (scope, gender, token) in targets and (scope, gender, token) not in ambiguous:
                    matched = True
                    break
            if not matched:
                continue
            audit['rows_matching_target'] += 1
            tip = source_time(row.get('tip_at'))
            finalized = str(row.get('status') or '').upper() == 'FINAL'
            known_final = source_time(row.get('known_final_at')) if row.get('known_final_at') else None
            if tip is None or tip >= cutoff_dt or not finalized or (known_final and known_final > cutoff_dt):
                audit['rows_rejected_future_or_unfinal'] += 1
                continue
            rows.append(dict(row))

    audit['status'] = 'OK' if rows else ('NO_MATCHING_HISTORY' if selected else 'NO_PRIOR_CAPTURE')
    return rows, audit


def merge_prior_capture_history(current_rows, prior_rows):
    """Append prior facts without allowing mirror/collision rows to multiply."""
    merged = list(current_rows or [])
    existing_event_ids = {str(row.get('event_id')) for row in merged if row.get('event_id')}
    fingerprints = {_history_game_fingerprint(row) for row in merged}
    fingerprints.discard(None)
    audit = {'status': 'OK', 'prior_rows_considered': len(prior_rows or []),
             'rows_added': 0, 'rows_deduplicated': 0,
             'rows_skipped_event_id_conflict': 0}
    for row in prior_rows or []:
        event_id = str(row.get('event_id') or '')
        fingerprint = _history_game_fingerprint(row)
        if fingerprint is not None and fingerprint in fingerprints:
            audit['rows_deduplicated'] += 1
            continue
        if event_id and event_id in existing_event_ids:
            # The current capture wins.  Do not introduce a second fact under
            # one event id merely because the provider's score representation
            # differs between captures.
            audit['rows_skipped_event_id_conflict'] += 1
            continue
        merged.append(row)
        if event_id:
            existing_event_ids.add(event_id)
        if fingerprint is not None:
            fingerprints.add(fingerprint)
        audit['rows_added'] += 1
    return merged, audit

def upcoming_7m_deep_capture_event_ids(events, day, observed_at=None):
    """Return today plus next-day 7M fixtures that need pre-market evidence.

    Market boards often list an NBA/WNBA morning fixture later than the daily
    schedule.  Capturing its identity and histories one day ahead means a later
    *fresh* quote can be priced immediately.  This is evidence preparation,
    never a substitute for a quoted market.
    """
    target=date.fromisoformat(day)
    permitted={(target+timedelta(days=offset)).isoformat() for offset in (0,1)}
    cutoff=observed_at or now()
    def include_event(event):
        label=' '.join(str(event.get(key) or '') for key in
                       ('league','competition_key','league_family')).upper()
        priority = (is_japan_b_league_event(event) or 'WNBA' in label or
                    ('NBA' in label and 'WNBA' not in label) or
                    any(token in label for token in
                        ('NBL_AU', 'AUSTRALIA_NBL', 'NCAAB', 'WNCAAB', 'NCAA')))
        # Preserve full current-day coverage.  For the new lookahead leg,
        # pre-warm the formal NBL/NCAA pools as well as the NBA/Japan
        # morning pools.  These leagues are routinely published on the 7M
        # board before their final market snapshot; waiting for a quote here
        # strands the team-history/box-score bridge and later makes a real
        # data gap look like a model limitation.
        return (str(event.get('source')).upper() == '7M' and
                event.get('bj_date') in permitted and
                (event.get('bj_date') == day or priority) and
                source_time(event.get('tip_at')) and
                source_time(event.get('tip_at')) > cutoff)
    return {str(event.get('event_id')) for event in (events or []) if include_event(event)}

def _reconcile_event_family(event):
    """Return a normalized family label for source reconciliation only."""
    family = str(event.get('league_family') or '').upper().strip()
    if family:
        return family
    try:
        family, _ = classify_global(
            event.get('league') or event.get('competition') or '',
            event.get('competition_key') or event.get('raw_event_name') or '',
        )
        if family:
            return str(family).upper()
    except Exception:
        pass
    return str(event.get('competition_key') or event.get('league') or '').upper().strip()


def reconcile_titan_events(events, titan_events, quotes, tolerance_minutes=5):
    """Canonicalize Titan schedule/quotes onto an unambiguous 7M event.

    Titan and 7M expose different source event IDs for the same fixture.  The
    merge is allowed only when the unordered normalized team pair and start
    time agree and the candidate is unique.  Ambiguous/unmatched rows remain
    separate and are reported; no quote is silently discarded.
    """
    for event in events.values():
        attach_canonical_team_ids(event)
    for event in titan_events:
        attach_canonical_team_ids(event)
    primary=[e for e in events.values() if str(e.get('source')).upper()!='TITAN007']
    mapping={};mapping_orientation={};matched=[];ambiguous=[];unmatched=[];consolidated=[]
    quote_counts=Counter(str(q.get('event_id') or '') for q in quotes)

    def preference(event):
        source=str(event.get('source') or '').upper()
        # Keep a market-backed 7M row as the canonical display/ledger row;
        # otherwise prefer 7M over broad-discovery mirrors.  This is only an
        # identity preference, never a pricing preference.
        return (
            1 if quote_counts.get(str(event.get('event_id') or ''), 0) else 0,
            1 if source == '7M' else 0,
            1 if event.get('identity_verified') is True else 0,
            1 if event.get('source_event_id') else 0,
            1 if source.startswith('ESPN') else 0,
        )

    def absorb(canonical, duplicate):
        duplicate_id=str(duplicate.get('event_id') or '')
        if not duplicate_id or duplicate_id == str(canonical.get('event_id') or ''):
            return
        ids=list(canonical.get('continuity_source_event_ids') or [canonical.get('event_id')])
        if duplicate_id not in ids:
            ids.append(duplicate_id)
        canonical['continuity_source_event_ids']=sorted({str(x) for x in ids if x})
        canonical['event_identity_continuity_method']='CANONICAL_TEAM_PAIR_AND_TIP_TIME'
        discoveries=list(canonical.get('discovery_sources') or [])
        duplicate_discoveries=list(duplicate.get('discovery_sources') or [])
        if not duplicate_discoveries:
            duplicate_discoveries=[{'source':duplicate.get('source'),
                                    'source_url':duplicate.get('source_url'),
                                    'source_event_id':duplicate.get('source_event_id'),
                                    'event_id':duplicate_id,
                                    'match_method':'TEAM_PAIR_AND_TIP_TIME'}]
        for item in duplicate_discoveries:
            if item not in discoveries:
                discoveries.append(item)
        canonical['discovery_sources']=discoveries
        if duplicate.get('global_source_ids'):
            canonical.setdefault('global_source_ids',[])
            canonical['global_source_ids'] += [x for x in duplicate['global_source_ids']
                                               if x not in canonical['global_source_ids']]
    for te in titan_events:
        original_id=te.get('event_id')
        if original_id in events and str(events[original_id].get('source')).upper()!='TITAN007':
            candidates=[events[original_id]];method='SHARED_SOURCE_EVENT_ID'
        else:
            tt=source_time(te.get('tip_at'))
            titan_pair=(te.get('canonical_team1_id'),te.get('canonical_team2_id'))
            candidates=[]
            for pe in primary:
                pt=source_time(pe.get('tip_at'))
                primary_pair=(pe.get('canonical_team1_id'),pe.get('canonical_team2_id'))
                te_family=_reconcile_event_family(te)
                pe_family=_reconcile_event_family(pe)
                same_family=(not te_family or not pe_family or te_family==pe_family)
                same_order=titan_pair==primary_pair and all(titan_pair)
                swapped_order=titan_pair==tuple(reversed(primary_pair)) and all(titan_pair)
                if (tt and pt and (same_order or swapped_order) and same_family and
                        abs((tt-pt).total_seconds())<=tolerance_minutes*60):
                    pe['_titan_reconciliation_orientation']='SAME' if same_order else 'SWAPPED'
                    candidates.append(pe)
            method='TEAM_PAIR_AND_TIP_TIME'
        if candidates:
            ordered=sorted(candidates,key=preference,reverse=True)
            canonical=ordered[0];canonical_id=canonical['event_id'];mapping[original_id]=canonical_id
            mapping_orientation[original_id]=canonical.pop('_titan_reconciliation_orientation','SAME')
            duplicate_ids=[]
            for duplicate in ordered[1:]:
                duplicate_id=str(duplicate.get('event_id') or '')
                if not duplicate_id or duplicate_id == canonical_id:
                    continue
                mapping[duplicate_id]=canonical_id
                duplicate_ids.append(duplicate_id)
                absorb(canonical,duplicate)
                events.pop(duplicate_id,None)
            canonical.setdefault('discovery_sources',[]).append({
                'source':'TITAN007','source_url':te.get('source_url'),
                'source_event_url':te.get('source_event_url'),'source_event_id':te.get('source_event_id'),
                'match_method':method})
            canonical.setdefault('titan007_source_event_ids',[]).append(te.get('source_event_id'))
            canonical['titan007_event']=te
            if original_id!=canonical_id and events.get(original_id) is te:
                events.pop(original_id,None)
            matched.append({'titan_event_id':original_id,'canonical_event_id':canonical_id,'method':method,
                            'orientation':mapping_orientation.get(original_id,'SAME'),
                            'candidate_event_ids':[x.get('event_id') for x in candidates],
                            'duplicate_event_ids_consolidated':duplicate_ids})
            if duplicate_ids:
                consolidated.append({'canonical_event_id':canonical_id,
                                      'duplicate_event_ids':duplicate_ids,
                                      'titan_event_id':original_id})
        else:
            unmatched.append(original_id)
    for q in quotes:
        old=q.get('event_id')
        if old in mapping:
            q['source_event_id_titan']=q.get('source_event_id')
            q['source_event_id_original']=q.get('source_event_id')
            q['source_event_id_canonical']=events[mapping[old]].get('source_event_id')
            q['original_event_id']=old
            q['event_id']=mapping[old]
            q['canonical_event_id']=mapping[old]
            q['event_match_method']='TITAN_TEAM_PAIR_AND_TIP_TIME'
            orientation=mapping_orientation.get(old,'SAME')
            q['canonical_quote_orientation']=orientation
            if orientation=='SWAPPED' and q.get('market_type')=='SPREAD':
                if isinstance(q.get('line_team1'),(int,float)):
                    q['line_team1']=-q['line_team1']
                if isinstance(q.get('raw_prices'),list) and len(q['raw_prices'])==2:
                    q['raw_prices']=list(reversed(q['raw_prices']))
                if isinstance(q.get('decimal_prices'),list) and len(q['decimal_prices'])==2:
                    q['decimal_prices']=list(reversed(q['decimal_prices']))
                q['orientation_transform']='SWAP_TEAMS_NEGATE_SIGN_AND_SWAP_PRICES'
    return {'matched':matched,'ambiguous':ambiguous,'unmatched_event_ids':unmatched,
            'matched_count':len(matched),'ambiguous_count':len(ambiguous),'unmatched_count':len(unmatched),
            'consolidated':consolidated,'consolidated_count':len(consolidated)}

def game_minutes_for(league):
    """A diagnostic league-rule label, deliberately not a pricing feature."""
    text=str(league or '')
    rules=load(Path(__file__).resolve().parents[2]/'config'/'game_rule_registry.json',{}).get('rules',[])
    for rule in rules:
        if str(rule.get('match','')).casefold() in text.casefold():
            return rule.get('minutes'),rule.get('source','LEAGUE_RULE_PRIOR')
    fallback=load(Path(__file__).resolve().parents[2]/'config'/'game_rule_registry.json',{}).get('fallback',{})
    return fallback.get('minutes'),fallback.get('source','UNKNOWN_NO_MINUTES_ASSUMED')

class Fetcher:
    """Bounded, independent public requests; no stale-cache success or challenge bypass."""
    def __init__(self,directory,timeout=12,workers=6,retry_attempts=4,sleeper=time.sleep):
        self.directory=Path(directory);self.directory.mkdir(parents=True,exist_ok=True)
        self.timeout=timeout;self.workers=workers;self.rows=[]
        self.retry_policy=RetryPolicy(attempts=max(3,min(5,int(retry_attempts))),delays=(2.0,4.0,8.0))
        self.sleeper=sleeper
    def one(self,kv):
        key,url=kv; started=stamp(); meta={'key':key,'url':url,'started_at':started,'ok':False}
        try:
            if urlparse(url).hostname not in ALLOWED_HOSTS:raise ValueError('host not permitted')
            host=urlparse(url).hostname
            referer='https://lq3.titan007.com/nba.htm' if host=='lq3.titan007.com' else 'https://basket.7m.com.cn/free_gb.aspx'
            headers={'User-Agent':'Mozilla/5.0','Referer':referer,'Accept':'application/xml,text/xml,*/*'}
            def operation():
                primary_error=None
                if curl_requests is not None:
                    try:
                        response=curl_requests.get(url,headers=headers,impersonate='chrome',timeout=self.timeout,allow_redirects=True)
                        if urlparse(str(response.url)).hostname not in ALLOWED_HOSTS:raise ValueError('unexpected redirect host')
                        blob=bytes(response.content)
                        if response.status_code!=200:raise urllib.error.HTTPError(url,response.status_code,'HTTP '+str(response.status_code),response.headers,None)
                        return {'blob':blob,'http_status':response.status_code,'response_date':response.headers.get('Date'),
                                'last_modified':response.headers.get('Last-Modified'),'age_header':response.headers.get('Age'),
                                'http_client':'curl_cffi'}
                    except Exception as exc:
                        primary_error=exc
                request=urllib.request.Request(url,headers=headers)
                with urllib.request.urlopen(request,timeout=self.timeout) as response:
                    if urlparse(response.geturl()).hostname not in ALLOWED_HOSTS:raise ValueError('unexpected redirect host')
                    return {'blob':response.read(8_000_001),'http_status':response.status,
                            'response_date':response.headers.get('Date'),'last_modified':response.headers.get('Last-Modified'),
                            'age_header':response.headers.get('Age'),'http_client':'urllib',
                            'fallback_from':type(primary_error).__name__ if primary_error else None}
            result,attempts=request_with_retry(
                operation,url=url,policy=self.retry_policy,
                validate=lambda item: bool(item.get('blob')) and len(item['blob'])<=8_000_000,
                status_of=lambda item:item.get('http_status'),sleeper=self.sleeper)
            blob=result.pop('blob');meta.update(result);meta['attempts']=attempts;meta['attempt_count']=len(attempts)
            p=self.directory/(safe_id(key)+'.raw');p.write_bytes(blob)
            meta.update(ok=True,path=str(p),sha256=sha(blob),bytes=len(blob),received_at=stamp())
        except Exception as e:
            meta.update(error_type=type(e).__name__,error=str(e),received_at=stamp(),
                        attempts=getattr(e,'retry_attempts',[]),attempt_count=len(getattr(e,'retry_attempts',[])))
        return meta
    def batch(self,urls):
        with ThreadPoolExecutor(max_workers=self.workers) as pool:rows=list(pool.map(self.one,urls.items()))
        self.rows.extend(rows);atomic(self.directory/'http_manifest.json',self.rows)
        return {r['key']:r for r in rows}

def text_of(row): return decode(Path(row['path']).read_bytes()) if row and row.get('ok') else ''

def family(league):
    league = str(league or '')
    # NBA/WNBA preseason is a phase change, not a different team/league
    # identity.  Keep the mature league family so prior-season team history
    # can be reused; price_event applies the explicit PRESEASON uncertainty
    # multiplier and preserves the unchanged evidence/market gates.
    mainstream_preseason = any(token in league.upper() for token in ('NBA', 'WNBA')) and '季前' in league
    if mainstream_preseason:
        return 'CLUB_MATURE'
    if any(x in league for x in ('友谊','夏季','热身','青年','U18','U16','U19','U20','杯赛','德国杯','季前')):return 'HIGH_UNCERTAINTY'
    if any(x in league for x in ('世界女子','世界男子','世界杯','世锦赛','亚运','亚洲运动','欧洲国家','亚洲杯','非洲杯','国家队','欧国杯','美洲杯','奥运')):return 'NATIONAL_TEAM'
    return 'CLUB_MATURE'

def gender(name):return 'WOMEN' if any(t in name for t in ('女','Women','women','WNBA')) else 'MEN'

def parse_identity(text,source_id,source_path=None,observed_at=None,timezone_verified=True):
    a=assignments(text)
    required=('a_tm','a_mn','a_hn','a_an','a_hid','a_aid','a_mid')
    if not all(a.get(k) is not None for k in required):raise ValueError('identity fields missing')
    tip=source_time(a['a_tm']) if timezone_verified else None
    if tip is None:raise ValueError('SOURCE_TIME_UNVERIFIED')
    eid='7m:'+str(source_id)
    event_gender=gender(a['a_mn']+a['a_hn']+a['a_an'])
    minutes,minutes_source=game_minutes_for(a['a_mn'])
    return {'event_id':eid,'canonical_event_id':eid,'source_event_id':str(source_id),'source':'7M',
      'team1_id':'7m-team:'+str(a['a_hid']),'team2_id':'7m-team:'+str(a['a_aid']),
      'team1_name':a['a_hn'].replace('中国台湾','中国台北'),'team2_name':a['a_an'].replace('中国台湾','中国台北'),
      'team1_source_id':str(a['a_hid']),'team2_source_id':str(a['a_aid']),
      'competition_id':'7m-comp:'+str(a['a_mid']),'competition_key':competition_key(a['a_mn'],event_gender),
      'league':a['a_mn'],'season_phase':competition_phase(a['a_mn']),'model_family':family(a['a_mn']),
      'gender':event_gender,'age_group':'SENIOR' if family(a['a_mn'])!='HIGH_UNCERTAINTY' else 'UNVERIFIED',
      'format_id':'BASKETBALL','tip_at':stamp(tip),'tip_time_utc':stamp(tip),'tip_time_bj':tip.astimezone(BJ).isoformat(),
      'bj_date':tip.astimezone(BJ).date().isoformat(),'source_time_raw':a['a_tm'],'source_timezone':'Asia/Shanghai',
      'time_basis':'7M page declares GMT+0800 unless otherwise labelled',
      'identity_verified':True,'source_url':f'https://bdata.7m.com.cn/analyse/gb/{source_id}.shtml',
      'identity_raw_path':str(source_path) if source_path else None,'observed_at':observed_at,'venue_status':'UNKNOWN',
      'home_sign':0,'home_adjustment_assumption':'NEUTRAL_UNLESS_VERIFIED',
      'game_minutes':minutes,'game_minutes_source':minutes_source,'game_minutes_used_in_pricing':False}

def parse_schedule(text,path,observed_at):
    out=[];fail=[]
    for key,r in assignments(text).items():
        m=re.fullmatch(r'bDt\[(\d+)\]',key)
        if not m or not isinstance(r,list) or len(r)<9:continue
        try:
            # 7M live bDt row: state, time, league id/name/color, team1 id/name, team2 id/name.
            tip=source_time(r[1]);sid=m.group(1)
            if tip is None or not isinstance(r[6],str) or not isinstance(r[8],str):raise ValueError('schedule schema')
            league=r[3]
            event_gender=gender(league+r[6]+r[8])
            minutes,minutes_source=game_minutes_for(league)
            out.append({'event_id':'7m:'+sid,'canonical_event_id':'7m:'+sid,'source_event_id':sid,'source':'7M',
              'team1_id':'7m-team:'+str(r[5]),'team2_id':'7m-team:'+str(r[7]),'team1_source_id':str(r[5]),'team2_source_id':str(r[7]),
              'team1_name':r[6].replace('中国台湾','中国台北'),'team2_name':r[8].replace('中国台湾','中国台北'),
              'competition_id':'7m-comp:'+str(r[2]),'competition_key':competition_key(league,event_gender),
              'league':league,'season_phase':competition_phase(league),'model_family':family(league),'gender':event_gender,
              'age_group':'UNVERIFIED' if family(league)=='HIGH_UNCERTAINTY' else 'SENIOR','format_id':'BASKETBALL',
              'tip_at':stamp(tip),'tip_time_utc':stamp(tip),'tip_time_bj':tip.astimezone(BJ).isoformat(),'bj_date':tip.astimezone(BJ).date().isoformat(),
              'source_time_raw':r[1],'source_timezone':'Asia/Shanghai','identity_verified':True,'source_status':r[0],
              'source_url':'https://basket.7m.com.cn/free_gb.aspx','identity_raw_path':str(path),'observed_at':observed_at,
              'home_sign':0,'home_adjustment_assumption':'NEUTRAL_UNLESS_VERIFIED','venue_status':'UNKNOWN',
              'game_minutes':minutes,'game_minutes_source':minutes_source,'game_minutes_used_in_pricing':False})
        except (TypeError,ValueError,IndexError) as e:fail.append({'id':m.group(1),'error':str(e)})
    return out,fail

def parse_event_results(text,path,observed_at):
    """Parse final scores from 7M daily event result snapshots.

    The ``event_YYYYMMDD_fgb1.js`` files use the live-board ``bDt`` schema,
    not the team-history schema. These rows are settlement evidence only and
    must never enter the pregame history pool or model inputs.
    """
    result={};errors=[]
    hash_=sha(Path(path).read_bytes()) if Path(path).exists() else sha(text.encode())
    for key,row in assignments(text).items():
        match=re.fullmatch(r'bDt\[(\d+)\]',key)
        if not match or not isinstance(row,list) or len(row)<24:
            continue
        try:
            state=row[0]
            if state not in (9,11):
                continue
            tip=source_time(row[1])
            if not tip:
                continue
            team1_id,team1_name=row[5],row[6]
            team2_id,team2_name=row[7],row[8]
            if not isinstance(team1_name,str) or not isinstance(team2_name,str):
                raise ValueError('event result team names missing')
            periods1=row[10:15]
            periods2=row[17:22]
            if (len(periods1)!=5 or len(periods2)!=5 or
                any(isinstance(x,bool) or not isinstance(x,(int,float)) or x<0 or int(x)!=x
                    for x in periods1+periods2)):
                raise ValueError('event result period scores invalid')
            periods1=list(map(int,periods1));periods2=list(map(int,periods2))
            event_id='7m:'+match.group(1)
            result[event_id]={
                'event_id':event_id,'source_event_id':match.group(1),
                'tip_at':stamp(tip),'status':'FINAL','league':row[3],
                'team1_id':'7m-team:'+str(team1_id),'team2_id':'7m-team:'+str(team2_id),
                'team1_name':team1_name,'team2_name':team2_name,
                'period_count':5,'period_points_team1':periods1,
                'period_points_team2':periods2,
                'score1_regulation':sum(periods1[:4]),
                'score2_regulation':sum(periods2[:4]),
                'score1_full':sum(periods1),'score2_full':sum(periods2),
                'ot_points1':periods1[4],'ot_points2':periods2[4],
                'score_basis':'7M_EVENT_RESULT_PERIODS',
                'known_final_at':observed_at,'evidence_kind':'EVENT_RESULT',
                'raw_path':str(path),'raw_sha256':hash_,
                'source_variable':key,'source_schema':'BDT_EVENT_RESULT_V1',
                'source_status':state,'home_sign':0,
            }
        except (ValueError,TypeError,IndexError) as exc:
            errors.append({'row_id':match.group(1),'error':str(exc),'path':str(path)})
    return list(result.values()),errors

def rows_in(value):
    if isinstance(value,list):
        # a_wf detail rows have 25 fields; n_history.js t_history rows have 24.
        if len(value)>=24 and isinstance(value[2],str) and re.fullmatch(r'\d{4}(?:,\d{1,2}){5}',value[2]):yield value
        else:
            for v in value:yield from rows_in(v)
    elif isinstance(value,dict):
        for v in value.values():yield from rows_in(v)

def parse_history(text,path,observed_at,source_url,kind='TEAM_HISTORY'):
    result={};errors=[];hash_=sha(Path(path).read_bytes()) if Path(path).exists() else sha(text.encode())
    data=assignments(text)
    for name,v in data.items():
        # Whitelist data arrays, not handicap histories / predictions / tips.
        if re.search(r'(odds|handicap|ats|pred)',name,re.I):continue
        trusted_history_endpoint=(kind=='TEAM_HISTORY' and urlparse(source_url).path.endswith('/gb/n_history.js'))
        if name!='a_wf' and not trusted_history_endpoint and not re.search(r'(history|match|game)',name,re.I):continue
        for r in rows_in(v):
            try:
                if r[1] not in (9,11):continue # source final / final after overtime codes
                tip=source_time(r[2])
                if not tip:continue
                # Detail a_wf and team n_history.js are different public schemas.
                # a_wf: comp id/name at 3/4, teams at 7..10, periods at 11..20.
                # t_history: comp label at 3, teams at 5..8, periods at 9..18.
                is_team_row=(len(r)>=24 and isinstance(r[3],str) and isinstance(r[5],(int,float)) and isinstance(r[6],str))
                if is_team_row:
                    league=r[3];comp_id=None;team1_id=r[5];team1_name=r[6];team2_id=r[7];team2_name=r[8]
                    scores=r[9:19];period_count=r[21] if len(r)>21 else None
                    half_summaries=()
                    schema='N_HISTORY_24'
                else:
                    if len(r)<25:raise ValueError('unsupported history row schema')
                    comp_id='7m-comp:'+str(r[3]);league=r[4];team1_id=r[7];team2_id=r[8];team1_name=r[9];team2_name=r[10]
                    scores=r[11:21];period_count=r[5];half_summaries=((r[21],None),(r[22],None));schema='A_WF_25'
                if len(scores)!=10 or any(isinstance(x,bool) or not isinstance(x,(int,float)) or x<0 or int(x)!=x for x in scores):raise ValueError('invalid period scores')
                hq=list(map(int,scores[:5]));aq=list(map(int,scores[5:]));s1=sum(hq);s2=sum(aq)
                if s1+s2==0:raise ValueError('empty final score')
                # Final score sums must agree with the source half-score summaries when present.
                for chunks,expected in ((x,s1 if i==0 else s2) for i,(x,_) in enumerate(half_summaries)):
                    if isinstance(chunks,str) and re.fullmatch(r'\d+/\d+',chunks) and sum(map(int,chunks.split('/')))!=expected:
                        raise ValueError('quarter/half score mismatch')
                row_gender=gender(league+team1_name+team2_name)
                ev='7m:'+str(r[0]); result[ev]={'event_id':ev,'source_event_id':str(r[0]),'tip_at':stamp(tip),'status':'FINAL',
                   'competition_id':comp_id,'competition_key':competition_key(league,row_gender),'competition_identity_level':'SOURCE_ID' if comp_id else 'CANONICAL_SOURCE_LABEL',
                    'league':league,'season_phase':competition_phase(league),'team1_id':'7m-team:'+str(team1_id),'team2_id':'7m-team:'+str(team2_id),
                   'team1_name':team1_name.replace('(中)','').replace('中国台湾','中国台北'),'team2_name':team2_name.replace('(中)','').replace('中国台湾','中国台北'),
                   'gender':row_gender,'format_id':'BASKETBALL','period_count':period_count,
                   # Preserve source quarter scoring so late-game diagnostics never
                   # have to reconstruct it from final scores.
                   'period_points_team1':hq,'period_points_team2':aq,
                   'score1_regulation':sum(hq[:4]),'score2_regulation':sum(aq[:4]),'score1_full':s1,'score2_full':s2,
                   'ot_points1':hq[4],'ot_points2':aq[4],'score_basis':'PERIOD_SUM','known_final_at':observed_at,
                   'evidence_kind':kind,'source_url':source_url,'raw_path':str(path),'raw_sha256':hash_,
                    'source_variable':name,'source_schema':schema,'source_status':r[1],'home_sign':0,'home_adjustment_assumption':'UNVERIFIED_NO_HOME_ADJUSTMENT'}
            except (ValueError,TypeError,IndexError) as e:errors.append({'row_id':str(r[0]) if r else None,'error':str(e)})
    return list(result.values()),errors

def discover_links(html,event):
    """Only follow the team-history template actually present in the downloaded page."""
    if '/Basketball_Team_Data/' not in html or '/gb/n_history.js' not in html:return {}
    return {str(t):f'https://bdata.7m.com.cn/Basketball_Team_Data/{t}/gb/n_history.js' for t in (event['team1_source_id'],event['team2_source_id'])}

def parse_total_context(text, path, received_at, source_url):
    """Retain 7M pregame aggregates without guessing undocumented meanings."""
    data=assignments(text)
    known={k:data[k] for k in ('avgWLPoint','teamStanding','pointStat','totalStat','bqcStat','teamStats') if k in data}
    stats=data.get('teamStats') if isinstance(data.get('teamStats'),dict) else None
    stats_profile={}
    if stats:
        fields=('fg_pct','three_pct','ft_pct','rebounds','assists','fouls','steals','turnovers','blocks','points')
        for side in ('A','B'):
            payload=stats.get(side) if isinstance(stats.get(side),dict) else {}
            stats_profile[side]={}
            for window in ('last5','last10','season'):
                values=payload.get(window)
                if not isinstance(values,list) or len(values)!=len(fields):continue
                try:stats_profile[side][window]={k:float(v) for k,v in zip(fields,values)}
                except (TypeError,ValueError):continue
    basic_offense_verified=bool(all((stats_profile.get(side) or {}).get('last5') or (stats_profile.get(side) or {}).get('last10') for side in ('A','B')))
    three_point_verified=bool(basic_offense_verified and all(any('three_pct' in row for row in (stats_profile.get(side) or {}).values()) for side in ('A','B')))
    return {'source_url':source_url,'raw_path':str(path),'raw_sha256':sha(Path(path).read_bytes()) if Path(path).exists() else sha(text.encode()),
            'captured_at':received_at,'available_variables':sorted(known),'source_aggregates':known,
            'possessions_per_game':None,'possessions_verified':False,
            'basic_offense_profile':stats_profile or None,'basic_offense_verified':basic_offense_verified,
            'three_point_profile':stats_profile or None,'three_point_verified':three_point_verified,
            'late_foul_profile':None,'late_foul_verified':False,
            'rotation_change':None,'rotation_verified':False,
            'schema_note':'7M aggregate arrays retained as raw evidence; unavailable fields are not inferred from score totals.'}

def parse_odds(text,path,received_at,company_selector,contracts):
    out=[];errors=[];selector_name,expected_namespace=COMPANIES[str(company_selector)]
    raw_sha=sha(Path(path).read_bytes()) if Path(path).exists() else sha(text.encode())
    contract=contracts.get('companies',{}).get(expected_namespace,{})
    for k,v in assignments(text).items():
        m=re.fullmatch(r'bOdds\[(\d+)\]\[(\d+)\]',k)
        if not m or not isinstance(v,dict):continue
        ns,sid=m.groups()
        if ns!=expected_namespace:errors.append({'id':sid,'error':'COMPANY_NAMESPACE_MISMATCH'});continue
        for raw_market,market in [('HB','SPREAD'),('TP','TOTAL')]:
            markets=v.get(raw_market)
            if not isinstance(markets,dict):continue
            for raw_key,a in markets.items():
                if not isinstance(a,list) or len(a)<4:
                    errors.append({'id':sid,'market_type':market,'raw_market':raw_market,'error':'ODDS_ARRAY_SCHEMA','loss_stage':market+'_PARSER_LOSS'});continue
                try:
                    p1,p2=float(a[0]),float(a[1]);line=float(a[3]);qt=source_time(a[2])
                    if not all(math.isfinite(x) for x in (p1,p2,line)):raise ValueError('nonfinite odds')
                except (ValueError,TypeError):
                    errors.append({'id':sid,'market_type':market,'raw_market':raw_market,'error':'INVALID_ODDS_VALUE','loss_stage':market+'_PARSER_LOSS'});continue
                # The platform contract is evidenced once for all legal 7M namespaces.
                platform_evidence=contracts.get('platform_semantics_evidence') or contract.get('semantics_evidence')
                verified=bool(platform_evidence and contract.get('price_format')=='HK')
                direction_mode=contract.get('spread_line_basis')
                sh=None
                if verified and market=='SPREAD':
                    if direction_mode=='SIGNED_TEAM1_HANDICAP':sh=line
                    elif direction_mode=='POSITIVE_TEAM1_GIVES':sh=-line
                    elif direction_mode=='FLAG':
                        sh=contract.get('spread_flag_map',{}).get(str(a[4] if len(a)>4 else None))
                        sh=None if sh is None else float(sh)*abs(line)
                main_index=7 if market=='SPREAD' else 6
                is_main=a[main_index] if len(a)>main_index else None
                main_or_alt='MAIN' if str(is_main)=='1' else 'ALT' if str(is_main)=='0' else 'UNVERIFIED'
                raw={'quote_id':sha((ns+sid+raw_market+str(raw_key)+str(a)+received_at).encode())[:24],
                   'event_id':'7m:'+sid,'source_event_id':sid,'feed_provider':'7M','bookmaker_id':'7m-company:'+ns,
                   'bookmaker':selector_name,'selector_id':str(company_selector),'company_namespace':ns,'market_type':market,
                   'raw_market_key':raw_market,'parse_status':'PARSED_AND_NORMALIZED',
                   'period':'FULL_GAME','main_or_alt':main_or_alt,'source_market_key':str(raw_key),'source_main_flag':is_main,
                   'source_array':a,'raw_line':line,'line_team1':sh,'direction_verified':sh is not None if market=='SPREAD' else verified,
                   'raw_prices':[p1,p2],'decimal_prices':[p1+1,p2+1] if verified and min(p1,p2)>0 else None,
                   'price_format':contract.get('price_format','UNVERIFIED'),'price_format_verified':verified,
                   'source_quote_at':stamp(qt) if qt else None,'source_timestamp_raw':a[2],
                   'source_timestamp_semantics':contract.get('timestamp_semantics','UNKNOWN'),
                   'received_at':received_at,'observed_at':received_at,'raw_path':str(path),'raw_sha256':raw_sha,
                   'ot_rule':contract.get('overtime_rule','UNKNOWN'),'rule_evidence':contract.get('rule_evidence'),
                   'comparison_scope':contract.get('comparison_scope','OBSERVATION_ONLY'),
                   'current_board_contract_verified':bool(contract.get('current_board_contract_verified') and platform_evidence),
                   'status':'OBSERVED','raw_verified':Path(path).is_file(),'execution_verified':False}
                out.append(raw)
    return out,errors

def retry_japan_b_league_boards(fetch, events, quotes, contracts, observed_at=None,
                                max_rounds=2):
    """Retry 7M boards when Japanese fixtures are known but the board is late.

    A non-empty ``comlive_*.js`` response can still contain no rows for a
    newly listed Japan B.League fixture.  The generic HTTP retry layer cannot
    distinguish that valid-but-empty board from a successful capture.  This
    bounded target-aware retry keeps the event inventory, waits 2s then 4s,
    and only appends quotes whose event id is actually present in the retry
    response.  It never reuses a historical odds page as a current quote.
    """
    cutoff=observed_at or now()
    candidates={str(event.get('event_id')):event for event in (events or [])
                if is_japan_b_league_event(event) and event.get('event_id') and
                source_time(event.get('tip_at')) and source_time(event.get('tip_at'))>cutoff-timedelta(hours=2)}
    observed={str(quote.get('event_id')) for quote in (quotes or [])
              if quote.get('feed_provider')=='7M' and quote.get('event_id')}
    missing=set(candidates)-observed
    audit={'status':'NOT_NEEDED' if not missing else 'RETRYING','candidate_event_ids':sorted(candidates),
           'initial_observed_event_ids':sorted(observed & set(candidates)),
           'initial_missing_event_ids':sorted(missing),'attempts':[],
           'retry_delays_seconds':[2.0,4.0][:max(0,int(max_rounds))],
           'quotes_added':0,'unresolved_event_ids':[]}
    added=[]
    if not missing:
        audit['status']='OBSERVED'
        return added,audit
    for attempt,delay in enumerate(audit['retry_delays_seconds'],1):
        if missing:
            fetch.sleeper(delay)
        tick=str(int(now().timestamp()*1000))
        urls={f'japan_retry_{attempt}_odds_company_{sel}':
              f'https://js-basket.7m.com.cn/odds/comlive_{ns}.js?t={tick}'
              for sel,(_,ns) in COMPANIES.items()}
        responses=fetch.batch(urls)
        parsed=[];errors=[]
        for key,row in responses.items():
            if not row.get('ok'):
                errors.append({'key':key,'url':row.get('url'),'error':row.get('error_type') or 'FETCH_FAILED'})
                continue
            try:
                qs,err=parse_odds(text_of(row),row.get('path'),row.get('received_at'),key.rsplit('_',1)[1],contracts)
                parsed.extend(qs);errors.extend(err)
            except Exception as exc:
                errors.append({'key':key,'path':row.get('path'),'error':type(exc).__name__+': '+str(exc)})
        target_parsed=[q for q in parsed if str(q.get('event_id')) in candidates]
        if target_parsed:
            added.extend(target_parsed)
            observed.update(str(q.get('event_id')) for q in target_parsed)
            missing=set(candidates)-observed
        audit['attempts'].append({'attempt':attempt,'delay_seconds':delay,'parsed_quotes':len(parsed),
                                  'target_quotes':len(target_parsed),'observed_target_event_ids':sorted(set(str(q.get('event_id')) for q in target_parsed)),
                                  'remaining_event_ids':sorted(missing),'errors':errors})
        if not missing:
            break
    audit['quotes_added']=len(added);audit['unresolved_event_ids']=sorted(missing)
    audit['status']='OBSERVED' if not missing else 'BOARD_NOT_YET_LISTED'
    return added,audit


def _betmonitor_text(value):
    """Decode the small HTML fragments returned by Betmonitor.

    The adapter intentionally uses only visible, non-script markup.  It never
    executes provider JavaScript and it keeps the original response as an
    immutable raw file for the evidence audit.
    """
    value = unescape(re.sub(r'<[^>]+>', ' ', str(value or '')))
    return re.sub(r'\s+', ' ', value).strip()


def _betmonitor_event_links(html):
    pattern = re.compile(
        r'href=["\'](/odds-comparison/basketball/japan-b-league-1/[^"\']+/([0-9]+))["\']',
        re.I,
    )
    seen = set(); out = []
    for match in pattern.finditer(html or ''):
        href, rid = match.groups()
        if rid == '10007979' or rid in seen:
            continue
        seen.add(rid); out.append((rid, urljoin(BETMONITOR_JAPAN_LEAGUE_URL, href)))
    return out


def _betmonitor_event_page(html, rid, url, day):
    stamp_match = re.search(r'class=["\']evtime-switch[^>]*data-type=["\']event-header["\'][^>]*data-timestamp=["\'](\d+)', html or '', re.I)
    if not stamp_match:
        stamp_match = re.search(r'class=["\']evtime-switch[^>]*data-timestamp=["\'](\d+)', html or '', re.I)
    if not stamp_match:
        return None
    tip = datetime.fromtimestamp(int(stamp_match.group(1)), UTC)
    if tip.astimezone(BJ).date().isoformat() != day:
        return None
    team_match = re.search(r'<div class=["\']teams(?:\s+[^"\']*)?["\'][^>]*>(.*?)<div class=["\']favorites', html or '', re.I | re.S)
    teams = _betmonitor_text(team_match.group(1) if team_match else '')
    if '—' not in teams:
        teams = teams.replace('–', '—').replace('-', '—', 1)
    pair = [x.strip() for x in teams.split('—', 1)] if '—' in teams else []
    if len(pair) != 2:
        return None
    lines = {}
    for market in ('mahc', 'ou'):
        top = re.search(r'<div class=["\']dd-item\s+' + market + r'\s+top[^>]*data-type=["\']([^"\']+)', html or '', re.I)
        any_line = re.search(r'<div class=["\']dd-item\s+' + market + r'(?:\s+[^"\']*)?[^>]*data-type=["\']([^"\']+)', html or '', re.I)
        lines[market] = (top or any_line).group(1) if (top or any_line) else None
    return {'rid': str(rid), 'url': url, 'tip_at': tip.isoformat(),
            'team1_name': pair[0], 'team2_name': pair[1], 'lines': lines}


def _betmonitor_post(fetch, rid, market, line, referer, observed_at):
    """Fetch one current Betmonitor market fragment with the common retry policy."""
    payload = urlencode({'rid': rid, 'bettype': market, 'line': str(line),
                         'view': 'classic', 'period': 'ft'}).encode()
    url = 'https://www.betmonitor.com/content/get_odds.php'
    headers = {'User-Agent': 'Mozilla/5.0 basketball-odds-trader/1.0',
               'Referer': referer, 'X-Requested-With': 'XMLHttpRequest',
               'Accept': 'text/html,*/*'}
    def operation():
        request = urllib.request.Request(url, data=payload, headers=headers, method='POST')
        with urllib.request.urlopen(request, timeout=fetch.timeout) as response:
            body = response.read(8_000_001)
            return {'blob': body, 'http_status': response.status}
    result, attempts = request_with_retry(
        operation, url=url, policy=fetch.retry_policy,
        validate=lambda item: bool(item.get('blob')) and len(item['blob']) <= 8_000_000,
        status_of=lambda item: item.get('http_status'), sleeper=fetch.sleeper)
    body = result['blob']
    path = fetch.directory / safe_id(f'betmonitor_{rid}_{market}_{line}')
    path = path.with_suffix('.html'); path.write_bytes(body)
    meta = {'key': f'betmonitor_{rid}_{market}', 'url': url,
            'source': 'betmonitor_japan_b_league', 'source_group': 'odds_board',
            'ok': True, 'path': str(path), 'sha256': sha(body),
            'bytes': len(body), 'http_status': result.get('http_status'),
            'attempts': attempts, 'attempt_count': len(attempts),
            'received_at': observed_at, 'market': market, 'rid': str(rid),
            'line': str(line), 'referer': referer}
    fetch.rows.append(meta)
    return body.decode('utf-8-sig', 'replace'), meta


def _betmonitor_quotes_fragment(html, event, market, line, meta, observed_at):
    """Normalize Betmonitor's visible bookmaker rows into the shared quote contract."""
    chunks = re.findall(r'<div class=["\']bookie-cont\b[^>]*>(.*?)(?=<div class=["\']bookie-cont\b|$)', html or '', re.I | re.S)
    out = []
    try:
        numeric_line = float(line)
    except (TypeError, ValueError):
        return out
    for chunk in chunks:
        name_match = re.search(r'<div class=["\']bookie["\'][^>]*>.*?<a[^>]*>(.*?)</a>', chunk, re.I | re.S)
        bookmaker = _betmonitor_text(name_match.group(1) if name_match else '')
        odds = []
        for value in re.findall(r'<span class=["\']odd-decimal[^"\']*["\']>\s*([0-9]+(?:\.[0-9]+)?)\s*</span>', chunk, re.I):
            try:
                price = float(value)
                if math.isfinite(price) and price > 1:
                    odds.append(price)
            except (TypeError, ValueError):
                continue
        if not bookmaker or len(odds) < 2:
            continue
        odds = odds[:2]
        provider = 'BETMONITOR'
        quote_id = sha((str(event.get('event_id')) + provider + bookmaker + market + str(line) + str(meta.get('sha256'))).encode())[:24]
        out.append({
            'quote_id': quote_id, 'event_id': event.get('event_id'),
            'canonical_event_id': event.get('canonical_event_id') or event.get('event_id'),
            'source_event_id': event.get('source_event_id'), 'feed_provider': provider,
            'upstream_provider': 'betmonitor', 'bookmaker_id': 'betmonitor-bookmaker:' + normalize_label(bookmaker),
            'bookmaker': bookmaker, 'market_type': 'SPREAD' if market == 'mahc' else 'TOTAL',
            'raw_market_key': 'BETMONITOR_MAHC' if market == 'mahc' else 'BETMONITOR_OU',
            'parse_status': 'PARSED_AND_NORMALIZED', 'period': 'FULL_GAME',
            'market_role': 'MAIN', 'main_or_alt': 'MAIN', 'source_main_flag': '1',
            'source_market_key': str(line), 'raw_line': numeric_line,
            'line_team1': numeric_line if market == 'mahc' else None,
            'direction_verified': True, 'raw_prices': odds, 'decimal_prices': odds,
            'price_format': 'DECIMAL', 'price_format_verified': True,
            'source_quote_at': observed_at, 'source_timestamp_raw': observed_at,
            'source_timestamp_semantics': 'CURRENT_BOARD_CAPTURE_ONLY',
            'received_at': observed_at, 'observed_at': observed_at,
            'raw_path': meta.get('path'), 'raw_sha256': meta.get('sha256'),
            'raw_verified': True, 'raw_integrity_verified': True,
            'status': 'OPEN', 'current_board_contract_verified': True,
            'last_verified_at': observed_at, 'quote_verified_for_paper': True,
            'identity_verified': True, 'ot_rule': 'INCLUDING_OT',
            'rule_evidence': 'BETMONITOR_FULL_GAME_MARKET_PAGE; capture-time OPEN listing',
            'ot_contract_status': 'SOURCE_RULE_OMITTED_POLICY_INCLUDED',
            'comparison_scope': 'PAPER_RESEARCH_ONLY', 'execution_verified': False,
            'source_url': meta.get('referer'), 'provider_capture_note':
                'Fallback current-board capture; use only when 7M has no target quote.',
        })
    return out


def collect_betmonitor_japan_b(fetch, events, day, observed_at=None):
    """Use Betmonitor as a bounded fallback when 7M has no Japan B quote.

    Betmonitor is a current odds comparison page, not a historical odds page.
    The adapter only accepts a page whose event date, ordered teams and main
    full-game line are all visible in the same capture.  It never carries a
    prior quote forward and it leaves unmatched events as NO_MARKET.
    """
    observed_at = observed_at or stamp(now())
    targets = [e for e in events or [] if is_japan_b_league_event(e)]
    audit = {'source': 'BETMONITOR', 'league_url': BETMONITOR_JAPAN_LEAGUE_URL,
             'target_events': len(targets), 'event_pages': 0, 'market_pages': 0,
             'quotes_added': 0, 'matched_event_ids': [], 'unmatched_event_ids': [],
             'errors': []}
    if not targets:
        audit['status'] = 'NO_TARGET_EVENTS'; return [], audit
    try:
        league_meta = fetch.one(('betmonitor_japan_b_league', BETMONITOR_JAPAN_LEAGUE_URL))
        fetch.rows.append(league_meta)
        if not league_meta.get('ok'):
            audit['status'] = 'SOURCE_UNAVAILABLE'; audit['errors'].append(league_meta); return [], audit
        league_html = text_of(league_meta); links = _betmonitor_event_links(league_html)
    except Exception as exc:
        audit['status'] = 'SOURCE_UNAVAILABLE'; audit['errors'].append({'error': str(exc)}); return [], audit
    pages = fetch.batch({f'betmonitor_event_{rid}': url for rid, url in links})
    parsed_pages = []
    for key, meta in pages.items():
        if not meta.get('ok'): continue
        rid = key.rsplit('_', 1)[-1]
        parsed = _betmonitor_event_page(text_of(meta), rid, meta.get('url'), day)
        if parsed: parsed_pages.append(parsed)
    audit['event_pages'] = len(parsed_pages)
    quotes = []; matched = set()
    for page in parsed_pages:
        source_pair = (canonical_team_token(BETMONITOR_TEAM_ALIASES.get(page['team1_name'], page['team1_name'])),
                       canonical_team_token(BETMONITOR_TEAM_ALIASES.get(page['team2_name'], page['team2_name'])))
        try: page_tip = datetime.fromisoformat(page['tip_at'])
        except ValueError: continue
        candidates = []
        for event in targets:
            # The 7M display label can be mojibake even when its canonical IDs
            # are valid.  Match Betmonitor's reviewed alias resolution to the
            # already-attached registry IDs, never to the raw display string.
            attach_canonical_team_ids(event)
            event_pair = (str(event.get('canonical_team1_id') or ''),
                          str(event.get('canonical_team2_id') or ''))
            try: delta = abs((datetime.fromisoformat(str(event.get('tip_at')).replace('Z', '+00:00')) - page_tip).total_seconds())
            except (TypeError, ValueError): delta = 10**9
            if source_pair == event_pair and delta <= 300:
                candidates.append(event)
        if len(candidates) != 1: continue
        event = candidates[0]; matched.add(str(event.get('event_id')))
        for market in ('mahc', 'ou'):
            line = page['lines'].get(market)
            if line is None: continue
            try:
                body, post_meta = _betmonitor_post(fetch, page['rid'], market, line, page['url'], observed_at)
                audit['market_pages'] += 1
                rows = _betmonitor_quotes_fragment(body, event, market, line, post_meta, observed_at)
                quotes.extend(rows)
            except Exception as exc:
                audit['errors'].append({'rid': page['rid'], 'market': market, 'url': page['url'],
                                        'error_type': type(exc).__name__, 'error': str(exc)})
    audit['matched_event_ids'] = sorted(matched)
    audit['unmatched_event_ids'] = sorted(str(e.get('event_id')) for e in targets if str(e.get('event_id')) not in matched)
    audit['quotes_added'] = len(quotes)
    audit['status'] = 'OBSERVED' if quotes else 'NO_CURRENT_BOARD_QUOTE'
    return quotes, audit


def _cloudbet_visible(fragment):
    """Return text from Cloudbet's SSR accessibility block without JS execution."""
    value = re.sub(r'<!--.*?-->', '', str(fragment or ''), flags=re.S)
    value = unescape(re.sub(r'<[^>]+>', ' ', value))
    return re.sub(r'\s+', ' ', value).strip()


def _cloudbet_event_links(html):
    pattern = re.compile(
        r'href=["\'](/en/sports/basketball/south-korea-kbl/(\d+))["\']', re.I)
    seen = set(); out = []
    for match in pattern.finditer(html or ''):
        href, event_id = match.groups()
        if event_id in seen:
            continue
        seen.add(event_id)
        out.append((event_id, urljoin(CLOUDBET_KBL_URL, href)))
    return out


def _cloudbet_fetch(fetch, key, url):
    """Cloudbet's CDN rejects curl_cffi's browser fingerprint; use normal HTTP.

    This remains inside the shared bounded retry contract and writes the same
    immutable raw response/health row as the other adapters.
    """
    started = stamp()
    def operation():
        headers={'User-Agent': 'Mozilla/5.0 basketball-odds-trader/1.0',
                 'Accept': 'text/html,application/xhtml+xml,*/*',
                 'Referer': 'https://www.cloudbet.com/en/sports/basketball'}
        if std_requests is not None:
            response = std_requests.get(url, headers=headers, timeout=fetch.timeout, allow_redirects=True)
            if response.status_code != 200:
                raise urllib.error.HTTPError(url, response.status_code, 'HTTP ' + str(response.status_code), response.headers, None)
            return {'blob': response.content, 'http_status': response.status_code}
        # GitHub Actions installs curl-cffi but not the standalone requests
        # distribution.  Keep the fallback dependency-free so a missing
        # optional package cannot turn a known KBL board into NO_MARKET.
        request=urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(request, timeout=fetch.timeout) as response:
            blob=response.read(8_000_001)
            status=int(getattr(response, 'status', 200))
            if status != 200:
                raise urllib.error.HTTPError(url, status, 'HTTP ' + str(status), response.headers, None)
            return {'blob': blob, 'http_status': status}
    try:
        result, attempts = request_with_retry(
            operation, url=url, policy=fetch.retry_policy,
            validate=lambda item: bool(item.get('blob')) and len(item['blob']) <= 8_000_000,
            status_of=lambda item: item.get('http_status'), sleeper=fetch.sleeper)
        blob = result['blob']; path = fetch.directory / (safe_id(key) + '.raw'); path.write_bytes(blob)
        meta = {'key': key, 'url': url, 'started_at': started, 'ok': True,
                'path': str(path), 'sha256': sha(blob), 'bytes': len(blob),
                'http_status': result.get('http_status'), 'attempts': attempts,
                'attempt_count': len(attempts), 'received_at': stamp(),
                'source': 'cloudbet_kbl', 'source_group': 'odds_board'}
    except Exception as exc:
        meta = {'key': key, 'url': url, 'started_at': started, 'ok': False,
                'error_type': type(exc).__name__, 'error': str(exc),
                'attempts': getattr(exc, 'retry_attempts', []),
                'attempt_count': len(getattr(exc, 'retry_attempts', [])),
                'received_at': stamp(), 'source': 'cloudbet_kbl', 'source_group': 'odds_board'}
    fetch.rows.append(meta)
    return meta


def _cloudbet_event_page(html, event_id, url, day, observed_at):
    """Parse one Cloudbet KBL SSR page into the two full-game main lines.

    The page exposes a server-rendered accessibility block.  We deliberately
    take only its first Handicap pair and first Total Points pair; alternate
    lines remain in the immutable HTML but are not silently treated as the
    main line.  The source is experimental until three successful target-day
    runs are audited.
    """
    start_match = re.search(r'"startTime":"([^"\\]+)"', html or '', re.I)
    if not start_match:
        start_match = re.search(r'"cutoffTime":"([^"\\]+)"', html or '', re.I)
    if not start_match:
        return None
    try:
        tip = datetime.fromisoformat(start_match.group(1).replace('Z', '+00:00'))
    except ValueError:
        return None
    if tip.astimezone(BJ).date().isoformat() != day:
        return None
    name_match = re.search(r'<h2>([^<]+\s+v\s+[^<]+)</h2>', html or '', re.I)
    if not name_match:
        name_match = re.search(r'"name":"([^"\\]+\s+v\s+[^"\\]+)"', html or '', re.I)
    if not name_match:
        return None
    pair = [part.strip() for part in re.split(r'\s+v\s+', unescape(name_match.group(1)), maxsplit=1)]
    if len(pair) != 2:
        return None
    handicap_block = re.search(r'<h2>Handicap</h2>(.*?)(?=<h2>Total Points</h2>)', html or '', re.I | re.S)
    total_block = re.search(r'<h2>Total Points</h2>(.*?)(?=<h2>Winning Margin</h2>|</section>)', html or '', re.I | re.S)
    handicap_text = _cloudbet_visible(handicap_block.group(1) if handicap_block else '')
    total_text = _cloudbet_visible(total_block.group(1) if total_block else '')
    spread = re.search(
        r'Home\s+([+-]?\d+(?:\.\d+)?)\s*:\s*([0-9]+(?:\.\d+)?)\s+'
        r'Away\s+([+-]?\d+(?:\.\d+)?)\s*:\s*([0-9]+(?:\.\d+)?)', handicap_text, re.I)
    total = re.search(
        r'Over\s+([+-]?\d+(?:\.\d+)?)\s*:\s*([0-9]+(?:\.\d+)?)\s+'
        r'Under\s+([+-]?\d+(?:\.\d+)?)\s*:\s*([0-9]+(?:\.\d+)?)', total_text, re.I)
    return {'event_id': str(event_id), 'url': url, 'tip_at': tip.isoformat(),
            'team1_name': pair[0], 'team2_name': pair[1],
            'spread': (float(spread.group(1)), float(spread.group(2)), float(spread.group(4))) if spread else None,
            'total': (float(total.group(1)), float(total.group(2)), float(total.group(4))) if total else None,
            'last_modified': re.search(r'"lastModified":"?(\d+)', html or '', re.I).group(1)
            if re.search(r'"lastModified":"?(\d+)', html or '', re.I) else None}


def _cloudbet_quote(event, page, market_type, line, prices, meta, observed_at):
    quote_id = sha((str(event.get('event_id')) + 'CLOUDBET' + market_type + str(line) + str(meta.get('sha256'))).encode())[:24]
    return {
        'quote_id': quote_id, 'event_id': event.get('event_id'),
        'canonical_event_id': event.get('canonical_event_id') or event.get('event_id'),
        'source_event_id': event.get('source_event_id'), 'feed_provider': 'CLOUDBET',
        'upstream_provider': 'cloudbet', 'bookmaker_id': 'cloudbet', 'bookmaker': 'Cloudbet',
        'market_type': market_type, 'raw_market_key': 'CLOUDBET_HANDICAP' if market_type == 'SPREAD' else 'CLOUDBET_TOTAL',
        'parse_status': 'PARSED_AND_NORMALIZED', 'period': 'FULL_GAME',
        'market_role': 'MAIN', 'main_or_alt': 'MAIN', 'source_main_flag': '1',
        'source_market_key': str(line), 'raw_line': float(line) if market_type == 'TOTAL' else abs(float(line)),
        'line_team1': float(line) if market_type == 'SPREAD' else None,
        'direction_verified': True, 'raw_prices': list(prices), 'decimal_prices': list(prices),
        'price_format': 'DECIMAL', 'price_format_verified': True,
        'source_quote_at': observed_at, 'source_timestamp_raw': observed_at,
        'source_timestamp_semantics': 'CURRENT_BOARD_CAPTURE_ONLY',
        'received_at': observed_at, 'observed_at': observed_at,
        'raw_path': meta.get('path'), 'raw_sha256': meta.get('sha256'),
        'raw_verified': True, 'raw_integrity_verified': True, 'status': 'OPEN',
        'current_board_contract_verified': True, 'last_verified_at': observed_at,
        'quote_verified_for_paper': True, 'identity_verified': True,
        'ot_rule': 'INCLUDING_OT', 'rule_evidence': 'CLOUDBET_FULL_GAME_MARKET_PAGE_CAPTURE',
        'ot_contract_status': 'SOURCE_CONFIRMED_INCLUDING_OT',
        'comparison_scope': 'EXPERIMENTAL_CURRENT_BOARD', 'execution_verified': False,
        'source_url': page.get('url'), 'provider_capture_note':
            'Cloudbet KBL current-board fallback; production verification pending three target-day runs.',
    }


def collect_cloudbet_kbl(fetch, events, day, observed_at=None):
    """Recover KBL current spread/total lines when 7M and Titan are empty."""
    observed_at = observed_at or stamp(now())
    targets = [e for e in events or [] if is_korea_kbl_event(e)]
    audit = {'source': 'CLOUDBET', 'league_url': CLOUDBET_KBL_URL, 'target_events': len(targets),
             'event_pages': 0, 'quotes_added': 0, 'matched_event_ids': [], 'unmatched_event_ids': [],
             'status': 'NO_TARGET_EVENTS', 'production_status': 'EXPERIMENTAL', 'errors': []}
    if not targets:
        return [], audit
    try:
        league_meta = _cloudbet_fetch(fetch, 'cloudbet_kbl_league', CLOUDBET_KBL_URL)
        if not league_meta.get('ok'):
            audit['status'] = 'SOURCE_UNAVAILABLE'; audit['errors'].append(league_meta); return [], audit
        links = _cloudbet_event_links(text_of(league_meta))
    except Exception as exc:
        audit['status'] = 'SOURCE_UNAVAILABLE'; audit['errors'].append({'error': str(exc)}); return [], audit
    pages = {rid: _cloudbet_fetch(fetch, f'cloudbet_kbl_event_{rid}', url) for rid, url in links}
    parsed_pages = []
    for key, meta in pages.items():
        if not meta.get('ok'):
            continue
        rid = key
        parsed = _cloudbet_event_page(text_of(meta), rid, meta.get('url'), day, observed_at)
        if parsed:
            parsed['meta'] = meta
            parsed_pages.append(parsed)
    audit['event_pages'] = len(parsed_pages)
    quotes = []; matched = set()
    for page in parsed_pages:
        def team_id(value):
            mapped = CLOUDBET_KBL_TEAM_ALIASES.get(value, value)
            return canonical_team_token(mapped)
        def event_team_id(event, side):
            cid = str(event.get('canonical_' + side + '_id') or '')
            # A legacy 7M row may carry an explicit normalized-label ID rather
            # than a registry ID.  Compare its normalized label token to the
            # reviewed Cloudbet alias in that case.
            if cid.startswith('basketball:label:'):
                return cid.split(':', 2)[-1]
            return cid or canonical_team_token(event.get(side + '_name'))
        source_pair = (team_id(page['team1_name']), team_id(page['team2_name']))
        try:
            page_tip = datetime.fromisoformat(page['tip_at'].replace('Z', '+00:00'))
        except ValueError:
            continue
        candidates = []
        for event in targets:
            attach_canonical_team_ids(event)
            event_pair = (event_team_id(event, 'team1'), event_team_id(event, 'team2'))
            try:
                delta = abs((datetime.fromisoformat(str(event.get('tip_at')).replace('Z', '+00:00')) - page_tip).total_seconds())
            except (TypeError, ValueError):
                delta = 10**9
            if source_pair == event_pair and delta <= 300:
                candidates.append(event)
        if len(candidates) != 1:
            continue
        event = candidates[0]; matched.add(str(event.get('event_id')))
        meta = page['meta']
        if page.get('spread'):
            line, home_price, away_price = page['spread']
            quotes.append(_cloudbet_quote(event, page, 'SPREAD', line, (home_price, away_price), meta, observed_at))
        if page.get('total'):
            line, over_price, under_price = page['total']
            quotes.append(_cloudbet_quote(event, page, 'TOTAL', line, (over_price, under_price), meta, observed_at))
    audit['matched_event_ids'] = sorted(matched)
    audit['unmatched_event_ids'] = sorted(str(e.get('event_id')) for e in targets if str(e.get('event_id')) not in matched)
    audit['quotes_added'] = len(quotes)
    audit['status'] = 'OBSERVED' if quotes else 'NO_CURRENT_BOARD_QUOTE'
    return quotes, audit

def collect_live(output_root,day,contracts,timeout=12,workers=6):
    run_started_perf=time.perf_counter();stage_timings={}
    root=Path(output_root); sid=now().strftime('%Y%m%dT%H%M%S')+'_'+uuid.uuid4().hex[:10]
    session=root/'raw'/'repair_v22'/sid;fetch=Fetcher(session,timeout,workers)
    first=fetch.batch({'page':'https://basket.7m.com.cn/free_gb.aspx','today':'https://js-basket.7m.com.cn/datafile/today.js'})
    # Titan007's visible NBA board is a separate production-readable source.
    # Its XML endpoints require the same numeric cache-buster used by the page.
    titan_tick=str(int(now().timestamp()*1000))
    titan_urls={'titan_schedule':f'https://lq3.titan007.com/NBA/today2.xml?t={titan_tick}'}
    for company_id in ('1','2','3','8','9'):
        titan_urls[f'titan_odds_{company_id}']=f'https://lq3.titan007.com/NBA/nbaGoal{company_id}.xml?t={titan_tick}'
    titan_res=fetch.batch(titan_urls)
    d=date.fromisoformat(day);urls={}
    for n in (-1,0,1):
        bucket=(d+timedelta(days=n)).strftime('%Y%m%d')
        for variant in ('S2_fgb1','fgb1'):urls[f'event_{bucket}_{variant}']=f'https://bdata.7m.com.cn/datafile/{bucket}/{variant}.js'
    for sel,(name,ns) in COMPANIES.items():urls['odds_company_'+sel]=f'https://js-basket.7m.com.cn/odds/comlive_{ns}.js'
    responses=fetch.batch(urls);events={};quotes=[];errors=[];settlement_facts={}
    titan_events=[]
    for key,r in titan_res.items():
        if not r.get('ok'):
            continue
        try:
            if key=='titan_schedule':
                parsed,err=parse_titan_schedule_xml(text_of(r),day,r.get('path'),r.get('received_at'))
                for event in parsed:
                    minutes, minutes_source = game_minutes_for(event.get('league'))
                    event['game_minutes'] = minutes
                    event['game_minutes_source'] = minutes_source
                    event['game_minutes_used_in_pricing'] = False
                titan_events.extend(parsed);errors+=err
            elif key.startswith('titan_odds_'):
                parsed,err=parse_titan_odds_xml(text_of(r),key.rsplit('_',1)[1],r.get('path'),r.get('received_at'))
                quotes.extend(parsed);errors+=err
        except Exception as exc:
            errors.append({'source':'titan007_nba','key':key,'path':r.get('path'),'error':type(exc).__name__+': '+str(exc)})
    # Keep the 7M identity when both sources expose the same source event, but
    # retain Titan's row and URL as an additional audited discovery source.
    for event in titan_events:
        old=events.get(event['event_id'])
        if old:
            old.setdefault('discovery_sources',[]).append({'source':'TITAN007','source_url':event.get('source_url'),'source_event_id':event.get('source_event_id')})
            old['titan007_event']=event
        else:
            events[event['event_id']]=event
    for meta in fetch.rows:
        if str(meta.get('key','')).startswith('titan_'):
            meta['source']='titan007_nba';meta['source_group']='odds_board_and_schedule'
    for key,r in responses.items():
        if not r['ok']:continue
        try:
            if key.startswith('event_'):
                body=text_of(r)
                evs,err=parse_schedule(body,r['path'],r['received_at']);events.update({e['event_id']:e for e in evs});errors+=err
                finals,final_errors=parse_event_results(body,r['path'],r['received_at'])
                settlement_facts.update({e['event_id']:e for e in finals});errors+=final_errors
            elif key.startswith('odds_company_'):
                qs,err=parse_odds(text_of(r),r['path'],r['received_at'],key.rsplit('_',1)[1],contracts);quotes+=qs;errors+=err
        except Exception as e:errors.append({'path':r['path'],'error':type(e).__name__+': '+str(e)})
    # The 7M current-board file rolls to the next date shortly after
    # midnight Beijing time.  A published evening inventory is therefore the
    # only durable pointer to same-day fixtures during the morning refresh.
    # Seed those source identities before the deep-capture decision so their
    # detail pages and team-history feeds are fetched in this run as well.
    # This carries forward events only; it never carries forward quotes.
    baseline_path = root / 'dashboard_v2' / 'data' / (day + '.json')
    baseline_document = load(baseline_path, {})
    baseline_events = []
    if isinstance(baseline_document, dict):
        for item in baseline_document.get('events', []):
            event = item.get('event') if isinstance(item, dict) and isinstance(item.get('event'), dict) else item
            if not isinstance(event, dict) or event.get('bj_date') != day or not event.get('event_id'):
                continue
            # Only 7M identities are safe to replay through the 7M detail and
            # history endpoints.  Titan rows are handled by their own board.
            if str(event.get('source') or '').upper() == '7M' or str(event.get('event_id')).startswith('7m:'):
                baseline_events.append(dict(event))
    baseline_seeded = 0
    for event in baseline_events:
        event_id = str(event.get('event_id'))
        if event_id not in events:
            events[event_id] = event
            baseline_seeded += 1
    # Japan B.League boards are often published after the schedule file.  Do
    # a target-aware bounded retry after baseline seeding, so a date-rollover
    # inventory row is eligible for the same current-board check.  A valid
    # empty board is not treated as an HTTP success for this continuity check.
    japan_retry_quotes,japan_retry_audit=retry_japan_b_league_boards(
        fetch, list(events.values()), quotes, contracts, observed_at=now(), max_rounds=2)
    if japan_retry_quotes:
        retry_ids={str(q.get('event_id')) for q in japan_retry_quotes}
        quotes=[q for q in quotes if not (q.get('feed_provider')=='7M' and str(q.get('event_id')) in retry_ids)]
        quotes.extend(japan_retry_quotes)
    # 7M can return a valid board while omitting the current Japan B.League
    # rows.  Use a current Betmonitor comparison page only for those still
    # unmatched events; never replace a verified 7M quote or use history odds.
    betmonitor_quotes, betmonitor_audit = collect_betmonitor_japan_b(
        fetch, list(events.values()), day, observed_at=stamp(now()))
    if betmonitor_quotes:
        existing_7m_markets={(str(q.get('event_id')), str(q.get('market_type')))
                             for q in quotes if q.get('feed_provider')=='7M'}
        quotes.extend(q for q in betmonitor_quotes
                      if (str(q.get('event_id')), str(q.get('market_type'))) not in existing_7m_markets)
    else:
        fallback_event_ids=set()
    # KBL is not covered by the Japan-only Betmonitor page.  The fallback is
    # deliberately deferred until after global discovery below: KBL fixtures
    # can be absent from the compact 7M schedule and only appear in the
    # broad/global event inventory.  Calling the fallback before that merge
    # made a real KBL fixture look like NO_MARKET even when Cloudbet had a
    # current board.
    cloudbet_audit = {'source': 'CLOUDBET', 'status': 'DEFERRED_UNTIL_GLOBAL_MERGE',
                      'target_events': 0, 'event_pages': 0, 'quotes_added': 0,
                      'matched_event_ids': [], 'unmatched_event_ids': [],
                      'production_status': 'EXPERIMENTAL', 'errors': []}
    # Market first: only quote-backed 7M events need identity/history and
    # technical enrichment for pricing.  Keep every no-market event in the
    # event inventory, but do not spend hundreds of requests enriching rows
    # that the evidence gate can never price.  This preserves coverage and
    # exact NO_MARKET outcomes while avoiding an unnecessary deep crawl.
    opening_market_event_ids={str(q.get('event_id')) for q in quotes if q.get('event_id')}
    # Only 7M source IDs belong in the 7M detail/history queue.  ESPN
    # current-board quotes use ESPN event IDs; sending those IDs to
    # bdata.7m.com.cn creates repeated 404/retry traffic and was the main
    # reason NBA runs became unnecessarily long.
    opening_market_source_ids={str(q.get('source_event_id')) for q in quotes
                               if q.get('source_event_id') and q.get('feed_provider')=='7M'}
    # Prepare both today's and next day's still-upcoming 7M fixtures.  NBA and
    # WNBA morning boards commonly publish after the schedule does; gathering
    # the next-day identity/history now avoids a missing-history race when a
    # fresh board quote appears.  It remains a NO_MARKET row until an actual
    # current quote passes the ordinary freshness and evidence gates.
    today_upcoming_7m=upcoming_7m_deep_capture_event_ids(list(events.values()),day,now())
    deep_events=[e for e in events.values()
                 if (str(e.get('source') or '').upper()=='7M' and
                     e.get('event_id') in opening_market_event_ids) or
                    e.get('event_id') in today_upcoming_7m or
                    (str(e.get('source_event_id')) in opening_market_source_ids and str(e.get('source')).upper()!='TITAN007')]
    ids=sorted({e['source_event_id'] for e in deep_events if e.get('source_event_id') and str(e.get('source')).upper()!='TITAN007'})
    deep_capture_event_ids={str(e.get('event_id')) for e in deep_events if e.get('event_id')}
    deep_capture_audit={'discovered_events_before_deep_capture':len(events),
                        'published_baseline_events_seeded':baseline_seeded,
                        'published_baseline_file':str(baseline_path) if baseline_seeded else None,
                        'opening_market_backed_events':len(deep_events),
                        'today_and_next_day_upcoming_7m_late_market_candidates':len(today_upcoming_7m),
                        'lookahead_bj_dates':[day,(date.fromisoformat(day)+timedelta(days=1)).isoformat()],
                        'no_market_events_retained_without_deep_capture':max(0,len(events)-len(deep_events)),
                        'detail_identity_ids_attempted':len(ids),
                        'rule':'deep identity/history/statistics capture is market-first; no-market rows remain auditable in the event inventory',
                        'japan_b_league_market_retry':japan_retry_audit,
                        'betmonitor_japan_b_league_fallback':betmonitor_audit,
                        'cloudbet_kbl_fallback':cloudbet_audit}
    detail=fetch.batch({f'detail_{i}':f'https://bdata.7m.com.cn/analyse/gb/{i}.shtml' for i in ids})
    id_urls={};htmls={}
    for k,r in detail.items():
        if not r['ok']:continue
        i=k.split('_')[1];html=text_of(r);htmls[i]=html
        # Identity script must be linked in the page itself.
        match=re.search(r'''<script[^>]+src=["'](js/\d+/'''+re.escape(i)+r'''\.js)["']''',html,re.I)
        if match:id_urls['identity_'+i]=urljoin(r['url'],match.group(1))
    identities=fetch.batch(id_urls);history={};team_urls={};identity_rows=[];total_urls={};total_context={};bottom_source_audit=[]
    for k,r in identities.items():
        if not r['ok']:continue
        i=k.split('_')[1]
        try:
            html=htmls[i];tv='GMT+0800' in html or 'GMT+08:00' in html
            e=parse_identity(text_of(r),i,r['path'],r['received_at'],tv)
            old=events.get(e['event_id'])
            if old and (old['team1_id'],old['team2_id'],old['tip_at'])!=(e['team1_id'],e['team2_id'],e['tip_at']):
                e['identity_verified']=False;e['identity_conflict']={'schedule':old,'detail':e.copy()}
            events[e['event_id']]=e;identity_rows.append(e)
            hs,err=parse_history(text_of(r),r['path'],r['received_at'],r['url'],'H2H');history.update({g['event_id']:g for g in hs});errors+=err
            if source_time(e['tip_at'])>now():
                team_urls.update(discover_links(html,e))
                for name in ('avgpoint','pointstat','totalstat','bqcstat','standings','stats'):
                    total_urls['total_'+i+'_'+name]=f'https://bdata-js.7m.com.cn/analyse/{i}/{name}.js'
                # 7M exposes a separate game-data feed for some live/final
                # fixtures.  It is an optional raw-source probe: the parser
                # never treats a missing/opaque response as pace evidence,
                # and the Titan technical box-score bridge remains the only
                # path that can produce verified FGA/FTA/ORB/TOV possessions.
                family = str(e.get('league_family') or e.get('competition_key') or '').upper()
                if any(token in family for token in ('NBL', 'NCAAB', 'WNCAAB', 'NCAA')):
                    total_urls['game_'+i]=f'https://lq.7m.com.cn/data/game/{i}.js'
        except Exception as exc:errors.append({'id':i,'error':str(exc)})
    hist_res=fetch.batch({'history_'+tid:u for tid,u in team_urls.items()}); history_page_audit=[]
    for k,r in hist_res.items():
        tid=k.split('_',1)[1]
        if not r['ok']:
            history_page_audit.append({'team_source_id':tid,'url':r['url'],'http_success':False,'parsed_games':0,'errors':[r.get('error_type') or 'FETCH_FAILED']})
            continue
        try:
            hs,err=parse_history(text_of(r),r['path'],r['received_at'],r['url'],'TEAM_HISTORY');history.update({g['event_id']:g for g in hs});errors+=err
            history_page_audit.append({'team_source_id':tid,'url':r['url'],'path':r['path'],'http_success':True,'parsed_games':len(hs),'errors':err})
        except Exception as e:
            errors.append({'path':r['path'],'error':str(e)});history_page_audit.append({'team_source_id':tid,'url':r['url'],'path':r['path'],'http_success':True,'parsed_games':0,'errors':[str(e)]})
    # Keep an explicit per-event bottom-source audit for the formal NCAA/NBL
    # pools.  The rows from n_history.js are valid score/period facts; they do
    # not become possession evidence until Titan technical FGA/FTA/ORB/TOV
    # rows are successfully bridged later in this run.
    for event in events.values():
        family = str(event.get('league_family') or event.get('competition_key') or '').upper()
        if not any(token in family for token in ('NBL', 'NCAAB', 'WNCAAB', 'NCAA')):
            continue
        team_ids = {str(event.get('team1_source_id') or ''), str(event.get('team2_source_id') or '')}
        pages = [row for row in history_page_audit if str(row.get('team_source_id') or '') in team_ids]
        bottom_source_audit.append({
            'event_id':event.get('event_id'),
            'league_family':family,
            'source':'7M_TEAM_HISTORY',
            'team_history_pages_attempted':len(pages),
            'team_history_pages_successful':sum(bool(row.get('http_success')) for row in pages),
            'parsed_games':sum(int(row.get('parsed_games') or 0) for row in pages),
            'urls':[row.get('url') for row in pages],
            'status':'CAPTURED_SCORE_PERIODS' if any(row.get('parsed_games') for row in pages) else 'NOT_CAPTURED',
            'pace_status':'WAITING_FOR_VERIFIED_TITAN_TECH_BOX_SCORE',
        })
    total_res=fetch.batch(total_urls)
    for key,r in total_res.items():
        if key.startswith('game_'):
            bottom_source_audit.append({
                'event_id':'7m:'+key.split('_',1)[1],
                'source':'7M_GAME_DATA',
                'url':r.get('url'),
                'http_success':bool(r.get('ok')),
                'status_code':r.get('status_code'),
                'raw_path':r.get('path'),
                'error_type':r.get('error_type'),
                'note':'raw probe only; no possession fields are inferred from an opaque or missing response',
            })
            continue
        if not r.get('ok'):continue
        event_id='7m:'+key.split('_')[1]
        context=total_context.setdefault(event_id, {'source_urls':[],'raw_paths':[],'variables':{},
                                                    'possessions_verified':False,'basic_offense_verified':False,'three_point_verified':False,
                                                    'late_foul_verified':False,'rotation_verified':False})
        parsed=parse_total_context(text_of(r),r['path'],r['received_at'],r['url'])
        context['source_urls'].append(parsed['source_url']);context['raw_paths'].append(parsed['raw_path'])
        context['variables'].update(parsed['source_aggregates'])
        context['available_variables']=sorted(set(context.get('available_variables',[]))|set(parsed['available_variables']))
        for flag in ('possessions_verified','basic_offense_verified','three_point_verified','late_foul_verified','rotation_verified'):
            context[flag]=bool(context.get(flag) or parsed.get(flag))
        if parsed.get('basic_offense_profile'):context['basic_offense_profile']=parsed['basic_offense_profile']
        if parsed.get('three_point_profile'):context['three_point_profile']=parsed['three_point_profile']
        context['schema_note']=parsed['schema_note']
    global_result=discover_global(day,root,timeout,workers)
    stage_timings['market_identity_global_collection_seconds']=round(time.perf_counter()-run_started_perf,3)
    # Histories and per-event context can take materially longer than the
    # current-board freshness window.  Refresh only the current odds boards at
    # the end of collection, preserving both raw captures in the source-health
    # ledger.  A successful provider refresh replaces its normalized opening
    # snapshot; a failed refresh leaves the earlier snapshot intact and is
    # visible in source health.  No timestamp is invented.
    refresh_tick=str(int(now().timestamp()*1000))
    refresh_urls={f'closing_titan_odds_{company_id}':f'https://lq3.titan007.com/NBA/nbaGoal{company_id}.xml?t={refresh_tick}'
                  for company_id in ('1','2','3','8','9')}
    for sel,(name,ns) in COMPANIES.items():
        refresh_urls[f'closing_7m_odds_{sel}']=f'https://js-basket.7m.com.cn/odds/comlive_{ns}.js?t={refresh_tick}'
    refresh_res=fetch.batch(refresh_urls);titan_refresh=[];sevenm_refresh=[];refresh_errors=[]
    for key,r in refresh_res.items():
        if not r.get('ok'):continue
        try:
            if key.startswith('closing_titan_odds_'):
                parsed,err=parse_titan_odds_xml(text_of(r),key.rsplit('_',1)[1],r.get('path'),r.get('received_at'))
                titan_refresh+=parsed;refresh_errors+=err
            elif key.startswith('closing_7m_odds_'):
                parsed,err=parse_odds(text_of(r),r.get('path'),r.get('received_at'),key.rsplit('_',1)[1],contracts)
                sevenm_refresh+=parsed;refresh_errors+=err
        except Exception as exc:
            refresh_errors.append({'key':key,'path':r.get('path'),'error':type(exc).__name__+': '+str(exc)})
    if titan_refresh:
        quotes=[q for q in quotes if q.get('feed_provider')!='TITAN007']+titan_refresh
    if sevenm_refresh:
        quotes=[q for q in quotes if q.get('feed_provider')!='7M']+sevenm_refresh
    errors+=refresh_errors
    market_refresh_audit={
        'attempted_at':stamp(now()),'end_of_collection_refresh':True,
        'titan_quotes_parsed':len(titan_refresh),'sevenm_quotes_parsed':len(sevenm_refresh),
        'titan_replaced_opening_snapshot':bool(titan_refresh),
        'sevenm_replaced_opening_snapshot':bool(sevenm_refresh),
        'errors':refresh_errors,
    }
    # ESPN is schedule-only unless its public response contains a complete
    # spread/total contract.  The global adapter records those explicit
    # current-board quotes separately; merge them now so NBA/WNBA events do
    # not remain NO_MARKET merely because Titan/7M publish on a different
    # clock.  No quote is synthesized when the response lacks both sides.
    global_quotes = list(global_result.get('market_quotes') or [])
    quotes.extend(global_quotes)
    merged_events=merge_with_primary(list(events.values()),global_result.get('events',[]),quotes)
    # KBL current-board fallback must see the fully merged event inventory.
    # Match remains exact on canonical team pair and the +/-5 minute
    # continuity key; the fallback never replaces a verified 7M/Titan quote.
    cloudbet_quotes, cloudbet_audit = collect_cloudbet_kbl(
        fetch, merged_events, day, observed_at=stamp(now()))
    # The audit dictionary is initialized before the global merge so that the
    # early market-first diagnostics remain present; replace its deferred
    # placeholder with the actual post-merge fallback result now.
    deep_capture_audit['cloudbet_kbl_fallback'] = cloudbet_audit
    if cloudbet_quotes:
        existing_market_keys={(str(q.get('event_id')), str(q.get('market_type')))
                              for q in quotes}
        quotes.extend(q for q in cloudbet_quotes
                      if (str(q.get('event_id')), str(q.get('market_type'))) not in existing_market_keys)
    # Reconcile only after detail identities and global discovery have both
    # landed.  Some 7M fixtures (notably NBL/EuroLeague) are absent from the
    # compact schedule JS and become identifiable only through the quote/detail
    # or global-discovery paths.  Reconciling earlier left valid Titan rows as
    # duplicate events even though team pair and tip time agreed exactly.
    merged_event_map={event['event_id']:event for event in merged_events}
    titan_reconciliation=reconcile_titan_events(merged_event_map,titan_events,quotes)
    merged_events=list(merged_event_map.values())
    # NBA/WNBA schedule and odds can be present on ESPN before Titan/7M
    # exposes the corresponding team page.  Preload the same target teams'
    # completed ESPN box scores into the immutable history pool so a provider
    # ID gap cannot be reported as a false "history insufficient" state.  This
    # bridge is source-audited and still obeys the formal 8 games / 3 opponent
    # gate; it does not lower the gate or use market fields in pricing.
    espn_history_rows, espn_contexts, espn_history_audit, espn_history_health = collect_espn_history(
        merged_events, root, cutoff=now(), workers=workers, max_games_per_team=10)
    history.update({row.get('event_id'): row for row in espn_history_rows if row.get('event_id')})
    for event_id, context in espn_contexts.items():
        existing = total_context.setdefault(event_id, {})
        existing.update(context)
    errors.extend(espn_history_audit.get('errors') or [])
    # Apply the shared league-family classifier to legacy 7M events as well as
    # newly discovered events, so coverage is comparable across all sources.
    for event in merged_events:
        family, region = classify_global(
            event.get('league') or event.get('competition') or '',
            event.get('competition_key') or event.get('raw_event_name') or '',
        )
        event['league_family'] = event.get('league_family') or family
        event['region'] = event.get('region') or region
    # Maintain the local Titan reference database on every live run.  Facts
    # enter model history only after source validation, cutoff checks and
    # cross-provider mirror de-duplication; failures are audited and do not
    # erase the already captured 7M history.
    titan_history_audit={"status":"NOT_ATTEMPTED"};titan_history_health=[];foundation_contexts={}
    unified_evidence_audit=[]
    history_rows=list(history.values())
    history_prepare_started=time.perf_counter()
    prior_capture_history, prior_capture_history_audit = load_prior_capture_history(
        root, merged_events, now(), current_session=session, max_capture_days=3)
    history_rows, prior_capture_merge_audit = merge_prior_capture_history(
        history_rows, prior_capture_history)
    # A Titan-led target can otherwise strand valid 7M team-history facts
    # behind a different provider ID namespace.  Bridge exact names before
    # resolving reused 7M IDs or entering the pricing/history evidence layer.
    cross_source_history_bridge_audit=bridge_cross_source_team_history_ids(
        history_rows, merged_events)
    # Resolve source-id reuse only after the full schedule, detail histories,
    # and global discovery are assembled.  Earlier resolution would miss a
    # collision disclosed by a team-history page and can still join two teams.
    identity_collision_audit=resolve_reused_7m_team_ids(merged_events,history_rows)
    pre_bridge_history=list(history_rows)
    stage_timings['prior_capture_and_identity_bridge_seconds']=round(time.perf_counter()-history_prepare_started,3)
    try:
        ref_root=root/'reference_data'/'titan007_history'
        year=now().astimezone(BJ).year
        market_event_ids={str(q.get('event_id')) for q in quotes if q.get('event_id')}
        # NBA/WNBA history must be warmed even when a board is published on a
        # different clock.  A missing current quote is a market state, not a
        # reason to skip the team's completed box-score/history bridge.
        nba_wnba_ids={str(e.get('event_id')) for e in merged_events
                      if str(e.get('league_family') or e.get('competition_key') or '').upper() in {'NBA','WNBA'}}
        history_scope_ids=deep_capture_event_ids|market_event_ids|nba_wnba_ids
        history_events=[e for e in merged_events if str(e.get('event_id')) in history_scope_ids]
        deep_capture_audit['history_database_events']=len(history_events)
        deep_capture_audit['history_database_events_skipped_no_market']=max(0,len(merged_events)-len(history_events))
        reference_update_started=time.perf_counter()
        reference=update_history_database(history_events,ref_root,cutoff=now(),years=[year,year-1],
                                          boxscore_limit=10,workers=workers)
        stage_timings['reference_database_update_seconds']=round(time.perf_counter()-reference_update_started,3)
        titan_history_health=reference.get('source_health',[])
        for row in titan_history_health:
            row['source']='titan007_history';row['source_group']='team_history_and_box_score'
        reference_merge_started=time.perf_counter()
        history_rows,merge_audit=merge_reference_history(history_rows,reference.get('history_rows',[]),merged_events)
        stage_timings['reference_history_merge_seconds']=round(time.perf_counter()-reference_merge_started,3)
        foundation_started=time.perf_counter()
        foundation_contexts=load_event_foundation_contexts(
            ref_root,merged_events,reference.get('mappings') or {},cutoff=now(),recent_limit=10)
        stage_timings['foundation_context_seconds']=round(time.perf_counter()-foundation_started,3)
        bridge_cutoff=now()
        normalized_started=time.perf_counter()
        normalized_rows,normalized_event_ids,normalized_audit=load_normalized_history_store(
            ref_root,merged_events,reference.get('mappings') or {},foundation_contexts,bridge_cutoff)
        history_rows,normalized_merge_audit=merge_reference_history(history_rows,normalized_rows,merged_events)
        stage_timings['normalized_history_load_and_merge_seconds']=round(time.perf_counter()-normalized_started,3)
        evidence_started=time.perf_counter()
        evidence_contexts,unified_evidence_audit=build_pregame_evidence_bundles(
            ref_root,merged_events,history_rows,reference.get('mappings') or {},foundation_contexts,
            bridge_cutoff,pre_bridge_history=pre_bridge_history)
        stage_timings['pregame_evidence_bundle_seconds']=round(time.perf_counter()-evidence_started,3)
        for event_id,foundation in foundation_contexts.items():
            context=total_context.setdefault(event_id,{
                'source_urls':[],'raw_paths':[],'variables':{},'possessions_verified':False,
                'basic_offense_verified':False,'three_point_verified':False,
                'late_foul_verified':False,'rotation_verified':False})
            context.update(evidence_contexts.get(event_id) or {})
            context['titan_foundation_pricing']=foundation
            # A Titan foundation refresh may be partial while the ESPN
            # history bridge already supplied a verified team box score.  Do
            # not overwrite a stronger Level-B context with an empty/default
            # Titan field merely because both providers were attempted.
            context['box_score_teams']=foundation.get('box_score_teams') or context.get('box_score_teams')
            context['foundation_history_ready']=bool(foundation.get('foundation_history_ready',False) or
                                                     context.get('foundation_history_ready',False))
            context['possessions_level']=foundation.get('possessions_level') or context.get('possessions_level','LEVEL_D')
            context['pace_source']=foundation.get('pace_source') or context.get('pace_source','UNAVAILABLE')
            for flag in ('possessions_verified','basic_offense_verified','three_point_verified'):
                context[flag]=bool(context.get(flag) or foundation.get(flag))
            context['available_variables']=sorted(set(context.get('available_variables',[]))|
                                                  set(foundation.get('available_variables',[])))
        titan_history_audit=dict(reference.get('audit') or {},status='OK',merge=merge_audit,
                                 normalized_history=normalized_audit,
                                 normalized_merge=normalized_merge_audit,
                                 normalized_event_ids=normalized_event_ids,
                                 database=reference.get('database'),audit_path=reference.get('audit_path'),
                                 event_pricing_contexts=len(foundation_contexts))
        for item in reference.get('audit',{}).get('errors',[]):
            errors.append({'source':'titan007_history',**item})
    except Exception as exc:
        titan_history_audit={'status':'FAILED','error_type':type(exc).__name__,'error':str(exc),
                             'reference_history_added':0,'real_execution_allowed':False}
        errors.append({'source':'titan007_history','error':type(exc).__name__+': '+str(exc)})
    # History collection can consume the opening quote freshness window. Take
    # one final current-board snapshot now, then price and compare. The frozen
    # independent model context above contains no market inputs.
    post_history_tick=str(int(now().timestamp()*1000))
    post_history_urls={f'post_history_titan_odds_{company_id}':f'https://lq3.titan007.com/NBA/nbaGoal{company_id}.xml?t={post_history_tick}'
                       for company_id in ('1','2','3','8','9')}
    for sel,(name,ns) in COMPANIES.items():
        post_history_urls[f'post_history_7m_odds_{sel}']=f'https://js-basket.7m.com.cn/odds/comlive_{ns}.js?t={post_history_tick}'
    post_history_res=fetch.batch(post_history_urls);post_titan=[];post_sevenm=[];post_errors=[]
    for key,r in post_history_res.items():
        if not r.get('ok'):continue
        try:
            if key.startswith('post_history_titan_odds_'):
                parsed,err=parse_titan_odds_xml(text_of(r),key.rsplit('_',1)[1],r.get('path'),r.get('received_at'))
                post_titan+=parsed;post_errors+=err
            elif key.startswith('post_history_7m_odds_'):
                parsed,err=parse_odds(text_of(r),r.get('path'),r.get('received_at'),key.rsplit('_',1)[1],contracts)
                post_sevenm+=parsed;post_errors+=err
        except Exception as exc:
            post_errors.append({'key':key,'path':r.get('path'),'error':type(exc).__name__+': '+str(exc)})
    if post_titan:quotes=[q for q in quotes if q.get('feed_provider')!='TITAN007']+post_titan
    if post_sevenm:quotes=[q for q in quotes if q.get('feed_provider')!='7M']+post_sevenm
    errors+=post_errors
    final_titan_reconciliation=reconcile_titan_events(merged_event_map,titan_events,quotes)
    merged_events=list(merged_event_map.values())
    # Identity resolution is complete at this point.  Freeze the reviewed
    # registry labels into the event rows before the pricing/report pipeline
    # copies them into display_event and the published HTML.
    for event in merged_events:
        apply_canonical_display_names(event)
    market_refresh_audit['post_history_refresh']={
        'attempted_at':stamp(now()),'titan_quotes_parsed':len(post_titan),
        'sevenm_quotes_parsed':len(post_sevenm),'errors':post_errors,
        'sequence':'MARKET_OPENING -> TITAN/7M_HISTORY -> MARKET_POST_HISTORY_REFRESH -> INDEPENDENT_PRICE -> MARKET_COMPARE',
    }
    market_routes={x['event_id']:x for x in route_odds(merged_events,quotes)}
    for event in merged_events:
        routing=market_routes.get(event.get('event_id'),{})
        event['market_status']=routing.get('market_status','NO_MARKET')
        event['market_match_method']=routing.get('market_match_method','NO_MATCH')
        event['discovery_status']='MARKET_FOUND' if routing.get('market_status')=='MARKET_FOUND' else event.get('discovery_status','DISCOVERED_ONLY')
        event.update(market_inventory_state(
            event.get('tip_at'),stamp(now()),event.get('market_status')=='MARKET_FOUND'))
    errors+=global_result.get('errors',[])
    stage_timings['collect_live_total_seconds']=round(time.perf_counter()-run_started_perf,3)
    end=stamp(now());result={'run_id':sid,'mode':'FORWARD_NATIVE','capture_finished_at':end,'requested_day':day,
       'events':merged_events,'quotes':quotes,'history':history_rows,'settlement_facts':settlement_facts,'total_context':total_context,
       'source_health':fetch.rows+global_result.get('source_health',[])+titan_history_health+espn_history_health,'errors':errors,
       'stage_timings':stage_timings,
       'global_discovery':{'run_id':global_result.get('run_id'),'event_count':len(global_result.get('events',[])),'raw_directory':global_result.get('raw_directory'),'source_health':global_result.get('source_health',[])},
       'deep_capture_audit':deep_capture_audit,'identity_collision_audit':identity_collision_audit,
       'bottom_source_audit':bottom_source_audit,
       'espn_history_audit':espn_history_audit,
       'cross_source_history_bridge_audit':cross_source_history_bridge_audit,
       'prior_capture_history_audit':dict(prior_capture_history_audit,
                                           merge=prior_capture_merge_audit),
       'raw_directory':str(session),'histories_attempted':len(hist_res),'histories_parsed':sum(1 for r in history_page_audit if r['parsed_games']>0),
       'team_history_games_parsed':sum(r['parsed_games'] for r in history_page_audit),'history_page_audit':history_page_audit,
       'source_timezone':'Asia/Shanghai','source_timezone_assumption_for_schedule':'7M and Titan007 schedule pages declare local GMT+0800; detail page verification required for conflicting events',
       'market_refresh_audit':market_refresh_audit,
       'market_history_pricing_sequence':{
           'order':['MARKET_OPENING_CAPTURE','TEAM_HISTORY_CAPTURE','MARKET_POST_HISTORY_REFRESH','INDEPENDENT_PRICE_FREEZE','MARKET_COMPARISON'],
           'foundation_context_events':len(foundation_contexts),'market_inputs_used_in_foundation_price':False,
           'final_titan_reconciliation':final_titan_reconciliation},
       'unified_evidence_audit':unified_evidence_audit,
       'titan007_history_audit':titan_history_audit,
       'titan007_audit':{'schedule_endpoint':'https://lq3.titan007.com/NBA/today2.xml','schedule_rows_target_day':len(titan_events),
                         'odds_endpoints_attempted':len([k for k in titan_res if k.startswith('titan_odds_')]),
                         'odds_quotes_parsed':sum(1 for q in quotes if q.get('feed_provider')=='TITAN007'),
                         'today_event_ids':sorted(e.get('source_event_id') for e in titan_events),
                         'missing_current_board_event_ids':sorted(set(e.get('source_event_id') for e in titan_events)-set(q.get('source_event_id') for q in quotes if q.get('feed_provider')=='TITAN007')),
                         'canonical_reconciliation':titan_reconciliation,
                         'market_found_canonical_event_ids':sorted({q.get('event_id') for q in quotes if q.get('feed_provider')=='TITAN007'}),
                          'note':'Titan current-board XML has no per-quote last-change timestamp. The source omission is retained; a verified OPEN listing may use capture time only as current-board freshness, never as an invented last-change time.'}}
    exclusive(session/'capture.json',result);return result

def replay_bundle(bundle_root,session_id=None):
    root=Path(bundle_root);out=root/'outputs'/'basketball_odds_trader' if (root/'outputs').exists() else root
    base=out/'raw/source_scout/sevenm_basket/sessions'
    dirs=[p for p in base.iterdir() if p.is_dir() and (p/'session.json').exists()]
    if not dirs:raise ValueError('no captured sessions in supplied bundle')
    session=next((p for p in dirs if p.name==session_id),None) if session_id else max(dirs,key=lambda p:load(p/'session.json')['captured_at'])
    if session is None:raise ValueError('session not found')
    meta=load(session/'session.json');observed=meta['captured_at'];events={};history={};errors=[]
    for p in sorted((session/'reverse').glob('*.js')):
        try:
            htmlp=p.with_suffix('.html');html=decode(htmlp.read_bytes()) if htmlp.exists() else ''
            e=parse_identity(decode(p.read_bytes()),p.stem,p,observed,'GMT+0800' in html)
            events[e['event_id']]=e
            hs,err=parse_history(decode(p.read_bytes()),p,observed,e['source_url'],'H2H');history.update({g['event_id']:g for g in hs});errors+=err
        except Exception as e:errors.append({'path':str(p),'error':str(e)})
    # Exporter omitted .raw files; do not invent either raw side from lossy normalized observations.
    quotes=[]
    for p in sorted((out/'markets'/'normalized').glob('*.json')):
        d=load(p,{})
        if d.get('capture_session_id')!=session.name:continue
        for idx,q in enumerate(d.get('quotes',[])):
            sid=str(d.get('event',{}).get('source_event_id',''))
            if '7m:'+sid not in events:continue
            ns=COMPANIES.get(str(q.get('company_id')),('?','UNKNOWN'))[1]
            quotes.append({'quote_id':sha((str(p)+str(idx)).encode())[:24],'event_id':'7m:'+sid,'source_event_id':sid,
              'feed_provider':'7M','bookmaker_id':'7m-company:'+ns,'bookmaker':q.get('company_name'),'market_type':q.get('market_type'),
              'raw_line':q.get('raw_line',q.get('line')),'line_team1':None,'direction_verified':False,'raw_prices':[q.get('raw_price'),None],
              'decimal_prices':None,'price_format_verified':False,'source_quote_at':stamp(source_time(q['source_quote_at'])) if source_time(q.get('source_quote_at')) else None,
              'source_timestamp_semantics':'UNKNOWN','received_at':q.get('captured_at',observed),'raw_verified':False,
              'ot_rule':'UNKNOWN','rule_evidence':None,'status':'LEGACY_NORMALIZED_UNVERIFIED','period':q.get('period','FULL_GAME'),'main_or_alt':'MAIN',
              'raw_path':None,'legacy_path':str(p),'legacy_record':q,'execution_verified':False,
              'migration_blockers':['RAW_ODDS_NOT_INCLUDED_IN_DEBUG_BUNDLE','LEGACY_LOST_SECOND_SIDE_AND_DIRECTION']})
    return {'run_id':'audit_'+session.name,'mode':'BUNDLE_AUDIT','capture_finished_at':observed,'requested_day':meta['target_bj_date'],
       'events':list(events.values()),'quotes':quotes,'history':list(history.values()),'errors':errors,'source_health':[],
       'raw_directory':str(session),'reported_legacy_event_count':meta.get('event_id_count'),'reported_legacy_odds_ids':meta.get('odds_id_count'),
       'missing_raw_files':[k for k in meta.get('raw_paths',{}) if not (session/(k+'.raw')).exists()],
       'limitations':['Supplied detail HTML/JS preserved; raw quote/event files omitted by exporter.',
                     'Audit-time reconstruction is not a prediction originally issued before the game.']}
