"""Finalize frozen-plan settlement and disclose uncompleted v3 evidence gates."""
import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
import sys

ROOT=Path(r'D:\codex\outputs\football_odds_trader')
sys.path.insert(0,r'D:\codex\skills\worldcup-odds-trader\scripts')
import asian_risk_v3 as risk
import build_football_daily_update as daily
import build_bettable_event_stats as categories


def read(path):
    with path.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))


def write(path, rows, fields):
    with path.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');w.writeheader();w.writerows(rows)


def main():
    date='2026-09-08'
    lock=json.loads((ROOT/'ledger/dashboard_plan_lock_20260908.json').read_text(encoding='utf-8'))
    raw_path=daily.latest_snapshot()
    current={r['match_id']:r for r in read(raw_path)}
    detail_path=ROOT/f'ledger/bettable_event_detail_{date}.csv'
    fields=list(read(detail_path)[0])
    fields += ['原模拟ID','记录口径']
    output=[]; seen=set()
    for entry in lock['records']:
        c,d=entry['card'],entry['decision']
        if d.get('action') not in ('可投','半仓可投'):continue
        identity=(c['date'],c.get('match_id') or c.get('sim_id'),d.get('team'),c.get('ah'))
        if identity in seen:continue
        seen.add(identity)
        team=d.get('team','').split('（')[0]
        home,away=c['match'].split(' vs ',1)
        parts=re.findall(r'(-?\d+(?:\.\d+)?)/(-?\d+(?:\.\d+)?)/(-?\d+(?:\.\d+)?)',c.get('ah',''))
        line=None
        if parts and team in (home,away):line=-float(parts[-1][1]) if team==home else float(parts[-1][1])
        live=current.get(c.get('match_id'),{})
        state=str(live.get('state',c.get('state','')))
        score=f"{live['home_score']}-{live['away_score']}" if live.get('home_score','')!='' and live.get('away_score','')!='' else c.get('score','')
        label='待结算' if state in ('1','2','3','4') else '赛果待核'
        unit=None
        water=d.get('water')
        if state=='-1' and re.fullmatch(r'\d+-\d+',score) and line is not None and water:
            hs,aws=map(int,score.split('-'))
            outcome=risk.result_units(hs-aws if team==home else aws-hs,line)
            label={1:'红',.5:'红半',0:'走水',-.5:'黑半',-1:'黑'}[outcome]
            unit=outcome*float(water) if outcome>0 else outcome
        league=c.get('league','')
        row={f:'' for f in fields}
        row.update({'统计日期':date,'数据源':lock['source'],'日期':c['date'],'开赛时间':c.get('time',''),
                    '比赛ID':c.get('match_id',''),'赛事':league,'比赛':c['match'],'微观板块':c.get('micro_region','未识别'),
                    '国家':categories.country_from_league(league),'赛事层级':categories.tier_from_class('',league),
                    '盘口':c.get('intent_line_bucket',''),'水位分层':categories.water_bucket(water),'倾向意图':c.get('intent_tag',''),
                    '动作':'反向' if d['mode']=='reverse' else '正向','投注盘向':'上盘' if line is not None and line<0 else '下盘' if line else '平手/待核',
                    '投注球队':team,'选中水位':water,'综合胜率':d.get('rate',''),'通过阈值':d.get('threshold',''),
                    '已结算':'是' if unit is not None else '否','结算标签':label,'实际盈亏Unit':round(unit,4) if unit is not None else '',
                    '赛果':score,'比分来源':str(raw_path) if live else '原页面赛果留底','即时亚盘':c.get('ah',''),
                    '盘口线':line,'原模拟ID':c.get('sim_id',''),'记录口径':'原页面冻结计划；同比赛同队同盘去重；均注模拟非真实成交'})
        output.append(row)
    write(detail_path,output,fields)
    stats_path=ROOT/f'ledger/bettable_event_stats_{date}.csv'
    stats_fields=list(read(stats_path)[0])
    groups=defaultdict(list)
    for r in output:
        if r['已结算']=='是':groups[tuple(r[k] for k in ('微观板块','国家','赛事层级','盘口','水位分层','倾向意图'))].append(r)
    stats=[]
    for key,rs in groups.items():
        counts=Counter(r['结算标签'] for r in rs);wins=counts['红']+.5*counts['红半'];loss=counts['黑']+.5*counts['黑半'];n=len(rs)
        pnl=sum(r['实际盈亏Unit'] for r in rs)
        x=dict(zip(('地区','国家','赛事层级','盘口','水位分层','倾向意图'),key))
        x.update({'统计日期':date,'数据源':str(detail_path),'样本':n,**{k:counts[k] for k in ('红','红半','走水','黑半','黑')},
                  '有效胜率':round(wins/(wins+loss),4) if wins+loss else '', '负率':round(loss/(wins+loss),4) if wins+loss else '',
                  '均注盈亏Unit':round(pnl,4),'平均水位':round(sum(float(r['选中水位']) for r in rs)/n,4),'ROI':round(pnl/n,4),
                  '备注':'冻结页面计划均注模拟；不同旧版本不得解释为新版通过或真实成交'})
        stats.append(x)
    write(stats_path,stats,stats_fields)
    yesterday=[r for r in output if r['日期']=='2026-09-07']
    settled=[r for r in yesterday if r['已结算']=='是']
    counts=Counter(r['结算标签'] for r in settled)
    pnl=sum(r['实际盈亏Unit'] for r in settled)
    lines=['# 2026-09-07 冻结可投计划结算', '',f"原计划{len(yesterday)}场，已结算{len(settled)}场；红{counts['红']}、红半{counts['红半']}、走水{counts['走水']}、黑半{counts['黑半']}、黑{counts['黑']}；均注盈亏{pnl:+.4f} Unit。",'',
           '|比赛|原选球队|原有符号盘口|水位|最新比分|结算|盈亏Unit|','|---|---|---:|---:|---|---|---:|']
    for r in yesterday:lines.append(f"|{r['比赛']}|{r['投注球队']}|{r['盘口线']}|{r['选中水位']}|{r['赛果']}|{r['结算标签']}|{r['实际盈亏Unit']}|")
    lines+=['','按原页面选队与水位结算，不使用现在的标签胜率改队。进行中比赛不计入胜率、ROI。','比分来源：'+str(raw_path)]
    review=ROOT/'reviews/frozen_bettable_settlement_2026-09-07.md';review.write_text('\n'.join(lines),encoding='utf-8')
    report=ROOT/'daily/2026-09-08_titan007_strict_update.md'
    legacy=report.read_text(encoding='utf-8')
    legacy=legacy.replace('严格按 skill 更新（Titan007赔率快照）','数据更新与校验缺口（未完成新版完整分析）')
    legacy=legacy.replace('等待HTML红框EV漏斗判断','新版校验待核；不作为可执行投注')
    prefix='\n> 本轮状态：盘口/比分/网页/分组回顾已刷新，但新版完整分析未完成。52场均尚未完成双方赛程、轮换深度、战意及独立Delta模型校验；确认可执行0场。28场有伤停资料，确认首发0场。缺PM/必发不是单独否决原因，周末不加严。后续兼容层统计仅作观察，不得理解为已通过新版。\n\n'
    report.write_text(legacy.split('\n',1)[0]+prefix+legacy.split('\n',1)[1]+'\n\n'+ '\n'.join(lines),encoding='utf-8')
    print(json.dumps({'frozen_unique_plans':len(output),'yesterday':len(yesterday),'settled':len(settled),'pnl':pnl,'labels':dict(counts)},ensure_ascii=False))


if __name__=='__main__':main()
