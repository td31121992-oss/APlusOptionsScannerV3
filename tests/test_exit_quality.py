import csv
import gzip
import tempfile
import unittest
from pathlib import Path

import exit_quality as eq

T0 = 10 * 3600                                                           # entry 10:00, exit 10:30


def trade(**kw):
    base = {"paper_trade_id": "a", "symbol": "ABB", "option_type": "CE", "status": "CLOSED", "entry_time": "2026-11-11T10:00:00", "exit_time": "2026-11-11T10:30:00",
            "entry_price": 10.0, "exit_price": 8.0, "quantity": 100, "net_pnl": -214.0, "exit_reason": "OPTION_STOP_LOSS", "mfe_amount": 50.0, "option_security_id": "11"}
    base.update(kw)
    return base


def ticks(*rows):                                                        # (seconds since midnight, price)
    return [(s, p, p) for s, p in rows]


class AnalyseTests(unittest.TestCase):
    def test_stopped_out_then_recovered_is_a_whipsaw_that_went_up(self):
        tk = ticks((T0 + 1700, 8.0), (T0 + 1900, 8.5), (T0 + 2500, 11.0), (T0 + 3000, 9.6), (T0 + 7000, 9.6))
        r = eq.analyse(trade(), tk)
        self.assertEqual((r["verdict"], r["whipsaw"]), ("WENT_UP", True))
        self.assertEqual(r["after_high_pct"], 37.5)
        self.assertEqual(r["after_close_pct"], 20.0)
        self.assertEqual((r["hold_to_close_rs"], r["best_case_rs"]), (160, 300))

    def test_option_that_kept_falling_means_a_good_exit(self):
        tk = ticks((T0 + 1900, 7.8), (T0 + 2500, 7.0), (T0 + 3000, 6.0), (T0 + 7000, 5.5))
        r = eq.analyse(trade(), tk)
        self.assertEqual((r["verdict"], r["whipsaw"]), ("WENT_DOWN", False))
        self.assertEqual(r["avoided_rs"], 250)

    def test_flat_inside_the_band_and_not_enough_ticks(self):
        self.assertEqual(eq.analyse(trade(), ticks((T0 + 1900, 8.05), (T0 + 2500, 8.1), (T0 + 7000, 8.1)))["verdict"], "FLAT")
        self.assertIsNone(eq.analyse(trade(), ticks((T0 + 1900, 8.05), (T0 + 2500, 8.1))))                   # fewer than 3 ticks after the exit
        self.assertIsNone(eq.analyse(trade(exit_time="2026-11-12T10:30:00"), ticks((T0 + 1900, 8.0), (T0 + 2000, 8.0), (T0 + 2100, 8.0))))   # exited on a later day


class RunTests(unittest.TestCase):
    def test_run_writes_the_files_for_trades_with_ticks_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / "data" / "option_ticks" / "2026-11-11"
            folder.mkdir(parents=True)
            with gzip.open(folder / "11_ABB.csv.gz", "wt", encoding="utf-8", newline="") as h:
                w = csv.writer(h)
                w.writerow(["ts", "ltp", "ask"])
                for s, p in ((T0 + 1900, 8.5), (T0 + 2500, 11.0), (T0 + 3000, 9.6), (T0 + 7000, 9.6)):
                    w.writerow([f"{int(s // 3600):02d}:{int(s % 3600 // 60):02d}:{int(s % 60):02d}.0", p, p])
            rows = eq.run([trade(), trade(paper_trade_id="b", option_security_id="999")], root)
            self.assertEqual([r["paper_trade_id"] for r in rows], ["a"])
            md = (root / "data" / "trade_archive" / "exit_quality.md").read_text(encoding="utf-8")
            self.assertIn("1 of 2 closed trades", md)
            self.assertIn("STOPPED OUT, THEN RECOVERED", md)


if __name__ == "__main__":
    unittest.main()
