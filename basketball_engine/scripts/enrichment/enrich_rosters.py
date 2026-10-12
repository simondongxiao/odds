from datetime import datetime
def enrich(event, rosters, cutoff):
    out=[]; blocked=[]
    for row in rosters or []:
        captured=row.get('captured_at') or row.get('source_published_at')
        if captured and captured>cutoff: blocked.append(row); continue
        out.append(row)
    return {'roster':out,'blocked':blocked,'leakage_blocked':bool(blocked),'input_captured_at':cutoff}
