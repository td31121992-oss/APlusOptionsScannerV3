import os
import tempfile
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

os.environ["TELEGRAM_ENABLED"] = "false"

import entry_tags as et
import paper_trade_journal as pj
from tests.test_journal_costs_and_session_end import _journal, _open_trade

IST = ZoneInfo("Asia/Kolkata")
T0 = datetime(2026, 10, 14, 10, 0, tzinfo=IST)


def candles(n, rng_pct, start=100.0):
    out, px = [], start
    t0 = datetime(2026, 10, 14, 9, 15)
    for i in range(n):
        half = px * rng_pct / 200.0
        out.append(SimpleNamespace(timestamp=t0 + timedelta(minutes=5 * i), open=px, high=px + half, low=px - half, close=px + 0.01, volume=1000))
    return out


class VolStopTests(unittest.TestCase):
    def test_quiet_stock_gets_a_tight_stop_and_busy_one_the_full_stop(self):
        quiet = et.entry_context(candles(14, 0.15), "BULLISH")        # 0.15% average 5-min range -> 2 x 0.15 x 23 = 6.9% -> floor 8%
        busy = et.entry_context(candles(14, 0.60), "BULLISH")         # 0.60% -> 27.6% -> capped at 20%
        mid = et.entry_context(candles(14, 0.30), "BULLISH")          # 0.30% -> 13.8%
        self.assertEqual(quiet["ctx_vol_stop30_pct"], 8.0)
        self.assertEqual(busy["ctx_vol_stop30_pct"], 20.0)
        self.assertAlmostEqual(mid["ctx_vol_stop30_pct"], 13.8, delta=0.2)
        self.assertIn("ctx_vol_stop60_pct", mid)

    def test_shadow_exits_at_the_tight_stop_while_the_real_trade_stays_open(self):
        self.assertIn("volstop30", pj.STOP_SHADOW_NAMES)
        with tempfile.TemporaryDirectory() as tmp:
            tr = _open_trade(entry_time="2026-10-14T10:00:00+05:30", option_stop=8.0, option_target1=50.0,
                             ctx_vol_stop30_pct=12.0, ctx_vol_stop60_pct=18.0)       # entry 10.0, real stop 8.0 (-20%)
            j = _journal(tmp, "2026-10-14", [tr])
            for i, p in enumerate([10.1, 9.7, 8.75, 8.5]):                          # 8.75 is -12.5%: breaks the 12% stop, not the real one
                j.update_open_positions(option_quotes={"123": {"last_price": p}}, when=T0 + timedelta(minutes=i + 1))
            t = j.trades[0]
            self.assertEqual(t["status"], "OPEN")
            self.assertEqual(t["shadow_volstop30_exit_price"], 8.75)
            self.assertNotIn("shadow_volstop60_exit_at", t)                         # the 18% stop (8.2) is not broken yet
            self.assertAlmostEqual(t["shadow_volstop30_floor"], 8.8, places=2)

    def test_missing_or_full_size_stop_adds_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            tr = _open_trade(entry_time="2026-10-14T10:00:00+05:30", option_stop=8.0, option_target1=50.0, ctx_vol_stop30_pct=20.0)
            j = _journal(tmp, "2026-10-14", [tr])
            j.update_open_positions(option_quotes={"123": {"last_price": 8.5}}, when=T0 + timedelta(minutes=1))
            self.assertNotIn("shadow_volstop30_exit_at", j.trades[0])
            self.assertNotIn("shadow_volstop60_exit_at", j.trades[0])


if __name__ == "__main__":
    unittest.main()
