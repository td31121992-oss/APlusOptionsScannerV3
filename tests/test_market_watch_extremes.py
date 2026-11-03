import tempfile
import unittest
from datetime import date
from pathlib import Path

import market_watch_extremes as mwe

HEADER = "time,symbol,ltp,volume\n"


class ExtremesTests(unittest.TestCase):
    def setUp(self):
        mwe._STATE.update(file=None, offset=0, header=None, ext={})

    def _root(self, body):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        p = Path(tmp.name, "data", "order_book")
        p.mkdir(parents=True)
        (p / "2026-10-09.csv").write_text(HEADER + body, encoding="utf-8")
        return Path(tmp.name), p / "2026-10-09.csv"

    def test_time_and_percent_from_open(self):
        root, _ = self._root("2026-10-09T09:20:00+05:30,AAA,101,1\n2026-10-09T10:05:00+05:30,AAA,105,1\n"
                             "2026-10-09T11:30:00+05:30,AAA,99,1\n2026-10-09T12:00:00+05:30,AAA,102,1\n")
        out = mwe.enrich({"rows": [{"symbol": "AAA", "open_0915": 100.0, "day_high": 105.0, "day_low": 99.0}]}, root, date(2026, 10, 9))
        r = out["rows"][0]
        self.assertEqual((r["high_time"], r["low_time"]), ("10:05", "11:30"))
        self.assertEqual((r["high_from_open_pct"], r["low_from_open_pct"]), (5.0, -1.0))

    def test_spike_between_readings_is_marked_approximate(self):
        root, _ = self._root("2026-10-09T10:00:00+05:30,AAA,100,1\n")
        r = mwe.enrich({"rows": [{"symbol": "AAA", "open_0915": 100.0, "day_high": 103.0, "day_low": 100.0}]}, root, date(2026, 10, 9))["rows"][0]
        self.assertEqual(r["high_time"], "~10:00")

    def test_reads_new_lines_incrementally_and_missing_file_is_safe(self):
        root, f = self._root("2026-10-09T09:20:00+05:30,AAA,100,1\n")
        row = {"symbol": "AAA", "open_0915": 100.0, "day_high": 110.0, "day_low": 100.0}
        mwe.enrich({"rows": [dict(row)]}, root, date(2026, 10, 9))
        with f.open("a", encoding="utf-8") as h:
            h.write("2026-10-09T09:45:00+05:30,AAA,110,1\n")
        r = mwe.enrich({"rows": [dict(row)]}, root, date(2026, 10, 9))["rows"][0]
        self.assertEqual(r["high_time"], "09:45")
        gone = mwe.enrich({"rows": [dict(row)]}, Path(tempfile.gettempdir(), "nope_aplus"), date(2026, 10, 9))["rows"][0]
        self.assertEqual(gone["high_time"], "")


if __name__ == "__main__":
    unittest.main()
