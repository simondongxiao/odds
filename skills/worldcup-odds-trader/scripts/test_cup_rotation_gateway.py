import unittest
from copy import deepcopy

import cup_rotation_gateway as gw


def fixture():
    evidence = {"Source": "synthetic-only", "Available_At": "2026-09-07T10:00:00+08:00"}
    teams = {team: {**evidence, "Schedule_Density": "正常", "Rotation_Risk": "低", "Strategic_Intent": "正常"}
             for team in ("A", "B")}
    return {"Match_ID": "second", "Tie_ID": "tie-1", "Match_Nature": "联赛",
            "Home_Team_ID": "A", "Away_Team_ID": "B", "Selected_Team_ID": "A",
            "Home_Handicap": -.75, "Neutral_Venue": False, "Base_Confidence": 100,
            "Confidence_Basis": "before_context_adjustment",
            "Decision_At": "2026-09-07T11:00:00+08:00", "Kickoff_At": "2026-09-08T03:00:00+08:00",
            "Nature_Evidence": evidence, "Venue_Evidence": evidence, "Teams": teams,
            "Fundamental_Evidence": {side: {key: {"source": "synthetic-only", "available_at": evidence["Available_At"], "status": "clear"}
                                              for key in ("schedule", "absences", "rotation_depth", "motivation")}
                                     for side in ("home", "away")},
            "First_Leg": {**evidence, "Match_ID": "first", "Tie_ID": "tie-1",
                          "Home_Team_ID": "B", "Away_Team_ID": "A", "Home_Goals": 0, "Away_Goals": 2,
                          "Finished_At": "2026-09-01T05:00:00+08:00"}}


class GatewayTests(unittest.TestCase):
    def call(self, data, **kwargs):
        called = []
        def delta():
            called.append("delta")
            return {"Delta_Conv": -.045}
        def funnel(metrics):
            called.append("funnel")
            self.assertEqual(metrics["Delta_Conv"], -.045)
            return {"Execution_Status": "READY", "Stake": 500, "original_pick": "A"}
        output = gw.run_guarded_analysis(data, calculate_delta=delta, existing_funnel=funnel,
                                         bankroll=10000, **kwargs)
        return output, called

    def test_exact_two_goal_lead_blocks_before_delta(self):
        data = fixture()
        data["Match_Nature"] = "两回合次回合"
        output, called = self.call(data)
        self.assertEqual(output["Execution_Status"], "强制跳过（警惕轮换与功利控盘）")
        self.assertEqual(output["First_Leg_Leader_ID"], "A")
        self.assertEqual(output["Stake"], 0)
        self.assertEqual(called, [])

    def test_either_leader_blocks_whole_match(self):
        for home_goals, away_goals in [(3, 0), (0, 3), (2, 0), (0, 2)]:
            for selected in ("A", "B"):
                data = fixture()
                data.update(Match_Nature="两回合次回合", Selected_Team_ID=selected)
                data["First_Leg"].update(Home_Goals=home_goals, Away_Goals=away_goals)
                self.assertEqual(self.call(data)[0]["Execution_Code"], "SKIP_SECOND_LEG_LEAD")

    def test_one_goal_lead_does_not_trigger_automatic_skip(self):
        data = fixture()
        data["Match_Nature"] = "两回合次回合"
        data["First_Leg"]["Away_Goals"] = 1
        output, called = self.call(data)
        self.assertEqual(output["Gateway_Status"], "PASS")
        self.assertEqual(called, ["delta", "funnel"])

    def test_missing_first_leg_is_unknown_not_zero(self):
        data = fixture()
        data["Match_Nature"] = "两回合次回合"
        del data["First_Leg"]
        self.assertEqual(self.call(data)[0]["Gateway_Status"], "DATA_PENDING")

    def test_wrong_tie_or_team_and_future_result(self):
        for field, value in [("Tie_ID", "other"), ("Home_Team_ID", "C"), ("Available_At", "2026-09-08T11:00:00+08:00")]:
            data = fixture()
            data["Match_Nature"] = "两回合次回合"
            data["First_Leg"][field] = value
            output, called = self.call(data)
            self.assertEqual(output["Gateway_Status"], "DATA_PENDING")
            self.assertEqual(called, [])

    def test_single_leg_and_first_leg_ignore_stale_first_leg_field(self):
        for nature in ("联赛", "单场杯赛", "两回合首回合"):
            data = fixture()
            data["Match_Nature"] = nature
            self.assertEqual(self.call(data)[0]["Execution_Status"], "READY")

    def test_dense_high_rotation_default_skip(self):
        for line, favorite in [(-.75, "A"), (-1, "A"), (.75, "B"), (1, "B")]:
            data = fixture()
            data["Home_Handicap"] = line
            data["Teams"][favorite].update(Schedule_Density="一周双赛", Rotation_Risk="高")
            self.assertEqual(self.call(data)[0]["Execution_Code"], "SKIP_DENSE_DEEP_ROTATION")

    def test_quarter_cap_is_absolute_not_double_multiplier(self):
        data = fixture()
        data["Teams"]["A"].update(Schedule_Density="一周双赛", Rotation_Risk="高")
        output, called = self.call(data, policy=gw.GatewayPolicy(dense_deep_action="quarter"))
        self.assertEqual(output["Stake"], 125)
        self.assertEqual(output["Stake_Cap_Units"], .25)
        self.assertEqual(called, ["delta", "funnel"])

    def test_other_line_and_low_rotation_not_dense_hard_stop(self):
        data = fixture()
        data["Home_Handicap"] = -1.25
        data["Teams"]["A"].update(Schedule_Density="一周双赛", Rotation_Risk="高")
        self.assertEqual(self.call(data)[0]["Gateway_Status"], "PASS")
        data["Home_Handicap"] = -.75
        data["Teams"]["A"]["Rotation_Risk"] = "低"
        self.assertEqual(self.call(data)[0]["Gateway_Status"], "PASS")

    def test_missing_or_future_team_and_venue_evidence_blocks(self):
        for field, value in [("Rotation_Risk", "未知"), ("Available_At", "2026-09-08T10:00:00+08:00"), ("Source", "")]:
            data = fixture()
            data["Teams"]["B"][field] = value
            self.assertEqual(self.call(data)[0]["Gateway_Status"], "DATA_PENDING")
        data = fixture()
        data["Neutral_Venue"] = None
        self.assertEqual(self.call(data)[0]["Gateway_Status"], "DATA_PENDING")

    def test_away_fatigue_is_stronger_than_home(self):
        team = fixture()["Teams"]["A"]
        team.update(Schedule_Density="一周双赛", Strategic_Intent="战意成疑")
        home = gw.confidence_adjustment(80, team, "主场")
        away = gw.confidence_adjustment(80, team, "客场")
        neutral = gw.confidence_adjustment(80, team, "中立")
        self.assertLess(away["Adjusted_Confidence"], neutral["Adjusted_Confidence"])
        self.assertLess(neutral["Adjusted_Confidence"], home["Adjusted_Confidence"])
        self.assertAlmostEqual(away["Adjusted_Confidence"], 61.2)

    def test_must_win_is_not_a_probability_bonus(self):
        team = fixture()["Teams"]["A"]
        team["Strategic_Intent"] = "必须全力争胜"
        self.assertEqual(gw.confidence_adjustment(80, team, "客场")["Adjusted_Confidence"], 80)

    def test_confidence_filter_blocks_without_changing_history_probability(self):
        data = fixture()
        data.update(Base_Confidence=70, p_comb=.64)
        data["Teams"]["A"].update(Strategic_Intent="战意成疑", Schedule_Density="一周双赛")
        before = deepcopy(data)
        output, called = self.call(data)
        self.assertEqual(output["Execution_Code"], "CONTEXT_CONFIDENCE_LOW")
        self.assertEqual(data, before)
        self.assertEqual(called, [])

    def test_no_double_confidence_deduction(self):
        data = fixture()
        data["Confidence_Basis"] = "already_adjusted"
        self.assertEqual(self.call(data)[0]["Gateway_Status"], "DATA_PENDING")

    def test_frozen_decision_is_returned_unchanged(self):
        data = fixture()
        data["Frozen_Decision"] = {"Execution_Status": "READY", "Stake": 50, "original_pick": "B"}
        before = deepcopy(data["Frozen_Decision"])
        output, called = self.call(data)
        self.assertEqual(output, before)
        self.assertIsNot(output, data["Frozen_Decision"])
        self.assertEqual(called, [])

    def test_later_veto_never_promoted_to_ready(self):
        output = gw.run_guarded_analysis(fixture(), calculate_delta=lambda: {"Delta_Conv": -.04},
            existing_funnel=lambda _: {"Execution_Status": "COOLDOWN", "Stake": 0}, bankroll=10000)
        self.assertEqual(output["Execution_Status"], "COOLDOWN")
        self.assertEqual(output["Stake"], 0)

    def test_minimum_stake_after_context_cap(self):
        data = fixture()
        data["Teams"]["A"].update(Schedule_Density="一周双赛", Rotation_Risk="高")
        output = gw.run_guarded_analysis(data, calculate_delta=lambda: {"Delta_Conv": -.04},
            existing_funnel=lambda _: {"Execution_Status": "READY", "Stake": 20},
            bankroll=1000, policy=gw.GatewayPolicy(dense_deep_action="quarter"))
        self.assertEqual(output["Execution_Status"], "BELOW_MIN_STAKE")
        self.assertEqual(output["Stake"], 0)

    def test_density_counts_unique_prior_matches_plus_current(self):
        self.assertEqual(gw.schedule_density([]), "正常")
        self.assertEqual(gw.schedule_density(["1", "1"]), "一周双赛")
        self.assertEqual(gw.schedule_density(["1", "2"]), "一周三赛")

    def test_invalid_delta_does_not_reach_original_funnel(self):
        def no_call(_):
            self.fail("Invalid Delta reached funnel")
        output = gw.run_guarded_analysis(fixture(), calculate_delta=lambda: {}, existing_funnel=no_call, bankroll=10000)
        self.assertEqual(output["Execution_Code"], "DELTA_DATA_PENDING")

    def test_started_match_does_not_create_new_prematch(self):
        data = fixture()
        data["Decision_At"] = data["Kickoff_At"]
        self.assertEqual(self.call(data)[0]["Execution_Code"], "MATCH_STARTED")

    def test_absence_evidence_required_before_delta(self):
        data = fixture()
        del data["Fundamental_Evidence"]["home"]["absences"]
        output, called = self.call(data)
        self.assertEqual(output["Gateway_Status"], "DATA_PENDING")
        self.assertEqual(called, [])

    def test_material_selected_absence_blocks_before_delta(self):
        data = fixture()
        data["Fundamental_Evidence"]["home"]["absences"]["status"] = "adverse"
        output, called = self.call(data)
        self.assertEqual(output["Execution_Code"], "FUNDAMENTALS_VETO")
        self.assertEqual(called, [])

    def test_known_second_leg_lead_does_not_require_odds(self):
        data = fixture()
        data["Match_Nature"] = "两回合次回合"
        del data["Home_Handicap"]
        self.assertEqual(self.call(data)[0]["Execution_Code"], "SKIP_SECOND_LEG_LEAD")

    def test_display_rounding_cannot_pass_confidence_threshold(self):
        data = fixture()
        data["Base_Confidence"] = 59.999999
        self.assertEqual(self.call(data)[0]["Execution_Code"], "CONTEXT_CONFIDENCE_LOW")


if __name__ == "__main__":
    unittest.main()
