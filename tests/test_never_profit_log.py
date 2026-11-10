import csv
import gzip
import tempfile
import unittest
from pathlib import Path

import never_profit_log as npl


def trade(**kw):
    base = {"paper_trade_id": "a", "symbol": "ABB", "option_type": "CE", "status": "CLOSED", "entry_time": "2026-11-09T10:00:00", "exit_time": "2026-11-09T10:12:00",
            "entry_price": 10.0, "highest_option_price": 10.0, "lowest_option_price": 8.0, "option_stop": 8.2, "exit_price": 8.1, "quantity": 100, "net_pnl": -214.0 - 190.0,
            "mfe_amount": 0.0, "exit_reason": "OPTION_STOP_LOSS", "spread_percent": 1.4, "lowest_option_price_at": "2026-11-09T10:11:00"}
    base.update(kw)
    return base


class NeverInProfitTests(unittest.TestCase):
    def test_definition(self):
        self.assertTrue(npl.never_in_profit(trade()))
        self.assertTrue(npl.never_in_profit(trade(mfe_amount=None, highest_option_price=9.9)))
        self.assertFalse(npl.never_in_profit(trade(mfe_amount=250.0, highest_option_price=10.5)))


class PostMortemTests(unittest.TestCase):
    def write_ticks(self, root, rows):
        folder = root / "data" / "ticks" / "2026-11-09"
        folder.mkdir(parents=True)
        with gzip.open(folder / "ABB.csv.gz", "wt", encoding="utf-8", newline="") as h:
            w = csv.writer(h)
            w.writerow(["ts", "sym", "ltp"])
            for ts, px in rows:
                w.writerow([ts, "ABB", px])

    def test_hints_and_stock_moves_for_a_call_that_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # the stock rose into our entry (+0.2% in the 2 minutes before), then fell: 5 minutes later it is below the entry price
            self.write_ticks(root, [("09:57:55", 1000.0), ("09:59:55", 1002.0), ("10:00:00", 1002.0), ("10:05:00", 999.0), ("10:11:00", 997.0), ("10:12:00", 998.0)])
            row = npl.post_mortem(trade(), root)
            hints = row["hints"].split(";")
            for h in ("SPREAD_WIDE", "CHASED", "NO_FOLLOWTHROUGH", "STOCK_AGAINST", "QUICK_STOP"):
                self.assertIn(h, hints)
            self.assertNotIn("EARLY_ENTRY", hints)
            self.assertGreater(row["stock_pre2m_pct"], 0.1)
            self.assertLess(row["stock_5m_pct"], 0)
            self.assertAlmostEqual(row["minutes_held"], 12.0)
            self.assertEqual(row["minutes_to_low"], 11.0)
            self.assertIn("OPTION_STOP_LOSS after 12.0 min", row["diagnosis"])

    def test_put_direction_is_flipped_and_missing_data_is_blank(self):
        with tempfile.TemporaryDirectory() as tmp:
            row = npl.post_mortem(trade(option_type="PE"), Path(tmp))                 # no tick or candle files at all
            self.assertIsNone(row["stock_5m_pct"])
            self.assertIn("SPREAD_WIDE", row["hints"])


class RunTests(unittest.TestCase):
    def test_writes_only_never_in_profit_trades_and_is_repeatable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            hist = [trade(paper_trade_id="a"), trade(paper_trade_id="b", mfe_amount=900.0, highest_option_price=11.0, net_pnl=500.0), trade(paper_trade_id="c", status="OPEN")]
            rows = npl.run(hist, root)
            rows2 = npl.run(hist, root)
            self.assertEqual([r["paper_trade_id"] for r in rows], ["a"])
            self.assertEqual(len(rows2), 1)
            lines = (root / "data" / "trade_archive" / "never_profit.csv").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 2)                                         # header + one trade, not duplicated by the second run
            self.assertIn("1 of 2 closed trades", (root / "data" / "trade_archive" / "never_profit.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()


class DailyMfeTests(unittest.TestCase):
    def test_per_day_counts_peaks_and_files(self):
        import daily_mfe_report as dm

        mk = lambda i, day, mfe, net, sym="ABB": dict(trade(paper_trade_id=i, symbol=sym, mfe_amount=mfe, net_pnl=net, entry_time=f"{day}T10:00:00", highest_option_price=10 + mfe / 100,      # noqa: E731
                                                       highest_option_price_at=f"{day}T10:20:00"))
        hist = [mk("a", "2026-11-05", 0.0, -400.0), mk("b", "2026-11-05", 3500.0, 1000.0, "TCS"), mk("c", "2026-11-06", 5200.0, 4000.0, "INFY"), trade(paper_trade_id="d", status="OPEN")]
        with tempfile.TemporaryDirectory() as tmp:
            days = dm.run(hist, Path(tmp))
            self.assertEqual([d["day"] for d in days], ["2026-11-05", "2026-11-06"])
            d1 = days[0]
            self.assertEqual((d1["trades"], d1["never_in_profit"], d1["touched_3k"], d1["touched_5k"], d1["best_peak_rs"], d1["best_peak_trade"], d1["net_pnl"]), (2, 1, 1, 0, 3500, "TCS CE", 600))
            self.assertEqual(days[1]["touched_5k"], 1)
            tm = (Path(tmp) / "data" / "trade_archive" / "trade_mfe.csv").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(tm), 4)                                          # header + 3 closed trades (the OPEN one is left out)
            self.assertIn("20.0", tm[2])                                          # minutes to the peak
