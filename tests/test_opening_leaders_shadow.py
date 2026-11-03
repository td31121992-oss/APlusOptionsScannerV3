import unittest

import opening_leaders_shadow as leaders
import opening_leaders_shadow_page as page


class OpeningLeadersShadowTests(unittest.TestCase):
    def test_ranks_reported_open_moves_without_inventing_a_score(self):
        report = {
            "generated_at": "2026-10-28T09:20:00+05:30",
            "age_seconds": 5,
            "stale": False,
            "rows": [
                {"symbol": "AAA", "from_open_pct": 2.4, "gap_pct": 0.5, "ltp": 102.4},
                {"symbol": "BBB", "from_open_pct": -1.7, "gap_pct": -0.2},
                {"symbol": "CCC", "from_open_pct": 1.1},
                {"symbol": "FLAT", "from_open_pct": 0},
            ],
        }

        result = leaders.build_payload(report)

        self.assertEqual([x["symbol"] for x in result["gainers"]], ["AAA", "CCC"])
        self.assertEqual([x["symbol"] for x in result["decliners"]], ["BBB"])
        self.assertEqual([x["rank"] for x in result["gainers"]], [1, 2])
        self.assertNotIn("score", result["gainers"][0])
        self.assertEqual(result["mode"], "SHADOW_INFORMATION_ONLY")
        self.assertEqual(result["generated_at"], report["generated_at"])
        self.assertFalse(result["stale"])

    def test_missing_and_malformed_report_fields_are_safe(self):
        result = leaders.build_payload({"rows": [
            {"symbol": "", "from_open_pct": 10},
            {"symbol": "BAD", "from_open_pct": "NaN"},
            {"symbol": "NO_MOVE"},
        ]})

        self.assertEqual(result["count"], 0)
        self.assertEqual(result["gainers"], [])
        self.assertEqual(result["decliners"], [])
        self.assertTrue(result["stale"])
        self.assertEqual(result["generated_at"], "")

    def test_stale_metadata_and_limitations_are_preserved(self):
        result = leaders.build_payload({
            "stale": True,
            "stale_reason": "report is old",
            "age_seconds": 240,
            "rows": [{"symbol": "AAA", "from_open_pct": 1}],
        })
        self.assertTrue(result["stale"])
        self.assertEqual(result["stale_reason"], "report is old")
        self.assertEqual(result["age_seconds"], 240)
        self.assertTrue(any("first-minute" in x for x in result["limitations"]))

    def test_page_is_information_only_and_uses_the_new_api(self):
        self.assertIn("/api/opening-leaders", page.HTML)
        self.assertIn("SHADOW / INFORMATION ONLY", page.HTML)
        self.assertIn("does not contain first-minute candle volume", page.HTML)
        self.assertIn("not a trade recommendation", page.HTML)


if __name__ == "__main__":
    unittest.main()
