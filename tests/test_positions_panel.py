from __future__ import annotations

import unittest

import aplus_live_pnl_dashboard as dash
from positions_panel import POSITIONS_HTML


class PanelTests(unittest.TestCase):
    def test_page_is_mobile_first_and_marked_paper(self) -> None:
        for needle in ('name="viewport"', ">PAPER<", "/api/snapshot", "Open (", "Qty", "Avg", "LTP", "Target", "Managed by Mr. Darpan Bobhate"):
            self.assertIn(needle, POSITIONS_HTML)

    def test_snapshot_rows_carry_quantity_expiry_and_stop(self) -> None:
        from datetime import datetime
        from unittest import mock

        today = datetime.now().date().isoformat()
        t = {"paper_trade_id": "PT-X", "symbol": "TEST", "direction": "BULLISH", "option_type": "CE", "status": "OPEN",
             "entry_price": 10.0, "last_option_price": 11.0, "quantity": 500, "expiry": "2026-10-27", "option_stop": 8.0,
             "option_target1": 13.0, "capital_deployed": 5000.0, "entry_time": f"{today}T10:00:00+05:30"}
        with mock.patch.object(dash, "_load_trades", return_value=[t]):
            row = dash.snapshot()["rows"][0]
        self.assertEqual((row["qty"], row["expiry"], row["sl"], row["tp"]), (500, "2026-10-27", 8.0, 13.0))

    def test_positions_link_is_added_to_the_main_page(self) -> None:
        page = dash._mobileize_html('<html><head></head><body><a href="/fno-market-watch">x</a></body></html>')
        self.assertIn('href="/positions"', page)


if __name__ == "__main__":
    unittest.main()
