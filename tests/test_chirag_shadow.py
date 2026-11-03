import unittest
from datetime import date

import numpy as np
import pandas as pd

import chirag_shadow as cs


def make_m5(days, start_price, step):
    """Straight-line 5-minute bars, 09:15..15:25, continuing across days."""
    rows, p = [], start_price
    for d in days:
        for k in range(75):
            ts = pd.Timestamp(d) + pd.Timedelta(hours=9, minutes=15 + 5 * k)
            o, c = p, p + step
            rows.append((ts, o, max(o, c) + abs(step) * 0.2, min(o, c) - abs(step) * 0.2, c, 1000))
            p = c
    return pd.DataFrame(rows, columns=["ts", "o", "h", "l", "c", "v"]).set_index("ts")


def make_daily(m5):
    g = m5.groupby(m5.index.normalize())
    return pd.DataFrame({"h": g.h.max(), "l": g.l.min(), "c": g.c.last()})


class SetupTests(unittest.TestCase):
    days = list(pd.bdate_range("2026-08-03", periods=40))

    def _run(self, step):
        m5 = make_m5(self.days, 1000.0, step)
        daily = make_daily(m5)
        scan = self.days[-1] + pd.Timedelta(hours=10, minutes=10)
        return cs.evaluate_setup(daily, m5, scan)

    def test_steady_uptrend_is_bullish(self):
        out = self._run(0.05)
        self.assertEqual(out["side"], "BULL")
        self.assertGreater(out["rsi_daily"], 60)

    def test_steady_downtrend_is_bearish(self):
        self.assertEqual(self._run(-0.05)["side"], "BEAR")

    def test_flat_market_has_no_setup(self):
        self.assertIsNone(self._run(0.0))

    def test_missing_scan_bar_returns_none(self):
        m5 = make_m5(self.days, 1000.0, 0.05)
        self.assertIsNone(cs.evaluate_setup(make_daily(m5), m5, self.days[-1] + pd.Timedelta(hours=10, minutes=12)))


class MarketTests(unittest.TestCase):
    def test_nifty_rule(self):
        self.assertTrue(cs.market_allows("BULL", True, True))
        self.assertTrue(cs.market_allows("BEAR", True, True))
        self.assertFalse(cs.market_allows("BULL", False, False))      # red market: bearish only
        self.assertTrue(cs.market_allows("BEAR", False, False))
        self.assertFalse(cs.market_allows("BEAR", True, False))       # Nifty and Bank Nifty disagree
        self.assertFalse(cs.market_allows("BEAR", None, True))

    def test_pivots(self):
        prev = pd.DataFrame({"h": [110.0], "l": [90.0], "c": [100.0]})
        lv = cs.pivots(prev)
        self.assertAlmostEqual(lv["P"], 100.0)
        self.assertAlmostEqual(lv["R1"], 110.0)
        self.assertAlmostEqual(lv["S1"], 90.0)
        self.assertAlmostEqual(lv["R2"], 120.0)


class OptionTests(unittest.TestCase):
    day = pd.Timestamp("2026-10-09")

    def _candles(self, prices):
        prev = pd.DataFrame({"o": [100.0, 100.0], "h": [110.0, 105.0], "l": [90.0, 95.0], "c": [100.0, 100.0], "v": [1000, 1000]},
                            index=[pd.Timestamp("2026-10-08 10:00"), pd.Timestamp("2026-10-08 15:00")])
        rows = []
        for k, (o, h, lo, c) in enumerate(prices):
            rows.append((self.day + pd.Timedelta(hours=9, minutes=15 + 5 * k), o, h, lo, c, 1000))
        today = pd.DataFrame(rows, columns=["ts", "o", "h", "l", "c", "v"]).set_index("ts")
        return pd.concat([prev, today])

    def _flat_rise(self, n=14):
        out, p = [], 101.5
        for _ in range(n):
            out.append((p, p + 0.1, p - 0.1, p + 0.05))
            p += 0.05
        return out

    def test_target_hit_at_upper_pivot(self):
        bars = self._flat_rise() + [(102.2, 111.0, 102.0, 109.0)]
        res = cs.replay_option(self._candles(bars), self.day, self.day + pd.Timedelta(hours=10), 1000)
        self.assertEqual((res["status"], res["reason"]), ("CLOSED", "PIVOT_TARGET"))
        self.assertEqual(res["exit"], 110.0)

    def test_trailing_stop_after_a_gain(self):
        bars = self._flat_rise() + [(102.3, 106.0, 102.2, 105.0), (105.0, 105.5, 100.2, 101.0)]
        res = cs.replay_option(self._candles(bars), self.day, self.day + pd.Timedelta(hours=10), 1000)
        self.assertEqual(res["reason"], "TRAIL5")
        self.assertAlmostEqual(res["exit"], round(106.0 * 0.95, 2), places=1)

    def test_close_below_pivot_is_the_stop(self):
        bars = self._flat_rise() + [(102.3, 102.4, 99.2, 99.5)]
        res = cs.replay_option(self._candles(bars), self.day, self.day + pd.Timedelta(hours=10), 1000)
        self.assertEqual(res["reason"], "PIVOT_SL")

    def test_loss_cap(self):
        bars = self._flat_rise() + [(102.3, 102.4, 60.0, 61.0)]
        res = cs.replay_option(self._candles(bars), self.day, self.day + pd.Timedelta(hours=10), 100)     # lot 100 -> Rs 4000 = 40 points
        self.assertEqual(res["reason"], "LOSS_CAP")

    def test_waits_when_no_data_for_today_yet(self):
        res = cs.replay_option(self._candles([]), self.day, self.day + pd.Timedelta(hours=10), 100)
        self.assertEqual(res["status"], "NO_DATA")


class PickTests(unittest.TestCase):
    def test_next_of_atm_and_month_roll(self):
        rows = []
        for exp in ("2026-10-27", "2026-11-24"):
            for k in (90, 100, 110, 120):
                for kind in ("CE", "PE"):
                    rows.append(dict(UNDERLYING_SYMBOL="AAA", OPTION_TYPE=kind, exp=exp, STRIKE_PRICE=float(k), SECURITY_ID=int(k) + (1 if kind == "CE" else 2), LOT_SIZE=500))
        m = pd.DataFrame(rows)
        ce = cs.pick_option(m, "AAA", "BULL", 101.0, date(2026, 10, 9))
        self.assertEqual((ce["strike"], ce["expiry"], ce["kind"]), (110.0, "2026-10-27", "CE"))      # ATM 100 -> next 110
        pe = cs.pick_option(m, "AAA", "BEAR", 101.0, date(2026, 10, 9))
        self.assertEqual(pe["strike"], 90.0)
        late = cs.pick_option(m, "AAA", "BULL", 101.0, date(2026, 10, 20))                           # after the 18th: next month
        self.assertEqual(late["expiry"], "2026-11-24")


if __name__ == "__main__":
    unittest.main()
