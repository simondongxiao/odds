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


if __name__ == "__main__":
    unittest.main()
