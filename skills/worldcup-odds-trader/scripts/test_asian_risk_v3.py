import unittest
from copy import deepcopy

import asian_risk_v3 as risk


class RiskTests(unittest.TestCase):
    def test_quarter_settlements(self):
        for margin, line, expected in [(0, -.25, -.5), (1, -.25, 1), (-1, -.25, -1),
                                       (-1, .75, -.5), (-2, .75, -1), (0, .75, 1),
                                       (1, -.75, .5), (1, -1.25, -.5), (2, -2, 0)]:
            self.assertEqual(risk.result_units(margin, line), expected)

    def test_two_sides_are_opposite_at_all_lines(self):
        for ticks in range(-12, 13):
            for margin in range(-5, 6):
                self.assertEqual(risk.result_units(margin, ticks / 4), -risk.result_units(-margin, -ticks / 4))

    def test_half_results_not_full_hits(self):
        stats = risk.effective_history({"win": 1, "half_loss": 2}, .8)
        self.assertEqual(stats["effective_rate"], .5)
        self.assertAlmostEqual(stats["pnl_at_current_water"], -.2)

    def test_fair_water_zero_ev_and_delta(self):
        masses = risk.settlement_distribution({0: .2, 1: .5, 2: .3}, -.75)
        a, b = .55, .2
        result = risk.conversion_metrics(masses, b / a, a / b)
        self.assertAlmostEqual(result["EV_Current"], 0)
        self.assertAlmostEqual(result["Delta_Conv"], 0)

    def test_example_delta(self):
        masses = dict(zip(risk.OUTCOMES, [1 / 1.85, 0, 0, 0, .85 / 1.85]))
        result = risk.conversion_metrics(masses, .96, .92)
        self.assertAlmostEqual(result["Theo_Water"], .85)
        self.assertAlmostEqual(result["Delta_Conv"], -.04569518, places=7)

    def test_invalid_inputs(self):
        with self.assertRaises(ValueError):
            risk.result_units(1, -.3)
        with self.assertRaises(ValueError):
            risk.settlement_distribution({0: .5}, -.5)
        with self.assertRaises(ValueError):
            risk.combined_rate(.6, 0, .7, 10)

    def assessment(self):
        return {side: {key: {"status": "clear", "source": "test-only", "available_at": "2026-09-07T10:00:00+08:00"}
                       for key in ("schedule", "absences", "rotation_depth", "motivation")}
                for side in ("home", "away")}

    def test_no_future_evidence(self):
        data = self.assessment()
        self.assertEqual(risk.fundamental_gate(data, "2026-09-07T09:00:00+08:00")["Fundamental_Status"], "pending")
        self.assertEqual(risk.fundamental_gate(data, "2026-09-07T11:00:00+08:00")["Fundamental_Status"], "pass")

    def test_opponent_absence_not_own_veto(self):
        data = self.assessment()
        data["away"]["absences"]["status"] = "adverse"
        self.assertEqual(risk.fundamental_gate(data, "2026-09-07T11:00:00+08:00", "away")["Fundamental_Status"], "veto")
        self.assertNotEqual(risk.fundamental_gate(data, "2026-09-07T11:00:00+08:00", "home")["Fundamental_Status"], "veto")

    def test_brand_alone_does_not_veto(self):
        self.assertFalse(risk.upper_veto(heat_verified=True))
        self.assertFalse(risk.upper_veto(heat_verified=False, resistance_failed=True))
        self.assertTrue(risk.upper_veto(heat_verified=True, fatigue_and_thin_squad=True))

    def test_delta_needs_confirmation(self):
        args = dict(fundamental_status="pass", snapshots=2, bookmakers=2, minimum_spacing_minutes=5,
                    resistance_verified=True, heat_verified=False, inducement_verified=False)
        self.assertEqual(risk.intent_crosscheck(-.045, **args), "BLOCK_UPPER_VALIDATION_CANDIDATE")
        self.assertEqual(risk.intent_crosscheck(-.15, **args), "DATA_OR_MODEL_CONFLICT")
        args["snapshots"] = 1
        self.assertEqual(risk.intent_crosscheck(-.045, **args), "PERSISTENCE_PENDING")

    def test_exposure_no_quota_flip(self):
        small = risk.exposure_gate(4, 0, active_days=1)
        self.assertEqual(small["Exposure_Status"], "SMALL_SAMPLE")
        full = risk.exposure_gate(27, 3, active_days=3)
        self.assertEqual(full["Upper_Multiplier"], .5)
        self.assertEqual(full["Upper_Safety_Buffer"], .04)

    def test_cooling_and_shadow_recovery(self):
        self.assertEqual(risk.next_day_risk("NORMAL", [-.1], 3)["Day_Multiplier"], .5)
        self.assertEqual(risk.next_day_risk("NORMAL", [-.1, -.1], 2)["Day_Multiplier"], 0)
        self.assertEqual(risk.next_day_risk("COOLDOWN", [], 0)["Day_Multiplier"], 0)
        self.assertEqual(risk.next_day_risk("COOLDOWN", [], 0, 3, .1)["Day_Multiplier"], 1)

    def test_generalized_kelly_binary_case(self):
        masses = dict(zip(risk.OUTCOMES, [.6, 0, 0, 0, .4]))
        self.assertAlmostEqual(risk.generalized_kelly(masses, 1), .2)

    def proposal(self):
        return dict(masses=dict(zip(risk.OUTCOMES, [.7, 0, 0, 0, .3])), water=1.,
                    effective_rate=.7, bankroll=500., signed_handicap=-.5,
                    fundamental_status="pass", conversion_passed=True, calibration_passed=True)

    def test_minimum_stake_never_rounded_up(self):
        args = self.proposal()
        args["day_multiplier"] = .5
        result = risk.execution_plan(**args)
        self.assertEqual(result["Execution_Status"], "BELOW_MIN_STAKE")
        self.assertEqual(result["Stake"], 0)

    def test_shadow_and_blind_spot_stop_orders(self):
        args = self.proposal()
        args["calibration_passed"] = False
        self.assertEqual(risk.execution_plan(**args)["Execution_Status"], "SHADOW_UNVALIDATED")
        args["calibration_passed"] = True
        args["signed_handicap"] = -.75
        self.assertEqual(risk.execution_plan(**args)["Execution_Status"], "BLIND_SPOT_UNVALIDATED")
        args["blind_validated"] = True
        self.assertEqual(risk.execution_plan(**args)["Execution_Status"], "BELOW_MIN_STAKE")

    def test_pure_decision_and_cap(self):
        args = self.proposal()
        args["high_confidence"] = True
        before = deepcopy(args)
        result = risk.execution_plan(**args)
        self.assertEqual(result["Stake"], 25)
        self.assertEqual(result["Execution_Status"], "READY")
        self.assertEqual(args, before)

    def test_european_devig(self):
        result = risk.de_vig_1x2(2, 3, 4)
        self.assertAlmostEqual(sum(result[k] for k in ("home", "draw", "away")), 1)
        self.assertAlmostEqual(result["home"], 6 / 13)
        with self.assertRaises(ValueError):
            risk.de_vig_1x2(1, 3, 4)

    def quotes(self):
        return [{"kind": kind, "match_id": "example", "bookmaker_id": "book-a", "period": "90m", "state": "pre",
                 "quoted_at": "2026-09-07T10:59:00+08:00", "observed_at": "2026-09-07T10:59:10+08:00",
                 "available_at": "2026-09-07T10:59:15+08:00"} for kind in ("1x2", "ah", "total")]

    def test_quote_alignment(self):
        self.assertEqual(risk.quote_alignment(self.quotes(), "2026-09-07T11:00:00+08:00")["Quote_Status"], "PASS")
        quotes = self.quotes()
        quotes[0]["quoted_at"] = "2026-09-07T10:55:00+08:00"
        self.assertIn("cross_market_skew", risk.quote_alignment(quotes, "2026-09-07T11:00:00+08:00")["Quote_Failed_Gates"])

    def test_future_stale_and_duplicate_quotes(self):
        for quotes, now in [(self.quotes(), "2026-09-07T10:00:00+08:00"),
                            (self.quotes(), "2026-09-07T12:00:00+08:00"),
                            (self.quotes()[:2], "2026-09-07T11:00:00+08:00")]:
            self.assertEqual(risk.quote_alignment(quotes, now)["Quote_Status"], "DATA_PENDING")

    def test_history_caps_model_sizing(self):
        args = self.proposal()
        args.update(bankroll=10000, effective_rate=.55, remaining_capacity=1000)
        low = risk.execution_plan(**args)
        args["effective_rate"] = .65
        high = risk.execution_plan(**args)
        self.assertLess(low["Stake"], high["Stake"])
        self.assertAlmostEqual(low["Kelly_Full"], .1)
        self.assertEqual(low["Sizing_Effective_Rate"], .55)

    def test_model_caps_optimistic_history(self):
        args = self.proposal()
        args["masses"] = dict(zip(risk.OUTCOMES, [.51, 0, 0, 0, .49]))
        self.assertEqual(risk.execution_plan(**args)["Execution_Status"], "PRICE_EDGE_FAILED")

    def test_mass_adjustment_preserves_push_and_half_mix(self):
        masses = dict(zip(risk.OUTCOMES, [.3, .2, .1, .1, .3]))
        adjusted = risk.conservative_masses(masses, .4)
        risk.validate_masses(adjusted)
        self.assertEqual(adjusted["push"], .1)
        self.assertAlmostEqual(adjusted["win"] / adjusted["half_win"], 1.5)
        self.assertAlmostEqual(adjusted["loss"] / adjusted["half_loss"], 3)
        a = adjusted["win"] + .5 * adjusted["half_win"]
        b = adjusted["loss"] + .5 * adjusted["half_loss"]
        self.assertAlmostEqual(a / (a + b), .4)

    def test_fundamental_veto_has_distinct_reason(self):
        args = self.proposal()
        args["fundamental_status"] = "veto"
        self.assertEqual(risk.execution_plan(**args)["Execution_Status"], "FUNDAMENTALS_VETO")

    def preflight(self):
        plan = {"Execution_Status": "READY", "decision_id": "synthetic-1", "match_id": "example",
                "bookmaker_id": "book-a", "team_id": "home", "signed_handicap": -.5, "period": "90m",
                "kickoff_at": "2026-09-07T12:00:00+08:00", "valid_until": "2026-09-07T11:02:00+08:00",
                "minimum_water": .9, "Stake": 50}
        quote = {k: plan[k] for k in ("match_id", "bookmaker_id", "team_id", "signed_handicap", "period")}
        quote.update(state="pre", water=.92, quoted_at="2026-09-07T10:59:00+08:00", available_at="2026-09-07T10:59:30+08:00")
        return plan, quote, "2026-09-07T11:00:00+08:00"

    def test_no_automatic_bet_authorization(self):
        plan, quote, now = self.preflight()
        self.assertEqual(risk.execution_recheck(plan, quote, now), "AUTHORIZATION_REQUIRED")
        self.assertEqual(risk.execution_recheck(plan, quote, now, authorized=True), "READY_FOR_AUTHORIZED_EXECUTOR")

    def test_uncertain_receipts_never_retry_blindly(self):
        for state in ("UNKNOWN", "PENDING", "FILLED", "PARTIAL"):
            plan, quote, now = self.preflight()
            self.assertEqual(risk.execution_recheck(plan, quote, now, receipt_states=(state,)), "DUPLICATE_OR_UNCERTAIN_EXECUTION")

    def test_preflight_does_not_change_started_pick(self):
        plan, quote, now = self.preflight()
        before = deepcopy(plan)
        quote["state"] = "live"
        self.assertEqual(risk.execution_recheck(plan, quote, now), "MATCH_STARTED")
        self.assertEqual(plan, before)

    def test_reprice_and_line_changes_block_execution(self):
        plan, quote, now = self.preflight()
        quote["water"] = .8
        self.assertEqual(risk.execution_recheck(plan, quote, now), "PRICE_BELOW_LIMIT")
        quote["signed_handicap"] = -.75
        self.assertEqual(risk.execution_recheck(plan, quote, now), "MARKET_CHANGED_NEW_DECISION_REQUIRED")

    def test_expired_plan_and_future_execution_quote(self):
        plan, quote, now = self.preflight()
        self.assertEqual(risk.execution_recheck(plan, quote, "2026-09-07T11:03:00+08:00"), "EXPIRED")
        quote["available_at"] = "2026-09-07T11:01:00+08:00"
        self.assertEqual(risk.execution_recheck(plan, quote, now), "QUOTE_STALE_OR_FUTURE")


if __name__ == "__main__":
    unittest.main()
