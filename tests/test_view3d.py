import unittest

import view3d


class View3dTests(unittest.TestCase):
    def test_build_merges_market_flow_and_trades(self):
        mw = {"rows": [{"symbol": "abc", "sector": "Auto", "from_open_pct": 1.234, "ltp": 100, "range_position_pct": 80.4}, {"symbol": "", "sector": "x"}, {"symbol": "XYZ"}]}
        flow = {"as_of": "15:30", "stocks": [{"symbol": "ABC", "flow_pct": 12.34, "net_cr": 5.55, "traded_cr": 40}],
                "sectors": [{"sector": "Auto", "flow_pct": 3, "net_cr": 9, "chg_pct": 0.5, "stocks": 4, "up": 3, "down": 1}]}
        snap = {"rows": [{"symbol": "ABC", "side": "BULLISH CE", "status": "OPEN", "entry_time": "10:05:00", "entry": 100, "last": 130, "high": 150, "sl": 100, "pnl": 3000},
                         {"symbol": "BAD", "entry": 0}]}
        out = view3d.build(mw, flow, snap)
        self.assertEqual([s["s"] for s in out["stocks"]], ["ABC", "XYZ"])
        abc = out["stocks"][0]
        self.assertEqual((abc["mv"], abc["flow"], abc["cr"], abc["traded"], abc["side"]), (1.23, 12.3, 40.0, True, "BULLISH"))
        self.assertFalse(out["stocks"][1]["traded"])
        self.assertEqual(out["sectors"][0]["n"], 4)
        self.assertEqual(len(out["trades"]), 1)                                   # the row without an entry price is skipped
        t = out["trades"][0]
        self.assertEqual((t["ret"], t["peak"], t["stop"], t["t"]), (30.0, 50.0, 0.0, "10:05"))

    def test_build_survives_empty_and_bad_input(self):
        out = view3d.build({}, None, {"rows": [{"symbol": "A", "entry": "x"}]})
        self.assertEqual((out["ok"], out["stocks"], out["sectors"], out["trades"]), (True, [], [], []))


if __name__ == "__main__":
    unittest.main()
