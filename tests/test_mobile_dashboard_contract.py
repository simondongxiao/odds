import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from automation.publish_basketball import mobile_document


class MobileDashboardContractTest(unittest.TestCase):
    def setUp(self):
        self.quote = {
            "quote_id": "selected-quote",
            "bookmaker": "36",
            "market_type": "SPREAD",
            "raw_line": 5.5,
            "line_team1": -5.5,
            "decimal_prices": [1.91, 1.91],
            "raw_prices": [0.91, 0.91],
            "direction_verified": True,
            "main_or_alt": "MAIN",
            "source_quote_at": "2026-10-16T20:00:00+08:00",
            "received_at": "2026-10-16T20:00:01+08:00",
            "ot_rule": "INCLUDING_OT",
            "raw_path": "raw/should-not-be-in-mobile",
            "raw_sha256": "x" * 64,
        }

    def test_projection_keeps_visible_contract_and_drops_audit_blobs(self):
        event = {
            "event_id": "global:test",
            "bj_date": "2026-10-17",
            "tip_time_bj": "2026-10-17T07:00:00+08:00",
            "team1_name": "纽约尼克斯",
            "team2_name": "明尼苏达森林狼",
            "league": "NBA季前",
            "league_family": "NBA",
            "canonical_event_id": "canonical:test",
            "titan_schedule_row": "huge raw schedule row",
        }
        selected = {
            "market_type": "SPREAD",
            "selection": "TEAM1",
            "line": -5.5,
            "decimal_odds": 1.91,
            "quote_id": "selected-quote",
            "pricing_decomposition": {"huge": "audit-only"},
        }
        document = {
            "date_bj": "2026-10-17",
            "generated_at": "2026-10-16T20:00:00+08:00",
            "funnel": {"events": 1, "paper_bettable": 1},
            "events": [{
                "id": "global:test",
                "generation": "REPAIR_V22",
                "event": event,
                "pricing": {
                    "mu_raw": -4.0,
                    "total_raw": 220.0,
                    "input_games": 10,
                    "pricing_status": "PRICEABLE",
                    "titan_foundation_pricing": {"huge": "audit-only"},
                },
                "execution": {
                    "triggered": True,
                    "comparison_ready": True,
                    "display_action": "手动实盘候选",
                    "selected": selected,
                    "market_decisions": {"SPREAD": {
                        "triggered": True,
                        "comparison_ready": True,
                        "model_state": "EDGE",
                        "selected": selected,
                    }},
                },
                "market": {"quotes": [self.quote], "quote_states": [{
                    "fresh_observation": True,
                    "paper_quote_eligible": True,
                    "raw_observation": {"huge": "audit-only"},
                }]},
                "display": {"status": "手动实盘候选", "reasons": []},
                "settlement": {"outcome": "PENDING"},
            }],
        }
        mobile = mobile_document(document)
        row = mobile["events"][0]
        self.assertEqual(len(mobile["events"]), len(document["events"]))
        self.assertEqual(row["event"]["team1_name"], "纽约尼克斯")
        self.assertEqual(row["event"]["team2_name"], "明尼苏达森林狼")
        self.assertEqual(row["execution"]["selected"]["quote_id"], "selected-quote")
        self.assertEqual(row["market"]["quotes"][0]["quote_id"], "selected-quote")
        self.assertNotIn("titan_foundation_pricing", row["pricing"])
        self.assertNotIn("raw_path", row["market"]["quotes"][0])
        self.assertNotIn("raw_sha256", row["market"]["quotes"][0])
        self.assertNotIn("titan_schedule_row", row["event"])

    def test_index_fetch_is_cache_busted(self):
        source = (ROOT / "basketball_engine/scripts/repair_v22/report.py").read_text(encoding="utf-8")
        self.assertIn("indexUrl.searchParams.set('ts',Date.now().toString())", source)
        self.assertIn("latest.mobile.json", source)
        self.assertIn("window.__MOBILE_ROW_LIMIT__", source)
        self.assertIn("mobile-more", source)


if __name__ == "__main__":
    unittest.main()
