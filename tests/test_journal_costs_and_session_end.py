from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

os.environ["TELEGRAM_ENABLED"] = "false"   # tests must never send alerts

from paper_trade_journal import PaperTradeJournal
from trade_costs import round_trip_costs

IST = ZoneInfo("Asia/Kolkata")


class _NoNotify:
    def notify_exit(self, trade) -> None: ...
    def notify_entry(self, trade) -> None: ...


def _journal(tmp: str, trading_date: str, trades: list[dict]) -> PaperTradeJournal:
    journal = PaperTradeJournal(state_dir=Path(tmp, "state"), report_dir=Path(tmp, "reports"))
    journal.notifier = _NoNotify()
    journal.trading_date = trading_date
    journal.trades = trades
    return journal


def _open_trade(**over) -> dict:
    trade = {
        "paper_trade_id": "PT-TEST-1", "symbol": "TEST", "direction": "BULLISH", "status": "OPEN",
        "option_security_id": "123", "option_transaction": "BUY", "entry_price": 10.0, "quantity": 1000,
        "capital_deployed": 10000.0, "option_stop": 9.0, "option_target1": 11.0, "spread_percent": 1.5,
        "entry_time": "2026-10-07T10:00:00+05:30", "last_option_price": 10.0,
        "highest_option_price": 10.0, "lowest_option_price": 10.0,
    }
    trade.update(over)
    return trade


class CostModelTests(unittest.TestCase):
    def test_costs_are_positive_and_itemised(self) -> None:
        c = round_trip_costs(100.0, 110.0, 100, spread_percent=1.5)
        self.assertEqual(c["brokerage"], 40.0)
        self.assertAlmostEqual(c["stt"], 11000 * 0.15 / 100, places=2)
        self.assertGreater(c["total"], 40.0)
        self.assertAlmostEqual(c["total"], sum(v for k, v in c.items() if k != "total"), delta=0.05)

    def test_zero_quantity_has_no_cost(self) -> None:
        self.assertEqual(round_trip_costs(10.0, 11.0, 0)["total"], 0.0)


class SessionEndTests(unittest.TestCase):
    def test_session_end_closes_at_last_price_with_costs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            journal = _journal(tmp, "2026-10-07", [_open_trade()])
            when = datetime(2026, 10, 7, 15, 30, tzinfo=IST)
            closed = journal.update_open_positions(
                option_quotes={"123": {"last_price": 10.4}}, when=when, force_close=True,
            )
            self.assertEqual(len(closed), 1)
            t = journal.trades[0]
            self.assertEqual(t["status"], "CLOSED")
            self.assertEqual(t["exit_reason"], "SESSION_END")
            self.assertEqual(t["exit_price"], 10.4)
            self.assertGreater(t["estimated_costs"], 0)
            self.assertAlmostEqual(t["net_pnl"], t["gross_pnl"] - t["estimated_costs"], places=1)

    def test_session_end_without_a_price_leaves_trade_open_and_flagged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            journal = _journal(tmp, "2026-10-07", [_open_trade()])
            when = datetime(2026, 10, 7, 15, 30, tzinfo=IST)
            journal.update_open_positions(option_quotes={}, when=when, force_close=True)
            self.assertEqual(journal.trades[0]["status"], "OPEN")
            self.assertEqual(journal.trades[0]["pnl_data_status"], "INCOMPLETE_MARK")


class HighLowTimeTests(unittest.TestCase):
    def _mark(self, journal, price, hh, mm):
        journal.update_open_positions(option_quotes={"123": {"last_price": price}},
                                      when=datetime(2026, 10, 7, hh, mm, tzinfo=IST))

    def test_exact_time_of_each_new_high_and_low_is_recorded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            journal = _journal(tmp, "2026-10-07", [_open_trade(entry_price=10.0, option_stop=1.0, option_target1=50.0,
                                                               highest_option_price=10.0, lowest_option_price=10.0)])
            self._mark(journal, 10.0, 10, 1)       # equal to entry: no new extreme, no time
            t = journal.trades[0]
            self.assertNotIn("highest_option_price_at", t)
            self._mark(journal, 11.5, 10, 2)       # new high
            self._mark(journal, 11.0, 10, 3)       # lower, not a new high / not below the entry-low
            self._mark(journal, 9.0, 10, 4)        # new low
            self._mark(journal, 12.5, 10, 5)       # newer high
            self.assertEqual((t["highest_option_price"], t["highest_option_price_at"][11:16]), (12.5, "10:05"))
            self.assertEqual((t["lowest_option_price"], t["lowest_option_price_at"][11:16]), (9.0, "10:04"))

    def test_csv_report_still_writes_with_the_new_columns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            journal = _journal(tmp, "2026-10-07", [_open_trade(option_stop=1.0, option_target1=50.0)])
            self._mark(journal, 12.0, 10, 2)
            self.assertTrue(journal.flush())
            header = Path(tmp, "reports", "paper_trades.csv").read_text(encoding="utf-8").splitlines()[0]
            self.assertIn("highest_option_price_at", header)
            self.assertIn("lowest_option_price_at", header)

    def test_option_trade_tape_is_actually_written(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            journal = _journal(tmp, "2026-10-07", [_open_trade(option_stop=1.0, option_target1=50.0)])
            self._mark(journal, 10.5, 10, 2)
            self._mark(journal, 10.7, 10, 3)
            tape = Path(tmp, "option_trade_tape", "2026-10-07", "PT-TEST-1.csv")
            self.assertTrue(tape.exists(), "tape file must exist (previous code silently never wrote it)")
            self.assertEqual(len(tape.read_text(encoding="utf-8").splitlines()), 3)    # header + 2 marks


class CarryoverTests(unittest.TestCase):
    def test_open_trade_is_closed_not_dropped_when_date_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            journal = _journal(tmp, "2026-10-06", [_open_trade(last_option_price=8.0)])
            journal._ensure_date(date(2026, 10, 7))
            self.assertEqual(journal.trades, [])           # new day starts clean
            history = json.loads(Path(tmp, "reports", "paper_trade_history.json").read_text(encoding="utf-8"))
            rows = history["paper_trades"]
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["status"], "CLOSED")
            self.assertEqual(rows[0]["exit_reason"], "PRIOR_SESSION_UNRESOLVED")
            self.assertEqual(rows[0]["exit_price"], 8.0)   # last known price, nothing invented
            self.assertLess(rows[0]["net_pnl"], 0)


if __name__ == "__main__":
    unittest.main()
