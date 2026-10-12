def shrink(mu_structural, market_margin, model_weight):
    w=min(1,max(0,float(model_weight)))
    return w*mu_structural+(1-w)*market_margin

def initial_weight(family, quality):
    base={'CLUB_MATURE':.65,'NATIONAL_TEAM':.40,'HIGH_UNCERTAINTY':.22}.get(family,.25)
    return max(.05,min(.85,base*(.6+.4*quality/100)))
