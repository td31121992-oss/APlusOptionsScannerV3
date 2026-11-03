import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

import sector_rrg as rrg
import trade_journal as tj


def series(n, start, f):
    d0 = date(2026, 8, 1)
    days = [(d0 + timedelta(days=i)).isoformat() for i in range(n)]
    return {d: f(i, start) for i, d in enumerate(days)}


def closes(n=60):
    bench = series(n, 20000.0, lambda i, s: s + i * 10)                      # market drifts up slowly
    strong = series(n, 30000.0, lambda i, s: s * (1 + 0.004 * i))             # steadily outperforming, accelerating at the end
    weak = series(n, 25000.0, lambda i, s: s * (1 - 0.002 * i))               # steadily underperforming
    return {"NIFTY 50": bench, "IT": strong, "METAL": weak}


class ComputeTests(unittest.TestCase):
    def test_quadrants(self):
        self.assertEqual(rrg.quadrant(101, 101), "LEADING")
        self.assertEqual(rrg.quadrant(101, 99), "WEAKENING")
        self.assertEqual(rrg.quadrant(99, 101), "IMPROVING")
        self.assertEqual(rrg.quadrant(99, 99), "LAGGING")

    def test_compute_ranks_and_tails(self):
        out = rrg.compute(closes())
        self.assertTrue(out["ok"])
        names = [r["sector"] for r in out["rows"]]
        self.assertEqual(sorted(names), ["IT", "METAL"])                         # benchmark itself is not a row
        it = next(r for r in out["rows"] if r["sector"] == "IT")
        metal = next(r for r in out["rows"] if r["sector"] == "METAL")
        self.assertGreater(it["ratio"], metal["ratio"])
        self.assertEqual(len(it["tail"]), 5)
        self.assertGreater(it["rel10"], 0)
        self.assertLess(metal["rel10"], 0)
        self.assertEqual(out["asof"], max(closes()["IT"]))

    def test_too_little_history_gives_no_rows(self):
        self.assertFalse(rrg.compute({"NIFTY 50": series(8, 100, lambda i, s: s + i), "IT": series(8, 100, lambda i, s: s + i)})["ok"])


class TagTests(unittest.TestCase):
    def _cache(self, tmp, asof=None, ratio=102.0):
        path = Path(tmp) / "sector_rrg.json"
        path.write_text(json.dumps({"ok": True, "asof": asof or date.today().isoformat(), "rows": [
            {"sector": "IT", "ratio": ratio, "momentum": 101.0, "quadrant": "LEADING", "tail": []},
            {"sector": "METAL", "ratio": 97.0, "momentum": 99.0, "quadrant": "LAGGING", "tail": []}]}))
        return path

    ROWS = [{"symbol": "TCS", "sector": "IT"}, {"symbol": "TATASTEEL", "sector": "Metals"}, {"symbol": "ZZZ", "sector": "Chemicals"}]

    def test_call_in_leading_sector_is_aligned_put_is_not(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = self._cache(tmp)
            call = rrg.tags_for("TCS", "BULLISH", self.ROWS, c)
            put = rrg.tags_for("TCS", "BEARISH", self.ROWS, c)
            self.assertEqual((call["rrg_index"], call["rrg_quadrant"], call["rrg_aligned"]), ("IT", "LEADING", True))
            self.assertFalse(put["rrg_aligned"])
            weak_put = rrg.tags_for("TATASTEEL", "BEARISH", self.ROWS, c)
            self.assertTrue(weak_put["rrg_aligned"])                                     # put in a lagging sector is WITH its weakness

    def test_unmapped_sector_stale_or_missing_cache_never_raise(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = self._cache(tmp)
            self.assertEqual(rrg.tags_for("ZZZ", "BULLISH", self.ROWS, c), {"rrg_sector": "Chemicals"})
            self.assertEqual(rrg.tags_for("NOPE", "BULLISH", self.ROWS, c), {})
            stale = self._cache(tmp, asof=(date.today() - timedelta(days=30)).isoformat())
            self.assertEqual(rrg.tags_for("TCS", "BULLISH", self.ROWS, stale), {"rrg_sector": "IT"})
            self.assertEqual(rrg.tags_for("TCS", "BULLISH", self.ROWS, Path(tmp) / "missing.json"), {"rrg_sector": "IT"})

    def test_refresh_writes_cache_atomically(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = rrg.refresh(Path(tmp), fetch=lambda root: closes(), cache=Path(tmp) / "c.json")
            self.assertTrue(out["ok"] and (Path(tmp) / "c.json").exists())
            self.assertEqual(rrg.load_cache(Path(tmp) / "c.json")["asof"], out["asof"])

    def test_journal_text(self):
        t = {"rrg_sector": "IT", "rrg_index": "IT", "rrg_quadrant": "LEADING", "rrg_ratio": 102.2, "rrg_momentum": 101.2,
             "rrg_asof": "2026-10-13", "rrg_aligned": True}
        self.assertIn("LEADING", tj._rrg_text(t))
        self.assertIn("WITH the sector's strength", tj._rrg_text(t))
        self.assertIn("AGAINST", tj._rrg_text({**t, "rrg_aligned": False}))
        self.assertEqual(tj._rrg_text({}), "")


if __name__ == "__main__":
    unittest.main()
