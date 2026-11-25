import unittest

import held_shadow_book as hb


def rows(prices, start_min=0, **extra):
    """prices: (ltp, bid, ask) once a minute from 09:30 + start_min."""
    out = []
    for i, (ltp, bid, ask) in enumerate(prices):
        out.append({"captured_at": f"2026-11-25T09:{30 + start_min + i:02d}:05+05:30", "signal_time": "2026-11-25T09:30:00", "ltp": ltp, "bid": bid, "ask": ask, "lot": 100,
                    "symbol": "AAA", "direction": "BULLISH", "kind": "ITM1", "group": "EXTENDED_WAIT", "status": "A_PLUS_WAIT_LATE_10M_OVERHEAT", "strike": 100, **extra})
    return out


class SimulateTests(unittest.TestCase):
    def test_buys_at_ask_and_initial_stop_fills_at_bid(self):
        t = hb.simulate(rows([(100, 99, 100), (90, 89, 91), (79, 78, 80), (120, 119, 121)]))
        self.assertEqual((t["entry"], t["exit"], t["how"]), (100, 78, "stop"))
        self.assertLess(t["net"], (78 - 100) * 100)                              # costs charged on top

    def test_target1_moves_stop_to_cost(self):
        t = hb.simulate(rows([(100, 99, 100), (121, 120, 122), (99, 98, 100)]))
        self.assertEqual((t["how"], t["exit"], t["mfe_pct"]), ("stop", 98, 21.0))

    def test_runner_floor_after_target3(self):
        t = hb.simulate(rows([(100, 99, 100), (160, 159, 161), (141, 140, 142)]))   # floor = 100 + 60 x 0.70 = 142
        self.assertEqual((t["how"], t["exit"]), ("stop", 140))

    def test_unfinished_day_is_open_and_late_price_is_dropped(self):
        self.assertEqual(hb.simulate(rows([(100, 99, 100), (105, 104, 106)]))["how"], "open")
        self.assertIsNone(hb.simulate(rows([(100, 99, 100)], start_min=7)))           # first price 7 minutes after the signal


class ReportTests(unittest.TestCase):
    def trade(self, day="2026-11-25", net=100.0, **extra):
        return {"day": day, "net": net, "direction": "BULLISH", "status": "A_PLUS_WAIT_LATE_VWAP_EXTENSION", "signal_time": "2026-11-25T09:40:00", "kind": "ITM1", "group": "EXTENDED_WAIT",
                "how": "end", "spread_pct": 0.5, **extra}

    def test_narrow_rule(self):
        self.assertTrue(hb.is_narrow(self.trade()))
        for bad in ({"direction": "BEARISH"}, {"status": "A_PLUS_WAIT_LATE_CLOSE_EXTENSION"}, {"signal_time": "2026-11-25T10:30:00"}):
            self.assertFalse(hb.is_narrow(self.trade(**bad)))

    def test_pass_mark(self):
        passed = hb.stats([self.trade(net=-10.0)])
        self.assertTrue(hb.verdict(hb.stats([self.trade()]), passed).startswith("COLLECTING"))
        good = [self.trade(day=f"2026-12-{d:02d}") for d in range(1, 11) for _ in range(10)]
        self.assertTrue(hb.verdict(hb.stats(good), passed).startswith("PASSES"))
        lucky = [self.trade(day=t["day"], net=-100.0) for t in good]
        lucky[0]["net"] = 50000.0
        self.assertIn("without its 5 best", hb.verdict(hb.stats(lucky), passed))

    def test_render_with_no_data(self):
        self.assertIn("COLLECTING", hb.render([]))


if __name__ == "__main__":
    unittest.main()
