import unittest

import exit_review as er


def trade(day, net, ladder, sbg60, hit=1):
    return {"day": day, "net": net, "d_user_ladder": ladder, "hit_user_ladder": hit, "d_sbg60": sbg60, "hit_sbg60": hit}


class ExitReviewTests(unittest.TestCase):
    def test_totals_days_and_verdict(self):
        trades = ([trade("2026-10-15", 1000, 500, 300) for _ in range(3)]
                  + [trade("2026-10-16", -500, 200, -100) for _ in range(3)]
                  + [trade("2026-10-19", 200, 100, -400) for _ in range(3)] + [trade("2026-10-20", 100, 50, -400) for _ in range(3)])
        s = er.summarize(trades)
        self.assertEqual(s["trades"], 12)
        lad = s["rules"]["user_ladder"]
        self.assertEqual(lad["total"], 2400 + 150)
        self.assertEqual((lad["days_helped"], lad["days_counted"]), (4, 4))
        self.assertTrue(lad["supports"])
        sb = s["rules"]["sbg60"]
        self.assertEqual(sb["total"], 900 - 300 - 1200 - 1200)
        self.assertFalse(sb["supports"])

    def test_rule_with_one_big_losing_day_is_not_supported(self):
        trades = ([trade("2026-10-15", 0, 100, 0) for _ in range(3)] + [trade("2026-10-16", 0, 100, 0) for _ in range(3)]
                  + [trade("2026-10-19", 0, -2000, 0) for _ in range(3)] + [trade("2026-10-20", 0, 400, 0) for _ in range(3)])
        s = er.summarize(trades)
        lad = s["rules"]["user_ladder"]
        self.assertEqual(lad["total"], 300 + 300 - 6000 + 1200)
        self.assertFalse(lad["supports"])

    def test_render_and_empty(self):
        text = er.render(er.summarize([trade("2026-10-15", 100, 50, 20) for _ in range(3)]))
        self.assertIn("Your ladder", text)
        self.assertIn("needs more days (1 of 4)", text)          # a single day is never enough
        self.assertIn("No shadow fields", er.render(er.summarize([{"day": "2026-10-15", "net": 5}])))


if __name__ == "__main__":
    unittest.main()
