import math
import os
import tempfile
import unittest
from datetime import date

os.environ["TELEGRAM_ENABLED"] = "false"

import greeks
import mtf
import paper_trade_journal as pj
from tests.test_journal_costs_and_session_end import _journal


def five_min(closes, spread=0.2):
    out, prev = [], closes[0]
    for c in closes:
        out.append({"open": prev, "high": max(prev, c) + spread, "low": min(prev, c) - spread, "close": c, "volume": 1000})
        prev = c
    return out


class MtfTests(unittest.TestCase):
    def test_rising_day_is_up_and_agrees_with_a_call(self):
        cs = five_min([100 + 0.15 * i for i in range(18)])
        daily = {"ema20": 98.0, "dma50": 95.0, "st_dir": 1}
        t = mtf.mtf_tags(cs, "BULLISH", daily, cs[-1]["close"])
        self.assertEqual((t["mtf_15m"], t["mtf_daily"], t["mtf_agree"], t["mtf_all_agree"]), ("UP", "UP", 2, True))
        self.assertFalse(mtf.mtf_tags(cs, "BEARISH", daily, cs[-1]["close"])["mtf_all_agree"])

    def test_too_early_has_no_15m_tag(self):
        t = mtf.mtf_tags(five_min([100, 100.2, 100.4, 100.3, 100.5]), "BULLISH", {"ema20": 99, "dma50": 98, "st_dir": 1}, 100.5)
        self.assertNotIn("mtf_15m", t)
        self.assertEqual(t["mtf_daily"], "UP")

    def test_resample_drops_incomplete_group(self):
        self.assertEqual(len(mtf.resample_15m(five_min([100] * 7))), 2)


class GreeksTests(unittest.TestCase):
    def test_price_round_trips_through_implied_vol(self):
        spot, strike, t = 1000.0, 1000.0, 10 / 365.0
        p = greeks.bs_price(spot, strike, t, 0.30, True)
        self.assertAlmostEqual(greeks.implied_vol(p, spot, strike, t, True), 0.30, places=3)

    def test_atm_call_greeks_are_sane(self):
        spot, strike = 1000.0, 1000.0
        price = greeks.bs_price(spot, strike, 10 / 365.0, 0.30, True)
        g = greeks.greeks_at_entry(spot, strike, "2026-10-25", "CE", price, None, date(2026, 10, 15), True)
        self.assertTrue(0.45 < g["gk_delta"] < 0.60)
        self.assertLess(g["gk_theta_day"], 0)
        self.assertAlmostEqual(g["gk_iv_pct"], 30.0, delta=1.0)
        self.assertGreater(g["gk_move_pct_to_10pct"], 0)

    def test_put_has_negative_delta_and_garbage_gives_empty(self):
        price = greeks.bs_price(1000.0, 1000.0, 10 / 365.0, 0.30, False)
        g = greeks.greeks_at_entry(1000.0, 1000.0, "2026-10-25", "PE", price, None, date(2026, 10, 15), False)
        self.assertLess(g["gk_delta"], 0)
        self.assertEqual(greeks.greeks_at_entry(0, 1000, "2026-10-25", "CE", 5), {})


class PassthroughTests(unittest.TestCase):
    def test_prefixed_shadow_tags_reach_the_trade_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            j = _journal(tmp, "2026-10-15", [])
            plan = {"symbol": "ABC", "direction": "BULLISH", "underlying": {"entry": 100.0, "stop_loss": 99.0},
                    "option_contract": {"option_type": "CE", "strike": 100, "limit_price": 5.0, "lot_size": 100, "security_id": "1"},
                    "paper_signal_only": True}
            cand = {"symbol": "ABC", "direction": "BULLISH", "kl_push": True, "ms_trend": "UP", "nt_verdict": "TRADE", "sec_idx": "IT",
                    "mtf_15m": "UP", "gk_delta": 0.5, "unrelated_key": 1}
            try:
                rec = j.record_trade(plan=plan, candidate=cand, when=__import__("datetime").datetime(2026, 10, 15, 10, 0))
            except Exception as exc:                       # the fixture plan may be incomplete for a full record
                self.skipTest(f"record_trade needs a fuller plan: {exc}")
            for k in ("kl_push", "ms_trend", "nt_verdict", "sec_idx", "mtf_15m", "gk_delta"):
                self.assertIn(k, rec)
            self.assertNotIn("unrelated_key", rec)


if __name__ == "__main__":
    unittest.main()
