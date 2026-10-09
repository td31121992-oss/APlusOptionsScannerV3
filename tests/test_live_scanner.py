import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

import live_scanner as ls

HEAD = "time,symbol,ltp,volume\n"


def line(hhmm, sym, ltp, vol):
    return f"2026-10-09T{hhmm}:00+05:30,{sym},{ltp},{vol}\n"


class LiveScannerTests(unittest.TestCase):
    def _run(self, body, ind=None):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / "data" / "order_book").mkdir(parents=True)
        (root / "data" / "reports").mkdir(parents=True)
        (root / "data" / "order_book" / "2026-10-09.csv").write_text(HEAD + body, encoding="utf-8")
        (root / "data" / "reports" / "daily_indicators.json").write_text(json.dumps({"symbols": ind or {}}), encoding="utf-8")
        return root

    def test_day_high_low_and_previous_day_breaks(self):
        body = "".join([line("09:20", "AAA", 100, 10), line("09:21", "AAA", 101, 20), line("09:22", "AAA", 99, 30), line("09:23", "AAA", 98, 40)])
        root = self._run(body, {"AAA": {"pdh": 100.5, "pdl": 98.5}})
        out = ls.payload("ALL", 50, root, date(2026, 10, 9))
        kinds = {e["kind"] for e in out["events"]}
        self.assertTrue({"DAY_HIGH", "PDH_BREAK", "DAY_LOW", "PDL_BREAK"} <= kinds)
        self.assertEqual(out["counts"]["BULLISH"], 2)
        self.assertEqual(out["events"][0]["time"], "09:23")           # newest first

    def test_opening_minutes_are_ignored(self):
        root = self._run(line("09:16", "AAA", 100, 1) + line("09:17", "AAA", 102, 2))
        self.assertEqual(ls.payload("ALL", 50, root, date(2026, 10, 9))["total"], 0)

    def test_rise_event_and_group_filter(self):
        rows = [line(f"09:{20 + i}", "AAA", 100 if i < 8 else 102, 1000 * i) for i in range(12)]
        root = self._run("".join(rows))
        out = ls.payload("RISEFALL", 100, root, date(2026, 10, 9))
        self.assertTrue(out["events"] and all(e["kind"] in ("RISE", "FALL") for e in out["events"]))

    def test_missing_file_is_safe(self):
        self.assertTrue(ls.payload("ALL", 10, Path(tempfile.gettempdir(), "no_aplus_dir"), date(2026, 10, 9))["ok"])


if __name__ == "__main__":
    unittest.main()
