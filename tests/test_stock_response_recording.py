import os
import tempfile
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

os.environ["TELEGRAM_ENABLED"] = "false"

import trade_journal as tj
from tests.test_journal_costs_and_session_end import _journal, _open_trade

IST = ZoneInfo("Asia/Kolkata")


def T(h, m, s=0):
    return datetime(2026, 10, 14, h, m, s, tzinfo=IST)


class StockResponseTests(unittest.TestCase):
    def _trade(self, **over):
        return _open_trade(underlying_entry=100.0, option_type="CE", entry_time="2026-10-14T10:00:00+05:30", **over)

    def test_call_records_move_gain_ratio_and_milestones(self):
        with tempfile.TemporaryDirectory() as tmp:
            j = _journal(tmp, "2026-10-14", [self._trade()])
            t = j.trades[0]
            t["last_option_price"] = 10.6                       # +6% option
            self.assertEqual(j.record_stock_response({"TEST": 100.3}, T(10, 5)), 1)       # stock +0.30%
            self.assertAlmostEqual(t["stock_move_fav_pct"], 0.3, places=2)
            self.assertAlmostEqual(t["stock_opt_gain_pct"], 6.0, places=1)
            self.assertEqual(t["stock_ms025_at"], "10:05:00")
            self.assertNotIn("stock_ms050_at", t)
            t["last_option_price"] = 11.5
            j.record_stock_response({"TEST": 100.9}, T(10, 9))
            self.assertEqual(t["stock_ms050_at"], "10:09:00")
            self.assertAlmostEqual(t["stock_ms050_opt_pct"], 15.0, places=1)
            self.assertAlmostEqual(t["stock_opt_per_1pct"], 15.0 / 0.9, places=0)
            t["last_option_price"] = 10.5
            j.record_stock_response({"TEST": 100.4}, T(10, 12))       # fell back: peak is kept, milestones are not rewritten
            self.assertAlmostEqual(t["stock_move_fav_max_pct"], 0.9, places=2)
            self.assertEqual(t["stock_ms050_at"], "10:09:00")

    def test_put_uses_inverted_direction(self):
        with tempfile.TemporaryDirectory() as tmp:
            tr = _open_trade(underlying_entry=100.0, option_type="PE", direction="BEARISH", entry_time="2026-10-14T10:00:00+05:30")
            j = _journal(tmp, "2026-10-14", [tr])
            tr["last_option_price"] = 11.0
            j.record_stock_response({"TEST": 99.0}, T(10, 5))             # stock fell 1% = favourable for a put
            self.assertAlmostEqual(tr["stock_move_fav_pct"], 1.0, places=2)
            self.assertEqual(tr["stock_ms100_at"], "10:05:00")

    def test_missing_price_or_entry_is_skipped_and_status_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            j = _journal(tmp, "2026-10-14", [self._trade()])
            self.assertEqual(j.record_stock_response({}, T(10, 5)), 0)
            self.assertEqual(j.record_stock_response({"TEST": 0}, T(10, 5)), 0)
            j.trades[0]["underlying_entry"] = 0.0
            self.assertEqual(j.record_stock_response({"TEST": 101.0}, T(10, 5)), 0)
            self.assertEqual(j.trades[0]["status"], "OPEN")
            self.assertNotIn("stock_move_fav_pct", j.trades[0])

    def test_response_text_for_the_journal_page(self):
        text = tj._response_text({"stock_move_fav_pct": 0.9, "stock_move_fav_max_pct": 1.2, "stock_opt_gain_pct": 18.0,
                                  "stock_opt_per_1pct": 20.0, "stock_ms025_at": "10:05:00", "stock_ms025_opt_pct": 6.0})
        self.assertIn("stock +0.90% now (peak +1.20%)", text)
        self.assertIn("option +18.0%", text)
        self.assertIn("20% option per 1% stock", text)
        self.assertIn("+0.25% stock at 10:05 (option +6%)", text)
        self.assertEqual(tj._response_text({}), "")


if __name__ == "__main__":
    unittest.main()
