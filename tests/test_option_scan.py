import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

import option_scan as osn


def stock(start, path):
    closes = (list(path) + [path[-1]] * 48)[:48]
    opens = [start] + closes[:-1]
    return {"minute": [555 + 5 * i for i in range(48)], "open": opens, "close": closes,
            "high": [max(o, c) * 1.001 for o, c in zip(opens, closes)], "low": [min(o, c) * 0.999 for o, c in zip(opens, closes)], "volume": [1000.0] * 48}


def master():
    rows = []
    for sid, s in ((1, "UP"), (3, "DOWN"), (5, "FLAT")):
        for k, side in ((0, "CE"), (1, "PE")):
            rows.append({"SECURITY_ID": sid + k, "INSTRUMENT": "OPTSTK", "UNDERLYING_SYMBOL": s, "SM_EXPIRY_DATE": "2026-10-27", "STRIKE_PRICE": 100.0, "OPTION_TYPE": side})
    return pd.DataFrame(rows)


def fetch(sid, day):
    # odd ids are calls (rise), even ids are puts (rise too) - enough to check the plumbing
    return [(555 + 5 * i, 10, 10 + i * 0.5, 9.5, 10 + i * 0.4) for i in range(40)]


class OptionScanTests(unittest.TestCase):
    def test_path_stats(self):
        bars = [(560 + 5 * i, 10, 10 + i, 9.9, 10 + i * 0.5) for i in range(12)]
        ps = osn.path_stats(bars, 580)
        self.assertGreater(ps["best"], 0)
        self.assertFalse(ps["stop_first"])
        self.assertEqual(osn.path_stats(bars, 100), {})

    def test_scan_day_direction_outcome_and_entries(self):
        syms = {"UP": stock(100, [100.6, 101.2, 102, 103, 104]), "DOWN": stock(100, [99.5, 98.8, 98, 97, 96]), "FLAT": stock(100, [100.1, 100.0, 100.1])}
        sigs = [{"symbol": "UP", "dir": "BULLISH", "fate": "A_PLUS:late_vwap_extension", "ready": "09:50", "kind": "ATM"}]
        rows = {r["symbol"]: r for r in osn.scan_day("2026-10-15", syms, {}, sigs, {("DOWN", "BEARISH")}, master(), fetch)}
        self.assertEqual(rows["UP"]["dir"], "BULLISH")
        self.assertTrue(rows["UP"]["contract"].endswith("CE"))
        self.assertEqual(rows["UP"]["outcome"], "A_PLUS:late_vwap_extension")
        self.assertEqual(rows["DOWN"]["dir"], "BEARISH")
        self.assertEqual(rows["DOWN"]["outcome"], "TRADED")
        self.assertEqual(rows["FLAT"]["outcome"], "NO_SIGNAL")
        self.assertIn("a_best_pct", rows["UP"])
        self.assertIn("b_best_pct", rows["UP"])                      # reached +1% from the open
        self.assertEqual(rows["UP"]["mark1"], "09:20")
        self.assertNotIn("b_best_pct", rows["FLAT"])                 # never reached +1%: only the 09:20 entry

    def test_run_and_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            syms = {"UP": stock(100, [100.6, 101.2, 102, 103, 104]), "DOWN": stock(100, [99.5, 98.8, 98, 97, 96])}
            path = osn.run("2026-10-15", root, syms, fetch, master())
            self.assertTrue(path.exists())
            md = (root / "data" / "shadow_rules" / "option_scan.md").read_text(encoding="utf-8")
            self.assertIn("Full-universe option scan", md)
            self.assertIn("Entry 09:20", md)
            self.assertIsNone(osn.run("2026-10-01", root))


if __name__ == "__main__":
    unittest.main()
