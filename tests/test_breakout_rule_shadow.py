import unittest

import breakout_rule_shadow as br


def day_rows(day, start_price, step, n=75, vol=10_000.0, spike_at=None, spike_vol=30_000.0, open_gap=None):
    rows, p = [], start_price
    for i in range(n):
        minute = 9 * 60 + 15 + 5 * i
        o = p
        p = p + step
        v = spike_vol if spike_at == i else vol
        rows.append([day, minute, o, max(o, p) + 0.02, min(o, p) - 0.02, p, v])
    return rows


class IndicatorTests(unittest.TestCase):
    def test_ema_and_rsi(self):
        self.assertAlmostEqual(br.ema([10, 10, 10], 9)[-1], 10.0)
        up = br.rsi([float(i) for i in range(30)])
        self.assertEqual(up[14], 100.0)
        self.assertIsNone(up[10])
        down = br.rsi([float(30 - i) for i in range(30)])
        self.assertEqual(down[-1], 0.0)


class SignalTests(unittest.TestCase):
    def long_rows(self, spike=3, spike_vol=30_000.0, gap_up=0.5):
        d1 = day_rows("2026-10-22", 100.0, 0.05)
        d1[30][3] = 110.0                                      # a spike high mid-day: the previous day's high is 110
        last = d1[-1][5]
        d2 = day_rows("2026-10-23", last * (1 + gap_up / 100), 0.05, spike_at=spike, spike_vol=spike_vol)
        return d1 + d2

    def test_breakout_on_opening_range_high_with_volume(self):
        sg = br.signals_for(self.long_rows())
        longs = [s for s in sg if s["side"] == "LONG"]
        self.assertEqual(len(longs), 1)
        self.assertEqual((longs[0]["day"], longs[0]["level_kind"], longs[0]["minute"]), ("2026-10-23", "ORH", 9 * 60 + 30))
        self.assertGreater(longs[0]["vol_x"], 1.5)
        self.assertGreater(longs[0]["rsi"], 60)

    def test_no_signal_without_volume_or_with_a_big_gap(self):
        self.assertEqual([s for s in br.signals_for(self.long_rows(spike_vol=12_000.0)) if s["side"] == "LONG"], [])        # volume only 1.2x
        self.assertEqual([s for s in br.signals_for(self.long_rows(gap_up=4.0)) if s["side"] == "LONG"], [])                  # gap above 3 %

    def test_illiquid_stock_is_skipped(self):
        rows = self.long_rows()
        for r in rows:
            r[6] = r[6] / 100.0
        self.assertEqual(br.signals_for(rows), [])

    def test_breakdown_mirror(self):
        d1 = day_rows("2026-10-22", 200.0, -0.05)
        d1[30][4] = 190.0
        d2 = day_rows("2026-10-23", d1[-1][5] * (1 - 0.005), -0.05, spike_at=3, spike_vol=30_000.0)
        sg = [s for s in br.signals_for(d1 + d2) if s["side"] == "SHORT"]
        self.assertEqual(len(sg), 1)
        self.assertEqual((sg[0]["level_kind"], sg[0]["minute"]), ("ORL", 9 * 60 + 30))
        self.assertLess(sg[0]["rsi"], 40)

    def test_only_requested_days(self):
        self.assertEqual(br.signals_for(self.long_rows(), {"2026-10-24"}), [])


if __name__ == "__main__":
    unittest.main()
