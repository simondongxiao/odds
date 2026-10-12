"""Disabled contaminated legacy demonstration. Original source is in install backup.

The former script filled pace=100, ORtg=71/82, and roster=0.5/1.0 without
numeric source evidence, then treated rank positions as rating-point inputs.
Its old output is audit-only, never a valid forecast or calibration observation.
"""
def run(*args,**kwargs):
    raise RuntimeError('LEGACY_HARDCODED_FIBA_DEMO_DISABLED: use run_basketball_daily.py --live; do not restore 4.5/153 as a verified prediction')
if __name__=='__main__':run()
