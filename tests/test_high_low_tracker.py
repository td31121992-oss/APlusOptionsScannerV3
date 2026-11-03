from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from high_low_tracker import HighLowTracker

IST = ZoneInfo("Asia/Kolkata")


def at(h: int, m: int) -> datetime:
    return datetime(2026, 10, 7, h, m, tzinfo=IST)


def trade(high: float, low: float, entry: float = 10.0, **extra) -> dict:
    return {"paper_trade_id": "PT-1", "entry_price": entry, "entry_time": "2026-10-07T09:30:11+05:30",
            "highest_option_price": high, "lowest_option_price": low, **extra}


class TrackerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name, "state", "hl.json")

    def test_extremes_equal_to_entry_use_the_entry_time(self) -> None:
        r = HighLowTracker(self.path).update(trade(10.0, 10.0), at(10, 0))
        self.assertEqual((r["high_time"], r["low_time"]), ("09:30", "09:30"))

    def test_pre_existing_extreme_is_labelled_before_tracking_then_new_extremes_get_times(self) -> None:
        t = HighLowTracker(self.path)
        r1 = t.update(trade(12.0, 9.0), at(10, 0))                    # first sight: extremes happened earlier
        self.assertEqual((r1["high_time"], r1["low_time"]), ("before 10:00", "before 10:00"))
        r2 = t.update(trade(12.0, 9.0), at(10, 5))                    # unchanged -> label unchanged
        self.assertEqual(r2["high_time"], "before 10:00")
        r3 = t.update(trade(13.5, 9.0), at(10, 7))                    # new high noticed at 10:07
        self.assertEqual((r3["high"], r3["high_time"], r3["low_time"]), (13.5, "10:07", "before 10:00"))
        r4 = t.update(trade(13.5, 8.2), at(10, 11))                   # new low at 10:11
        self.assertEqual((r4["low"], r4["low_time"], r4["high_time"]), (8.2, "10:11", "10:07"))

    def test_exact_times_from_the_journal_win(self) -> None:
        t = HighLowTracker(self.path)
        r = t.update(trade(12.0, 9.0, highest_option_price_at="2026-10-07T09:48:30+05:30",
                           lowest_option_price_at="2026-10-07T10:02:00+05:30"), at(11, 0))
        self.assertEqual((r["high_time"], r["low_time"]), ("09:48", "10:02"))

    def test_state_survives_a_restart(self) -> None:
        a = HighLowTracker(self.path)
        a.update(trade(12.0, 9.0), at(10, 0))
        a.update(trade(14.0, 9.0), at(10, 9))
        b = HighLowTracker(self.path)                                  # new process, same file
        r = b.update(trade(14.0, 9.0), at(10, 30))
        self.assertEqual((r["high_time"], r["low_time"]), ("10:09", "before 10:00"))

    def test_bad_input_never_raises(self) -> None:
        t = HighLowTracker(self.path)
        self.assertEqual(t.update({}, at(10, 0))["high"], 0.0)
        self.assertEqual(t.update({"paper_trade_id": "x", "highest_option_price": "n/a"}, at(10, 0))["high_time"], "")


class DashboardRowTests(unittest.TestCase):
    def test_snapshot_rows_carry_high_low_and_capital(self) -> None:
        from unittest import mock
        import aplus_live_pnl_dashboard as dash

        today = datetime.now(IST).date().isoformat()
        t = {"paper_trade_id": "PT-DASH-1", "symbol": "TEST", "direction": "BEARISH", "option_type": "PE", "status": "OPEN",
             "entry_price": 10.0, "last_option_price": 11.0, "quantity": 100, "capital_deployed": 1000.0,
             "highest_option_price": 12.0, "lowest_option_price": 9.5, "entry_time": f"{today}T09:30:00+05:30"}
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(dash, "_load_trades", return_value=[t]), \
                 mock.patch.object(dash, "_HL", HighLowTracker(Path(tmp, "hl.json"))):
                row = dash.snapshot()["rows"][0]
        self.assertEqual((row["high"], row["low"]), (12.0, 9.5))
        self.assertTrue(row["high_time"].startswith("before "))     # extremes predate the tracker
        self.assertEqual(row["capital"], 1000.0)

    def test_page_has_new_columns_and_cards(self) -> None:
        import aplus_live_pnl_dashboard as dash

        for needle in ("High ₹ (time)", "Low ₹ (time)", "cap_deployed", "open_return", "day_return", "x.high_time"):
            self.assertIn(needle, dash.HTML)


if __name__ == "__main__":
    unittest.main()
