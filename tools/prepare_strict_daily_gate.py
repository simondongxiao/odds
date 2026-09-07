"""Expose missing v3 evidence explicitly; never promote legacy price-only picks."""
import csv
import datetime as dt
import json
from pathlib import Path
import sys

import build_football_daily_update as daily

ROOT = daily.ROOT
sys.path.insert(0, str(Path(r"D:\codex\skills\worldcup-odds-trader\scripts")))
import asian_risk_v3 as risk


def main():
    date = daily.TODAY.isoformat()
    now = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).isoformat()
    snapshot = daily.latest_snapshot()
    rows = [r for r in daily.read_csv(snapshot) if daily.in_target_list_date(r) and daily.eligible_competitive_row(r)]
    details = daily.load_details()
    gates, records = {}, []
    for row in rows:
        detail = details.get(row['match_id'], {})
        # Legacy detail summaries are not verified four-part, as-of team assessments.
        fundamental = risk.fundamental_gate({}, now)
        reason = "双方赛程密度、轮换深度与战意尚未完成结构化核验；独立净胜球模型/Delta及留出校准未接入"
        if not all(row.get(k, '') != '' for k in ('ah_full_current_line_or_draw','ah_full_current_home_or_over','ah_full_current_away_or_under')):
            reason = "亚盘盘口/水位需核验；" + reason
        evidence = ["价格候选仅供观察，不等于已验证的亚盘意图。",
                    f"盘口快照：{snapshot.name}；本次计算版本：{risk.VERSION}",
                    f"球探分析：{detail.get('analysis_url', '待核')}；伤停资料状态：{detail.get('injury_ok', '未知')}；首发状态：{detail.get('lineup_ok', '未知')}",
                    "没有真实投注数据不单独否决亚盘；本场未过的是基本面/独立模型校验。",
                    "周末不加严；原水位盈亏平衡+安全垫规则保留。"]
        gates[date+'|'+row['match_id']] = dict(action="不投", mode="none", team="无（证据待核）",
                                               reason=reason, details=evidence, rule_version=risk.VERSION,
                                               decision_at=now, snapshot_id=snapshot.stem)
        records.append({"日期":date, "比赛ID":row['match_id'], "赛事":row['league_cn'],
                        "北京时间":row.get('bj_time',''), "比赛":row['home_cn']+' vs '+row['away_cn'],
                        "原始候选":daily.asian_intent_candidate(row), "基本面状态":fundamental['Fundamental_Status'],
                        "伤停资料":detail.get('injury_ok',''), "首发确认":detail.get('lineup_ok',''),
                        "动作":"不投", "未通过环节":reason, "规则版本":risk.VERSION, "快照":str(snapshot)})
    out=ROOT/'ledger'/f'current_v3_gate_{date}.json'
    out.write_text(json.dumps(gates,ensure_ascii=False,indent=2),encoding='utf-8')
    audit=ROOT/'ledger'/f'strict_v3_evidence_audit_{date}.csv'
    with audit.open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(records[0]) if records else ['日期','比赛ID','动作','未通过环节'])
        writer.writeheader();writer.writerows(records)
    print(json.dumps({'covered':len(rows),'verified_ready':0,'evidence_pending':len(rows),'gate':str(out)},ensure_ascii=False))


if __name__=='__main__':
    main()
