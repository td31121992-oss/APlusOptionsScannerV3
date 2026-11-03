import unittest
from types import SimpleNamespace as NS

import flow_tags as ft


def leg(oi, ltp, iv=30.0):
    return NS(oi=oi, ltp=ltp, iv=iv, volume=10, bid=ltp - 0.1, ask=ltp + 0.1, previous_oi=oi, previous_close=ltp, oi_change=0)


def snap(oi_by_strike):
    rows = []
    for k, (coi, poi) in oi_by_strike.items():
        rows.append(NS(strike=k, call=leg(coi, max(0.5, 100.5 - k) + 3), put=leg(poi, max(0.5, k - 99.5) + 3)))
    return NS(symbol="ZZ", expiry="2026-12-31", underlying_ltp=100.0, strikes=sorted(rows, key=lambda r: r.strike))


class GammaTests(unittest.TestCase):
    def test_wall_and_share_ahead(self):
        s = snap({96: (100, 100), 98: (100, 100), 100: (5000, 5000), 102: (100, 100), 104: (100, 100)})
        t = ft.gamma_tags(s, "BEARISH", 100.0)
        self.assertEqual(t["fp_gamma_wall"], 100)
        self.assertEqual(t["fp_gamma_ahead_strike"], 98)                       # first strike below the stock for a put
        self.assertLess(t["fp_gamma_ahead_share"], 0.2)                        # little gamma in our way
        up = ft.gamma_tags(s, "BULLISH", 100.0)
        self.assertEqual(up["fp_gamma_ahead_strike"], 102)

    def test_big_gamma_right_ahead_gives_a_high_share(self):
        s = snap({96: (100, 100), 98: (9000, 9000), 100: (200, 200), 102: (100, 100)})
        t = ft.gamma_tags(s, "BEARISH", 100.0)
        self.assertEqual(t["fp_gamma_ahead_strike"], 98)
        self.assertEqual(t["fp_gamma_ahead_share"], 1.0)
        self.assertLess(t["fp_gamma_wall_dist_pct"], 0)

    def test_bad_input(self):
        self.assertEqual(ft.gamma_tags(None, "BULLISH", 100.0), {})
        self.assertEqual(ft.gamma_tags(NS(strikes=[]), "BULLISH", 100.0), {})


class OiWindowTests(unittest.TestCase):
    def test_needs_an_earlier_look_and_reports_flat_or_not(self):
        ft._oi_seen.clear()
        s = snap({98: (1000, 1000), 100: (1000, 1000), 102: (1000, 1000)})
        self.assertEqual(ft.oi_window_tags(s, "BEARISH", 100.0, now=1000.0), {})        # first look: nothing to compare with
        t = ft.oi_window_tags(s, "BEARISH", 100.0, now=1000.0 + 10 * 60)
        self.assertEqual((t["fp_oi_win_min"], t["fp_oi_win_pct"], t["fp_oi_flat"]), (10.0, 0.0, True))
        for k in s.strikes:
            k.put.oi = 1100
        t2 = ft.oi_window_tags(s, "BEARISH", 100.0, now=1000.0 + 12 * 60)
        self.assertEqual((t2["fp_oi_win_pct"], t2["fp_oi_flat"]), (10.0, False))
        self.assertEqual(ft.oi_window_tags(s, "BEARISH", 100.0, now=1000.0 + 12 * 60 + 3600), {})   # too old (and the old looks were dropped)


def bars(deltas):
    out, cum = [], 0
    for i, d in enumerate(deltas):
        cum += d
        out.append({"delta": d, "cum_delta": cum, "buy_vol": max(d, 0) + 100, "sell_vol": max(-d, 0) + 100})
    return out


class CvdTests(unittest.TestCase):
    def test_steady_selling_is_linear_for_a_put(self):
        t = ft.cvd_line_stats(bars([-100] * 12), "BEARISH")
        self.assertEqual(t["fp_cvd_r2"], 1.0)
        self.assertGreater(t["fp_cvd_dir"], 0)
        self.assertTrue(t["fp_cvd_linear"])
        self.assertFalse(ft.cvd_line_stats(bars([-100] * 12), "BULLISH")["fp_cvd_linear"])       # same tape, wrong side

    def test_choppy_delta_is_not_linear(self):
        t = ft.cvd_line_stats(bars([-300, 280, -310, 290, -300, 310, -290, 300, -280, 270, -300, 300]), "BEARISH")
        self.assertLess(t["fp_cvd_r2"], 0.3)
        self.assertFalse(t["fp_cvd_linear"])

    def test_too_few_bars_and_missing_file(self):
        self.assertEqual(ft.cvd_line_stats(bars([-1, -1]), "BEARISH"), {})
        self.assertEqual(ft.cvd_tags("NOPE", "BEARISH", "2000-01-01"), {})


if __name__ == "__main__":
    unittest.main()
