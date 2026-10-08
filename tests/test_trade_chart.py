from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import trade_chart as tc

TRADE = {"paper_trade_id": "PT-1", "symbol": "TEST", "direction": "BEARISH", "option_type": "PE", "status": "OPEN", "strike": 440.0,
         "expiry": "2026-10-27", "option_security_id": "87351", "entry_price": 12.7, "option_stop": 10.2, "option_target1": 15.25,
         "option_target2": 17.15, "option_target3": 19.05, "underlying_entry": 440.55, "underlying_stop": 442.47,
         "underlying_target1": 438.63, "underlying_target2": 436.71, "underlying_target3": 434.79, "last_option_price": 14.0,
         "quantity": 1250, "entry_time": "2026-10-08T09:53:03+05:30", "setup_family": "HEALTHY_PULLBACK"}


class TradeChartTests(unittest.TestCase):
    def test_levels_for_option_and_stock_have_entry_sl_and_three_targets(self) -> None:
        lv = tc.levels(TRADE)
        self.assertEqual([x["name"] for x in lv["option"]], ["Entry", "SL", "T1", "T2", "T3"])
        self.assertEqual([x["price"] for x in lv["stock"]], [440.55, 442.47, 438.63, 436.71, 434.79])

    def test_payload_combines_trade_levels_and_candles(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data" / "intraday_movement").mkdir(parents=True)
            (root / "data" / "intraday_movement" / "paper_trade_journal.json").write_text(json.dumps({"trades": [TRADE]}), encoding="utf-8")
            tc._CACHE.clear()
            tc._UNIVERSE.clear()
            tc._UNIVERSE["TEST"] = 1
            candle = [{"t": 1, "o": 1.0, "h": 2.0, "l": 0.5, "c": 1.5}]
            with mock.patch.object(tc, "_candles", return_value=candle):
                d = tc.payload("PT-1", root)
        self.assertTrue(d["ok"])
        self.assertEqual((d["option_label"], d["status"], d["qty"]), ("TEST 440 PE", "OPEN", 1250))
        self.assertAlmostEqual(d["pnl"], (14.0 - 12.7) * 1250)
        self.assertEqual((len(d["stock"]), len(d["option"])), (1, 1))

    def test_unknown_trade_and_page(self) -> None:
        tc._CACHE.clear()
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(tc.payload("PT-NOPE", Path(tmp))["ok"])
        self.assertIn("createPriceLine", tc.TRADE_HTML)
        self.assertIn("/api/trade-chart", tc.TRADE_HTML)

    def test_positions_panel_and_dashboard_link_to_the_trade_page(self) -> None:
        import aplus_live_pnl_dashboard as dash
        from positions_panel import POSITIONS_HTML

        self.assertIn("/trade?id=", POSITIONS_HTML)
        self.assertIn("/trade?id=", dash.HTML)


if __name__ == "__main__":
    unittest.main()
