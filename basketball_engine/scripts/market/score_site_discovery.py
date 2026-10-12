from __future__ import annotations
import re
def normalize_team(name): return re.sub(r'\[[^]]*\]','',str(name or '')).strip()
def asian_to_decimal(value, fmt):
    v=float(value)
    if fmt=='decimal': return v
    if fmt=='hong_kong': return 1+v
    if fmt=='malay': return 1+v if v>=0 else 1+1/abs(v)
    if fmt=='indonesia': return 1+v if v>=0 else 1+1/abs(v)
    raise ValueError('unknown price format')
def map_spread(team, side, value):
    v=float(value); return -abs(v) if side in ('home','upper') and team else abs(v)
def normalize_quote(event, row):
    if row.get('overtime_rule','UNKNOWN')=='UNKNOWN': row['executable_verified']=False
    if not row.get('raw_price_format'): row['executable_verified']=False
    if row.get('raw_price') is not None and row.get('raw_price_format'):
        row['decimal_odds']=asian_to_decimal(row['raw_price'],row['raw_price_format'])
    row['feed_provider']='qiutan';row.setdefault('upstream_provider','UNKNOWN');row.setdefault('timestamp_type','CAPTURE_TIME_ONLY')
    row['canonical_event_id']=event.get('canonical_event_id');return row
