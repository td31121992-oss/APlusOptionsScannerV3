from __future__ import annotations

import unittest
from datetime import date

from update_safety_data import parse_ban_list, parse_combine_oi, parse_holidays

BAN_TEXT = "Securities in Ban For Trade Date 07-OCT-2026:\n1,AMBUJACEM\n2,BANDHANBNK\n3,SAIL\n"


class UpdateSafetyDataTests(unittest.TestCase):
    def test_parse_ban_list(self) -> None:
        trade_date, symbols = parse_ban_list(BAN_TEXT)
        self.assertEqual(trade_date, date(2026, 10, 7))
        self.assertEqual(symbols, ["AMBUJACEM", "BANDHANBNK", "SAIL"])

    def test_parse_ban_list_with_no_securities(self) -> None:
        trade_date, symbols = parse_ban_list("Securities in Ban For Trade Date 08-OCT-2026:\n")
        self.assertEqual(trade_date, date(2026, 10, 8))
        self.assertEqual(symbols, [])

    def test_parse_ban_list_rejects_garbage(self) -> None:
        with self.assertRaises(ValueError):
            parse_ban_list("<html>blocked</html>")
        with self.assertRaises(ValueError):
            parse_ban_list("")

    def test_parse_combine_oi_utilization_and_ban_flag(self) -> None:
        text = (
            "Date, ISIN, Scrip Name, NSE Symbol, MWPL, Open Interest, Future Equivalent Open Interest, Limit for Next Day\n"
            "06-OCT-2026,X1,AMBUJA,AMBUJACEM,100000000,114693600,95000000,No Fresh Positions\n"
            "06-OCT-2026,X2,RELIANCE,RELIANCE,200000000,30000000,40000000,\n"
            "06-OCT-2026,X3,BAD,BADROW,0,1,1,\n"
        )
        data_date, rows = parse_combine_oi(text)
        self.assertEqual(data_date, date(2026, 10, 6))
        by = {r["symbol"]: r for r in rows}
        self.assertEqual(sorted(by), ["AMBUJACEM", "RELIANCE"])  # zero-MWPL row skipped
        self.assertAlmostEqual(by["AMBUJACEM"]["utilization"], 95.0)
        self.assertTrue(by["AMBUJACEM"]["no_fresh"])
        self.assertAlmostEqual(by["RELIANCE"]["utilization"], 20.0)
        self.assertFalse(by["RELIANCE"]["no_fresh"])

    def test_parse_combine_oi_rejects_empty(self) -> None:
        with self.assertRaises(ValueError):
            parse_combine_oi("Date, NSE Symbol, MWPL\n")

    def test_parse_holidays_uses_fo_segment_sorted(self) -> None:
        payload = {
            "CM": [{"tradingDate": "01-Jan-2026", "description": "ignore"}],
            "FO": [
                {"tradingDate": "20-Oct-2026", "description": "Dussehra"},
                {"tradingDate": "02-Oct-2026", "description": "Mahatma Gandhi Jayanti"},
            ],
        }
        self.assertEqual(
            parse_holidays(payload),
            [(date(2026, 10, 2), "Mahatma Gandhi Jayanti"), (date(2026, 10, 20), "Dussehra")],
        )


if __name__ == "__main__":
    unittest.main()
