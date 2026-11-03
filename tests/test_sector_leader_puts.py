import json
import tempfile
import unittest
from pathlib import Path

import sector_groups as sg
import sector_leader_puts as sl


def candles(first_open, fall_pct, n=8):
    minute = [555 + 5 * i for i in range(n)]
    close = [first_open * (1 + fall_pct / 100.0 * (i + 1) / n) for i in range(n)]
    return {"minute": minute, "open": [first_open] + close[:-1], "high": [first_open] * n, "low": close, "close": close, "volume": [1000.0] * n}


class SectorLeaderTests(unittest.TestCase):
    def test_fine_sector_splits_financials_only(self):
        self.assertEqual(sg.fine_sector("HDFCLIFE", "Banking/Financial Services"), "Insurance")
        self.assertEqual(sg.fine_sector("BSE", "Banking/Financial Services"), "Capital Markets")
        self.assertEqual(sg.fine_sector("GODREJPROP", "Banking/Financial Services"), "Realty")
        self.assertEqual(sg.fine_sector("SBIN", "Banking/Financial Services"), "Banks")
        self.assertEqual(sg.fine_sector("TCS", "IT"), "IT")
        self.assertEqual(sg.fine_sector("UNKNOWNFIN", "Banking/Financial Services"), "Banking/Financial Services")

    def test_only_falling_sector_leaders_listed(self):
        syms = {"A": candles(100, -3.0), "B": candles(100, -2.0), "C": candles(100, -1.0), "D": candles(100, -0.6),
                "X": candles(100, 1.0), "Y": candles(100, 1.2), "Z": candles(100, 0.8)}
        secs = {"A": "Banks", "B": "Banks", "C": "Banks", "D": "Banks", "X": "IT", "Y": "IT", "Z": "IT"}
        got = {r["symbol"]: r for r in sl.find_signals(syms, secs)}
        self.assertEqual(set(got), {"A", "B", "C"})                      # D is 4th, IT is rising
        self.assertEqual(got["A"]["rank"], 1)
        self.assertEqual(got["A"]["sector"], "Banks")
        self.assertLessEqual(got["A"]["sector_move"], -0.5)

    def test_small_sector_ignored(self):
        syms = {"A": candles(100, -3.0), "B": candles(100, -2.0)}
        self.assertEqual(sl.find_signals(syms, {"A": "Banks", "B": "Banks"}), [])

    def test_run_writes_csv_and_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cd = root / "data" / "pattern_log" / "candles"
            cd.mkdir(parents=True)
            syms = {"A": candles(100, -3.0), "B": candles(100, -2.0), "C": candles(100, -1.0)}
            (cd / "2026-10-15.json").write_text(json.dumps({"day": "2026-10-15", "symbols": syms}), encoding="utf-8")
            wd = root / "data" / "reports"
            wd.mkdir(parents=True)
            (wd / "fno_market_watch_latest.json").write_text(json.dumps({"rows": [{"symbol": s, "sector": "IT"} for s in syms]}), encoding="utf-8")
            path = sl.run("2026-10-15", root, with_options=False)
            self.assertTrue(path.exists())
            self.assertIn("Falling-sector put leaders", (root / "data" / "shadow_rules" / "sector_leader_puts.md").read_text(encoding="utf-8"))
            self.assertIsNone(sl.run("2026-10-01", root))

    def test_verdict_bar(self):
        self.assertFalse(sl.verdict([])[0])
        rows = [{"day": f"2026-10-0{1 + i % 6}", "opt_close_pct": "8.0"} for i in range(40)]
        self.assertTrue(sl.verdict(rows)[0])
        one_day = [{"day": "2026-10-01", "opt_close_pct": "8.0"} for _ in range(40)]
        self.assertFalse(sl.verdict(one_day)[0])


if __name__ == "__main__":
    unittest.main()
