from __future__ import annotations
import csv,datetime as dt,hashlib,json,os,re
from pathlib import Path
import yaml

ROOT=Path(__file__).resolve().parent
WORKSPACE=ROOT.parent
TZ=dt.timezone(dt.timedelta(hours=8))
STATES=('W','HW','P','HL','L')
def now():return dt.datetime.now(TZ)
def clock(value):
    if isinstance(value,dt.datetime):
        if value.tzinfo is None:raise ValueError('TIMEZONE_REQUIRED')
        return value.astimezone(TZ)
    text=str(value or '')
    for fmt in ('%Y%m%d_%H%M%S','%Y%m%dT%H%M%SZ'):
        try:
            x=dt.datetime.strptime(text,fmt)
            return x.replace(tzinfo=dt.timezone.utc if text.endswith('Z') else TZ).astimezone(TZ)
        except ValueError:pass
    x=dt.datetime.fromisoformat(text.replace('Z','+00:00'))
    if x.tzinfo is None:raise ValueError('TIMEZONE_REQUIRED')
    return x.astimezone(TZ)
def timestamp(value,year=None):
    text=str(value or '').strip()
    m=re.fullmatch(r'(?:(\d{4})-)?(\d{1,2})-(\d{1,2})[ T](\d{1,2}):(\d{2})(?::(\d{2}))?',text)
    if m:
        y,mo,d,h,mi,se=m.groups()
        if not (y or year):raise ValueError('YEAR_REQUIRED')
        return dt.datetime(int(y or year),int(mo),int(d),int(h),int(mi),int(se or 0),tzinfo=TZ).isoformat()
    return clock(text).isoformat()
def number(x):
    try:
        v=float(x)
        return v if __import__('math').isfinite(v) else None
    except (TypeError,ValueError):return None
def read(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def canonical(x):return json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)
def digest(x):return hashlib.sha256(canonical(x).encode()).hexdigest()
def filehash(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def config(name):return yaml.safe_load((ROOT/'config'/f'{name}.yaml').read_text(encoding='utf-8'))
def write(p,x,immutable=False):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    body=json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False)+'\n'
    if immutable:
        if p.exists():
            if read(p)!=x:raise ValueError(f'IMMUTABLE_CONFLICT:{p}')
            return
        with p.open('x',encoding='utf-8') as h:h.write(body)
    else:
        temp=p.with_name(p.name+'.tmp')
        temp.write_text(body,encoding='utf-8');os.replace(temp,p)
def csvwrite(p,rows,fields=None):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    fields=fields or list(dict.fromkeys(k for r in rows for k in r)) or ['status']
    with p.open('w',encoding='utf-8-sig',newline='') as h:
        w=csv.DictWriter(h,fieldnames=fields,extrasaction='ignore');w.writeheader()
        for r in rows:w.writerow({k:canonical(v) if isinstance(v,(list,dict)) else v for k,v in r.items()})
def result_for_margin(margin,line):
    q=round(line*4)
    if abs(q/4-line)>1e-8:raise ValueError('NON_QUARTER_HANDICAP')
    parts=[q/4,q/4] if q%2==0 else [(q-1)/4,(q+1)/4]
    z=sum(1 if margin+h>0 else -1 if margin+h<0 else 0 for h in parts)
    return {2:'W',1:'HW',0:'P',-1:'HL',-2:'L'}[z]
def payoff(water):return [water,.5*water,0.,-.5,-1.]
def support(line):return [s in {result_for_margin(m,line) for m in range(-50,51)} for s in STATES]
def mirror(p):return list(reversed(p))
def effective(p):
    a=p[0]+.5*p[1];b=p[4]+.5*p[3]
    return a/(a+b) if a+b else None
