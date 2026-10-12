from __future__ import annotations
from .generic_schedule_article import parse_article

def parse_cba_article(text, source_url, published_at=None, target_year=2026):
    rows = parse_article(text, source_url, published_at, target_year)
    for row in rows:
        row.update({"league_family": "CBA_SUMMER", "source_name": "cba_article",
                    "source_group": "league_specific", "upstream_provider": "article_page",
                    "discovery_method": "league_article", "source_confidence": "high",
                    "raw_event_name": f"{row['team_1']} vs {row['team_2']}"})
    return rows
