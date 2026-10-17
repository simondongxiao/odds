from __future__ import annotations
import argparse, json, traceback
from pathlib import Path
from .pipeline import execute
from .common import now, BJ, load, atomic, stamp, iso, fingerprint
from datetime import timedelta

def main(argv=None):
    workspace=Path(__file__).resolve().parents[4]
    ap=argparse.ArgumentParser(description='篮球 v2.2：实际抓取→补全→独立定价→同规则判断→冻结→页面')
    ap.add_argument('--root',default=str(workspace/'outputs'/'basketball_odds_trader'))
    ap.add_argument('--date',default='auto')
    ap.add_argument('--live',action='store_true')
    ap.add_argument('--replay-bundle',help='已解压源码诊断包根目录；离线核查单独输出，不冒充前向样本')
    ap.add_argument('--session-id')
    ap.add_argument('--backtest-recent',type=int,default=0)
    ap.add_argument('--publish-beta',action='store_true')
    ap.add_argument('--publish-dir','--publish',dest='publish_dir')
    ap.add_argument('--push',action='store_true',help='显式允许在已存在仓库提交并推送篮球 beta 文件')
    ap.add_argument('--timeout',type=int,default=12)
    # The skill caps public HTTP concurrency at six.  Use the cap by default
    # so a normal production run does not leave four network workers idle
    # while still preserving the bounded-request contract.
    ap.add_argument('--workers',type=int,default=6)
    a=ap.parse_args(argv)
    if not 0<=a.backtest_recent<=365:ap.error('--backtest-recent 应在0~365之间')
    if not 1<=a.workers<=6 or not 1<=a.timeout<=60:ap.error('workers 应为1~6，timeout 应为1~60')
    root=Path(a.root)
    if a.replay_bundle:
        root=root/'validation'/'bundle_audit'
        if a.publish_beta or a.publish_dir or a.push:ap.error('离线核查不能发布成实时结果')
    pub=a.publish_dir
    if a.publish_beta and not pub:
        candidates=[workspace/'outputs/football_odds_trader/github_publish/odds',workspace/'github_publish/odds',workspace/'odds']
        pub=next((str(p) for p in candidates if (p/'.git').exists()),None)
    try:
        result=execute(root,a.date,live=a.live,bundle=a.replay_bundle,session_id=a.session_id,
              backtest_n=a.backtest_recent,publish_dir=pub,push=a.push,timeout=a.timeout,workers=a.workers)
        if a.publish_beta and not pub:result['publish']={'status':'NOT_CONFIGURED','reason':'未找到现有发布仓库；本地结果已生成，用 --publish-dir 指定仓库根目录。'}
        print(json.dumps(result,ensure_ascii=False,indent=2));return 0 if result.get('update_status')!='FAILED' else 2
    except Exception as exc:
        traceback.print_exc()
        error={'status':'FAILED','error_type':type(exc).__name__,'message':str(exc),'real_execution_allowed':False}
        atomic(root/'audits'/'repair_v22_failure.json',error)
        print(json.dumps(error,ensure_ascii=False,indent=2));return 2

def checkpoint_main(argv=None):
    workspace=Path(__file__).resolve().parents[4]
    ap=argparse.ArgumentParser(description='实际checkpoint执行器；需由Windows计划任务调用，不会自称后台已启动')
    ap.add_argument('--root',default=str(workspace/'outputs/basketball_odds_trader'));ap.add_argument('--publish-dir');ap.add_argument('--force',action='store_true')
    a=ap.parse_args(argv);root=Path(a.root);t=now();day=t.astimezone(BJ).date().isoformat()
    manifest=root/'manifests'/'repair_checkpoint_state.json';state=load(manifest,{'checkpoints':{}});due=[]
    for p in (root/'dashboard_v2'/'data').glob('20??-??-??.json'):
        if p.stem<day:continue
        for row in load(p,{}).get('events',[]):
            e=row.get('event',{});tip=e.get('tip_at')
            if not tip:continue
            for name,mins in [('T-24h',1440),('T-6h',360),('T-90m',90),('T-30m',30),('T-5m',5)]:
                key=e['event_id']+'|'+tip+'|'+name;dt=iso(tip)-timedelta(minutes=mins)
                if key in state['checkpoints']:continue
                if dt<=t<dt+timedelta(minutes=6) and t<iso(tip):due.append(key)
                elif t>=dt+timedelta(minutes=6):state['checkpoints'][key]={'status':'MISSED','observed_at':stamp(t)}
    if due or a.force:
        r=execute(root,day,live=True,publish_dir=a.publish_dir)
        for key in due:state['checkpoints'][key]={'status':'ATTEMPTED','run_id':r.get('run_id'),'result':r.get('update_status'),'at':stamp()}
    else:r={'status':'NO_DUE_CHECKPOINT','scheduler_installed_by_this_command':False}
    state['last_check_at']=stamp();atomic(manifest,state);print(json.dumps(r,ensure_ascii=False,indent=2));return 0
