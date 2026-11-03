import unittest
from datetime import datetime

import entry_tags as et


class EntryTagTests(unittest.TestCase):
    def test_flags(self):
        t = et.evaluate(12.5, datetime(2026, 10, 14, 10, 5), "chop")
        self.assertTrue(t["f_time_0945"] and t["f_premium_5"] and t["f_all"])
        self.assertEqual(t["day_regime"], "CHOP")
        e = et.evaluate(4.0, datetime(2026, 10, 14, 9, 30))
        self.assertFalse(e["f_time_0945"] or e["f_premium_5"] or e["f_all"])
        self.assertEqual(e["day_regime"], "UNKNOWN")
        self.assertEqual(et.evaluate("x", datetime(2026, 10, 14, 9, 45))["entry_premium"], 0.0)

    def test_regime_of(self):
        self.assertEqual(et.regime_of({"regime": "bull"}), "BULL")
        self.assertEqual(et.regime_of(None), "UNKNOWN")

    def test_mover_tags_gap_direction_and_buckets(self):
        up = et.mover_tags("AAA", "BULLISH", 2.6, indicators={"vol_x_prev": 1.2, "last_chg_pct": -4.5})
        self.assertEqual((up["mv_gap_dir_pct"], up["mv_gap_bucket"], up["mv_in_play"]), (2.6, "with>2", True))
        self.assertEqual((up["mv_pre_vol_x"], up["mv_pre_abs_chg1"]), (1.2, 4.5))
        against = et.mover_tags("AAA", "BEARISH", 2.6, indicators={})                 # a put into a gap UP: the gap is against us
        self.assertEqual((against["mv_gap_dir_pct"], against["mv_gap_bucket"]), (-2.6, "against>2"))
        self.assertNotIn("mv_pre_vol_x", against)                                    # blank until the evening file carries it
        self.assertEqual([et.mover_tags("A", "BULLISH", g, indicators={})["mv_gap_bucket"] for g in (1.5, 0.4, -0.9, -1.5)], ["with1-2", "flat", "flat", "against1-2"])

    def test_mover_tags_in_play_by_volume_alone(self):
        t = et.mover_tags("AAA", "BULLISH", 0.3, indicators={"vol_x_prev": 2.7})
        self.assertTrue(t["mv_in_play"])
        self.assertFalse(et.mover_tags("AAA", "BULLISH", 0.3, indicators={"vol_x_prev": 1.1})["mv_in_play"])

    def test_opening_volume_tags_compare_the_first_bars_with_earlier_sessions(self):
        from datetime import timedelta
        from types import SimpleNamespace as NS
        today = datetime(2026, 10, 28, 9, 35)
        candles = []
        for back, vols in ((5, (100, 80, 60)), (4, (120, 80, 60)), (3, (80, 80, 60)), (2, (100, 80, 60))):             # four earlier sessions: first bar avg 100, first three avg 240
            day = datetime(2026, 10, 28 - back, 9, 15)
            candles += [NS(timestamp=day + timedelta(minutes=5 * i), volume=v) for i, v in enumerate(vols)]
        candles += [NS(timestamp=datetime(2026, 10, 28, 9, 15 + 5 * i), volume=v) for i, v in enumerate((350, 300, 250))]
        t = et.opening_volume_tags(candles, today)
        self.assertEqual(t["mv_orv5"], 3.5)
        self.assertEqual(t["mv_orv15"], round(900 / 240, 2))
        self.assertEqual(t["mv_orv_days"], 4)
        early = et.opening_volume_tags(candles, datetime(2026, 10, 28, 9, 22))                                           # the 09:20 bar is still forming
        self.assertEqual(early["mv_orv5"], 3.5)
        self.assertNotIn("mv_orv15", early)
        self.assertEqual(et.opening_volume_tags(candles[-3:], today), {})                                                # no earlier sessions: no baseline
        self.assertEqual(et.opening_volume_tags(None, today), {})
        self.assertEqual(et.opening_volume_tags(candles, None), {})

    def test_mover_tags_never_raise(self):
        self.assertIsInstance(et.mover_tags("AAA", "BULLISH", "bad", indicators={"vol_x_prev": "x"}), dict)


if __name__ == "__main__":
    unittest.main()
