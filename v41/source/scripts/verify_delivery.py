"""Independent challenger delivery checks, plus byte-for-byte control guard."""
import sys,math
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from v41.common import *
from v41.control import verify_original
from v41.forward import reconcile,settlement
checks={'original_control':verify_original('--runtime' in sys.argv)};decisions=[read(p) for p in (ROOT/'decisions').glob('*/*.json')]
for f in decisions:
    body={k:v for k,v in f.items() if k!='decision_id'};assert digest(body)==f['decision_id'],'FROZEN_CONTENT_CHANGED'
    s=f['snapshot'];d=f['decision'];p=f['probability'];c=f['control'];model=read(ROOT/'models'/f"{f['model_version']}.json")
    assert f['real_money'] is False and clock(model['created_at'])<=clock(f['frozen_at'])<clock(s['kickoff_at'])
    if f.get('execution_policy_version'):
        policy=config('execution_policy')
        assert f['execution_policy_version']==policy['version']
        assert policy['primary_freeze_min_minutes_exclusive']<s['minutes_to_kickoff']<=policy['primary_freeze_max_minutes_inclusive']
    else:
        assert 25<=s['minutes_to_kickoff']<=40
    assert 0<=(clock(f['frozen_at'])-clock(s['quote_at'])).total_seconds()/60<=3
    assert c['match_id']==s['match_id'] and abs((clock(c['quote_at'])-clock(s['quote_at'])).total_seconds())<2
    assert clock(c['decision_at'])<clock(s['kickoff_at'])
    for name in ['raw_probability','calibrated_probability']:
        assert abs(sum(p[name])-1)<1e-10 and min(p[name])>=0
    assert d['candidate_team']==s[d['candidate_side']+'_team']
    assert d['candidate_handicap']==(-1 if d['candidate_side']=='giving' else 1)*abs(s['handicap'])
    assert (d['P_giving_cover']>.5)==(d['candidate_side']=='giving')
    assert abs(sum(x*y for x,y in zip(d['selected_probability'],payoff(d['water'])))-d['EV_mean'])<1e-10
    assert all(not p['source_timestamp'] or clock(p['source_timestamp'])<=clock(f['frozen_at']) for p in f['features']['provenance'])
    for margin in range(-8,9):assert STATES.index(result_for_margin(margin,-abs(s['handicap'])))+STATES.index(result_for_margin(-margin,abs(s['handicap'])))==4
rows=reconcile();checks['immutable_paired_decisions']=len(decisions);checks['settled_pairs']=sum(r['settlement_status']=='SETTLED' for r in rows)
for path in (ROOT/'reports').glob('????-??-??.json'):
    r=read(path);frozen=[c for c in r['cards'] if c.get('frozen_at')];assert r['summary']['frozen']==len(frozen)
    assert all(r['summary']['grades'][g]==sum(c['decision']['grade']==g for c in frozen) for g in 'ABCN')
checks['all_checks_passed']=True;checks['verified_at']=now().isoformat();write(ROOT/'diagnostics/delivery_verification.json',checks);print(canonical(checks))
