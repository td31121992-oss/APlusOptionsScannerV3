from __future__ import annotations

import unittest

import numpy as np

import daily_indicators as di
from stock_alerts import evaluate_rows, rule_catalog


def series(n=260, start=100.0, step=0.5):
    c = [start + i * step for i in range(n)]
    return [x + 1 for x in c], [x - 1 for x in c], c


class IndicatorTests(unittest.TestCase):
    def test_ranges_and_averages_use_completed_days(self) -> None:
        h, l, c = series()
        ind = di.compute_indicators(h, l, c)
        self.assertAlmostEqual(ind["hi_5d"], max(h[-5:]))
        self.assertAlmostEqual(ind["lo_10d"], min(l[-10:]))
        self.assertAlmostEqual(ind["dma50"], float(np.mean(c[-50:])))
        self.assertGreater(ind["ema20"], ind["dma200"])           # rising series: fast average above slow
        self.assertEqual(ind["st_dir"], 1)

    def test_enrich_marks_breakouts_crosses_and_supertrend_flip(self) -> None:
        h, l, c = series()
        ind = {"AAA": di.compute_indicators(h, l, c)}
        top = ind["AAA"]["hi_5d"]
        rows = di.enrich_rows([{"symbol": "AAA", "ltp": top + 5}, {"symbol": "ZZZ", "ltp": 100}], ind)
        a, z = rows
        self.assertTrue(a["range_5d_breakout"])
        self.assertFalse(a["range_5d_breakdown"])
        self.assertFalse(z["range_5d_breakout"])                   # no indicators -> silent
        self.assertEqual(z["supertrend_direction"], "")
        # a crash below the supertrend lower band flips it to "down"
        crash = di.enrich_rows([{"symbol": "AAA", "ltp": ind["AAA"]["st_lower"] - 1}], ind)[0]
        self.assertEqual(crash["supertrend_direction"], "down")

    def test_cross_requires_prev_close_on_the_other_side(self) -> None:
        ind = {"AAA": {"last_close": 99.0, "dma50": 100.0, "dma100": 0.0, "dma200": 0.0, "ema20": 0.0}}
        crossed = di.enrich_rows([{"symbol": "AAA", "ltp": 101.0}], ind)[0]
        self.assertTrue(crossed["dma50_breakout"])
        self.assertFalse(crossed["dma200_breakout"])
        stayed = di.enrich_rows([{"symbol": "AAA", "ltp": 99.5}], ind)[0]
        self.assertFalse(stayed["dma50_breakout"])

    def test_alert_rules_become_available_and_fire(self) -> None:
        h, l, c = series()
        ind = {"AAA": di.compute_indicators(h, l, c)}
        rows = di.enrich_rows([{"symbol": "AAA", "ltp": ind["AAA"]["hi_52w"] + 10, "day_high": 1, "from_open_pct": 0.1}], ind)
        available = [r["rule_id"] for r in rule_catalog(rows) if r["available"]]
        self.assertGreaterEqual(len(available), 18)
        fired = {a["rule_id"] for a in evaluate_rows(rows)}
        self.assertIn("range_52w_bo", fired)
        self.assertIn("range_5d_bo", fired)


class PreviousDayTests(unittest.TestCase):
    def test_previous_day_high_low_breakouts(self) -> None:
        h, l, c = series()
        ind = {"AAA": di.compute_indicators(h, l, c)}
        self.assertEqual((ind["AAA"]["pdh"], ind["AAA"]["pdl"]), (h[-1], l[-1]))
        up = di.enrich_rows([{"symbol": "AAA", "ltp": h[-1] + 1}], ind)[0]
        dn = di.enrich_rows([{"symbol": "AAA", "ltp": l[-1] - 1}], ind)[0]
        self.assertTrue(up["pdh_breakout"] and not up["pdl_breakdown"])
        self.assertTrue(dn["pdl_breakdown"] and not dn["pdh_breakout"])
        fired = {a["rule_id"] for a in evaluate_rows([up, dn])}
        self.assertTrue({"pdh_bo", "pdl_bd"} <= fired)


if __name__ == "__main__":
    unittest.main()
