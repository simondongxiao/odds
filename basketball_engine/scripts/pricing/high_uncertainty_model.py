def structural_margin(home, away):
    return float(home.get('prior_margin',0))+float(home.get('roster_value',0))-float(away.get('roster_value',0))
