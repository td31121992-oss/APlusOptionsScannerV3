import unittest
from datetime import datetime, timedelta

from scripts.offline_breakout_validation import (
    apply_overlap_control, chronological_split, find_pullback_entry, trend_aligned,
)


def bar(index, close, high=None, low=None, open_=None):
    return {
        "timestamp": datetime(2026, 10, 1, 9, 15) + timedelta(minutes=3 * index),
        "open": close if open_ is None else open_,
        "high": close if high is None else high,
        "low": close if low is None else low,
        "close": close,
        "volume": 100,
    }


class OfflineBreakoutValidationTests(unittest.TestCase):
    def test_chronological_split_keeps_later_sessions_out_of_sample(self):
        dates = [f"2026-10-{day:02d}" for day in range(1, 11)]
        train, test = chronological_split(dates)
        self.assertEqual(len(train), 7)
        self.assertEqual(len(test), 3)
        self.assertLess(max(train), min(test))

    def test_trend_alignment_uses_prior_bars_and_direction(self):
        rising = [bar(i, 100 + i * 0.1) for i in range(45)]
        falling = [bar(i, 110 - i * 0.1) for i in range(45)]
        self.assertTrue(trend_aligned(rising, 44, "LONG_BREAKOUT"))
        self.assertTrue(trend_aligned(falling, 44, "SHORT_BREAKDOWN"))
        self.assertFalse(trend_aligned(rising, 10, "LONG_BREAKOUT"))

    def test_pullback_entry_requires_retest_and_directional_close(self):
        bars = [
            bar(0, 102, high=103, low=101),
            bar(1, 101.5, high=102, low=100.9, open_=101.2),
        ]
        signal = {
            "_bars": bars, "_index": 0, "side": "LONG_BREAKOUT", "prior_20_high": 101,
        }
        entry = find_pullback_entry(signal)
        self.assertEqual(entry[0], 1)
        self.assertAlmostEqual(entry[1], 101.5)

    def test_overlap_flag_is_consistent_across_horizons(self):
        rows = []
        for index, stamp in ((0, "09:30"), (3, "09:39"), (6, "09:48")):
            for horizon in (5, 10, 15):
                rows.append({
                    "symbol": "TEST", "session_date": "2026-10-01", "side": "LONG_BREAKOUT",
                    "filter_variant": "baseline", "signal_timestamp": stamp,
                    "signal_index": index, "horizon_bars": horizon,
                })
        apply_overlap_control(rows, min_gap_bars=5)
        by_signal = {}
        for row in rows:
            by_signal.setdefault(row["signal_timestamp"], set()).add(row["non_overlapping"])
        self.assertEqual(by_signal["09:30"], {True})
        self.assertEqual(by_signal["09:39"], {False})
        self.assertEqual(by_signal["09:48"], {True})


if __name__ == "__main__":
    unittest.main()
