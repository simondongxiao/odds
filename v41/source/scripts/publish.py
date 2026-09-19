"""Only stage independent v41 subtree. Never commits unrelated work."""
import argparse,shutil,subprocess,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from v41.common import *
from v41.control import verify_original
p=argparse.ArgumentParser();p.add_argument('--push',action='store_true');args=p.parse_args();verify_original(True)
repo=WORKSPACE/'outputs/football_odds_trader/github_publish/odds'
def git(*args):return subprocess.check_output(['git','-C',str(repo),*args],text=True,encoding='utf-8').strip()
before={str(p.relative_to(repo)):filehash(p) for folder in ['v4','v3-legacy'] for p in (repo/folder).rglob('*') if p.is_file()}
status=git('status','--porcelain')
if any(not line[3:].replace('"','').startswith('v41/') for line in status.splitlines()):raise ValueError('UNRELATED_GIT_CHANGES_DO_NOT_STAGE')
dest=repo/'v41';shutil.copytree(ROOT/'dashboard',dest,dirs_exist_ok=True)
for relative in ['README.md','diagnostics/V41_BUILD_REPORT.md','diagnostics/locked_test_evaluation.json','diagnostics/dataset_audit.json','diagnostics/delivery_verification.json','models/V4.1_R1.json','calibration/TEMP_R1.json']:
    source=ROOT/relative;target=dest/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
for folder in ['config','scripts','tests']:
    for source in (ROOT/folder).glob('*'):
        if source.is_file() and source.suffix in {'.py','.yaml'}:
            target=dest/'source'/folder/source.name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
for source in ROOT.glob('*.py'):
    target=dest/'source'/source.name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
assert all(filehash(repo/path)==sha for path,sha in before.items()),'EXISTING_PAGES_CHANGED'
if not args.push:print(canonical({'staged_copy':str(dest),'existing_page_files_unchanged':len(before)}));raise SystemExit
git('add','--','v41')
staged=git('diff','--cached','--name-only');assert all(s.startswith('v41/') for s in staged.splitlines())
if staged:git('commit','-m','Add isolated V4.1_R1 Shadow challenger and paired forward comparison')
git('-c','http.proxy=http://127.0.0.1:16780','-c','http.sslVerify=true','push','origin','gh-pages')
commit=git('rev-parse','HEAD');remote=git('-c','http.proxy=http://127.0.0.1:16780','-c','http.sslVerify=true','ls-remote','origin','refs/heads/gh-pages').split()[0];assert remote==commit
write(ROOT/'diagnostics/push_receipt.json',{'commit':commit,'remote_commit':remote,'old_page_files_unchanged':len(before),'pushed_at':now().isoformat()});print(canonical({'commit':commit,'remote_matches':True,'old_page_files_unchanged':len(before)}))
