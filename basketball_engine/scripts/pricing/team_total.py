def team_totals(home_points, away_points, market=None):
    return {'fair_home_team_total':home_points,'fair_away_team_total':away_points,
            'market_home_team_total':(market or {}).get('home'),'market_away_team_total':(market or {}).get('away')}
