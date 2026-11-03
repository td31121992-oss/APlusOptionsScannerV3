import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace

import v2_shadow as v2


def U(*pairs):
    return [SimpleNamespace(security_id=str(i), symbol=s) for i, s in enumerate(pairs, 1)]


def quotes(prices, opens):
    return {"NSE_EQ": {str(i): {"last_price": p, "ohlc": {"open": o, "close": o}} for i, (p, o) in enumerate(zip(prices, opens), 1)}}


T0 = datetime(2026, 10, 14, 10, 0)


class FreshRankTests(unittest.TestCase):
    def test_ranks_by_recent_move_not_by_move_since_open(self):
        uni = U("AAA", "BBB", "CCC")
        tr = v2.FreshTracker()
        # 10:00 snapshot: AAA is the big mover since the open (+4%), CCC is flat
        v2.rank_fresh(uni, quotes([104.0, 101.0, 100.0], [100.0, 100.0, 100.0]), tr, T0, 15, 5)
        # 10:16: AAA stalled, CCC just ran +2%
        out = v2.rank_fresh(uni, quotes([104.1, 101.2, 102.0], [100.0, 100.0, 100.0]), tr, T0 + timedelta(minutes=16), 15, 5)
        up = [r["symbol"] for r in out["top_up"]]
        self.assertEqual(up[0], "CCC")                                   # freshest mover first
        self.assertEqual(out["top_up"][0]["v2_rank"], 1)
        self.assertLess([r["fresh_pct"] for r in out["top_up"] if r["symbol"] == "AAA"][0], 0.2)    # AAA's last 15 min was flat
        self.assertGreater([r["from_open_pct"] for r in out["top_up"] if r["symbol"] == "AAA"][0], 3.9)

    def test_down_side_and_top_n(self):
        uni = U("AAA", "BBB", "CCC", "DDD")
        tr = v2.FreshTracker()
        v2.rank_fresh(uni, quotes([100, 100, 100, 100], [100] * 4), tr, T0, 15, 2)
        out = v2.rank_fresh(uni, quotes([99.0, 98.0, 101.0, 102.0], [100] * 4), tr, T0 + timedelta(minutes=16), 15, 2)
        self.assertEqual([r["symbol"] for r in out["top_down"]], ["BBB", "AAA"])
        self.assertEqual([r["symbol"] for r in out["top_up"]], ["DDD", "CCC"])
        self.assertEqual(len(out["symbols"]), 4)

    def test_before_enough_history_the_move_since_open_stands_in(self):
        uni = U("AAA")
        tr = v2.FreshTracker()
        out = v2.rank_fresh(uni, quotes([103.0], [100.0]), tr, T0, 15, 5)
        self.assertAlmostEqual(out["top_up"][0]["fresh_pct"], 3.0, places=2)

    def test_missing_quotes_are_skipped(self):
        out = v2.rank_fresh(U("AAA", "BBB"), {"NSE_EQ": {"1": {"last_price": 101.0, "ohlc": {"open": 100.0}}}}, v2.FreshTracker(), T0, 15, 5)
        self.assertEqual(out["universe_rows_ranked"], 1)

    def test_snapshots_are_rate_limited_and_trimmed(self):
        tr = v2.FreshTracker(keep_minutes=10)
        tr.update({"AAA": 100.0}, T0)
        tr.update({"AAA": 101.0}, T0 + timedelta(seconds=5))              # too soon: ignored
        tr.update({"AAA": 102.0}, T0 + timedelta(minutes=11))             # old one falls out
        self.assertEqual(len(tr.hist["AAA"]), 1)
        self.assertEqual(tr.hist["AAA"][0][1], 102.0)


if __name__ == "__main__":
    unittest.main()
