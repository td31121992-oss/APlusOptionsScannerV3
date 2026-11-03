import json
import tempfile
import unittest
from pathlib import Path

import early_movers as em


def stock(start, path, burst_at=None):
    closes = (list(path) + [path[-1]] * 48)[:48]
    opens = [start] + closes[:-1]
    vol = [1000.0] * 48
    if burst_at is not None:
        vol[burst_at] = 5000.0
    return {"minute": [555 + 5 * i for i in range(48)], "open": opens, "close": closes,
            "high": [max(o, c) * 1.0005 for o, c in zip(opens, closes)], "low": [min(o, c) * 0.9995 for o, c in zip(opens, closes)], "volume": vol}


def tape():
    up = [100.3, 100.6, 101.0, 101.3, 101.6]
    return {"A": stock(100, up, 3), "B": stock(100, up, 3), "C": stock(100, up, 3),            # a rising sector with a burst bar
            "D": stock(100, up),                                                                 # no burst
            "E": stock(100, [99.5, 99.0, 98.7, 98.5], 3), "F": stock(100, [99.5, 99.0, 98.7, 98.5], 3), "G": stock(100, [99.5, 99.0, 98.7, 98.5], 3)}


SECT = {"A": "UP", "B": "UP", "C": "UP", "D": "UP2", "E": "DOWN", "F": "DOWN", "G": "DOWN"}


class EarlyMoverTests(unittest.TestCase):
    def test_signals_need_move_burst_and_sector(self):
        got = {r["symbol"]: r for r in em.find_signals(tape(), SECT)}
        self.assertEqual(set(got), {"A", "B", "C", "E", "F", "G"})                 # D has no burst and its sector has too few stocks
        self.assertEqual(got["A"]["dir"], "BULLISH")
        self.assertEqual(got["E"]["dir"], "BEARISH")
        self.assertGreaterEqual(got["A"]["burst_x"], 3.0)
        self.assertTrue(1.0 <= abs(got["A"]["move_pct"]) <= 2.5)

    def test_too_extended_stock_is_skipped(self):
        syms = tape()
        syms["A"] = stock(100, [101.5, 103.0, 104.0], 3)                           # already +3%+ before any decision point it qualifies at
        self.assertNotIn("A", {r["symbol"] for r in em.find_signals(syms, SECT)})

    def test_stock_after_direction(self):
        d = stock(100, [100.3 + 0.1 * i for i in range(48)])
        fwd, end = em.stock_after(d, 600, True)
        self.assertGreater(fwd, 0)
        self.assertGreater(end, 0)
        fwd2, end2 = em.stock_after(d, 600, False)
        self.assertLess(fwd2, 0)

    def test_option_outcome_uses_the_right_side(self):
        import pandas as pd
        master = pd.DataFrame([{"SECURITY_ID": 1, "INSTRUMENT": "OPTSTK", "UNDERLYING_SYMBOL": "A", "SM_EXPIRY_DATE": "2026-10-27", "STRIKE_PRICE": 100.0, "OPTION_TYPE": "CE"},
                               {"SECURITY_ID": 2, "INSTRUMENT": "OPTSTK", "UNDERLYING_SYMBOL": "A", "SM_EXPIRY_DATE": "2026-10-27", "STRIKE_PRICE": 100.0, "OPTION_TYPE": "PE"}])
        seen = []

        def fetch(sid, day):
            seen.append(sid)
            return [(560 + 5 * i, 10, 10 + i, 9, 10 + i * 0.5) for i in range(12)]
        r = em.option_outcome("A", 580, 100.0, "2026-10-15", True, fetch, master)
        self.assertEqual(seen, [1])
        self.assertTrue(r["contract"].endswith("CE"))
        self.assertGreater(r["opt_best_pct"], 0)
        em.option_outcome("A", 580, 100.0, "2026-10-15", False, fetch, master)
        self.assertEqual(seen, [1, 2])

    def test_run_writes_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cd = root / "data" / "pattern_log" / "candles"
            cd.mkdir(parents=True)
            (cd / "2026-10-15.json").write_text(json.dumps({"symbols": tape()}), encoding="utf-8")
            wd = root / "data" / "reports"
            wd.mkdir(parents=True)
            (wd / "fno_market_watch_latest.json").write_text(json.dumps({"rows": [{"symbol": s, "sector": k} for s, k in SECT.items()]}), encoding="utf-8")
            path = em.run("2026-10-15", root, with_options=False)
            self.assertTrue(path.exists())
            self.assertIn("Early-mover shadow list", (root / "data" / "shadow_rules" / "early_movers.md").read_text(encoding="utf-8"))
            self.assertIsNone(em.run("2026-10-01", root))

    def test_verdict(self):
        self.assertFalse(em.verdict([])[0])
        rows = [{"day": f"2026-10-0{1 + i % 6}", "opt_close_pct": "8.0"} for i in range(40)]
        self.assertTrue(em.verdict(rows)[0])


if __name__ == "__main__":
    unittest.main()
