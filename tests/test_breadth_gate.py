import unittest

import breadth_gate as bg


def rows(n_up, n_down, extra=()):
    r = [{"symbol": f"U{i}", "sector": "A", "from_prev_close_pct": 0.5, "ltp": 100} for i in range(n_up)]
    r += [{"symbol": f"D{i}", "sector": "A", "from_prev_close_pct": -0.5, "ltp": 100} for i in range(n_down)]
    return r + list(extra)


class BreadthGateTests(unittest.TestCase):
    def test_call_passes_when_most_stocks_up(self):
        self.assertEqual(bg.evaluate("U1", "BULLISH", rows(150, 60))["breadth_tag"], "PASS")

    def test_call_would_block_when_most_stocks_down(self):
        out = bg.evaluate("U1", "BULLISH", rows(30, 180))
        self.assertEqual(out["breadth_tag"], "WOULD_BLOCK")
        self.assertAlmostEqual(out["breadth_pct_with"], 14.3, places=1)

    def test_put_passes_when_most_stocks_down(self):
        self.assertEqual(bg.evaluate("D1", "BEARISH", rows(30, 180))["breadth_tag"], "PASS")

    def test_strong_stock_against_the_market_is_an_exception(self):
        star = {"symbol": "STAR", "sector": "B", "from_prev_close_pct": 3.0, "ltp": 210}
        peers = [{"symbol": f"P{i}", "sector": "B", "from_prev_close_pct": -0.5, "ltp": 50} for i in range(3)]
        out = bg.evaluate("STAR", "BULLISH", rows(30, 180, [star, *peers]), {"STAR": {"pdh": 200}}, rel_volume_15m=2.5)
        self.assertEqual((out["breadth_tag"], out["breadth_evidence"]), ("EXCEPTION", 4))

    def test_weak_evidence_is_not_enough(self):
        star = {"symbol": "STAR", "sector": "B", "from_prev_close_pct": 2.5, "ltp": 210}
        out = bg.evaluate("STAR", "BULLISH", rows(30, 180, [star]), {}, rel_volume_15m=0.5)
        self.assertEqual(out["breadth_tag"], "WOULD_BLOCK")

    def test_no_data_is_unknown(self):
        self.assertEqual(bg.evaluate("X", "BULLISH", [])["breadth_tag"], "UNKNOWN")


if __name__ == "__main__":
    unittest.main()
