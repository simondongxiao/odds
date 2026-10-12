def structural_margin(home, away):
    return float(home['prior'])-float(away['prior'])+float(home.get('roster_value',0))-float(away.get('roster_value',0))+float(home.get('context_adjustment',0))-float(away.get('context_adjustment',0))
