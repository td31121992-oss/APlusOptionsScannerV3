import unittest

import numpy as np
import pandas as pd

import chart_zones as cz


def make(days, today_open=None):
    """Price swings between ~100 and ~105 every two hours on every day; today optionally opens at `today_open`."""
    rows = []
    for di, d in enumerate(days):
        for k in range(75):
            ts = pd.Timestamp(d) + pd.Timedelta(hours=9, minutes=15 + 5 * k)
            base = 102.5 + 2.5 * np.sin(2 * np.pi * k / 24)
            if today_open is not None and di == len(days) - 1:
                base += today_open
            rows.append((ts, base, base + 0.15, base - 0.15, base, 1000))
    return pd.DataFrame(rows, columns=["ts", "o", "h", "l", "c", "v"]).set_index("ts")


class ZoneTests(unittest.TestCase):
    days = list(pd.bdate_range("2026-09-21", periods=14))

    def test_swing_clusters_become_supply_and_demand_zones(self):
        m5 = make(self.days)
        out = cz.build_zones(m5, self.days[-1], 102.5)
        kinds = {z["kind"] for z in out["zones"]}
        self.assertTrue({"supply", "demand", "pivot", "pd"} <= kinds)
        sup = [z for z in out["zones"] if z["kind"] == "supply"][0]
        dem = [z for z in out["zones"] if z["kind"] == "demand"][0]
        self.assertGreaterEqual(sup["touches"], 2)
        self.assertGreater(sup["low"], 104.0)
        self.assertLess(dem["high"], 101.0)

    def test_zones_far_from_price_are_dropped(self):
        out = cz.build_zones(make(self.days), self.days[-1], 140.0)
        self.assertEqual([z for z in out["zones"] if z["kind"] in ("supply", "demand")], [])

    def test_pivot_values(self):
        prev = pd.DataFrame({"h": [110.0], "l": [90.0], "c": [100.0]})
        lv = cz.pivot_levels(prev)
        self.assertAlmostEqual(lv["P"], 100.0)
        self.assertAlmostEqual(lv["R1"], 110.0)
        self.assertAlmostEqual(lv["S1"], 90.0)
        self.assertAlmostEqual(lv["R2"], 120.0)

    def test_gap_opening_range_and_vwap_use_todays_bars(self):
        m5 = make(self.days, today_open=3.0)                                # today starts 3 points above
        today = pd.Timestamp(self.days[-1])
        out = cz.build_zones(m5[m5.index <= today + pd.Timedelta(hours=11)], today, 105.0)
        names = [z["name"] for z in out["zones"]]
        self.assertTrue(any(n.startswith("Gap up") for n in names))
        self.assertIn("OR high", names)
        self.assertTrue(out["vwap"])
        first = pd.Timestamp(self.days[-1]) + pd.Timedelta(hours=9, minutes=15)
        self.assertEqual(out["vwap"][0]["t"], int(first.tz_localize("UTC").timestamp()))   # same axis as the chart candles

    def test_too_little_history_returns_nothing(self):
        out = cz.build_zones(make(self.days[:2]), self.days[1], 102.0)
        self.assertEqual(out["zones"], [])

    def test_cluster_groups_nearby_levels(self):
        z = cz.cluster([(1, 100.0), (5, 100.2), (9, 100.3), (3, 110.0)])
        self.assertEqual(sorted(x["touches"] for x in z), [1, 3])


if __name__ == "__main__":
    unittest.main()
