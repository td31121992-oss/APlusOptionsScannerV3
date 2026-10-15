import unittest

import market_xray as mx


def rows():
    return [{"symbol": "AAA", "sector": "IT", "open_0915": 100.0, "ltp": 102.0, "from_prev_close_pct": 2.5},
            {"symbol": "BBB", "sector": "IT", "open_0915": 200.0, "ltp": 198.0, "from_prev_close_pct": -0.5},
            {"symbol": "CCC", "sector": "Pharma", "open_0915": 50.0, "ltp": 49.0, "from_prev_close_pct": -2.5},
            {"symbol": "DDD", "sector": "Pharma", "open_0915": 0, "ltp": 10.0},           # no open: skipped
            {"symbol": "EEE", "sector": "Pharma", "open_0915": 100.0, "ltp": 100.0}]


class XrayTests(unittest.TestCase):
    def test_counts_sectors_and_leaders(self):
        d = mx.build(rows(), {}, 9 * 60 + 40)
        self.assertEqual((d["bullish"], d["bearish"], d["flat"]), (1, 2, 1))
        self.assertEqual(d["leading"]["name"], "IT")
        self.assertEqual(d["lagging"]["name"], "Pharma")
        self.assertEqual([s["s"] for s in d["stocks"]], ["AAA", "BBB", "CCC", "EEE"])
        self.assertEqual(d["minutes"][0], 555)
        self.assertEqual(d["now"], "09:40")

    def test_path_uses_ticks_and_ends_on_the_live_price(self):
        ticks = {"AAA": [(555, 100.0), (562, 101.0), (572, 103.0)]}
        d = mx.build(rows(), ticks, 9 * 60 + 35)
        a = next(s for s in d["stocks"] if s["s"] == "AAA")
        self.assertEqual(len(a["p"]), len(d["minutes"]))
        self.assertEqual(a["p"][0], 0.0)
        self.assertEqual(a["p"][1], 0.0)                       # 09:20: the 562 tick has not happened yet
        self.assertEqual(a["p"][-1], 2.0)                      # the last point is the live price 102 vs 100
        b = next(s for s in d["stocks"] if s["s"] == "BBB")
        self.assertTrue(all(v is None for v in b["p"][:-1]))   # no ticks: only the live endpoint

    def test_grid_path_carries_forward(self):
        p = mx.grid_path([(556, 100.0), (571, 105.0)], 100.0, 9 * 60 + 35)
        self.assertEqual(p, [None, 0.0, 0.0, 0.0, 5.0])

    def test_page_has_the_canvases(self):
        for key in ("id=\"race\"", "id=\"rank\"", "id=\"dots\"", "/api/market-xray"):
            self.assertIn(key, mx.XRAY_HTML)


if __name__ == "__main__":
    unittest.main()
