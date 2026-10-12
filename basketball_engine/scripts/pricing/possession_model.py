def project_possessions(home, away):
    return (float(home['pace'])+float(away['pace']))/2

def project_score(home, away, possessions):
    def adj(t):
        return 1 + sum(float(t.get(k,0)) for k in ('transition_rate','turnover_rate','offensive_rebound_rate','free_throw_rate','three_point_attempt_rate','three_point_variance','defensive_anchor','bench_offense','bench_defense','late_foul_environment','garbage_time_tempo'))
    hp=possessions*float(home['ortg'])/100*adj(home); ap=possessions*float(away['ortg'])/100*adj(away)
    return hp, ap
