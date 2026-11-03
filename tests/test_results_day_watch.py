import csv
import tempfile
import unittest
from pathlib import Path

import results_day_watch as rdw


def feed(w, sym, prices, start=14 * 3600 + 20 * 60, step=10.0, day_base=0.0):
    for i, p in enumerate(prices):
        w.update(start + i * step, sym, p, day_base, 1.0)


class WatchTests(unittest.TestCase):
    def test_quiet_stock_makes_path_rows_but_no_alert(self):
        w = rdw.Watch(["AAA"])
        feed(w, "AAA", [100.0 + 0.001 * i for i in range(60)])
        self.assertEqual(w.alerts, [])
        self.assertGreaterEqual(len(w.paths), 9)                     # one row a minute for ten minutes

    def test_fast_move_alerts_once_and_marks_the_filing(self):
        w = rdw.Watch(["AAA"], {"AAA": 14 * 3600 + 26 * 60})
        feed(w, "AAA", [100.0] * 40 + [101.0, 102.0, 103.0, 104.0] + [104.0] * 20)
        self.assertEqual(len(w.alerts), 1)                            # throttled to one per five minutes
        a = w.alerts[0]
        self.assertEqual((a["direction"], a["filed"]), ("UP", 1))
        self.assertGreater(a["filed_min_ago"], 0)

    def test_down_move_and_unwatched_stock(self):
        w = rdw.Watch(["AAA"])
        feed(w, "AAA", [100.0] * 40 + [99.0, 98.0, 97.0] + [97.0] * 5)
        feed(w, "BBB", [100.0] * 40 + [90.0, 80.0])
        self.assertEqual([a["direction"] for a in w.alerts], ["DOWN"])
        self.assertEqual({a["symbol"] for a in w.alerts}, {"AAA"})

    def test_filing_flag_only_after_the_filing(self):
        w = rdw.Watch(["AAA"], {"AAA": 14 * 3600 + 25 * 60})
        feed(w, "AAA", [100.0] * 30, start=14 * 3600 + 20 * 60)
        self.assertEqual([r["filed"] for r in w.paths][:3], [0, 0, 0])
        self.assertEqual(w.paths[-1]["filed"], 0 if w.paths[-1]["time"] < "14:25:00" else 1)


class ListTests(unittest.TestCase):
    def test_results_symbols_from_any_archive_file(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            cal = root / "data" / "event_calendar"
            cal.mkdir(parents=True)
            for name, rows in (("2026-10-23.csv", [("ATHERENERG", "2026-10-26", "FINANCIAL RESULTS"), ("XXX", "2026-10-26", "DIVIDEND")]),
                               ("2026-10-26.csv", [("BAJAJ-AUTO", "2026-10-27", "FINANCIAL RESULTS"), ("NOTFNO", "2026-10-26", "FINANCIAL RESULTS")])):
                with (cal / name).open("w", encoding="utf-8", newline="") as h:
                    w = csv.writer(h)
                    w.writerow(["symbol", "event_date", "event_type", "severity", "as_of", "source", "notes"])
                    for s, dte, typ in rows:
                        w.writerow([s, dte, typ, "HIGH", "x", "x", ""])
            self.assertEqual(rdw.results_symbols("2026-10-26", root, {"ATHERENERG", "BAJAJ-AUTO"}), ["ATHERENERG"])
            self.assertEqual(rdw.next_event_date("2026-10-26", root), "2026-10-27")


if __name__ == "__main__":
    unittest.main()
