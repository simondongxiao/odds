import sys,subprocess,requests
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from v41.common import *
repo=WORKSPACE/'outputs/football_odds_trader/github_publish/odds';commit=subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD'],text=True).strip();proxies={'http':'http://127.0.0.1:16780','https':'http://127.0.0.1:16780'}
r=requests.get('https://api.github.com/repos/simondongxiao/odds/actions/runs',params={'head_sha':commit,'per_page':5},proxies=proxies,timeout=30);r.raise_for_status();runs=r.json()['workflow_runs'];run=next((r for r in runs if r['head_sha']==commit),None)
if not run or run['conclusion']!='success':print(canonical({'commit':commit,'status':run['status'] if run else 'NOT_FOUND','conclusion':run['conclusion'] if run else None}));raise SystemExit(2)
def verify(rel):
    url='https://simondongxiao.github.io/odds/'+rel+'?v='+commit[:7];r=requests.get(url,proxies=proxies,timeout=60);r.raise_for_status();return {'url':url,'status':r.status_code,'content_matches':r.content.decode('utf-8-sig').replace('\r\n','\n')==(repo/rel).read_text(encoding='utf-8-sig').replace('\r\n','\n')}
with ThreadPoolExecutor(max_workers=4) as pool:checks=list(pool.map(verify,['v41/index.html','v41/compare/index.html','v41/V41_BUILD_REPORT.md','v41/forward_comparison.csv','v41/cards.json','v4/index.html','v3-legacy/index.html']))
out={'commit':commit,'pages_run':run['html_url'],'pages_conclusion':run['conclusion'],'checks':checks,'pass':all(x['content_matches'] for x in checks),'verified_at':now().isoformat()};write(ROOT/'diagnostics/publication_verification.json',out);print(canonical(out));raise SystemExit(0 if out['pass'] else 1)
