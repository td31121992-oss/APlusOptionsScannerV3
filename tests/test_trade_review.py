from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import trade_review


def trade(**over) -> dict:
    t = {"paper_trade_id": "PT-20261007-100000-TEST-ABC", "symbol": "TEST", "direction": "BEARISH", "status": "CLOSED",
         "setup_family": "FRESH_BREAKOUT", "entry_time": "2026-10-07T10:00:00+05:30", "exit_time": "2026-10-07T11:00:00+05:30",
         "entry_price": 10.0, "exit_price": 11.0, "quantity": 1000, "highest_option_price": 14.0,
         "highest_option_price_at": "2026-10-07T10:30:00+05:30", "lowest_option_price": 8.0, "option_stop": 7.0,
         "capital_deployed": 10000, "spread_percent": 1.0, "exit_reason": "PROFIT_PROTECTION_EXIT"}
    t.update(over)
    return t


class ReviewTests(unittest.TestCase):
    def test_row_metrics(self) -> None:
        r = trade_review.review_row(trade())
        self.assertEqual((r["mfe_pct"], r["mae_pct"], r["return_pct"], r["captured_pct"], r["stop_pct"]), (40.0, -20.0, 10.0, 25, 30.0))
        self.assertEqual(r["gross"], 1000)
        self.assertLess(r["net"], r["gross"])
        self.assertEqual(r["high_time"], "10:30")

    def test_open_trade_uses_last_mark_and_is_flagged(self) -> None:
        r = trade_review.review_row(trade(status="OPEN", exit_price=0.0, last_option_price=9.0))
        self.assertEqual((r["status"], r["exit_price"], r["gross"]), ("OPEN", 9.0, -1000))

    def test_render_and_write_handle_gave_back_and_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertIsNone(trade_review.write("2026-10-07", root=root, out_root=root / "out"))
            rows = [trade_review.review_row(trade(exit_price=10.2))]
            text = trade_review.render("2026-10-07", rows)
            self.assertIn("Gave back a gain", text)
            self.assertIn("Deep drawdown", text)
            self.assertIn("By setup", text)

    def test_every_recorded_shadow_tag_reaches_the_csv_with_union_columns(self) -> None:
        import csv
        import json
        a = trade(paper_trade_id="PT-20261007-0001", mv_gap_bucket="with>2", px_x_avg=3.1, ob_shadow="not a tag prefix")
        b = trade(paper_trade_id="PT-20261007-0002", mv_in_play=True, cs_story={"k": 1})
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            journal = root / "data" / "intraday_movement"
            journal.mkdir(parents=True)
            (journal / "paper_trade_journal.json").write_text(json.dumps({"trades": [a, b]}), encoding="utf-8")
            folder = trade_review.write("2026-10-07", root=root, out_root=root / "out")
            with (folder / "trade_review.csv").open(encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 2)
        self.assertEqual((rows[0]["mv_gap_bucket"], rows[0]["px_x_avg"], rows[0]["mv_in_play"]), ("with>2", "3.1", ""))     # a tag only the other trade has is blank here
        self.assertEqual((rows[1]["mv_in_play"], rows[1]["mv_gap_bucket"]), ("True", ""))
        self.assertEqual(rows[1]["cs_story"], '{"k": 1}')
        self.assertNotIn("ob_shadow", rows[0])                                                                        # only the shadow-tag prefixes are copied


if __name__ == "__main__":
    unittest.main()
