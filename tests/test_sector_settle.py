import os
import unittest
from unittest import mock

import sector_priority as sp
import settle_window as sw


def rows(moves, sector="Information Technology", me="ME"):
    out = [{"symbol": me, "sector": sector, "from_open_pct": 0.0}]
    out += [{"symbol": f"P{i}", "sector": sector, "from_open_pct": m} for i, m in enumerate(moves)]
    out += [{"symbol": "OTHER", "sector": "Metals", "from_open_pct": -3.0}]
    return out


class SectorPriorityTests(unittest.TestCase):
    def test_most_peers_up_is_a_leader_for_a_call_and_against_a_put(self):
        r = rows([1.0, 0.8, 1.2, 0.9, 0.7, 1.1, 0.2])                      # 6 of 7 up more than 0.5%
        t = sp.sector_tags(r, "ME", "BULLISH")
        self.assertEqual((t["sp_peers"], t["sp_frac"], t["sp_score"], t["sp_leader"]), (7, 0.86, 86.0, True))
        p = sp.sector_tags(r, "ME", "BEARISH")
        self.assertEqual((p["sp_frac"], p["sp_leader"]), (0.0, False))
        self.assertLess(p["sp_avg"], 0)

    def test_too_few_peers_gives_no_score(self):
        t = sp.sector_tags(rows([1.0, 1.0]), "ME", "BULLISH")
        self.assertNotIn("sp_score", t)
        self.assertEqual(t["sp_peers"], 2)

    def test_unknown_symbol_and_bad_input(self):
        self.assertEqual(sp.sector_tags(rows([1.0] * 5), "NOPE", "BULLISH"), {})
        self.assertEqual(sp.sector_tags(None, "ME", "BULLISH"), {})


class SettleTests(unittest.TestCase):
    def test_default_is_shadow_and_never_blocks(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("APLUS_SETTLE_MODE", None)
            os.environ.pop("APLUS_SETTLE_UNTIL", None)
            self.assertEqual(sw.mode(), "SHADOW")
            self.assertEqual(sw.evaluate(9 * 60 + 40), {"settle_until": "10:00", "settle_would_block": 1})
            self.assertEqual(sw.evaluate(10 * 60)["settle_would_block"], 0)
            self.assertFalse(sw.blocks(9 * 60 + 40))

    def test_enforce_blocks_before_the_time_only(self):
        with mock.patch.dict(os.environ, {"APLUS_SETTLE_MODE": "ENFORCE", "APLUS_SETTLE_UNTIL": "09:45"}):
            self.assertTrue(sw.blocks(9 * 60 + 44))
            self.assertFalse(sw.blocks(9 * 60 + 45))
        with mock.patch.dict(os.environ, {"APLUS_SETTLE_MODE": "bogus", "APLUS_SETTLE_UNTIL": "xx"}):
            self.assertEqual(sw.mode(), "SHADOW")
            self.assertEqual(sw.until_minute(), 600)


if __name__ == "__main__":
    unittest.main()
