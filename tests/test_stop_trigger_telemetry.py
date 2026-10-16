"""Regression tests for additive stop-trigger audit telemetry."""

import unittest
from datetime import datetime, timezone

from paper_trade_journal import PaperTradeJournal


class StopTriggerTelemetryTests(unittest.TestCase):
    def test_records_observed_price_and_gap_without_changing_exit_fields(self):
        trade = {"status": "OPEN", "exit_price": 0.0}
        when = datetime(2026, 10, 16, 10, 0, tzinfo=timezone.utc)

        PaperTradeJournal._record_stop_trigger(
            trade,
            when=when,
            observed_price=9.15,
            stop_level=9.35,
            reason="OPTION_STOP_LOSS",
        )

        self.assertEqual(trade["stop_trigger_at"], when.isoformat())
        self.assertEqual(trade["stop_trigger_reason"], "OPTION_STOP_LOSS")
        self.assertEqual(trade["stop_trigger_level"], 9.35)
        self.assertEqual(trade["stop_trigger_price"], 9.15)
        self.assertAlmostEqual(trade["stop_trigger_gap_percent"], (9.35 - 9.15) / 9.35 * 100, places=4)
        self.assertEqual(trade["status"], "OPEN")
        self.assertEqual(trade["exit_price"], 0.0)

    def test_equal_stop_has_zero_gap(self):
        trade = {}
        PaperTradeJournal._record_stop_trigger(
            trade,
            when=datetime(2026, 10, 16, 10, 0, tzinfo=timezone.utc),
            observed_price=10.0,
            stop_level=10.0,
            reason="OPTION_STOP_LOSS",
        )
        self.assertEqual(trade["stop_trigger_gap_percent"], 0.0)

    def test_invalid_prices_do_not_create_trigger_record(self):
        trade = {}
        PaperTradeJournal._record_stop_trigger(
            trade,
            when=datetime(2026, 10, 16, 10, 0, tzinfo=timezone.utc),
            observed_price=0.0,
            stop_level=10.0,
            reason="OPTION_STOP_LOSS",
        )
        self.assertEqual(trade, {})


if __name__ == "__main__":
    unittest.main()
