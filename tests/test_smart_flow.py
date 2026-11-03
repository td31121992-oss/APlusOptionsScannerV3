import unittest

import smart_flow as sf


def feed(state, sym, rows):
    for t, ltp, vol in rows:
        sf.step(state, sym, t, ltp, vol)


class SmartFlowTests(unittest.TestCase):
    def test_bucket_and_tick_rule(self):
        self.assertEqual(sf._bucket("10:07"), "10:05")
        st = {}
        feed(st, "AAA", [("09:15", 100.0, 1000), ("09:16", 101.0, 2000), ("09:17", 100.0, 3000), ("09:21", 100.5, 4000)])
        b = st["AAA"]["b"]
        self.assertGreater(b["09:15"]["buy"], 0)
        self.assertGreater(b["09:15"]["sell"], 0)
        self.assertEqual((b["09:15"]["h"], b["09:15"]["l"], b["09:15"]["c"]), (101.0, 100.0, 100.0))
        self.assertIn("09:20", b)

    def test_build_ranks_and_aggregates(self):
        st = {}
        for sym, px in (("UP1", 105.0), ("UP2", 102.0), ("DN1", 95.0)):
            feed(st, sym, [("09:15", 100.0, 1000), ("09:20", px, 5000)])
        market = {s: {"previous_close": 100.0, "sector": "Banks" if s != "DN1" else "IT"} for s in st}
        out = sf.build(st, "09:20", {}, market, [{"name": "NIFTY 50", "ltp": 25000, "pct_prev": 0.5}])
        self.assertEqual([x["s"] for x in out["gainers"][:2]], ["UP1", "UP2"])
        self.assertEqual(out["losers"][0]["s"], "DN1")
        self.assertEqual((out["breadth"]["up"], out["breadth"]["down"]), (2, 1))
        self.assertEqual((out["lead"], out["lag"]), ("Banks", "IT"))
        self.assertEqual(out["times"], ["09:15", "09:20"])
        nifty = out["cards"][0]
        self.assertEqual((nifty["name"], nifty["chg"], nifty["ltp"]), ("NIFTY 50", 0.5, 25000))
        self.assertEqual(len(nifty["bars"]), 2)

    def test_build_handles_no_stocks(self):
        out = sf.build({}, "09:20", {}, {}, None)
        self.assertEqual((out["ok"], out["gainers"], out["sectors"], out["lead"]), (True, [], [], ""))


if __name__ == "__main__":
    unittest.main()
