import unittest

from momentum_discovery_shadow import evaluate_session, score_at


def rising_bars(count=50):
    minutes = list(range(9 * 60 + 15, 9 * 60 + 15 + count))
    close = [100.0 + i * 0.12 for i in range(count)]
    high = [value + 0.04 for value in close]
    low = [value - 0.04 for value in close]
    high[19] = close[19] + 0.02
    high[20] = close[20] + 0.05
    volume = [100.0] * count
    volume[20] = 250.0
    return {"minute": minutes, "open": [100.0] * count, "high": high, "low": low,
            "close": close, "volume": volume, "vwap_estimate": [100.0] * count}


def rows_from_bars(symbol, bars):
    rows = []
    for i, minute in enumerate(bars["minute"]):
        rows.append({"symbol": symbol,
                     "bar_minute": f"{minute // 60:02d}:{minute % 60:02d}",
                     "open": bars["open"][i], "high": bars["high"][i],
                     "low": bars["low"][i], "close": bars["close"][i],
                     "volume_delta": bars["volume"][i],
                     "volume_weighted_ltp_estimate": bars["vwap_estimate"][i]})
    return rows


class MomentumDiscoveryShadowTests(unittest.TestCase):
    def test_late_and_extension_conditions_annotate_without_rejecting(self):
        bars = rising_bars()
        result = score_at(bars, 20)
        self.assertIsNotNone(result)
        self.assertEqual(result["side"], "BULLISH")
        self.assertGreater(result["score"], 50)
        self.assertTrue(result["breakout_confirmed"])
        self.assertIn("LATE_10M_MOVE_REVIEW", result["cautions"])
        self.assertIn("VWAP_EXTENSION_REVIEW", result["cautions"])
        self.assertEqual(result["readiness"], "BREAKOUT_CONFIRMED_SHADOW")

    def test_discontinuous_history_does_not_get_ranked(self):
        bars = rising_bars()
        bars["minute"][15] += 1
        self.assertIsNone(score_at(bars, 20))

    def test_session_ranking_keeps_candidates_and_labels_future_separately(self):
        bars = rising_bars(50)
        report = evaluate_session(rows_from_bars("AAA", bars), "2026-10-28", top_n_per_side=1)
        self.assertTrue(report["research_only"])
        self.assertTrue(report["method"]["caution_rules_remove_candidates"] is False)
        self.assertGreater(report["counts"]["ranked_rows"], 0)
        self.assertGreater(report["counts"]["complete_forward_outcomes"], 0)
        self.assertTrue(all(row["forward_15m_close_pct"] is not None
                            for row in report["selections"] if row["snapshot_minute"] <= bars["minute"][-16]))


if __name__ == "__main__":
    unittest.main()
