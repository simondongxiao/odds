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
from repair_v22.model import quote_state  # noqa: E402
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


def _quote_for_current_board(event_id="7m:nbl"):
    return {
        "quote_id": "q1", "event_id": event_id, "bookmaker_id": "7m-company:0",
        "status": "OBSERVED", "current_board_contract_verified": True,
        "source_timestamp_semantics": "LAST_CHANGE",
        "source_quote_at": "2026-10-14T10:00:00+00:00",
        "received_at": "2026-10-16T09:59:00+00:00",
        "raw_verified": True, "period": "FULL_GAME", "main_or_alt": "MAIN",
        "price_format_verified": True, "direction_verified": True,
        "ot_rule": "INCLUDING_OT", "rule_evidence": "policy",
    }


def test_current_board_receipt_overrides_old_nbl_last_change_for_freshness():
    event = {"event_id": "7m:nbl", "identity_verified": True,
             "tip_at": "2026-10-16T12:00:00+00:00"}
    state = quote_state(_quote_for_current_board(), event,
                        "2026-10-16T10:00:00+00:00")
    assert state["paper_quote_eligible"] is True
    assert "STALE_QUOTE" not in state["reasons"]
    assert "QUOTE_LAST_CHANGE_OLD" in state["warnings"]
    assert state["freshness_basis"] == "VERIFIED_CURRENT_BOARD_CAPTURE"


def test_unverified_current_board_still_blocks_old_quote():
    event = {"event_id": "7m:nbl", "identity_verified": True,
             "tip_at": "2026-10-16T12:00:00+00:00"}
    quote = _quote_for_current_board()
    quote["current_board_contract_verified"] = False
    state = quote_state(quote, event, "2026-10-16T10:00:00+00:00")
    assert "STALE_QUOTE" in state["reasons"]
    assert state["paper_quote_eligible"] is False
