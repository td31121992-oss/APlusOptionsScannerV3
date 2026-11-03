import json
import tempfile
import unittest
from pathlib import Path

import big_movers_review as bm


def stock(start, path):
    """48 five-minute bars from 09:15; `path` = list of closes (repeated/padded to 48 bars)."""
    closes = (list(path) + [path[-1]] * 48)[:48]
    opens = [start] + closes[:-1]
    return {"minute": [555 + 5 * i for i in range(48)], "open": opens, "close": closes,
            "high": [max(o, c) * 1.0005 for o, c in zip(opens, closes)], "low": [min(o, c) * 0.9995 for o, c in zip(opens, closes)], "volume": [1000.0] * 48}


class BigMoverTests(unittest.TestCase):
    def test_finds_up_and_down_movers_and_marks(self):
        syms = {"UP": stock(100, [100.5, 101.2, 102.1, 103.5, 104.0]), "DOWN": stock(100, [99.5, 98.8, 97.5, 96.0]), "FLAT": stock(100, [100.2, 100.4, 100.1])}
        got = {r["symbol"]: r for r in bm.find_movers(syms)}
        self.assertEqual(set(got), {"UP", "DOWN"})
        self.assertEqual(got["UP"]["dir"], "BULLISH")
        self.assertEqual(got["UP"]["mark1"], "09:20")             # second bar (09:20) is the first close at +1%
        self.assertEqual(got["UP"]["mark2"], "09:25")             # third bar closes at +2.1%
        self.assertEqual(got["DOWN"]["dir"], "BEARISH")
        self.assertGreater(got["UP"]["left_after_1"], 2.5)

    def test_classify_outcomes_and_lag(self):
        movers = [{"symbol": "A", "dir": "BULLISH", "move_pct": 4, "_mark1_min": 560, "mark1": "09:20", "left_after_1": 3},
                  {"symbol": "B", "dir": "BULLISH", "move_pct": 4, "_mark1_min": 560, "mark1": "09:20", "left_after_1": 3},
                  {"symbol": "C", "dir": "BEARISH", "move_pct": 4, "_mark1_min": 570, "mark1": "09:30", "left_after_1": 3},
                  {"symbol": "D", "dir": "BEARISH", "move_pct": 4, "_mark1_min": 570, "mark1": "09:30", "left_after_1": 3}]
        sigs = [{"symbol": "A", "dir": "BULLISH", "fate": "A_PLUS:late_vwap_extension", "ready": "09:50"},
                {"symbol": "B", "dir": "BULLISH", "fate": "TRADED", "ready": "09:25"},
                {"symbol": "C", "dir": "BEARISH", "fate": "V2_BLOCKED", "ready": "09:28"}]
        rows = {r["symbol"]: r for r in bm.classify(movers, sigs, set())}
        self.assertEqual(rows["A"]["outcome"], "A_PLUS:late_vwap_extension")
        self.assertEqual(rows["A"]["lag_min"], 30)
        self.assertEqual(rows["B"]["traded"], 1)
        self.assertEqual(rows["C"]["lag_min"], -2)
        self.assertEqual(rows["D"]["outcome"], "NO_SIGNAL")
        self.assertEqual(bm.classify(movers[3:], [], {("D", "BEARISH")})[0]["traded"], 1)

    def test_run_and_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cd = root / "data" / "pattern_log" / "candles"
            cd.mkdir(parents=True)
            syms = {"UP": stock(100, [100.5, 101.2, 102.1, 103.5, 104.0]), "FLAT": stock(100, [100.2])}
            (cd / "2026-10-15.json").write_text(json.dumps({"symbols": syms}), encoding="utf-8")
            path = bm.run("2026-10-15", root)
            self.assertTrue(path.exists())
            md = (root / "data" / "shadow_rules" / "big_movers.md").read_text(encoding="utf-8")
            self.assertIn("Big movers we did not trade", md)
            self.assertIn("NO_SIGNAL", md)
            self.assertIsNone(bm.run("2026-10-01", root))


if __name__ == "__main__":
    unittest.main()
