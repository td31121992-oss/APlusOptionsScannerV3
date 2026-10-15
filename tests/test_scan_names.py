import unittest

import scan_review as sr
import trade_review as tr
import trend_tags as tt


def trend():
    return {"5M": {"bullish": 8, "neutral": 1, "bearish": 2, "score": 0.6, "table": []},
            "15M": {"bullish": 8, "neutral": 1, "bearish": 2, "score": 0.6, "table": []},
            "scans": [{"text": "Open = Low", "tone": "bull", "time": "09:15"}, {"text": "5 Days Breakout", "tone": "bull"},
                      {"text": "Below yesterday's low", "tone": "bear"}]}


class ScanNameTests(unittest.TestCase):
    def test_names_and_groups_are_recorded_for_a_call(self):
        t = tt.tags_from_trend(trend(), "BULLISH")
        self.assertEqual(t["tr_scans_names"], "Open = Low|5 Days Breakout")
        self.assertEqual(t["tr_scans_against_names"], "Below yesterday's low")
        self.assertTrue(t["tr_open_ext"])
        self.assertTrue(t["tr_multi_day"])

    def test_put_side_uses_the_bearish_scans(self):
        t = tt.tags_from_trend(trend(), "BEARISH")
        self.assertEqual(t["tr_scans_names"], "Below yesterday's low")
        self.assertFalse(t["tr_open_ext"])
        self.assertFalse(t["tr_multi_day"])


class ReviewTests(unittest.TestCase):
    def rows(self):
        return [{"tr_scans_names": "Open = Low|Above yesterday's high", "net": 1000, "tr_all_aligned": "True"},
                {"tr_scans_names": "Above yesterday's high|5 Days Breakout", "net": -500, "tr_all_aligned": "False"},
                {"tr_scans_names": "Above yesterday's high", "net": -200, "tr_all_aligned": "True"}]

    def test_nightly_table(self):
        text = "\n".join(tr.scans_section(self.rows()))
        self.assertIn("| Above yesterday's high | 3 | 1 | +300 |", text)
        self.assertIn("| Open = Low | 1 | 1 | +1,000 |", text)
        self.assertEqual(tr.scans_section([{"net": 5}]), [])

    def test_cumulative_review_groups(self):
        trades = [{"day": "2026-10-16", "net": 900, "mfe_pct": 30, "exit_reason": "RUNNER_TRAIL_EXIT", "tr_scans_names": "Open = Low",
                   "tr_open_ext": True, "tr_multi_day": False},
                  {"day": "2026-10-16", "net": -700, "mfe_pct": 0, "exit_reason": "OPTION_STOP_LOSS", "tr_scans_names": "5 Days Breakout",
                   "tr_open_ext": False, "tr_multi_day": True}]
        s = sr.summarize(trades)
        self.assertEqual(s["groups"]["Open at the day's extreme (Open = Low / High)"]["net"], 900)
        self.assertEqual(s["groups"]["A 5/10/30/90-day level already broken"]["stopped"], 1)
        self.assertIn("Each scan", sr.render(s))
        self.assertIn("No trades with scan names", sr.render(sr.summarize([])))


if __name__ == "__main__":
    unittest.main()
