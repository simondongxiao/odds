import unittest
from copy import deepcopy

import asian_risk_v3 as risk
import market_move_guard as guard


NOW = "2026-09-12T11:00:00+08:00"
KICKOFF = "2026-09-12T20:00:00+08:00"


def fixture():
    old = dict(match_id="match", snapshot_id="s1", bookmaker_id="book", model_version="model-1",
               home_team_id="A", away_team_id="B", period="90m", state="pre",
               home_handicap=-.5, home_water=.96, away_water=.92,
               quoted_at="2026-09-12T10:58:00+08:00", available_at="2026-09-12T10:58:02+08:00")
    current = {**old, "snapshot_id": "s2", "home_water": .95,
               "quoted_at": "2026-09-12T10:59:00+08:00", "available_at": "2026-09-12T10:59:02+08:00"}
    basis = {k: current[k] for k in ("match_id", "period", "home_handicap", "snapshot_id")}
    basis.update(sources=["synthetic-source"], fact_summary="Synthetic test evidence, not live data",
                 observed_at="2026-09-12T10:59:03+08:00", available_at="2026-09-12T10:59:04+08:00")
    public = {**basis, "evidence_id": "public-1", "kind": "actual_money_share", "team_id": "A",
              "share": .7, "theoretical_share": .5, "theoretical_basis": "same-market model-1",
              "window_amount": 10000}
    resistance = {**basis, "evidence_id": "res-1", "public_team_id": "A",
                  "assessment": "counter_public_resistance", "basis": "cross_market_response",
                  "supports_team_id": "B", "independent_evidence_ids": ["euro-response-1"]}
    previous = dict(decision_id="d1", match_id="match", list_date="2026-09-11", snapshot_id="s1",
                    team_id="A", Execution_Status="READY", Stake=50,
                    decision_at="2026-09-12T10:58:10+08:00")
    proposed = {**previous, "decision_id": "d2", "snapshot_id": "s2", "team_id": "B", "decision_at": NOW}
    return old, current, public, resistance, previous, proposed


class MoveTests(unittest.TestCase):
    def check(self, old, current, public, resistance):
        return guard.assess_market_move(old, current, decision_at=NOW, public=public, resistance=resistance)

    def run_update(self, old, current, public, resistance, previous, proposed):
        return guard.run_market_reassessment(previous, old, current, decision_at=NOW, kickoff_at=KICKOFF,
                                             public=public, resistance=resistance,
                                             build_proposal=lambda review: proposed)

    def test_single_new_quote_no_five_minute_wait(self):
        data = fixture()
        result = self.check(*data[:4])
        self.assertEqual(result["Move_Status"], "COUNTER_PUBLIC_CONFIRMED")
        self.assertEqual(result["Changed_Fields"], ["home_water"])

    def test_small_water_change_still_reviewed(self):
        old, current, public, resistance, _, _ = fixture()
        current["home_water"] = .9599
        self.assertEqual(self.check(old, current, public, resistance)["Move_Status"], "COUNTER_PUBLIC_CONFIRMED")

    def test_complete_reversal_allowed_both_directions(self):
        for target in ("A", "B"):
            data = list(fixture())
            data[3]["supports_team_id"] = target
            data[4]["team_id"] = "B" if target == "A" else "A"
            data[5]["team_id"] = target
            result = self.run_update(*data)
            self.assertEqual(result["Accepted_New_Decision"]["team_id"], target)
            self.assertEqual(result["Previous_Decision"], data[4])

    def test_passive_public_move_cannot_flip(self):
        data = list(fixture())
        data[3]["assessment"] = "passive_public_adjustment"
        result = self.run_update(*data)
        self.assertEqual(result["Current_Execution_Status"], "DIRECTION_CHANGE_BLOCKED")
        self.assertIsNone(result["Accepted_New_Decision"])
        self.assertEqual(result["Move_Review"]["Move_Status"], "PASSIVE_PUBLIC_MOVE")
        self.assertEqual(result["Previous_Decision"]["team_id"], "A")

    def test_missing_flow_and_no_qualitative_evidence_does_not_invent_heat(self):
        data = list(fixture())
        data[2] = {}
        result = self.run_update(*data)
        self.assertEqual(result["Current_Execution_Status"], "DIRECTION_CHANGE_BLOCKED")
        self.assertIsNone(result["Move_Review"]["Public_Heat_Excess"])

    def test_qualitative_sources_allowed_without_money_percentages(self):
        data = list(fixture())
        data[2].update(kind="public_consensus", sources=["source-one", "source-two"])
        result = self.run_update(*data)
        self.assertEqual(result["Current_Execution_Status"], "READY")
        self.assertIsNone(result["Move_Review"]["Public_Heat_Excess"])

    def test_single_qualitative_source_is_pending(self):
        data = list(fixture())
        data[2]["kind"] = "public_consensus"
        self.assertEqual(self.run_update(*data)["Current_Execution_Status"], "DIRECTION_CHANGE_BLOCKED")

    def test_heat_exactly_five_percentage_points_is_not_hot(self):
        for share, theory in ((.55, .5), (.6, .55), (.65, .6)):
            old, current, public, resistance, _, _ = fixture()
            public.update(share=share, theoretical_share=theory)
            self.assertEqual(self.check(old, current, public, resistance)["Move_Status"], "PUBLIC_HEAT_NOT_ESTABLISHED")

    def test_heat_above_five_passes_without_rounding_to_boundary(self):
        data = list(fixture())
        data[2].update(share=.55001, theoretical_share=.5)
        self.assertEqual(self.check(*data[:4])["Move_Status"], "COUNTER_PUBLIC_CONFIRMED")

    def test_odds_proxy_is_not_actual_money(self):
        for kind in ("odds_implied_share", "ticket_share"):
            data = list(fixture())
            data[2]["kind"] = kind
            self.assertNotEqual(self.check(*data[:4])["Move_Status"], "COUNTER_PUBLIC_CONFIRMED")

    def test_future_stale_or_misaligned_evidence_blocks(self):
        for key, value in (("available_at", "2026-09-12T11:01:00+08:00"),
                           ("observed_at", "2026-09-12T10:00:00+08:00"),
                           ("home_handicap", -1), ("match_id", "wrong"), ("snapshot_id", "s1")):
            for index in (2, 3):
                data = list(fixture())
                data[index][key] = value
                self.assertEqual(self.run_update(*data)["Current_Execution_Status"], "DIRECTION_CHANGE_BLOCKED")

    def test_no_counter_resistance_from_ah_price_alone(self):
        data = list(fixture())
        data[3]["basis"] = "ah_water_only"
        self.assertEqual(self.run_update(*data)["Current_Execution_Status"], "DIRECTION_CHANGE_BLOCKED")

    def test_wrong_supported_side_does_not_approve_flip(self):
        data = list(fixture())
        data[3]["supports_team_id"] = "A"
        self.assertEqual(self.run_update(*data)["Current_Execution_Status"], "DIRECTION_CHANGE_BLOCKED")

    def test_self_referencing_corroboration_rejected(self):
        for evidence in ("s2", "public-1", "res-1"):
            data = list(fixture())
            data[3]["independent_evidence_ids"] = [evidence]
            self.assertEqual(self.run_update(*data)["Current_Execution_Status"], "DIRECTION_CHANGE_BLOCKED")

    def test_provider_model_live_or_old_quote_is_not_a_move(self):
        for key, value in (("bookmaker_id", "other"), ("model_version", "model-2"), ("state", "live"),
                           ("quoted_at", "2026-09-12T10:58:00+08:00"), ("home_water", float("nan")),
                           ("available_at", "2026-09-12T11:01:00+08:00")):
            data = list(fixture())
            data[1][key] = value
            self.assertEqual(self.check(*data[:4])["Move_Status"], "DATA_PENDING")

    def test_no_movement_does_not_justify_price_flip(self):
        data = list(fixture())
        data[1]["home_water"] = data[0]["home_water"]
        self.assertEqual(self.run_update(*data)["Current_Execution_Status"], "DIRECTION_CHANGE_BLOCKED")

    def test_started_and_settled_do_not_call_new_prediction(self):
        for state in ("live", "closed", "finished"):
            old, current, public, resistance, previous, _ = fixture()
            current["state"] = state
            result = guard.run_market_reassessment(previous, old, current, decision_at=NOW, kickoff_at=KICKOFF,
                                                   build_proposal=lambda review: self.fail("Historical recomputation"))
            self.assertEqual(result["Current_Execution_Status"], "HISTORICAL_LOCK")
            self.assertEqual(result["Previous_Decision"], previous)

    def test_clock_alone_locks_even_if_provider_still_says_pre(self):
        old, current, _, _, previous, _ = fixture()
        result = guard.run_market_reassessment(previous, old, current, decision_at=KICKOFF, kickoff_at=KICKOFF,
                                               build_proposal=lambda review: self.fail("Started recomputation"))
        self.assertEqual(result["Current_Execution_Status"], "HISTORICAL_LOCK")

    def test_rejected_gate_does_not_revive_old_execution(self):
        data = list(fixture())
        data[5].update(Execution_Status="COOLDOWN", Stake=0, team_id=None)
        result = self.run_update(*data)
        self.assertEqual(result["Current_Execution_Status"], "COOLDOWN")
        self.assertEqual(result["Accepted_New_Decision"]["Stake"], 0)
        self.assertEqual(result["Previous_Decision"]["Execution_Status"], "READY")

    def test_immutable_list_date_and_original_snapshot(self):
        for index, key, value in ((5, "list_date", "2026-09-12"), (5, "decision_id", "d1"),
                                  (5, "snapshot_id", "s1"), (4, "snapshot_id", "wrong")):
            data = list(fixture())
            data[index][key] = value
            self.assertEqual(self.run_update(*data)["Current_Execution_Status"], "DATA_PENDING")

    def test_no_mutation(self):
        data = fixture()
        before = deepcopy(data)
        self.run_update(*data)
        self.assertEqual(data, before)

    def test_nonready_proposal_must_not_carry_money(self):
        data = list(fixture())
        data[5]["Execution_Status"] = "COOLDOWN"
        self.assertEqual(self.run_update(*data)["Current_Execution_Status"], "DATA_PENDING")

    def test_same_team_changed_direction_still_requires_move_guard(self):
        data = list(fixture())
        data[4]["direction"] = "forward"
        data[5].update(team_id="A", direction="reverse")
        data[3]["assessment"] = "passive_public_adjustment"
        self.assertEqual(self.run_update(*data)["Current_Execution_Status"], "DIRECTION_CHANGE_BLOCKED")

    def test_omitting_old_conclusion_cannot_bypass_review(self):
        data = list(fixture())
        data[4]["verified_intent"] = "block_upper"
        self.assertEqual(self.run_update(*data)["Current_Execution_Status"], "DATA_PENDING")

    def test_full_reference_chain_retains_cup_veto_and_allows_valid_flip(self):
        import cup_rotation_gateway as cup
        from test_cup_rotation_gateway import fixture as cup_fixture
        for cup_veto in (False, True):
            old, current, public, resistance, previous, identity = fixture()
            context = cup_fixture()
            context.update(Match_ID="match", Selected_Team_ID="B", Home_Handicap=-.5,
                           Decision_At=NOW, Kickoff_At=KICKOFF)
            if cup_veto:
                context["Match_Nature"] = "两回合次回合"
            called = []
            def delta():
                called.append("delta")
                masses = dict(zip(risk.OUTCOMES, [.7, 0, 0, 0, .3]))
                return risk.conversion_metrics(masses, current["away_water"], current["home_water"])
            def full_funnel(metrics):
                self.assertEqual(metrics["Context_Gateway"]["Gateway_Status"], "PASS")
                return risk.execution_plan(masses=dict(zip(risk.OUTCOMES, [.7, 0, 0, 0, .3])),
                                           water=current["away_water"], effective_rate=.7, bankroll=10000,
                                           signed_handicap=.5, fundamental_status="pass", conversion_passed=True,
                                           calibration_passed=True, kickoff_at=KICKOFF)
            def build(review):
                return {**identity, **cup.run_guarded_analysis(context, calculate_delta=delta,
                                                               existing_funnel=full_funnel, bankroll=10000)}
            result = guard.run_market_reassessment(previous, old, current, decision_at=NOW, kickoff_at=KICKOFF,
                                                   public=public, resistance=resistance, build_proposal=build)
            self.assertEqual(result["Previous_Decision"], previous)
            if cup_veto:
                self.assertEqual(called, [])
                self.assertEqual(result["Accepted_New_Decision"]["Stake"], 0)
                self.assertNotEqual(result["Current_Execution_Status"], "READY")
            else:
                self.assertEqual(called, ["delta"])
                self.assertEqual(result["Accepted_New_Decision"]["team_id"], "B")
                self.assertEqual(result["Current_Execution_Status"], "READY")
                self.assertEqual(result["Accepted_New_Decision"]["Weekend_Policy"], "AUDIT_ONLY")


class WeekendAuditTests(unittest.TestCase):
    def plan(self, **overrides):
        args = dict(masses=dict(zip(risk.OUTCOMES, [.62, 0, 0, 0, .38])), effective_rate=.62,
                    water=.8, bankroll=10000, signed_handicap=-.5, fundamental_status="pass",
                    conversion_passed=True, calibration_passed=True, kickoff_at=KICKOFF,
                    remaining_capacity=1000)
        args.update(overrides)
        return risk.execution_plan(**args)

    def test_original_water_threshold_restored(self):
        self.assertEqual(self.plan()["Threshold"], round(1 / 1.8 + .02, 4))
        self.assertEqual(self.plan()["Weekend_Policy"], "AUDIT_ONLY")

    def test_all_lines_have_same_weekday_weekend_decision_and_stake(self):
        for line in (0, .25, .5, 1.5, -.25, -.5, -.75, -1, -1.25, -2.5):
            weekend = self.plan(signed_handicap=line)
            weekday = self.plan(signed_handicap=line, kickoff_at="2026-09-14T20:00:00+08:00")
            for key in ("Threshold", "Stake", "Execution_Status", "Sizing_Effective_Rate", "EV_Current", "Kelly_Full"):
                self.assertEqual(weekend[key], weekday[key], (line, key))

    def test_actual_beijing_kickoff_not_list_date_or_host_timezone(self):
        self.assertTrue(self.plan(kickoff_at="2026-09-11T16:01:00+00:00")["Is_Weekend"])
        self.assertFalse(self.plan(kickoff_at="2026-09-13T16:01:00+00:00")["Is_Weekend"])
        self.assertEqual(self.plan(kickoff_at="2026-09-11T16:01:00+00:00")["Kickoff_Date_BJ"], "2026-09-12")

    def test_old_callers_without_kickoff_still_work(self):
        result = self.plan(kickoff_at=None)
        self.assertNotIn("Is_Weekend", result)
        self.assertEqual(result["Execution_Status"], "READY")

    def test_independent_exposure_buffer_is_retained_not_multiplied(self):
        self.assertEqual(self.plan(safety_buffer=.04)["Threshold"], round(1 / 1.8 + .04, 4))

    def test_cancelled_weekend_veto_no_longer_blocks(self):
        result = self.plan()
        self.assertEqual(result["Execution_Status"], "READY")
        self.assertGreater(result["Stake"], 0)
        self.assertEqual(result["Sizing_Effective_Rate"], .62)
        self.assertEqual(self.plan(kickoff_at="2026-09-14T20:00:00+08:00")["Execution_Status"], "READY")

    def test_high_probability_can_still_buy_upper(self):
        result = self.plan(masses=dict(zip(risk.OUTCOMES, [.7, 0, 0, 0, .3])), effective_rate=.7)
        self.assertEqual(result["Execution_Status"], "READY")
        self.assertGreater(result["Stake"], 0)

    def test_prior_hard_gates_cannot_be_overridden(self):
        for overrides, code in (({"fundamental_status": "veto"}, "FUNDAMENTALS_VETO"),
                                ({"day_multiplier": 0}, "COOLDOWN"),
                                ({"signed_handicap": -.75}, "BLIND_SPOT_UNVALIDATED")):
            self.assertEqual(self.plan(**overrides)["Execution_Status"], code)

    def test_invalid_timezone_rejected(self):
        with self.assertRaises(ValueError):
            self.plan(kickoff_at="2026-09-12T20:00:00")

    def test_removed_weekend_configuration_cannot_reenable_tightening(self):
        for value in (.10, .15):
            with self.assertRaises(TypeError):
                self.plan(weekend_tightening=value)


if __name__ == "__main__":
    unittest.main()
