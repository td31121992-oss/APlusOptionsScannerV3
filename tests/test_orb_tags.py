import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS

import orb_tags as ot

IST = timezone(timedelta(hours=5, minutes=30))


def bars(rows):
    """rows = (open, high, low, close, volume); consecutive 5-minute bars from 09:15."""
    base = datetime(2026, 10, 21, 9, 15, tzinfo=IST)
    return [NS(timestamp=base + timedelta(minutes=5 * i), open=o, high=h, low=l, close=c, volume=v) for i, (o, h, l, c, v) in enumerate(rows)]


RANGE = [(100, 101, 99.5, 100.2, 1000)] * 3 + [(100.2, 100.8, 99.6, 100.0, 1000)] * 3          # 09:15-09:44, high 101, low 99.5


class OrbTests(unittest.TestCase):
    def test_forming_before_the_range_is_complete(self):
        self.assertEqual(ot.orb_tags(bars(RANGE[:4]), "BULLISH"), {"orb_state": "FORMING"})

    def test_breakdown_is_with_a_put_against_a_call_and_retest_is_found(self):
        rows = RANGE + [(100, 100, 98.8, 99.0, 2500),           # 09:45 closes below 99.5: breakdown, volume 2.5x the range bars
                        (99.0, 99.2, 98.5, 98.7, 1200),
                        (98.7, 99.6, 98.6, 99.2, 1500)]         # touches back above the broken edge (99.5) but closes below it again: retest
        put = ot.orb_tags(bars(rows), "BEARISH")
        call = ot.orb_tags(bars(rows), "BULLISH")
        self.assertEqual((put["orb_state"], put["orb_with"], call["orb_with"]), ("BELOW", "with", "against"))
        self.assertEqual((put["orb_break_dir"], put["orb_break_time"], put["orb_break_vol_x"]), ("BEARISH", "09:50", 2.5))
        self.assertTrue(put["orb_retested"])
        self.assertEqual(put["orb_mins_since"], 10)
        self.assertGreater(put["orb_dist_edge_pct"], 0)
        self.assertLess(call["orb_dist_edge_pct"], 0)

    def test_inside_the_range_has_no_breakout(self):
        t = ot.orb_tags(bars(RANGE + [(100, 100.5, 99.8, 100.1, 900)]), "BULLISH")
        self.assertEqual((t["orb_state"], t["orb_with"], t["orb_break_dir"]), ("INSIDE", "inside", ""))
        self.assertNotIn("orb_retested", t)

    def test_no_retest_when_price_never_comes_back(self):
        rows = RANGE + [(100.5, 102.5, 100.5, 102.0, 2000), (102.0, 103.5, 101.9, 103.0, 1500), (103.0, 104.0, 102.8, 103.8, 1500)]
        t = ot.orb_tags(bars(rows), "BULLISH")
        self.assertEqual((t["orb_state"], t["orb_with"], t["orb_break_dir"]), ("ABOVE", "with", "BULLISH"))
        self.assertFalse(t["orb_retested"])

    def test_bad_input(self):
        self.assertEqual(ot.orb_tags(None, "BULLISH"), {})
        self.assertEqual(ot.orb_tags([], "BULLISH"), {})


if __name__ == "__main__":
    unittest.main()
