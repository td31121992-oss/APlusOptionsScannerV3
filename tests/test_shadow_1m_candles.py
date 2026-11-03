import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import shadow_1m_candles as shadow

IST = timezone(timedelta(hours=5, minutes=30))


class ShadowOneMinuteTests(unittest.TestCase):
    def test_aggregates_observed_ohlc_volume_and_quote_marks(self):
        rows = [
            {"ts": "09:15:00.100", "ltp": "100", "tq": "", "bid": "99", "ask": "101"},
            {"ts": "09:15:20.300", "ltp": "102", "tq": "10", "bid": "101", "ask": "103"},
            {"ts": "09:16:01.000", "ltp": "101", "tq": "5", "bid": "104", "ask": "103"},
        ]
        result = shadow.aggregate_ticks(rows, day="2026-10-28", symbol="AAA", security_id="7")
        self.assertEqual(len(result), 2)
        first = result[0]
        self.assertEqual((first["open"], first["high"], first["low"], first["close"]), (100.0, 102.0, 100.0, 102.0))
        self.assertEqual(first["volume_delta"], 10.0)
        self.assertEqual(first["volume_weighted_ltp_estimate"], 102.0)
        self.assertEqual(first["last_valid_mid"], 102.0)
        second = result[1]
        self.assertEqual(second["quote_ticks"], 0)
        self.assertEqual(second["crossed_quote_ticks"], 1)
        self.assertEqual(second["last_valid_mid"], "")
        self.assertIn("CROSSED_QUOTES_OMITTED", second["quality_flags"])

    def test_skips_invalid_time_or_price_without_filling_missing_minutes(self):
        rows = [
            {"ts": "bad", "ltp": "100", "tq": "1"},
            {"ts": "09:15:01", "ltp": "NaN", "tq": "1"},
            {"ts": "09:17:01", "ltp": "101", "tq": ""},
        ]
        result = shadow.aggregate_ticks(rows, day="2026-10-28", symbol="AAA")
        self.assertEqual([r["bar_minute"] for r in result], ["09:17"])
        self.assertIn("NO_RECORDED_VOLUME_DELTA", result[0]["quality_flags"])

    def test_current_session_refuses_partial_files_by_default(self):
        now = datetime(2026, 10, 28, 14, 0, tzinfo=IST)
        with self.assertRaisesRegex(ValueError, "still be open"):
            shadow.build_day(Path("unused-root"), "2026-10-28", now=now)
        self.assertFalse(shadow.session_collection_complete("2026-10-28", now))
        self.assertTrue(shadow.session_collection_complete("2026-10-27", now))
        self.assertTrue(shadow.session_collection_complete("2026-10-28", datetime(2026, 10, 28, 15, 33, tzinfo=IST)))
        with self.assertRaisesRegex(ValueError, "timezone-aware IST"):
            shadow.session_collection_complete("2026-10-28", datetime(2026, 10, 28, 16, 0))


if __name__ == "__main__":
    unittest.main()
