from __future__ import annotations

import csv
import datetime as dt
import hashlib
from pathlib import Path
import unittest

import v3_cup_match_state as cup


TZ = dt.timezone(dt.timedelta(hours=8))


class CupRefactorTests(unittest.TestCase):
    def test_competition_name_never_hard_blocks(self):
        gate = cup.cup_match_state_gateway(
            "英联杯", {"赛制阶段": ""}, {},
            decision_at=dt.datetime(2026, 10, 1, 12, tzinfo=TZ),
            kickoff_at=dt.datetime(2026, 10, 1, 20, tzinfo=TZ),
        )
        self.assertEqual(gate["Cup_Gateway_Status"], "PARTIAL_MISSING")
        self.assertNotIn("action", gate)
        self.assertEqual(gate["Cup_Match_State"], "MISSING")

    def test_gateway_recognizes_verified_second_leg(self):
        gate = cup.cup_match_state_gateway(
            "欧冠", {"赛制阶段": "两回合次回合；总比分 2-1"}, {},
            decision_at=dt.datetime(2026, 10, 1, 12, tzinfo=TZ),
            kickoff_at=dt.datetime(2026, 10, 1, 20, tzinfo=TZ),
        )
        self.assertEqual(gate["Cup_Match_State"], "TWO_LEG_SECOND")
        self.assertEqual(gate["Cup_Aggregate_State"], "HOME_LEADS")
        self.assertEqual(gate["Cup_Qualification_Utility"], "HOME_CAN_MANAGE_MARGIN")

    def test_pull_and_public_pull_are_separate(self):
        row = {
            "euro_full_current_home_or_over": "1.70",
            "euro_full_current_line_or_draw": "3.80",
            "euro_full_current_away_or_under": "5.00",
            "ah_full_current_line_or_draw": "1.0",
        }
        result = cup.pull_and_fair_line(row, {}, {"Cup_Qualification_Utility": "MISSING"})
        self.assertIsInstance(result["Football_Pull_Score"], float)
        self.assertEqual(result["Public_Pull"], "MISSING")
        self.assertEqual(result["Public_Pull_Basis"], "NO_VERIFIED_PUBLIC_FLOW")

    def test_fair_line_changes_with_match_strength(self):
        weak = {"euro_full_current_home_or_over": "2.60", "euro_full_current_line_or_draw": "3.20", "euro_full_current_away_or_under": "2.70", "ah_full_current_line_or_draw": "0"}
        strong = {"euro_full_current_home_or_over": "1.35", "euro_full_current_line_or_draw": "5.00", "euro_full_current_away_or_under": "8.00", "ah_full_current_line_or_draw": "0"}
        gateway = {"Cup_Qualification_Utility": "MISSING"}
        self.assertGreater(cup.pull_and_fair_line(strong, {}, gateway)["fair_handicap"], cup.pull_and_fair_line(weak, {}, gateway)["fair_handicap"])

    def test_intent_can_be_confirmed_or_rejected_for_same_cup(self):
        confirmed = cup.refine_intent("诱上/阻下", -1.0, {"fair_handicap": -0.5})
        rejected = cup.refine_intent("真实示强/阻上", -1.0, {"fair_handicap": -0.25})
        self.assertEqual(confirmed["Cup_Intent"], "诱上/阻下")
        self.assertEqual(rejected["Cup_Intent"], "平衡盘/等待临场确认")

    def test_hierarchy_backoff_and_local_evidence(self):
        rows = [
            {"赛事": "英联杯", "倾向意图": "诱上/阻下", "结算标签": "红", "实际盈亏Unit": "0.9"},
            {"赛事": "英联杯", "倾向意图": "诱上/阻下", "结算标签": "黑", "实际盈亏Unit": "-1"},
            {"赛事": "欧冠", "倾向意图": "诱上/阻下", "结算标签": "红", "实际盈亏Unit": "0.8"},
        ]
        model = cup.HierarchicalCupEvidence(rows)
        exact = model.posterior("英联杯", "诱上/阻下", "MISSING")
        unseen = model.posterior("挪威杯", "诱上/阻下", "MISSING")
        self.assertEqual(exact["Cup_Bayes_Level"], "L1_COMPETITION_INTENT_STATE")
        self.assertIn(unseen["Cup_Bayes_Level"], {"L2_DOMAIN_INTENT", "L3_MICRO_REGION_INTENT", "L4_GLOBAL_TAG"})
        self.assertGreater(exact["Cup_Bayes_Posterior"], 0)
        self.assertLess(exact["Cup_Bayes_Posterior"], 1)

    def test_future_only_activation(self):
        before = cup.cup_match_state_gateway(
            "欧冠", {"赛制阶段": "小组赛"}, {},
            decision_at=cup.ACTIVATION_AT - dt.timedelta(minutes=1),
            kickoff_at=cup.ACTIVATION_AT + dt.timedelta(hours=3),
        )
        after = cup.cup_match_state_gateway(
            "欧冠", {"赛制阶段": "小组赛"}, {},
            decision_at=cup.ACTIVATION_AT + dt.timedelta(minutes=1),
            kickoff_at=cup.ACTIVATION_AT + dt.timedelta(hours=3),
        )
        self.assertFalse(before["Cup_Refactor_Eligible"])
        self.assertTrue(after["Cup_Refactor_Eligible"])

    def test_historical_freezes_unchanged(self):
        backup = Path(r"D:\codex\outputs\football_odds_trader\backups\v3_cup_refactor_20260930_153649\historical_freeze_hashes_before.csv")
        with backup.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertTrue(rows)
        for row in rows:
            path = Path(row["Path"])
            self.assertTrue(path.exists())
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest().upper(), row["SHA256"].upper())

    def test_domain_classifier(self):
        self.assertEqual(cup.NORMALIZER.competition_domain("欧冠"), "CONTINENTAL_CLUB")
        self.assertEqual(cup.NORMALIZER.competition_domain("英联杯"), "CLUB_CUP")
        self.assertEqual(cup.NORMALIZER.competition_domain("非洲杯"), "NATIONAL_OFFICIAL")
        self.assertEqual(cup.NORMALIZER.competition_domain("东盟杯"), "NATIONAL_OFFICIAL")


if __name__ == "__main__":
    unittest.main()
