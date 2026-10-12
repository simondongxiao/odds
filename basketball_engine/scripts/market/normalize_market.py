from __future__ import annotations
import hashlib
def market_id(event_id, market_type, period='FULL_GAME', overtime_rule='INCLUDING_OT', selection_scope='MAIN'):
    raw='|'.join(map(str,(event_id,market_type,period,overtime_rule,selection_scope)))
    return hashlib.sha256(raw.encode()).hexdigest()[:24]
def normalize(row):
    x=dict(row);x['canonical_market_id']=market_id(x['canonical_event_id'],x['market_type'],x.get('period','FULL_GAME'),x.get('overtime_rule','INCLUDING_OT'),x.get('selection_scope','MAIN'))
    x.setdefault('market_status','OPEN');x.setdefault('reference_class','UNKNOWN');x.setdefault('captured_at',x.get('timestamp'))
    return x
