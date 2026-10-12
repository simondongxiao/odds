"""Legacy compatibility functions; a real Student-t, not a renamed logistic CDF.
The argument historically called scale is now documented as residual standard deviation.
"""
from repair_v22.verified_core import t_cdf, threshold_probability

def cdf(x, mu, scale, df=6):
    return t_cdf(x, mu, scale, df)

def interval(mu, scale, df=6):
    def q(p):
        lo,hi=mu-100*scale,mu+100*scale
        for _ in range(90):
            mid=(lo+hi)/2
            if cdf(mid,mu,scale,df)<p:lo=mid
            else:hi=mid
        return (lo+hi)/2
    return {'p10':q(.1),'p50':mu,'p90':q(.9),'standard_deviation':scale}

def push_probs(line, mu, scale, df=6):
    p=threshold_probability(lambda x:cdf(x,mu,scale,df),line,'OVER')
    return {'p_win':p.win,'p_push':p.push,'p_loss':p.loss}
