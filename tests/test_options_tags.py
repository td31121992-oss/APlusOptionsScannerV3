import unittest
from types import SimpleNamespace as NS

import options_tags as ot


def leg(oi, vol=0, iv=0.0, d_oi=0, prev=0):
    return NS(oi=oi, volume=vol, iv=iv, oi_change=d_oi, previous_oi=prev)


def snap():
    rows = [(95, leg(100, 10, 30, 0, 100), leg(900, 50, 31, 200, 700)),
            (100, leg(500, 40, 28, -100, 600), leg(500, 60, 32, 300, 200)),
            (105, leg(1500, 80, 27, 50, 1450), leg(100, 5, 33, 0, 100)),
            (110, leg(300, 20, 26, 0, 300), leg(50, 2, 34, 0, 50))]
    return NS(underlying_ltp=100.0, strikes=[NS(strike=k, call=c, put=p) for k, c, p in rows])


class OptionTagTests(unittest.TestCase):
    def test_walls_pcr_iv(self):
        t = ot.chain_tags(snap(), "BULLISH", 100.0)
        self.assertEqual(t["oc_call_wall"], 105)
        self.assertEqual(t["oc_put_wall"], 95)
        self.assertAlmostEqual(t["oc_pcr_oi"], round(1550 / 2400, 2))
        self.assertEqual(t["oc_atm_iv"], 30.0)
        self.assertEqual(t["oc_iv_skew"], 4.0)
        self.assertEqual(t["oc_room_pct"], 5.0)
        self.assertFalse(t["oc_wall_close"])

    def test_direction_picks_the_wall_in_our_way(self):
        t = ot.chain_tags(snap(), "BEARISH", 100.0)
        self.assertEqual(t["oc_room_pct"], t["oc_put_wall_pct"])

    def test_wall_close_flag(self):
        s = snap()
        self.assertTrue(ot.chain_tags(s, "BULLISH", 104.5)["oc_wall_close"])

    def test_flow_sign_and_alignment(self):
        t = ot.chain_tags(snap(), "BULLISH", 100.0)
        self.assertGreater(t["oc_flow"], 0)                        # put OI added, call OI shed
        self.assertTrue(t["oc_flow_aligned"])
        self.assertFalse(ot.chain_tags(snap(), "BEARISH", 100.0)["oc_flow_aligned"])

    def test_missing_previous_oi_gives_no_flow(self):
        s = snap()
        for k in s.strikes:
            k.call.previous_oi = k.put.previous_oi = 0
        self.assertNotIn("oc_flow", ot.chain_tags(s, "BULLISH", 100.0))

    def test_contract_quality_and_iv_rank(self):
        import tempfile
        from pathlib import Path

        import iv_history as ivh

        s = snap()
        s.symbol, s.expiry = "ZZZ", "2026-12-31"
        for k in s.strikes:
            for lg in (k.call, k.put):
                lg.ltp, lg.bid, lg.ask, lg.previous_close = 5.0, 4.9, 5.1, 4.0
        t = ot.chain_tags(s, "BULLISH", 100.0)
        self.assertEqual(t["oc_k_strike"], 100)                    # 99.5 wanted: nearest listed strike
        self.assertAlmostEqual(t["oc_k_spread_pct"], 4.0, places=1)
        self.assertEqual(t["oc_k_run_pct"], 25.0)
        self.assertIn("oc_k_delta", t)
        self.assertNotIn("oc_iv_rank", t)                          # no history yet
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for i in range(12):
                ivh.record("Q", 20.0 + i, f"2026-09-{i + 1:02d}", root)
            self.assertEqual(ivh.rank("Q", 25.5, root=root, day="2026-10-01"), 50.0)
            self.assertIsNone(ivh.rank("Q", 25.5, root=root, day="2026-09-05"))      # fewer than 10 earlier days

    def test_bad_input_never_raises(self):
        self.assertEqual(ot.chain_tags(None, "BULLISH", 100.0), {})
        self.assertEqual(ot.chain_tags(NS(strikes=[]), "BULLISH", 100.0), {})


if __name__ == "__main__":
    unittest.main()
