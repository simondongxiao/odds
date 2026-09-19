"""Snapshot V4 identities and copy exact runtime into an isolated CONTROL sandbox."""
import sys,json,shutil,subprocess
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from v41.common import *
destination=ROOT/'data/control_baseline';manifest=destination/'manifest.json'
if not manifest.exists():
    files=[]
    for p in sorted((WORKSPACE/'v4').rglob('*')):
        if p.is_file() and '__pycache__' not in p.parts:
            q=destination/p.relative_to(WORKSPACE);q.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,q)
            files.append({'source':str(p),'relative':str(p.relative_to(WORKSPACE)),'sha256':filehash(p)})
    for relative in ['v3_legacy/tools/fetch_titan007_odds.py','tools/football_competition_normalizer.py','tools/football_intent_engine.py','outputs/football_odds_trader/research/v4_market_base_ready.csv']:
        p=WORKSPACE/relative;q=destination/relative;q.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,q)
        files.append({'source':str(p),'relative':relative,'sha256':filehash(p)})
    repo=WORKSPACE/'outputs/football_odds_trader/github_publish/odds'
    write(manifest,{'frozen_at':now().isoformat(),'git_commit':subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD'],text=True).strip(),'files':files},immutable=True)
print(json.dumps({'baseline':str(manifest),'files':len(read(manifest)['files'])}))
