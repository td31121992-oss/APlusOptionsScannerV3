import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

import signal_shadow as ss


def write_day(root, day, signals, prices):
    (root / "data" / "signal_snapshots").mkdir(parents=True)
    (root / "data" / "chart_history" / day).mkdir(parents=True)
    pd.DataFrame(signals, columns=["time", "symbol", "direction", "status"]).to_csv(root / "data" / "signal_snapshots" / f"{day}.csv", index=False)
    pd.DataFrame(prices, columns=["timestamp", "symbol", "ltp"]).to_csv(root / "data" / "chart_history" / day / "market_watch_1m.csv", index=False)


def minutes(symbol, start, n, p0, step):
    t = pd.Timestamp(start)
    return [((t + pd.Timedelta(minutes=i)).strftime("%Y-%m-%dT%H:%M:%S"), symbol, p0 + step * i) for i in range(n)]


class EarlyExtTests(unittest.TestCase):
    def run_day(self, signals, prices):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_day(root, "2026-11-24", signals, prices)
            with mock.patch.object(ss, "ROOT", root):
                return ss.day_moves("2026-11-24", ss.EARLY_EXT, "BULLISH")

    def test_only_the_two_statuses_before_1030_count(self):
        sig = [("2026-11-24T09:50:00", "AAA", "BULLISH", "A_PLUS_WAIT_LATE_VWAP_EXTENSION"),
               ("2026-11-24T10:00:00", "BBB", "BULLISH", "A_PLUS_WAIT_LATE_10M_OVERHEAT"),
               ("2026-11-24T10:10:00", "CCC", "BULLISH", "A_PLUS_WAIT_LATE_CLOSE_EXTENSION"),     # not one of the two
               ("2026-11-24T10:45:00", "DDD", "BULLISH", "A_PLUS_WAIT_LATE_VWAP_EXTENSION"),      # after 10:30
               ("2026-11-24T09:55:00", "EEE", "BEARISH", "A_PLUS_WAIT_LATE_VWAP_EXTENSION")]      # wrong side
        prices = []
        for s in ("AAA", "BBB", "CCC", "DDD", "EEE"):
            prices += minutes(s, "2026-11-24T09:15:00", 360, 100.0, 0.01)
        moves = self.run_day(sig, prices)
        self.assertEqual(len(moves), 2)
        self.assertTrue(all(m > 0 for m in moves))

    def test_nothing_recorded_gives_an_empty_list(self):
        sig = [("2026-11-24T10:45:00", "DDD", "BULLISH", "A_PLUS_WAIT_LATE_VWAP_EXTENSION")]
        self.assertEqual(self.run_day(sig, minutes("DDD", "2026-11-24T09:15:00", 360, 100.0, 0.01)), [])


if __name__ == "__main__":
    unittest.main()
