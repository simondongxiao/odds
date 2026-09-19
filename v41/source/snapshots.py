from __future__ import annotations
import csv,importlib.util,re,sys
from collections import defaultdict
from functools import lru_cache
from .common import *
@lru_cache(maxsize=4096)
def sourcehash(p):return filehash(p) if Path(p).is_file() else None

def adapter():
    path=ROOT/'data/control_baseline/v3_legacy/tools/fetch_titan007_odds.py'
    spec=importlib.util.spec_from_file_location('v41_titan_readonly_parser',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module
def roster_map():
    out={}
    for base in [WORKSPACE/'outputs/football_odds_trader/ledger/slate_rosters',WORKSPACE/'v3_legacy/outputs/football_odds_trader/ledger/slate_rosters',ROOT/'data/rosters']:
        for p in sorted(base.glob('*.json')):
            x=read(p);day=x.get('list_date')
            if not day:continue
            for mid,r in (x.get('matches') or {}).items():
                if mid not in out or day<out[mid]['list_date']:out[mid]={**r,'list_date':day}
    return out
def normalize(row,observed_at,source,list_date=None):
    """Allowlist only; no score/result columns can enter a snapshot."""
    t=clock(observed_at);day=list_date or row.get('list_date')
    if not day:raise ValueError('MISSING_LIST_DATE')
    k=timestamp(row.get('bj_time') or row.get('kickoff'),day[:4])
    def n(key):return number(row.get(key))
    h=n('ah_full_current_line_or_draw');hw=n('ah_full_current_home_or_over');aw=n('ah_full_current_away_or_under')
    opening=n('ah_full_open_line_or_draw')
    gh=row.get('home_cn') or row.get('home_team');ah=row.get('away_cn') or row.get('away_team')
    clean=lambda s:re.sub('<[^>]+>','',str(s or '')).strip()
    gh,ah=clean(gh),clean(ah)
    valid=h is not None and abs(h*4-round(h*4))<1e-8 and hw is not None and aw is not None and hw>0 and aw>0 and bool(gh and ah)
    giving=gh if h is not None and h>0 else ah if h is not None and h<0 else None
    receiving=ah if giving==gh else gh if giving==ah else None
    euro=[n('euro_full_current_'+s) for s in ['home_or_over','line_or_draw','away_or_under']]
    oeuro=[n('euro_full_open_'+s) for s in ['home_or_over','line_or_draw','away_or_under']]
    snap={'match_id':str(row['match_id']),'list_date':day,'home':gh,'away':ah,'league':row.get('league_cn') or row.get('competition',''),'kickoff_at':k,
          'quote_at':t.isoformat(),'observed_at':t.isoformat(),'provider_quote_at':None,'quote_time_kind':'OBSERVED_PRICE_NOT_PROVIDER_TICK','source':str(source),'source_hash':sourcehash(str(source)),
          'minutes_to_kickoff':(clock(k)-t).total_seconds()/60,'handicap':h,'giving_team':giving,'receiving_team':receiving,
          'giving_water':hw if giving==gh else aw if giving==ah else None,'receiving_water':aw if giving==gh else hw if giving==ah else None,
          'home_water':hw,'away_water':aw,'opening_handicap':opening,'opening_home_water':n('ah_full_open_home_or_over'),'opening_away_water':n('ah_full_open_away_or_under'),
          'opening_quote_at':None,'euro':euro if all(v is not None and v>1 for v in euro) else None,'opening_euro':oeuro if all(v is not None and v>1 for v in oeuro) else None,
          'valid_market':valid,'prematch':str(row.get('state',''))=='0' and clock(k)>t,'state':str(row.get('state','')),'neutral_venue':None,'elo_difference':None,'recent_form_difference':None,'bookmaker_dispersion':None,'bookmaker_consensus':None}
    snap['snapshot_id']=digest(snap)
    return snap
def window_name(minutes,policy=None):
    policy=policy or config('snapshot_policy')
    for name,bounds in policy['windows'].items():
        if bounds and bounds[0]<=minutes<=bounds[1]:return name
    return 'OUTSIDE_STANDARD_WINDOWS'
def windows(path,as_of,policy=None):
    policy=policy or config('snapshot_policy');as_of=clock(as_of)
    eligible=[s for s in path if clock(s['quote_at'])<=as_of and s['prematch'] and s['valid_market']]
    out={}
    for name,bounds in policy['windows'].items():
        choices=[s for s in eligible if (s.get('opening_quote_at') if name=='OPEN' else bounds[0]<=s['minutes_to_kickoff']<=bounds[1])]
        out[name]={'status':'AVAILABLE','snapshot':max(choices,key=lambda s:s['quote_at'])} if choices else {'status':'MISSING','snapshot':None}
    return out
def ingest(snap):
    p=ROOT/'snapshots'/snap['list_date']/snap['match_id']/(snap['snapshot_id']+'.json');write(p,snap,immutable=True);return p
def paths_for(day,mid):return [read(p) for p in sorted((ROOT/'snapshots'/day/str(mid)).glob('*.json'))]
def collect(day):
    """Fresh network observations; all outputs under v41, never legacy raw or roster."""
    m=adapter();started=now();stamp=started.strftime('%Y%m%d_%H%M%S');folder=ROOT/'data/raw'/stamp;folder.mkdir(parents=True,exist_ok=False)
    import concurrent.futures
    errors=[];files={}
    def one(name):return name,m.fetch(name,stamp,folder)
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        for future in [pool.submit(one,name) for name in ['bfdata_ut.js','sbOddsData.js','ch_goalbf3.xml']]:
            try:name,p=future.result();files[name]=p
            except Exception as e:errors.append(type(e).__name__+':'+str(e))
    if 'bfdata_ut.js' not in files or 'sbOddsData.js' not in files:raise RuntimeError('FRESH_SOURCE_FAILED:'+str(errors))
    observed=now();schedule=m.parse_schedule(m.read_text(files['bfdata_ut.js']));odds=m.parse_sbodds(m.read_text(files['sbOddsData.js']))
    # The list roster is fetched separately and NEVER derived from natural kickoff date.
    locked=roster_map();existing={mid:r for mid,r in locked.items() if r['list_date']==day};roster=dict(existing)
    try:
        p,raw=m.fetch_url(f'{m.BF_BASE}/football/Next_{day.replace("-", "")}.htm',stamp,folder,'list_date.htm')
        for mid,r in m.parse_future_schedule(m.decode_text(raw)).items():
            if mid in locked and locked[mid]['list_date']!=day:continue
            roster.setdefault(mid,{**r,'list_date':day,'source':str(p)})
    except Exception as e:errors.append('LIST_PAGE:'+str(e))
    if not roster:raise RuntimeError('LIST_DATE_ROSTER_MISSING')
    write(ROOT/'data/rosters'/f'{day}.json',{'list_date':day,'matches':roster})
    # XML has no per-tick clock; do not mix a possibly older feed into the sb matrix.
    rows=m.build_rows(schedule,odds,{})
    scoped=[];snaps=[];results=[]
    for r in rows:
        mid=str(r['match_id'])
        if mid not in roster:continue
        r={**r,'list_date':day,'snapshot_stamp':observed.strftime('%Y%m%d_%H%M%S')};scoped.append(r)
        try:s=normalize(r,observed,files['sbOddsData.js'],day)
        except (ValueError,KeyError):continue
        if s['prematch']:
            ingest(s);snaps.append(s)
        if str(r.get('state'))=='-1' and r.get('home_score','').isdigit() and r.get('away_score','').isdigit():
            results.append({'match_id':mid,'list_date':day,'home':s['home'],'away':s['away'],'score':f"{r['home_score']}-{r['away_score']}",'result_available_at':observed.isoformat(),'source':str(files['bfdata_ut.js']),'source_hash':filehash(files['bfdata_ut.js']),'settlement_clock':'90_MIN_FINAL_SCHEDULE','status':'FINAL'})
    for x in results:write(ROOT/'data/results'/day/x['match_id']/(digest(x)+'.json'),x,immutable=True)
    csvpath=folder/'control_raw.csv';csvwrite(csvpath,scoped)
    info={'list_date':day,'observed_at':observed.isoformat(),'roster_count':len(roster),'received':len(scoped),'prematch_snapshots':len(snaps),'errors':errors,'raw_csv':str(csvpath)}
    write(folder/'manifest.json',info,immutable=True)
    return roster,snaps,info

def historical_inventory():
    """First-observed result time is conservative availability, never fabricated kickoff+2h."""
    histories=defaultdict(list);finals=defaultdict(list);rejected=defaultdict(int);locked=roster_map();sources=[]
    for base in [WORKSPACE/'outputs/football_odds_trader/raw/titan007',WORKSPACE/'v3_legacy/outputs/football_odds_trader/raw/titan007']:
        for p in sorted(base.glob('**/*_titan007_odds_snapshot.csv')):
            match=re.match(r'(\d{8}_\d{6})_',p.name)
            if not match:continue
            observed=clock(match[1])
            if observed>now():continue
            sources.append({'path':str(p),'sha256':filehash(p),'observed_at':observed.isoformat()})
            with p.open(encoding='utf-8-sig',newline='') as h:
                for r in csv.DictReader(h):
                    mid=str(r.get('match_id',''));day=r.get('list_date') or locked.get(mid,{}).get('list_date')
                    if not day:rejected['missing_list_date']+=1;continue
                    try:s=normalize(r,observed,p,day)
                    except (ValueError,KeyError):rejected['invalid_identity_or_clock']+=1;continue
                    if str(r.get('state'))=='-1' and str(r.get('home_score','')).isdigit() and str(r.get('away_score','')).isdigit() and observed>clock(s['kickoff_at']):
                        finals[mid].append({'match_id':mid,'home':s['home'],'away':s['away'],'score':f"{r['home_score']}-{r['away_score']}",'result_available_at':observed.isoformat(),'source':str(p),'source_hash':s['source_hash']})
                    # If row explicitly retains older prices, file time is NOT its price observation.
                    if r.get('snapshot_stamp') and r['snapshot_stamp']!=match[1]:rejected['retained_quote']+=1;continue
                    if r.get('odds_frozen_from_snapshot') and r['odds_frozen_from_snapshot']!=match[1]:rejected['retained_quote']+=1;continue
                    if r.get('refresh_status') and r['refresh_status'] not in {'REFRESHED',''}:rejected['unrefreshed_quote']+=1;continue
                    if s['prematch'] and s['valid_market'] and s['handicap'] and s['euro']:histories[mid].append(s)
    cleanfinal={}
    for mid,rs in finals.items():
        if len({(r['score'],r['home'],r['away']) for r in rs})!=1:rejected['conflicting_final']+=1;continue
        cleanfinal[mid]=min(rs,key=lambda r:r['result_available_at'])
    write(ROOT/'data/historical_source_manifest.json',{'built_at':now().isoformat(),'sources':sources,'rejected_counts':dict(rejected)})
    return histories,cleanfinal,rejected
