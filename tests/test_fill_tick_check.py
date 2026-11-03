import gzip
import json
import tempfile
import unittest
from pathlib import Path

import fill_tick_check as fc

HEAD = "ts,ltp,ltq,vol,oi,tbq,tsq,bid,bq,ask,aq,bsum5,asum5,tq,side,mid,spread_pct"


def ticks_file(root, day, sid, sym, rows):
    d = root / "data" / "option_ticks" / day
    d.mkdir(parents=True, exist_ok=True)
    lines = [HEAD] + [f"{ts},{ltp},1,1,1,1,1,{bid},{bq},{ask},{aq},{bs},{asum},{tq},B,," for ts, ltp, bid, bq, ask, aq, bs, asum, tq in rows]
    with gzip.open(d / f"{sid}_{sym}.csv.gz", "wt", encoding="utf-8") as h:
        h.write("\n".join(lines) + "\n")


def trade(**kw):
    t = {"paper_trade_id": "T1", "status": "CLOSED", "symbol": "AAA", "option_security_id": "77", "quantity": 100, "entry_price": 10.0, "exit_price": 12.0,
         "entry_time": "2026-10-26T10:00:00.500000+05:30", "exit_time": "2026-10-26T10:30:00+05:30"}
    t.update(kw)
    return t


class CheckTests(unittest.TestCase):
    def setup_day(self, root, trades, rows):
        (root / "data" / "intraday_movement").mkdir(parents=True)
        (root / "data" / "intraday_movement" / "paper_trade_journal.json").write_text(json.dumps({"trades": trades}), encoding="utf-8")
        ticks_file(root, "2026-10-26", "77", "AAA", rows)

    def test_entry_and_exit_books_and_prints(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = [("10:00:01.000", 10.2, 9.9, 500, 10.2, 40, 900, 150, 5),             # ask 10.2 vs paper 10.0, only 40 on top, 150 over five levels
                    ("10:00:06.000", 9.95, 9.9, 500, 10.0, 200, 900, 800, 20),           # then a print below the paper price
                    ("10:30:00.500", 12.0, 11.8, 60, 12.1, 50, 400, 300, 0),            # exit: bid 11.8 vs paper 12.0, top 60 < 100, five levels 400
                    ("10:30:04.000", 12.1, 11.9, 500, 12.1, 50, 900, 300, 10)]          # a print above the paper exit price
            self.setup_day(root, [trade()], rows)
            s = fc.run(root)
            e, x = s["ENTRY"], s["EXIT"]
            self.assertEqual((e["n"], x["n"]), (1, 1))
            self.assertEqual(e["median_book_vs_paper_pct"], 2.0)                           # paid 2 % above the paper entry at the displayed ask
            self.assertEqual((e["top_covers_pct"], e["depth5_covers_pct"], e["traded_at_paper_pct"]), (0.0, 100.0, 100.0))
            self.assertEqual(x["median_book_vs_paper_pct"], round((12.0 - 11.8) / 12.0 * 100, 2))
            self.assertEqual((x["top_covers_pct"], x["depth5_covers_pct"], x["traded_at_paper_pct"]), (0.0, 100.0, 100.0))
            self.assertIn("Tick-level fill check", (root / "data" / "reports" / "fill_tick_check.md").read_text(encoding="utf-8"))
            self.assertEqual(len((root / "data" / "reports" / "fill_tick_check.csv").read_text(encoding="utf-8").splitlines()), 3)

    def test_no_print_at_the_paper_price_and_missing_ticks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = [("10:00:01.000", 10.4, 10.3, 500, 10.4, 500, 900, 900, 5), ("10:00:08.000", 10.5, 10.4, 500, 10.5, 500, 900, 900, 5),
                    ("10:30:01.000", 11.0, 10.9, 500, 11.1, 500, 900, 900, 5)]
            other = trade(paper_trade_id="T2", symbol="BBB", option_security_id="88")      # no tick file for this contract
            self.setup_day(root, [trade(), other], rows)
            s = fc.run(root)
            self.assertEqual(s["trades_without_ticks"], 1)
            self.assertEqual(s["ENTRY"]["traded_at_paper_pct"], 0.0)                        # nothing printed at or below 10.0
            self.assertEqual(s["EXIT"]["traded_at_paper_pct"], 0.0)                         # nothing printed at or above 12.0
            self.assertEqual(s["ENTRY"]["top_covers_pct"], 100.0)

    def test_nothing_to_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(fc.run(Path(tmp)))


if __name__ == "__main__":
    unittest.main()
