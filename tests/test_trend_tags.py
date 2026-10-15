import unittest

import trend_tags as tt
import trade_review as tr


def trend(s5, s15, sd):
    def block(score):
        return {"bullish": 8 if score > 0 else 2, "neutral": 1, "bearish": 2 if score > 0 else 8, "score": score,
                "table": [{"name": "ADX", "value": "40.0", "text": "x", "tone": "bull"}, {"name": "RSI", "value": "62.0", "text": "x", "tone": "bull"}]}
    return {"5M": block(s5), "15M": block(s15), "DAILY": block(sd),
            "scans": [{"text": "a", "tone": "bull"}, {"text": "b", "tone": "bull"}, {"text": "c", "tone": "bear"}]}


class TrendTagTests(unittest.TestCase):
    def test_bullish_trade_aligned_when_5m_and_15m_up(self):
        t = tt.tags_from_trend(trend(0.8, 0.5, -0.2), "BULLISH")
        self.assertTrue(t["tr_aligned_5m"] and t["tr_aligned_15m"] and t["tr_all_aligned"])
        self.assertFalse(t["tr_aligned_daily"])
        self.assertEqual((t["tr_scans_for"], t["tr_scans_against"]), (2, 1))
        self.assertEqual(t["tr_adx_5m"], "40.0")

    def test_bearish_trade_flips_the_sign(self):
        t = tt.tags_from_trend(trend(0.8, 0.5, 0.1), "BEARISH")
        self.assertFalse(t["tr_all_aligned"])
        self.assertEqual((t["tr_scans_for"], t["tr_scans_against"]), (1, 2))
        t2 = tt.tags_from_trend(trend(-0.7, -0.4, -0.5), "BEARISH")
        self.assertTrue(t2["tr_all_aligned"])

    def test_empty_trend(self):
        self.assertEqual(tt.tags_from_trend({}, "BULLISH"), {})

    def test_review_groups_by_alignment(self):
        rows = [{"tr_all_aligned": "True", "net": 500}, {"tr_all_aligned": "False", "net": -200}, {"tr_all_aligned": "True", "net": -100}]
        text = "\n".join(tr.verdict_section(rows))
        self.assertIn("5M and 15M agree with the trade | 2 | 1 | +400", text)


if __name__ == "__main__":
    unittest.main()
