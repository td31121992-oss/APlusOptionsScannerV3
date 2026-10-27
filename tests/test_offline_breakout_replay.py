import csv
import tempfile
import unittest
from pathlib import Path

from scripts.offline_breakout_replay import evaluate_signal, find_signals, load_candles, run


def candle(day, minute, open_, high, low, close, volume=100):
    from datetime import datetime, timedelta
    stamp = datetime.fromisoformat(day + "T09:15:00") + timedelta(minutes=minute)
    return {"timestamp": stamp, "open": open_, "high": high, "low": low, "close": close, "volume": volume}


class OfflineBreakoutReplayTests(unittest.TestCase):
    def test_detects_crossing_breakout_and_volume_confirmation(self):
        bars = []
        for i in range(22):
            bars.append(candle("2026-10-01", i * 3, 100, 101, 99, 100, 100))
        # First bar beyond the previous 20-bar range; volume is 2x prior mean.
        bars[21].update({"open": 100, "high": 103, "low": 100, "close": 102, "volume": 200})
        signals = find_signals(bars, "TEST", 3)
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0]["side"], "LONG_BREAKOUT")
        self.assertTrue(signals[0]["volume_confirmed"])

    def test_mfe_mae_and_directional_return_for_long(self):
        bars = [candle("2026-10-01", i * 3, 100, 100, 100, 100) for i in range(5)]
        bars[1].update({"high": 103, "low": 99, "close": 101})
        bars[2].update({"high": 105, "low": 98, "close": 102})
        bars[3].update({"high": 104, "low": 100, "close": 103})
        signal = {"side": "LONG_BREAKOUT", "entry_reference_close": 100, "_bars": bars, "_index": 0}
        result = evaluate_signal(signal, 3)
        self.assertAlmostEqual(result["mfe_pct"], 5.0)
        self.assertAlmostEqual(result["mae_pct"], -2.0)
        self.assertAlmostEqual(result["directional_return_pct"], 3.0)

    def test_incomplete_future_horizon_is_not_scored(self):
        bars = [candle("2026-10-01", i * 3, 100, 100, 100, 100) for i in range(3)]
        signal = {"side": "LONG_BREAKOUT", "entry_reference_close": 100, "_bars": bars, "_index": 1}
        self.assertIsNone(evaluate_signal(signal, 2))

    def test_replay_writes_reports_and_flags_bad_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / "input"
            out = Path(tmp) / "out"
            data.mkdir()
            path = data / "TEST_3m.csv"
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(["timestamp", "open", "high", "low", "close", "volume", "open_interest"])
                from datetime import datetime, timedelta
                for i in range(30):
                    stamp = datetime.fromisoformat("2026-10-01T09:15:00") + timedelta(minutes=i * 3)
                    close = 102 if i == 21 else 100
                    high = max(101, close + 1)
                    writer.writerow([stamp.isoformat(), 100, high, 99, close, 200 if i == 21 else 100, ""])
            code = run(data, out, symbols=None, intervals=(3,))
            self.assertEqual(code, 0)
            self.assertTrue((out / "breakout_replay_events.csv").exists())
            self.assertTrue((out / "breakout_replay_summary.json").exists())


if __name__ == "__main__":
    unittest.main()
