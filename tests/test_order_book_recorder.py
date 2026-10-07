from __future__ import annotations

import csv
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import order_book_recorder as ob

IST = ZoneInfo("Asia/Kolkata")
QUOTE = {"last_price": 100.5, "volume": 12345, "last_quantity": 20, "buy_quantity": 3000, "sell_quantity": 1000,
         "depth": {"buy": [{"quantity": 500, "price": 100.45}, {"quantity": 300, "price": 100.4}],
                   "sell": [{"quantity": 200, "price": 100.55}, {"quantity": 100, "price": 100.6}]}}


class RecorderTests(unittest.TestCase):
    def test_row_has_book_pressure(self) -> None:
        r = ob.book_row("ABC", QUOTE, "2026-10-08T10:00:00+05:30")
        self.assertEqual((r["bid"], r["bid_qty"], r["ask"], r["ask_qty"]), (100.45, 500.0, 100.55, 200.0))
        self.assertEqual((r["depth_buy5"], r["depth_sell5"]), (800.0, 300.0))
        self.assertAlmostEqual(r["imbalance"], 0.5)                     # (3000-1000)/4000

    def test_empty_or_missing_fields_do_not_raise(self) -> None:
        r = ob.book_row("ABC", {}, "t")
        self.assertEqual((r["ltp"], r["imbalance"], r["bid"]), (0.0, 0.0, 0.0))

    def test_session_window(self) -> None:
        self.assertTrue(ob.in_session(datetime(2026, 10, 8, 10, 0, tzinfo=IST)))
        self.assertFalse(ob.in_session(datetime(2026, 10, 8, 8, 0, tzinfo=IST)))
        self.assertFalse(ob.in_session(datetime(2026, 10, 10, 10, 0, tzinfo=IST)))          # Saturday

    def test_append_writes_header_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            rows = [ob.book_row("A", QUOTE, "t1"), ob.book_row("B", QUOTE, "t1")]
            ob.append_rows(rows, "2026-10-08", Path(tmp))
            path = ob.append_rows(rows, "2026-10-08", Path(tmp))
            lines = list(csv.reader(path.open(encoding="utf-8")))
            self.assertEqual(len(lines), 5)
            self.assertEqual(lines[0], ob.FIELDS)


if __name__ == "__main__":
    unittest.main()
