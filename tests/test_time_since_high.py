import os
import tempfile
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

os.environ["TELEGRAM_ENABLED"] = "false"

import aplus_live_pnl_dashboard as d
from tests.test_journal_costs_and_session_end import _journal, _open_trade

IST = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 10, 14, 13, 57, tzinfo=IST)
BASE = {"status": "OPEN", "entry_time": "2026-10-14T10:15:35+05:30", "last_option_price": 44.15, "option_type": "CE",
        "direction": "BULLISH", "stock_at_high": 1000.0, "stock_last_price": 1000.5}
HL = {"high": 49.95, "high_time": "13:15"}


class SinceHighTests(unittest.TestCase):
    def test_age_drawdown_and_melting(self):
        r = d._since_high(BASE, HL, NOW)
        self.assertEqual((r["high_age_min"], r["from_high_pct"], r["high_state"]), (42, -11.6, "MELTING"))

    def test_stock_reversing(self):
        r = d._since_high({**BASE, "stock_last_price": 996.0}, HL, NOW)
        self.assertEqual((r["high_state"], r["stock_since_high_pct"]), ("STOCK_REVERSING", -0.4))

    def test_put_direction_is_inverted(self):
        up = d._since_high({**BASE, "option_type": "PE", "direction": "BEARISH", "stock_last_price": 1004.0}, HL, NOW)
        self.assertEqual(up["high_state"], "STOCK_REVERSING")                  # stock rose against a put
        down = d._since_high({**BASE, "option_type": "PE", "direction": "BEARISH", "stock_last_price": 996.0}, HL, NOW)
        self.assertEqual(down["high_state"], "MELTING")                        # stock fell, option still down from high

    def test_small_drawdown_and_closed_trades_have_no_state(self):
        self.assertEqual(d._since_high({**BASE, "last_option_price": 49.0}, HL, NOW)["high_state"], "")
        closed = {**BASE, "status": "CLOSED", "exit_price": 40.0, "exit_time": "2026-10-14T13:45:00+05:30"}
        r = d._since_high(closed, HL, NOW)
        self.assertEqual((r["high_age_min"], r["high_state"]), (30, ""))

    def test_missing_data_is_safe(self):
        r = d._since_high({"status": "OPEN"}, {"high": 0, "high_time": ""}, NOW)
        self.assertEqual((r["high_age_min"], r["from_high_pct"], r["high_state"]), (None, None, ""))


class JournalRemembersStockAtHigh(unittest.TestCase):
    def test_stock_price_is_stored_when_the_option_makes_a_new_high(self):
        with tempfile.TemporaryDirectory() as tmp:
            tr = _open_trade(underlying_entry=100.0, option_type="CE", entry_time="2026-10-14T10:00:00+05:30",
                             highest_option_price_at="2026-10-14T10:05:00+05:30", last_option_price=10.5)
            j = _journal(tmp, "2026-10-14", [tr])
            j.record_stock_response({"TEST": 100.4}, datetime(2026, 10, 14, 10, 5, tzinfo=IST))
            self.assertEqual(tr["stock_at_high"], 100.4)
            j.record_stock_response({"TEST": 100.1}, datetime(2026, 10, 14, 10, 8, tzinfo=IST))      # same high: not overwritten
            self.assertEqual(tr["stock_at_high"], 100.4)
            tr["highest_option_price_at"] = "2026-10-14T10:09:00+05:30"                                # new high: updated
            j.record_stock_response({"TEST": 100.8}, datetime(2026, 10, 14, 10, 9, tzinfo=IST))
            self.assertEqual(tr["stock_at_high"], 100.8)


if __name__ == "__main__":
    unittest.main()
