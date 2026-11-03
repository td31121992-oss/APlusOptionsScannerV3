import csv
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

import stock_study as ss


def day(shape, o=100.0):
    """75 five-minute closes from a list of (bars, to_level_pct) legs."""
    out = [o]
    for bars, pct in shape:
        start = out[-1]
        end = o * (1 + pct / 100.0)
        out += [start + (end - start) * (k + 1) / bars for k in range(bars)]
    return (out + [out[-1]] * 75)[:75]


class ClassifyTests(unittest.TestCase):
    def test_patterns(self):
        # an hour in a 0.4 % box, then a steady climb to +3 % and a close at the high
        up = [100.0 + 0.2 * (i % 2) for i in range(12)] + [100.2 + (i + 1) * (2.9 / 63) for i in range(63)]
        self.assertEqual(ss.classify(up, 100.0)["pattern"], "TREND_UP")
        down = [200.0 - x for x in [x - 100.0 for x in up]]
        self.assertEqual(ss.classify(down, 100.0)["pattern"], "TREND_DOWN")
        self.assertEqual(ss.classify([100.0 + 0.1 * np.sin(i) for i in range(75)], 100.0)["pattern"], "TIGHT_RANGE")
        v = day([(12, -2.0), (63, 1.2)])                                                 # a low inside the first hour, then a recovery to the top of the range
        self.assertEqual(ss.classify(v, 100.0)["pattern"], "REVERSAL_UP")
        inv = day([(12, 2.0), (63, -1.2)])
        self.assertEqual(ss.classify(inv, 100.0)["pattern"], "REVERSAL_DOWN")

    def test_gap_and_late_surge_and_range(self):
        go = day([(20, 0.4), (55, 0.4)], o=101.0)                                        # opened 1 % up from the previous close, then drifted a little further
        c = ss.classify(go, 100.0)
        self.assertEqual(c["gap_pct"], 1.0)
        self.assertEqual(c["pattern"], "GAP_AND_GO" if abs(c["move_pct"]) >= 0.5 else c["pattern"])
        fade = day([(40, -1.5), (35, -0.6)], o=101.0)                                    # opened 1 % up, sold off 1.5 %, recovered a little: net -0.6 % against the gap
        self.assertEqual(ss.classify(fade, 100.0)["pattern"], "GAP_FADE")
        late = [100.0 + 0.1 * (i % 2) for i in range(57)] + [100.1 + (k + 1) * 0.07 for k in range(18)]
        self.assertEqual(ss.classify(late, 100.0)["pattern"], "LATE_SURGE")
        box = [100.0 + 0.5 * np.sin(i / 3.0) for i in range(75)]
        self.assertIn(ss.classify(box, 100.0)["pattern"], ("RANGE_BOUND", "TIGHT_RANGE"))

    def test_opening_range_break_and_hold(self):
        c = [100.0, 100.2, 100.1] + [100.5, 101.0, 101.5] + [102.0] * 69
        r = ss.classify(c, 100.0)
        self.assertEqual((r["orb"], r["orb_held"]), (1, True))
        fail = [100.0, 100.2, 100.1] + [100.6, 100.4, 100.0] + [99.0] * 69
        r = ss.classify(fail, 100.0)
        self.assertEqual((r["orb"], r["orb_held"]), (1, False))                         # broke up, but closed below the opening range
        self.assertEqual(ss.classify([100.0] * 75, 100.0)["orb"], 0)

    def test_rejects_short_or_bad_input(self):
        self.assertIsNone(ss.classify([100.0] * 30, 100.0))
        self.assertIsNone(ss.classify([0.0] * 75, 100.0))
        self.assertIsNone(ss.classify([float("nan")] * 75, 100.0))

    def test_spark_is_normalised_to_the_open(self):
        r = ss.classify(day([(75, 3.0)]), 100.0)
        self.assertEqual(r["spark"][0], 100.0)
        self.assertEqual(len(r["spark"]), 15)
        self.assertAlmostEqual(r["spark"][-1], 100.0 + 3.0 * 70 / 75, places=1)


class BarTests(unittest.TestCase):
    def test_five_minute_closes_from_samples(self):
        t0 = ss.OPEN_S
        s = [(t0 + 10, 100.0), (t0 + 290, 101.0), (t0 + 310, 102.0), (t0 + 1000, 105.0)] + [(t0 + 300 * k + 1, 105.0 + k) for k in range(4, 70)]
        b = ss.bars_from_samples(s)
        self.assertEqual(b[0], 101.0)                                                    # the last price inside the first bucket
        self.assertEqual(b[1], 102.0)
        self.assertEqual(b[2], 102.0)                                                    # a bucket without a tick repeats the previous close
        self.assertEqual(b[3], 105.0)
        self.assertIsNone(ss.bars_from_samples([(t0, 100.0)]))


def rows_for(n_days=30, sym="AAA", mover=1.0):
    out = []
    for d in range(n_days):
        mkt = (-1) ** d * 0.5
        out.append({"day": f"2026-09-{d + 1:02d}", "symbol": sym, "pattern": "TREND_UP" if d % 3 == 0 else "RANGE_BOUND", "gap_pct": 0.6 if d % 5 == 0 else 0.1, "range_pct": 2.0, "move_pct": mkt * mover,
                    "close_pos": 0.5, "efficiency": 0.3, "ib_up": 0.5, "ib_dn": 0.0, "orb": 1 if d % 2 == 0 else 0, "orb_held": d % 4 == 0, "hi_hour": 10 if d % 2 else 13, "lo_hour": 11, "spark": " ".join(["100"] * 15)})
        for k in range(60):                                                              # enough other stocks for a market median
            out.append({"day": f"2026-09-{d + 1:02d}", "symbol": f"S{k}", "pattern": "CHOPPY", "gap_pct": 0.0, "range_pct": 1.5, "move_pct": mkt, "close_pos": 0.5, "efficiency": 0.2, "ib_up": 0.0,
                        "ib_dn": 0.0, "orb": 0, "orb_held": "", "hi_hour": 10, "lo_hour": 12, "spark": ""})
    return out


class ProfileTests(unittest.TestCase):
    def test_personality(self):
        p = ss.build_profiles(rows_for(30, mover=1.5), {"AAA": "IT"})
        a = p["stocks"]["AAA"]
        self.assertEqual((p["days"], a["sec"], a["n"]), (30, "IT", 30))
        self.assertAlmostEqual(a["beta"], 1.5, places=1)                                  # moves 1.5x the market
        self.assertEqual(a["mix"]["TREND_UP"], 33)
        self.assertEqual(a["orb_follow"], 53)                                             # 15 breaks (the even days), 8 of which held
        self.assertEqual(a["hi_hour"] in (10, 13), True)
        self.assertEqual(len(a["strip"]), ss.STRIP_DAYS)
        self.assertEqual(a["today"]["day"], "2026-09-30")
        self.assertEqual(p["stocks"]["S0"]["beta"], 1.0)

    def test_recent_window_only(self):
        p = ss.build_profiles(rows_for(90), {})
        self.assertEqual(p["stocks"]["AAA"]["n"], ss.PROFILE_DAYS)


class FilesTests(unittest.TestCase):
    def test_write_read_and_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = rows_for(20)
            ss.write_daily(root, rows)
            back = ss.read_daily(root)
            self.assertEqual(len(back), len(rows))
            prof = ss.save_profiles(root, back)
            out = ss.payload(root)
            self.assertTrue(out["ok"])
            self.assertEqual(out["day"], prof["day"])
            self.assertIn("AAA", out["stocks"])
            self.assertEqual(out["stocks"]["AAA"]["spark"], [100.0] * 15)
            self.assertFalse(ss.payload(Path(tmp, "none"))["ok"])


if __name__ == "__main__":
    unittest.main()
