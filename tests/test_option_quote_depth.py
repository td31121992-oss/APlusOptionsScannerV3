import csv
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

os.environ["TELEGRAM_ENABLED"] = "false"

import paper_trade_journal as pj
from tests.test_journal_costs_and_session_end import _journal, _open_trade

IST = ZoneInfo("Asia/Kolkata")


def T(m):
    return datetime(2026, 10, 14, 10, m, tzinfo=IST)


def quote(last, bid, bq, ask, aq):
    return {"last_price": last, "depth": {"buy": [{"price": bid, "quantity": bq}], "sell": [{"price": ask, "quantity": aq}]}}


class QuoteDepthTests(unittest.TestCase):
    def test_best_quote_reads_depth_or_top_level_fields(self):
        J = pj.PaperTradeJournal
        self.assertEqual(J._best_quote(quote(10, 9.9, 500, 10.1, 300)), (9.9, 500, 10.1, 300))
        self.assertEqual(J._best_quote({"last_price": 10, "bid": 9.8, "bid_qty": 40, "ask": 10.2, "ask_qty": 60}), (9.8, 40, 10.2, 60))
        self.assertEqual(J._best_quote({"last_price": 10}), (0.0, 0, 0.0, 0))
        self.assertEqual(J._best_quote(None), (0.0, 0, 0.0, 0))

    def test_entry_spread_and_slip(self):
        J = pj.PaperTradeJournal
        opt = {"bid": 9.9, "ask": 10.1, "ltp": 10.0, "limit_price": 10.1}
        self.assertEqual(J._entry_spread_pct(opt), 1.98)
        self.assertEqual(J._entry_slip_pct(opt), 1.0)
        self.assertEqual(J._entry_spread_pct({"ltp": 10}), "")

    def test_exit_records_the_real_bid_and_tape(self):
        with tempfile.TemporaryDirectory() as tmp:
            j = _journal(tmp, "2026-10-14", [_open_trade(entry_time="2026-10-14T10:00:00+05:30", option_stop=9.0)])
            j.update_open_positions(option_quotes={"123": quote(10.5, 10.4, 5000, 10.6, 100)}, when=T(1))
            self.assertEqual(j.trades[0]["last_bid"], 10.4)
            j.update_open_positions(option_quotes={"123": quote(8.8, 8.6, 300, 9.0, 800)}, when=T(2))       # stop (9.0) hit; bid 8.6 holds only 300 of 1000
            t = j.trades[0]
            self.assertEqual(t["status"], "CLOSED")
            self.assertEqual((t["exit_price"], t["exit_bid"], t["exit_ask"], t["exit_bid_qty"]), (8.8, 8.6, 9.0, 300))
            self.assertEqual((t["exit_bid_covers_qty"], t["exit_slip_amount"], t["exit_spread_pct"]), (0, 200.0, 4.44))
            self.assertLess(t["net_pnl_at_bid"], t["net_pnl"] + 1)                                         # selling at the bid is never better than at the last price
            tape = Path(tmp, "option_quote_tape", "2026-10-14.csv")
            with tape.open(encoding="utf-8-sig") as fh:
                rows = list(csv.DictReader(fh))
            self.assertEqual([r["bid"] for r in rows], ["10.4", "8.6"])
            self.assertIn("exit_bid", pj.PaperTradeJournal.CSV_FIELDS)

    def test_quote_without_depth_leaves_exit_fields_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            j = _journal(tmp, "2026-10-14", [_open_trade(entry_time="2026-10-14T10:00:00+05:30", option_stop=9.0)])
            j.update_open_positions(option_quotes={"123": {"last_price": 8.5}}, when=T(1))
            t = j.trades[0]
            self.assertEqual(t["status"], "CLOSED")
            self.assertNotIn("exit_bid", t)


if __name__ == "__main__":
    unittest.main()
