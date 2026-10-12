def structural_margin(home, away, adjustments=None):
    adjustments=adjustments or {}
    return (float(home['ortg'])-float(home['drtg']))-(float(away['ortg'])-float(away['drtg']))+float(adjustments.get('home_court',0))+float(adjustments.get('lineup',0))+float(adjustments.get('rest',0))+float(adjustments.get('travel',0))+float(adjustments.get('matchup',0))
