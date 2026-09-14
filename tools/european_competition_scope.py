"""Compatibility wrapper around the unified competition normalizer."""

from football_competition_normalizer import normalize

def competition_scope(league: str) -> str | None:
    value = normalize(league)
    return value.competition_scope if value.competition_scope in {
        "欧冠独立赛事", "欧联独立赛事", "欧协联独立赛事",
        "亚冠精英独立赛事", "亚冠2独立赛事", "亚冠独立赛事",
        "亚运会足球独立赛事",
    } else None
