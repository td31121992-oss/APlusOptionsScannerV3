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

    def test_higher_timeframes_30m_1h_and_the_count_of_aligned_ones(self):
        tr_ = trend(-0.7, -0.4, -0.5)
        tr_["30M"] = {"bullish": 1, "neutral": 1, "bearish": 8, "score": -0.7, "table": []}
        tr_["1H"] = {"bullish": 2, "neutral": 1, "bearish": 7, "score": -0.5, "table": []}
        t = tt.tags_from_trend(tr_, "BEARISH")
        self.assertEqual((t["tr_30m_score"], t["tr_1h_score"]), (-0.7, -0.5))
        self.assertTrue(t["tr_aligned_30m"] and t["tr_aligned_1h"])
        self.assertEqual((t["tr_htf_n"], t["tr_htf_all"]), (4, True))              # 15m, 30m, 1h and daily all point down
        c = tt.tags_from_trend(tr_, "BULLISH")                                      # the same tape is against a call
        self.assertEqual((c["tr_htf_n"], c["tr_htf_all"]), (0, False))
        tr_["1H"]["score"] = 0.1
        mixed = tt.tags_from_trend(tr_, "BEARISH")
        self.assertEqual((mixed["tr_htf_n"], mixed["tr_htf_all"]), (3, False))

    def test_empty_trend(self):
        self.assertEqual(tt.tags_from_trend({}, "BULLISH"), {})

    def test_review_groups_by_alignment(self):
        rows = [{"tr_all_aligned": "True", "net": 500}, {"tr_all_aligned": "False", "net": -200}, {"tr_all_aligned": "True", "net": -100}]
        text = "\n".join(tr.verdict_section(rows))
        self.assertIn("5M and 15M agree with the trade | 2 | 1 | +400", text)


if __name__ == "__main__":
    unittest.main()
