import sys
import unittest

sys.path.insert(0, r"D:\codex\v4")
from direction_contract import assert_side_identity, candidate_fields, map_intent, mirror_probs, parse_titan_market


class V4DirectionFixTests(unittest.TestCase):
    def market(self, line):
        return parse_titan_market({
            "home_team": "H", "away_team": "A",
            "ah_full_current_line_or_draw": str(line),
            "ah_full_current_home_or_over": "0.90",
            "ah_full_current_away_or_under": "0.80",
            "ah_full_open_line_or_draw": str(line),
            "ah_full_open_home_or_over": "0.90",
            "ah_full_open_away_or_under": "0.80",
        })

    def test_receiving_intents(self):
        for tag in ("诱上/阻下", "真实示弱/阻下", "阻下/下盘保护"):
            self.assertEqual(map_intent(tag)["candidate_side"], "receiving")

    def test_giving_intents(self):
        for tag in ("阻上/诱下", "降温保护/诱下", "真实示强/阻上"):
            self.assertEqual(map_intent(tag)["candidate_side"], "giving")

    def test_neutral_and_unknown(self):
        self.assertEqual(map_intent("平衡盘/等待临场确认")["candidate_side"], "neutral")
        self.assertEqual(map_intent("意图未接入")["candidate_side"], "unknown")

    def test_titan_positive_home_gives(self):
        m = self.market(0.75)
        self.assertEqual((m["giving_team"], m["receiving_team"]), ("H", "A"))
        ok, _ = assert_side_identity(m, candidate_fields(m, "giving"))
        self.assertTrue(ok)

    def test_titan_negative_away_gives(self):
        m = self.market(-0.75)
        self.assertEqual((m["giving_team"], m["receiving_team"]), ("A", "H"))
        ok, _ = assert_side_identity(m, candidate_fields(m, "receiving"))
        self.assertTrue(ok)

    def test_pk_neutral(self):
        m = self.market(0)
        self.assertTrue(m["pk"])
        self.assertEqual(candidate_fields(m, "giving")["candidate_side"], "neutral")

    def test_water_follows_candidate_team(self):
        m = self.market(-0.5)
        c = candidate_fields(m, "receiving")
        self.assertEqual(c["candidate_team"], "H")
        self.assertEqual(c["candidate_water"], 0.9)

    def test_mirror_is_exact(self):
        p = {"W": .1, "HW": .2, "P": .3, "HL": .15, "L": .25}
        self.assertEqual(mirror_probs(mirror_probs(p)), p)


if __name__ == "__main__":
    unittest.main()
