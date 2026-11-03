from __future__ import annotations

import unittest

import missed_option_returns as mor


def c(minute: int, high: float, low: float, close: float) -> dict:
    return {"minute": minute, "high": high, "low": low, "close": close}


class MetricsTests(unittest.TestCase):
    def test_entry_is_first_candle_after_ready_plus_slip_and_target_time_recorded(self) -> None:
        candles = [c(600, 9, 8, 8.5), c(605, 10, 9.5, 10.0), c(610, 11, 9.8, 10.9), c(615, 14, 10.5, 13.5), c(620, 12, 11, 11.5)]
        m = mor.option_metrics(candles, 605)
        self.assertAlmostEqual(m["entry"], 10.1)
        self.assertEqual(m["t_target"], "10:15")             # 14 >= 10.1 * 1.30 = 13.13
        self.assertEqual(m["stop_first"], False)
        self.assertEqual(m["best"], round((14 / 10.1 - 1) * 100, 1))

    def test_stop_hit_before_target_is_flagged(self) -> None:
        candles = [c(600, 10, 9.9, 10), c(605, 10, 7.0, 7.5), c(610, 14, 7, 13)]
        self.assertTrue(mor.option_metrics(candles, 600)["stop_first"])

    def test_too_little_data_returns_none(self) -> None:
        self.assertIsNone(mor.option_metrics([c(600, 10, 9, 9.5)], 600))
        self.assertIsNone(mor.option_metrics([], 600))

    def test_render_and_summary(self) -> None:
        rows = [{"symbol": "AAA", "dir": "BULLISH", "fate": "V2_BLOCKED", "ready": "10:00", "strike": 100, "kind": "ATM",
                 "entry": 5.0, "best": 45.0, "worst": -3.0, "close": 20.0, "t_target": "11:00", "stop_first": False},
                {"symbol": "BBB", "dir": "BEARISH", "fate": "TRADED", "ready": "10:05", "strike": 50, "kind": "ATM",
                 "entry": 5.0, "best": 10.0, "worst": -30.0, "close": -20.0, "t_target": "", "stop_first": None}]
        s = mor.summarize(rows)[0]
        self.assertEqual((s["n"], s["hit30"], s["fell_25"]), (2, 1, 1))
        text = mor.render("2026-10-07", rows)
        self.assertIn("V2_BLOCKED", text)
        self.assertIn("AAA", text)


if __name__ == "__main__":
    unittest.main()
