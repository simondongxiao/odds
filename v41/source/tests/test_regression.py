import copy,datetime as dt
import numpy as np
import pytest
from v41.common import *
from v41.snapshots import normalize,windows
from v41.features import build
from v41.probability import predict,encode
from v41.decision import decide,freeze
from v41.forward import settlement
from v41.health import probability_health

@pytest.fixture(scope='module')
def model():return read(ROOT/'models/V4.1_R1.json')
@pytest.fixture
def sample():
    r=next(r for r in read(ROOT/'data/training_dataset.json') if r['eligible'] and abs(r['snapshot']['handicap'])==.5);return copy.deepcopy(r)
def test_same_handicap_match_specific(model,sample):
    f=sample['features'];a=predict(model,f,sample['snapshot']);f['values']['euro_giving']=.85;f['values']['euro_receiving']=.05;b=predict(model,f,sample['snapshot']);assert np.max(np.abs(np.array(a['calibrated_probability'])-b['calibrated_probability']))>1e-4
def test_intent_not_hard_side_mapping(model,sample):
    from v41.common import effective
    sides=[]
    for tag in ['真实示弱/阻下','真实示强/阻上','UNKNOWN','MIXED','NEUTRAL']:
        f=copy.deepcopy(sample['features']);f['categorical']['intent']=tag;sides.append(effective(predict(model,f,sample['snapshot'])['calibrated_probability'])>.5)
    assert len(sides)>len(set(sides))
    source=(ROOT/'decision.py').read_text(encoding='utf-8');assert "categorical" not in source and 'map_intent' not in source
def test_missing_T30_never_substitutes(sample):
    s=sample['snapshot'];s['minutes_to_kickoff']=500;assert windows([s],s['quote_at'])['T-30']['status']=='MISSING'
def test_future_feature_rejected(sample):
    with pytest.raises(ValueError):build(sample['snapshot'],[sample['snapshot']],clock(sample['snapshot']['quote_at'])-dt.timedelta(seconds=1))
def test_score_not_in_snapshot():
    row={'match_id':'1','list_date':'2026-09-19','bj_time':'9-20 02:00','home_cn':'甲','away_cn':'乙','state':'0','ah_full_current_line_or_draw':'.5','ah_full_current_home_or_over':'.9','ah_full_current_away_or_under':'.95','home_score':'99','away_score':'0'}
    a=normalize(row,'2026-09-19T23:00:00+08:00','synthetic');row['home_score']='0';assert a==normalize(row,'2026-09-19T23:00:00+08:00','synthetic');assert a['list_date']=='2026-09-19'
def test_freeze_immutable(tmp_path):
    p=tmp_path/'freeze.json';write(p,{'side':'giving'},immutable=True)
    with pytest.raises(ValueError):write(p,{'side':'receiving'},immutable=True)
    assert read(p)['side']=='giving'
def test_settlement_cannot_change_recommendation(sample):
    s=sample['snapshot'];d={'grade':'C','candidate_side':'giving','candidate_team':s['giving_team'],'candidate_handicap':-.5,'water':.9};f={'snapshot':s,'decision':d,'decision_id':'synthetic'};before=canonical(f)
    outcome={'home':s['home'],'away':s['away'],'score':'2-1','result_available_at':(clock(s['kickoff_at'])+dt.timedelta(hours=3)).isoformat(),'source':'SYNTHETIC','source_hash':'fixture'};settlement(f,outcome);assert canonical(f)==before
def test_probability_sums_and_support(model,sample):
    p=predict(model,sample['features'],sample['snapshot'])
    for k in ['raw_probability','calibrated_probability','bucket_probability']:
        assert sum(p[k])==pytest.approx(1);assert all(v>=0 for v in p[k]);assert p[k][1:4]==[0,0,0]
@pytest.mark.parametrize('line,margin,label',[( -.25,0,'HL'),(.25,0,'HW'),(-1,1,'P'),(-.75,1,'HW'),(.75,-1,'HL'),(-.5,1,'W'),(-.5,0,'L')])
def test_payoff_and_mirror(line,margin,label):
    assert result_for_margin(margin,line)==label;assert STATES.index(result_for_margin(-margin,-line))==4-STATES.index(label)
    p=np.zeros(5);p[STATES.index(label)]=1;assert np.dot(p,payoff(.8))=={'W':.8,'HW':.4,'P':0,'HL':-.5,'L':-1}[label]
def test_titan_identity_sign():
    for line,expected in [(.5,'甲'),(-.5,'乙')]:
        s=normalize({'match_id':'1','list_date':'2026-09-19','bj_time':'9-19 22:00','home_cn':'甲','away_cn':'乙','state':'0','ah_full_current_line_or_draw':line,'ah_full_current_home_or_over':.9,'ah_full_current_away_or_under':.8},'2026-09-19T21:30:00+08:00','fixture');assert s['giving_team']==expected;assert s['giving_water']==(.9 if line>0 else .8)
def test_c_is_not_any_positive_ev(sample):
    s=sample['snapshot'];s['quote_at']='2026-09-19T21:30:00+08:00';s['kickoff_at']='2026-09-19T22:00:00+08:00';s['minutes_to_kickoff']=30;s['prematch']=True;p=[.55,0,0,0,.45]
    pred={'calibrated_probability':p,'ensemble':[p]*20,'train_support':1000,'calibration_support':500,'window_calibration_support':0};d=decide(pred,s,sample['features'],s['quote_at']);assert d['grade']=='N';assert 'INSUFFICIENT_T30_CALIBRATION_SUPPORT' in d['decision_reason']
def test_probability_collapse_alarm():
    cs=[{'snapshot':{'handicap':.5},'probability':{'calibrated_probability':[.6,0,0,0,.4]}}]*10;assert probability_health(cs)[0]['status']=='PROBABILITY_COLLAPSE_CRITICAL'
def test_strict_training_asof():
    for r in read(ROOT/'data/training_dataset.json'):
        if r['eligible']:assert clock(r['result_available_at'])<=clock(r['training_cutoff'])
        assert all(not x['source_timestamp'] or clock(x['source_timestamp'])<=clock(r['decision_at']) for x in r['features']['provenance'])
def test_original_control_unchanged():
    from v41.control import verify_original
    assert verify_original()['unchanged']
def test_control_uses_settlement_signed_field_not_display_magnitude(sample):
    s=sample['snapshot'];d={'grade':'N','candidate_side':'giving','candidate_team':s['giving_team'],'candidate_handicap':-.5,'water':.9};c={'grade':'C','candidate_side':'giving','candidate_team':s['giving_team'],'candidate_handicap':.5,'selected_handicap_signed':-.5,'selected_water_hk':.9};f={'snapshot':s,'decision':d,'control':c,'decision_id':'fixture'}
    result={'home':s['home'],'away':s['away'],'score':'0-0','result_available_at':(clock(s['kickoff_at'])+dt.timedelta(hours=3)).isoformat(),'source':'fixture','source_hash':'fixture'}
    out=settlement(f,result);assert out['v4_result']=='L' and out['v4_pnl']==-1
