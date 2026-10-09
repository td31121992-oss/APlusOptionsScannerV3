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

    def test_session_end_without_a_quote_uses_a_recent_last_mark(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            journal = _journal(tmp, "2026-10-07", [_open_trade(
                last_option_price=10.8, last_successful_mark_at="2026-10-07T15:29:12+05:30")])
            when = datetime(2026, 10, 7, 15, 30, 44, tzinfo=IST)
            journal.update_open_positions(option_quotes={}, when=when, force_close=True)
            t = journal.trades[0]
            self.assertEqual((t["status"], t["exit_reason"], t["exit_price"]), ("CLOSED", "SESSION_END_LAST_MARK", 10.8))

    def test_session_end_does_not_close_on_a_stale_mark(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            journal = _journal(tmp, "2026-10-07", [_open_trade(
                last_option_price=10.8, last_successful_mark_at="2026-10-07T14:00:00+05:30")])
            journal.update_open_positions(option_quotes={}, when=datetime(2026, 10, 7, 15, 30, 44, tzinfo=IST), force_close=True)
            self.assertEqual(journal.trades[0]["status"], "OPEN")

    def test_failed_price_request_at_session_end_still_closes_at_the_last_mark(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            journal = _journal(tmp, "2026-10-07", [_open_trade(
                last_option_price=10.8, last_successful_mark_at="2026-10-07T15:29:06+05:30")])
            when = datetime(2026, 10, 7, 15, 30, 6, tzinfo=IST)
            journal.mark_open_positions_unavailable(when, error_type="DhanMarketDataAuthorizationError", force_close=True)   # the 401 path
            t = journal.trades[0]
            self.assertEqual((t["status"], t["exit_reason"], t["exit_price"]), ("CLOSED", "SESSION_END_LAST_MARK", 10.8))

    def test_failed_price_request_during_the_day_never_closes_anything(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            journal = _journal(tmp, "2026-10-07", [_open_trade(
                last_option_price=10.8, last_successful_mark_at="2026-10-07T11:00:00+05:30")])
            journal.mark_open_positions_unavailable(datetime(2026, 10, 7, 11, 1, tzinfo=IST), error_type="Timeout", force_close=False)
            self.assertEqual(journal.trades[0]["status"], "OPEN")


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


class ProfitLockTests(unittest.TestCase):
    def _run(self, mode: str, prices: list[float]):
        os.environ["APLUS_PROFIT_LOCK_MODE"] = mode
        self.addCleanup(os.environ.pop, "APLUS_PROFIT_LOCK_MODE", None)
        with tempfile.TemporaryDirectory() as tmp:
            journal = _journal(tmp, "2026-10-07", [_open_trade(option_stop=1.0, option_target1=50.0)])
            for i, price in enumerate(prices):
                journal.update_open_positions(option_quotes={"123": {"last_price": price}},
                                              when=datetime(2026, 10, 7, 10, 1 + i, tzinfo=IST))
            return dict(journal.trades[0])

    def test_floor_values(self) -> None:
        f = PaperTradeJournal._profit_lock_floor
        self.assertEqual(f(10.0, 10.9), 0.0)                       # below the +10% trigger: no floor
        self.assertAlmostEqual(f(10.0, 11.0), 10.2)                # +10% -> lock +2%
        self.assertAlmostEqual(f(10.0, 12.0), 11.2)                # +20% peak -> trails to +12%
        self.assertAlmostEqual(f(10.0, 15.0), 10.0 * 1.42)         # +50% -> trails 8 points under the peak

    def test_enforce_closes_a_winner_before_it_turns_into_a_loss(self) -> None:
        t = self._run("ENFORCE", [10.5, 11.2, 10.9, 10.1])
        self.assertEqual((t["status"], t["exit_reason"], t["exit_price"]), ("CLOSED", "PROFIT_LOCK_EXIT", 10.1))
        self.assertGreater(t["exit_price"], t["entry_price"])

    def test_shadow_records_but_does_not_close(self) -> None:
        t = self._run("SHADOW", [10.5, 11.2, 10.1])
        self.assertEqual(t["status"], "OPEN")
        self.assertEqual(t["lock_shadow_exit_price"], 10.1)

    def test_off_and_below_trigger_do_nothing(self) -> None:
        self.assertEqual(self._run("OFF", [11.2, 10.1])["status"], "OPEN")
        t = self._run("ENFORCE", [10.5, 10.9, 9.9])                # never reached +10%
        self.assertEqual(t["status"], "OPEN")


class StopShadowTests(unittest.TestCase):
    """COLPAL-style path: entry 10, T1 12, T2 13.5, T3 15; peak 14.2 then fade. Shadows never change the real trade."""
    def _run(self, prices: list[float]):
        with tempfile.TemporaryDirectory() as tmp:
            journal = _journal(tmp, "2026-10-07", [_open_trade(option_stop=8.0, option_target1=12.0, option_target2=13.5, option_target3=15.0)])
            for i, price in enumerate(prices):
                journal.update_open_positions(option_quotes={"123": {"last_price": price}},
                                              when=datetime(2026, 10, 7, 10, 1 + i, tzinfo=IST))
            return dict(journal.trades[0])

    def test_ladder_and_trail_exit_higher_than_the_real_plus8_stop(self) -> None:
        t = self._run([12.1, 13.6, 14.2, 11.9, 10.7])
        self.assertEqual((t["status"], t["exit_price"]), ("CLOSED", 10.7))                 # real rule only exits at the +8% stop (10.8)
        self.assertEqual(t["shadow_ladder_exit_price"], 11.9)                              # ladder floor = target 1 (12.0)
        self.assertEqual(t["shadow_trail60_exit_price"], 11.9)                             # 10 + 0.6*4.2 = 12.52 -> first mark below
        self.assertNotIn("shadow_ladder_at_real_exit", t)

    def test_half10_books_at_plus_10_then_stops_rest_at_entry(self) -> None:
        t = self._run([10.5, 11.2, 10.6, 9.9])                     # +10% touched, then back through entry (10.0)
        self.assertEqual(t["shadow_half10_book_price"], 11.0)
        self.assertEqual(t["shadow_half10_exit_price"], 9.9)
        self.assertEqual(t["status"], "OPEN")                      # real trade untouched (its stop is 8.0)

    def test_half10_never_booked_follows_the_real_exit(self) -> None:
        t = self._run([9.0, 7.9])
        self.assertNotIn("shadow_half10_book_at", t)
        self.assertEqual(t["shadow_half10_exit_price"], 7.9)

    def test_untriggered_shadow_closes_at_real_exit_price(self) -> None:
        t = self._run([9.0, 7.9])                                                          # plain stop loss, no target reached
        self.assertEqual(t["exit_reason"], "OPTION_STOP_LOSS")
        self.assertEqual(t["shadow_ladder_exit_price"], 7.9)
        self.assertTrue(t["shadow_trail60_at_real_exit"])


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
