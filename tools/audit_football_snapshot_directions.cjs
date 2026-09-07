const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const cp = require('node:child_process');
const crypto = require('node:crypto');
const root = 'D:/codex/outputs/football_odds_trader';
const repo = path.join(root, 'github_publish/odds');
const refs = ['40fc6d2','0f2577d','3867a15','a7fa39a','66e0a62','9a01ffc','8027010'];
const out = path.join(root, 'reviews/direction_audit_20260907');
fs.mkdirSync(out, {recursive:true});
const output = [];
const contexts = new Map();
for (const ref of refs) {
  try {
    const html = cp.execFileSync('git', ['-C',repo,'show',`${ref}:index.html`], {maxBuffer:128*1024*1024}).toString('utf8');
    const timestamp = cp.execFileSync('git', ['-C',repo,'show','-s','--format=%aI',ref]).toString().trim();
    const script = [...html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/g)].map(m=>m[1]).find(s=>s.includes('const cardsData = '));
    const context = vm.createContext({document:{},window:{},console:{log(){},warn(){}}});
    vm.runInContext(script.replace(/\binit\(\);\s*$/, ''), context, {timeout:30000});
    contexts.set(ref, context);
    const rows = JSON.parse(JSON.stringify(vm.runInContext(`cardsData.filter(r=>['2026-09-04','2026-09-07'].includes(r.date)).map(r=>{
      const cell=intentMatrixCell(r.intent_line_bucket,r.intent_tag);
      const d=typeof plannedSkillDecision==='function'?plannedSkillDecision(r):(typeof frozenSkillDecision==='function'&&frozenSkillDecision(r))||top5Decision(r,cell)||frameworkDecision(r,cell);
      return {date:r.date,id:r.match_id,match:r.display_match,time:r.time,league:r.league,state:r.state,
        ah:r.ah,euro:r.euro,total:r.total,tag:r.intent_tag,forward:r.intent_forward_team,region:r.micro_region,
        selected_side:d.frozen?(String(r.frozen_bettable_side).includes('上盘')?'upper':String(r.frozen_bettable_side).includes('下盘')?'lower':''):(d.mode==='forward'?r.intent_forward_side:d.mode==='reverse'?reverseSide(r.intent_forward_side):''),
        decision:d,tag_stats:tagPerformanceEntry(r.intent_tag),cell,edge:microEdgeEntry(r),risk:riskEntry(r)};
    })`,context,{timeout:30000})));
    fs.writeFileSync(path.join(out,`${ref}_replayed.json`),JSON.stringify({ref,timestamp,rows},null,2));
    const groups=[...new Set(rows.map(r=>r.date))].map(date=>{
      const pool=rows.filter(r=>r.date===date);
      const eligible=pool.filter(r=>['可投','半仓可投'].includes(r.decision.action));
      const level=r=>/即 [^/]+\/[-]?0(?:\.0)?\//.test(r.ah);
      const summary=rs=>({n:rs.length,upper:rs.filter(r=>!level(r)&&r.selected_side==='upper').length,lower:rs.filter(r=>!level(r)&&r.selected_side==='lower').length,level:rs.filter(level).length});
      return {date,total:pool.length,eligible:summary(eligible),top5:summary(eligible.filter(r=>r.region==='欧洲五大系列'))};
    });
    output.push({ref,timestamp,groups,matches:rows.filter(r=>['3013674','2995332'].includes(r.id))});
  } catch(error) {output.push({ref,error:String(error)});}
}
const counterfactual = [];
if (contexts.has('3867a15') && contexts.has('a7fa39a')) {
  const old = contexts.get('3867a15');
  const latest = contexts.get('a7fa39a');
  for (const id of ['3013674','2995332']) {
    old.auditCard = JSON.parse(JSON.stringify(vm.runInContext(`cardsData.find(r=>r.match_id==='${id}')`, latest)));
    counterfactual.push({id, old_statistics_and_function_new_card: JSON.parse(JSON.stringify(vm.runInContext('frameworkDecision(auditCard,intentMatrixCell(auditCard.intent_line_bucket,auditCard.intent_tag))', old)))});
  }
  const hash = ctx=>crypto.createHash('sha256').update(vm.runInContext('frameworkDecision.toString()',ctx)).digest('hex');
  fs.writeFileSync(path.join(out,'counterfactual.json'), JSON.stringify({old_function_hash:hash(old),new_function_hash:hash(latest),counterfactual},null,2));
}
fs.writeFileSync(path.join(out,'version_comparison.json'),JSON.stringify(output,null,2));
console.log(JSON.stringify(output.map(v=>({...v,matches:v.matches?.map(r=>({match:r.match,tag:r.tag,ah:r.ah,euro:r.euro,action:r.decision.action,team:r.decision.team,reason:r.decision.reason}))})),null,2));
