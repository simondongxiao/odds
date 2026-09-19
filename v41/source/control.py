"""Run an exact-byte CONTROL copy with redirected output root, never original V4."""
import contextlib,importlib.util,io,shutil,sys
from .common import *
def verify_original(allow_daily_outputs=False):
    manifest=read(ROOT/'data/control_baseline/manifest.json');protected=[x for x in manifest['files'] if not allow_daily_outputs or Path(x['source']).suffix=='.py'];bad=[x['source'] for x in protected if not Path(x['source']).exists() or filehash(x['source'])!=x['sha256']]
    if bad:raise ValueError('CONTROL_CHANGED:'+str(bad))
    return {'checked':len(protected),'unchanged':True,'scope':'RULE_SOURCE_ONLY_ALLOW_INDEPENDENT_DAILY_OUTPUTS' if allow_daily_outputs else 'FULL_BUILD_BASELINE','baseline_commit':manifest['git_commit']}
def original_state():
    return {str(p):filehash(p) for p in (WORKSPACE/'v4').rglob('*') if p.is_file() and '__pycache__' not in p.parts}
def run(day,raw_csv,run_id):
    verify_original(True);before=original_state();baseline=ROOT/'data/control_baseline';sandbox=ROOT/'control_runs'/run_id;sandbox.mkdir(parents=True,exist_ok=False)
    relative=Path('outputs/football_odds_trader/research/v4_market_base_ready.csv');dest=sandbox/relative;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(baseline/relative,dest)
    saved={n:sys.modules.get(n) for n in ['direction_contract','v4_dual_pipeline','v41_control_runtime']};argv=sys.argv[:]
    try:
        for name,filename in [('direction_contract','direction_contract.py'),('v4_dual_pipeline','v4_dual_pipeline.py'),('v41_control_runtime','run_daily_v4.py')]:
            spec=importlib.util.spec_from_file_location(name,baseline/'v4'/filename);module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module)
            if hasattr(module,'ROOT'):module.ROOT=sandbox
        sys.argv=['control','--list-date',day,'--raw-csv',str(raw_csv)]
        with contextlib.redirect_stdout(io.StringIO()):module.main()
        out=read(sandbox/'v4/outputs'/f'v4_decisions_{day}.json')
        write(sandbox/'control_manifest.json',{'role':'CONTROL','source':'EXACT_BYTE_V4_RUNTIME_WITH_OUTPUT_ROOT_REDIRECT','original_v4_untouched':True,'real_money':False,'input_csv':str(raw_csv),'input_sha256':filehash(raw_csv),'run_at':now().isoformat()},immutable=True)
        return {r['match_id']:r for r in out['matches']}
    finally:
        sys.argv=argv
        for n,m in saved.items():
            if m is None:sys.modules.pop(n,None)
            else:sys.modules[n]=m
        verify_original(True)
        if original_state()!=before:raise ValueError('ORIGINAL_V4_CHANGED_DURING_ISOLATED_RUN')
