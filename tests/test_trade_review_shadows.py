import unittest

import trade_review as tr


class ShadowDeltaTests(unittest.TestCase):
    def test_deltas_and_comparison_table(self):
        t = {"symbol": "AAA", "direction": "BULLISH", "entry_price": 100.0, "quantity": 10, "status": "CLOSED", "exit_price": 108.0,
             "shadow_peak8_a30_exit_at": "2026-10-09T10:18:00+05:30", "shadow_peak8_a30_exit_price": 128.0,
             "shadow_ladder_exit_at": "2026-10-09T10:40:00+05:30", "shadow_ladder_exit_price": 108.0, "shadow_ladder_at_real_exit": True}
        row = tr.review_row(t)
        self.assertEqual(row["d_peak8_a30"], 200)                    # (128 - 108) * 10
        self.assertEqual(row["hit_peak8_a30"], 1)
        self.assertEqual(row["hit_ladder"], 0)                       # fell back to the real exit
        text = tr.render("2026-10-09", [row])
        self.assertIn("Exit-rule comparison", text)
        self.assertIn("8% below the peak, after +30% reached", text)


if __name__ == "__main__":
    unittest.main()
