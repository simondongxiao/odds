from __future__ import annotations
from .archive_snapshot import save_immutable

CHECKPOINTS=('T-24h','T-6h','T-90m','T-30m','T-5m')
def archive_checkpoint(root,event,checkpoint,pricing_cutoff,raw,enrichment,pricing):
    if checkpoint not in CHECKPOINTS: raise ValueError(checkpoint)
    return save_immutable(root,'FORWARD_NATIVE',f"{event['canonical_event_id']}_{checkpoint}",{
        'canonical_event_id':event['canonical_event_id'],'league_family':event.get('league_family'),
        'tip_time':event.get('tip_time_utc') or event.get('tip_utc'),'pricing_cutoff':pricing_cutoff,
        'checkpoint':checkpoint,'raw_snapshot':raw,'enrichment_snapshot':enrichment,'pricing_snapshot':pricing})
