LEAGUE_STRENGTH={'NBA':1.00,'EuroLeague':.88,'EuroCup':.78,'ACB':.82,'CBA':.72,'NBL':.70,'domestic':.62,'youth':.45}
def roster_value(players):
    total=minutes=0.0; rows=[]
    for p in players or []:
        m=float(p.get('expected_minutes_share',0)); base=float(p.get('base_player_value',p.get('player_value',0)))
        factor=float(p.get('league_strength_factor',LEAGUE_STRENGTH.get(p.get('club_league'),'domestic')))
        avail=float(p.get('availability_multiplier',1)); adj=base*factor; contribution=adj*m*avail
        rows.append({'player':p.get('player'),'base_player_value':base,'league_adjusted_value':adj,'expected_minutes':m,'availability_multiplier':avail,'final_roster_contribution':contribution})
        total+=contribution; minutes+=m
    return {'roster_strength':total,'roster_coverage_pct':min(100,minutes*100),'minutes_coverage_pct':min(100,minutes*100),'roster_uncertainty':max(0,1-minutes),'players':rows}
