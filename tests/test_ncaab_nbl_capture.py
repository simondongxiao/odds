import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "basketball_engine"))
sys.path.insert(0, str(ROOT / "basketball_engine" / "scripts"))

from global_discovery import classify  # noqa: E402
from discover_events import classify_family  # noqa: E402
from repair_v22.common import competition_key  # noqa: E402
from repair_v22.source import upcoming_7m_deep_capture_event_ids  # noqa: E402
from providers.titan007_history_adapter import (  # noqa: E402
    _team_search_queries,
    parse_search_response,
)


def test_ncaab_is_a_formal_competition_family():
    assert competition_key("NCAA") == "NCAAB"
    assert classify("NCAA") [0] == "NCAAB"
    assert classify_family("NCAA Men's Basketball") == "NCAAB"


def test_nbl_aliases_keep_reviewed_search_variants():
    queries = _team_search_queries("塔斯曼尼亚跳蚁")
    assert "塔斯曼尼亚跳蚁" in queries
    assert "塔斯马尼亚跳蚁" in queries
    assert "Tasmania JackJumpers" in queries


def test_titan_search_accepts_an_exact_reviewed_alias_only():
    html = (
        '<table><tr><td>澳大利亚NBL</td><td>塔斯马尼亚跳蚁</td>'
        '<td><a href="Team.aspx?TeamID=9001">Tasmania JackJumpers</a></td>'
        '<td><a href="League.aspx?SclassID=22">NBL</a></td></tr></table>'
    )
    parsed = parse_search_response(html, "Tasmania JackJumpers")
    assert parsed["status"] == "EXACT"
    assert parsed["exact"]["team_id"] == "9001"


def test_next_day_nbl_and_ncaab_are_pre_warmed():
    events = [
        {
            "event_id": "7m:nbl",
            "source": "7M",
            "bj_date": "2026-10-16",
            "league": "澳大利亚国家篮球联赛",
            "league_family": "AUSTRALIA_NBL",
            "tip_at": "2026-10-16T12:00:00+08:00",
        },
        {
            "event_id": "7m:ncaa",
            "source": "7M",
            "bj_date": "2026-10-17",
            "league": "NCAA",
            "league_family": "NCAAB",
            "tip_at": "2026-10-17T12:00:00+08:00",
        },
    ]
    observed = datetime(2026, 10, 15, tzinfo=timezone.utc)
    assert upcoming_7m_deep_capture_event_ids(events, "2026-10-16", observed) == {
        "7m:nbl",
        "7m:ncaa",
    }
