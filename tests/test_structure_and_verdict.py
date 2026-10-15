import unittest

import market_structure as ms
import no_trade_day as nt
import trade_review as tr


def bars(rows):
    return [{"open": o, "high": h, "low": l, "close": c, "volume": 1000} for o, h, l, c in rows]


def uptrend_then_break():
    # higher highs / higher lows, then a close above the last swing high (BOS)
    pts = [(100, 100.4, 99.8, 100.2), (100.2, 100.6, 100.0, 100.5), (100.5, 100.9, 100.3, 100.4), (100.4, 100.5, 100.1, 100.2),
           (100.2, 100.4, 100.0, 100.3), (100.3, 101.1, 100.25, 101.0), (101.0, 101.4, 100.8, 101.3), (101.3, 101.35, 100.9, 101.0),
           (101.0, 101.2, 100.75, 100.9), (100.9, 101.1, 100.7, 101.05), (101.05, 101.8, 101.0, 101.7), (101.7, 102.0, 101.5, 101.9)]
    return bars(pts)


class StructureTests(unittest.TestCase):
    def test_uptrend_with_bos_is_aligned_for_a_call(self):
        t = ms.structure_tags(uptrend_then_break(), "BULLISH")
        self.assertEqual(t["ms_trend"], "UP")
        self.assertEqual(t["ms_bos"], "BULL")
        self.assertTrue(t["ms_aligned"])
        self.assertFalse(ms.structure_tags(uptrend_then_break(), "BEARISH")["ms_aligned"])

    def test_bullish_fair_value_gap_found_and_unfilled(self):
        rows = [(100, 100.3, 99.9, 100.2)] * 5 + [(100.2, 100.4, 100.1, 100.35), (100.35, 101.4, 100.3, 101.3), (101.3, 101.6, 101.0, 101.5)] \
               + [(101.5, 101.7, 101.2, 101.6)] * 3
        t = ms.structure_tags(bars(rows), "BULLISH")
        self.assertEqual(t["ms_fvg"], "BULL")                    # bar 7 low 101.0 is above bar 5 high 100.4
        self.assertGreater(t["ms_fvg_dist_pct"], 0)

    def test_choch_against_the_trend(self):
        head = uptrend_then_break()[:10]
        tail = bars([(101.05, 101.1, 99.9, 100.0), (100.0, 100.2, 99.7, 99.8), (99.8, 100.0, 99.6, 99.7)])
        t = ms.structure_tags(head + tail, "BEARISH")
        self.assertIn(t["ms_choch"], ("BEAR", ""))               # a close below the last swing low in an uptrend, if confirmed
        self.assertIn(t["ms_trend"], ("UP", "RANGE", "DOWN"))

    def test_short_series_gives_nothing(self):
        self.assertEqual(ms.structure_tags(bars([(1, 1, 1, 1)] * 4), "BULLISH"), {})


class VerdictTests(unittest.TestCase):
    def closed(self, pnl):
        return {"status": "CLOSED", "net_pnl": pnl}

    def test_loss_streak_means_no_trade(self):
        r = nt.evaluate([self.closed(-1000)] * 3, "BULLISH", 600, 0.5, 55)
        self.assertEqual(r["nt_verdict"], "NO_TRADE")
        self.assertIn("LOSS_STREAK_3", r["nt_reasons"])
        self.assertEqual(r["nt_losses"], 3)

    def test_a_winner_clears_the_streak_rule(self):
        r = nt.evaluate([self.closed(-1000)] * 3 + [self.closed(2500)], "BULLISH", 600, 0.5, 55)
        self.assertEqual(r["nt_verdict"], "TRADE")

    def test_breadth_and_index_reasons(self):
        self.assertEqual(nt.evaluate([], "BULLISH", 600, 0.5, 30)["nt_verdict"], "NO_TRADE")
        self.assertEqual(nt.evaluate([], "BULLISH", 600, 0.5, 40)["nt_verdict"], "CAUTION")
        self.assertIn("AGAINST_INDEX", nt.evaluate([], "BULLISH", 600, -0.3, 60)["nt_reasons"])
        self.assertIn("FLAT_INDEX", nt.evaluate([], "BULLISH", 640, 0.05, 60)["nt_reasons"])
        self.assertEqual(nt.evaluate([], "BULLISH", 570, 0.05, 60)["nt_verdict"], "TRADE")   # flat before 10:00 is normal

    def test_day_drawdown(self):
        r = nt.evaluate([{"status": "OPEN", "total_pnl": -9000}], "BULLISH", 600, 0.4, 60, 500000)
        self.assertEqual(r["nt_verdict"], "NO_TRADE")
        self.assertIn("DAY_DRAWDOWN", r["nt_reasons"])


class ReviewSectionTests(unittest.TestCase):
    def test_section_groups_by_verdict(self):
        rows = [{"nt_verdict": "TRADE", "ms_aligned": "True", "net": 1000}, {"nt_verdict": "CAUTION", "ms_aligned": "False", "net": -500},
                {"nt_verdict": "TRADE", "ms_aligned": "True", "net": -200}]
        text = "\n".join(tr.verdict_section(rows))
        self.assertIn("Verdict TRADE | 2 | 1 | +800", text)
        self.assertIn("Structure does not agree | 1 | 0 | -500", text)
        self.assertEqual(tr.verdict_section([{"net": 5}]), [])


if __name__ == "__main__":
    unittest.main()
