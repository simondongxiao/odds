"""Chronological, masked multinomial model. Intent is a learned covariate only."""
from collections import Counter
import numpy as np
from scipy.optimize import minimize, minimize_scalar
from scipy.special import softmax
from .common import *

def encoder(rows):
    cfg=config('feature_config');names=cfg['numeric'];a=np.array([[r['features']['values'].get(k,np.nan) if r['features']['values'].get(k) is not None else np.nan for k in names] for r in rows])
    med=[float(np.median(a[np.isfinite(a[:,j]),j])) if np.isfinite(a[:,j]).any() else 0. for j in range(len(names))]
    filled=np.where(np.isfinite(a),a,np.array(med));scale=np.std(filled,axis=0);scale[scale<1e-8]=1
    return {'numeric':names,'median':med,'scale':scale.tolist(),'categories':{k:sorted({r['features']['categorical'].get(k,'UNKNOWN') for r in rows}) for k in cfg['categorical']}}
def encode(features,enc):
    a=np.array([features['values'].get(k) if features['values'].get(k) is not None else np.nan for k in enc['numeric']],float);missing=~np.isfinite(a)
    z=(np.where(missing,enc['median'],a)-enc['median'])/enc['scale']
    return np.array([1.,*np.clip(z,-20,20),*missing.astype(float),*[float(features['categorical'].get(k)==v) for k,vs in enc['categories'].items() for v in vs]])
def names(enc):return ['intercept']+enc['numeric']+[k+':MISSING' for k in enc['numeric']]+[k+'='+v for k,vs in enc['categories'].items() for v in vs]
def bucket(s):return str(abs(s['handicap']))
def priors(rows):
    counts={}
    for r in rows:
        b=bucket(r['snapshot']);counts.setdefault(b,np.ones(5));counts[b][STATES.index(r['label'])]+=1
    return {b:a.tolist() for b,a in counts.items()}
def prior(s,counts):
    a=np.array(counts.get(bucket(s),[1.]*5));a*=np.array(support(-abs(s['handicap'])));return a/a.sum()
def probabilities(logits,mask,temperature=1.):return softmax(np.where(mask,logits/temperature,-1e30),axis=-1)
def fit(rows,enc,l2=1.,weights=None):
    x=np.array([encode(r['features'],enc) for r in rows]);y=np.array([STATES.index(r['label']) for r in rows]);counts=priors(rows)
    p=np.array([prior(r['snapshot'],counts) for r in rows]);mask=p>0;offset=np.log(np.maximum(p,1e-30));w=np.ones(len(rows)) if weights is None else np.array(weights,float);den=w.sum()
    def loss(flat):
        b=flat.reshape(x.shape[1],5);pred=probabilities(offset+x@b,mask);nll=-(w*np.log(np.maximum(pred[np.arange(len(y)),y],1e-30))).sum()/den
        error=pred.copy();error[np.arange(len(y)),y]-=1;grad=x.T@(error*w[:,None])/den
        penalty=b.copy();penalty[0]=0
        return nll+l2*np.sum(penalty**2)/(2*den),(grad+l2*penalty/den).ravel()
    result=minimize(loss,np.zeros(x.shape[1]*5),jac=True,method='L-BFGS-B',options={'maxiter':500,'ftol':1e-10})
    if not result.success:raise RuntimeError('MODEL_FIT_FAILED:'+result.message)
    return {'coefficients':result.x.reshape(x.shape[1],5).tolist(),'priors':counts,'converged':bool(result.success)}
def raw_logits(model,f,s,enc):
    p=prior(s,model['priors']);return np.log(np.maximum(p,1e-30))+encode(f,enc)@np.array(model['coefficients']),p>0
def calibrate(model,validation,enc):
    z=[raw_logits(model,r['features'],r['snapshot'],enc) for r in validation];logits=np.array([t[0] for t in z]);mask=np.array([t[1] for t in z]);y=np.array([STATES.index(r['label']) for r in validation])
    def objective(t):
        p=probabilities(logits,mask,t);return -np.log(np.maximum(p[np.arange(len(y)),y],1e-30)).mean()
    result=minimize_scalar(objective,bounds=config('model_config')['calibration']['temperature_bounds'],method='bounded')
    if not result.success:raise RuntimeError('CALIBRATION_FAILED')
    return float(result.x)
def train():
    target=ROOT/'models/V4.1_R1.json'
    if target.exists():return read(target)
    allrows=read(ROOT/'data/training_dataset.json');cfg=config('model_config');train=[r for r in allrows if r['eligible'] and r['partition']=='train'];val=[r for r in allrows if r['eligible'] and r['partition']=='validation']
    for r in train+val:
        if clock(r['result_available_at'])>clock(r['training_cutoff']):raise ValueError('RESULT_TIME_LEAKAGE')
        if any(p['source_timestamp'] and clock(p['source_timestamp'])>clock(r['decision_at']) for p in r['features']['provenance']):raise ValueError('FEATURE_TIME_LEAKAGE')
    if len(train)<cfg['calibration']['min_train']:raise ValueError('INSUFFICIENT_TRAINING')
    enc=encoder(train);model=fit(train,enc,cfg['regularization_l2']);valid=len(val)>=cfg['calibration']['min_validation'] and len({r['list_date'] for r in val})>=cfg['calibration']['min_validation_dates']
    temperature=calibrate(model,val,enc) if valid else None;members=[];rng=np.random.default_rng(cfg['seed']);dates=sorted({r['list_date'] for r in train});vdates=sorted({r['list_date'] for r in val})
    if valid:
        for _ in range(cfg['bootstrap_members']):
            days=Counter(rng.choice(dates,len(dates),replace=True));sample=[r for r in train for repeat in range(days[r['list_date']])];m=fit(sample,enc,cfg['regularization_l2'])
            vd=Counter(rng.choice(vdates,len(vdates),replace=True));vs=[r for r in val for repeat in range(vd[r['list_date']])];m['temperature']=calibrate(m,vs,enc);members.append(m)
    artifact={'model_version':cfg['model_version'],'created_at':now().isoformat(),'status':'SHADOW','real_money':False,'model_type':cfg['probability_model'],'encoder':enc,'model':model,'temperature':temperature,'calibration_state':'FITTED_INDEPENDENT_VALIDATION' if valid else 'INSUFFICIENT_CALIBRATION','calibration_version':'TEMP_R1','bootstrap':members,'uncertainty_kind':'DATE_CLUSTER_BOOTSTRAP_MODEL_DEPENDENT_NOT_COVERAGE_GUARANTEE','train_count':len(train),'validation_count':len(val),'train_bucket_counts':dict(Counter(bucket(r['snapshot']) for r in train)),'validation_bucket_counts':dict(Counter(bucket(r['snapshot']) for r in val)),'validation_T30_bucket_counts':dict(Counter(bucket(r['snapshot']) for r in val if r['snapshot_window']=='T-30')),'config_hashes':{n:filehash(ROOT/'config'/f'{n}.yaml') for n in ['model_config','feature_config','snapshot_policy']},'dataset_sha256':filehash(ROOT/'data/training_dataset.json'),'split':cfg['split']}
    artifact['artifact_id']=digest(artifact);write(target,artifact,immutable=True)
    write(ROOT/'calibration/TEMP_R1.json',{'method':'temperature_scaling_multiclass','temperature':temperature,'validation_count':len(val),'window_support':artifact['validation_T30_bucket_counts'],'state':artifact['calibration_state'],'test_used_for_selection':False,'model_artifact_id':artifact['artifact_id']},immutable=True);return artifact
def predict(artifact,f,s):
    enc=artifact['encoder'];m=artifact['model'];logits,mask=raw_logits(m,f,s,enc);raw=probabilities(logits,mask);cal=probabilities(logits,mask,artifact['temperature']) if artifact['temperature'] is not None else None
    ensemble=[probabilities(*raw_logits(b,f,s,enc),b['temperature']).tolist() for b in artifact['bootstrap']]
    contribution=encode(f,enc)[:,None]*np.array(m['coefficients']);direction=contribution[:,0]-contribution[:,4];drivers=sorted(zip(names(enc),direction.tolist()),key=lambda z:z[1],reverse=True)
    return {'raw_probability':raw.tolist(),'calibrated_probability':cal.tolist() if cal is not None else None,'bucket_probability':prior(s,m['priors']).tolist(),'ensemble':ensemble,'top_positive_drivers':[{'feature':k,'logit_giving_minus_receiving':v} for k,v in drivers if v>0][:5],'top_negative_drivers':[{'feature':k,'logit_giving_minus_receiving':v} for k,v in reversed(drivers) if v<0][:5],'train_support':artifact['train_bucket_counts'].get(bucket(s),0),'calibration_support':artifact['validation_bucket_counts'].get(bucket(s),0),'window_calibration_support':artifact['validation_T30_bucket_counts'].get(bucket(s),0)}
