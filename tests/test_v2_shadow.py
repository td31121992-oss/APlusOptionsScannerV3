from __future__ import annotations

import csv
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import v2_shadow

IST = ZoneInfo("Asia/Kolkata")
RANK = {"top_up": [{"symbol": "AAA", "v2_rank": 7, "from_open_pct": 1.2}], "top_down": [{"symbol": "BBB", "v2_rank": 9, "from_open_pct": -2.1}]}


class ShadowTests(unittest.TestCase):
    def test_logs_each_symbol_direction_once_per_day_with_rank(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            seen: set = set()
            when = datetime(2026, 10, 8, 10, 0, tzinfo=IST)
            c1 = SimpleNamespace(symbol="AAA", direction="BULLISH", ltp=100.0, stage="S", setup_family="F")
            c2 = SimpleNamespace(symbol="BBB", direction="BEARISH", ltp=50.0, stage="S", setup_family="F")
            self.assertEqual(v2_shadow.log_new([c1, c2], RANK, when, seen, Path(tmp)), 2)
            self.assertEqual(v2_shadow.log_new([c1, c2], RANK, when, seen, Path(tmp)), 0)       # same day: not repeated
            rows = list(csv.DictReader(Path(tmp, "2026-10-08.csv").open(encoding="utf-8")))
            self.assertEqual([(r["symbol"], r["top10_rank"]) for r in rows], [("AAA", "7"), ("BBB", "9")])
            self.assertEqual({r["scenario"] for r in rows}, {"top10"})

    def test_report_compares_extra_passes_with_the_rest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data" / "shadow_v2").mkdir(parents=True)
            (root / "data" / "missed_opportunities" / "2026-10-08").mkdir(parents=True)
            Path(root, "data", "shadow_v2", "2026-10-08.csv").write_text("time,symbol,direction\n10:00:00,AAA,BULLISH\n", encoding="utf-8")
            opts = [{"symbol": s, "dir": d, "kind": "ATM", "fate": f, "close": c, "best": b}
                    for s, d, f, c, b in (("AAA", "BULLISH", "V2_BLOCKED:x", 10.0, 35.0), ("CCC", "BEARISH", "V2_BLOCKED:y", -4.0, 5.0),
                                          ("DDD", "BEARISH", "TRADED", 6.0, 12.0))]
            Path(root, "data", "missed_opportunities", "2026-10-08", "option_returns.json").write_text(json.dumps(opts), encoding="utf-8")
            out = v2_shadow.report(root)
            text = out.read_text(encoding="utf-8")
            self.assertIn("**Extra top-10 passes:** n=1", text)
            self.assertIn("**Other V2-blocked:** n=1", text)
            self.assertIn("**Live trades:** n=1", text)
            self.assertIn("NO rank rule at all", text)
            self.assertIsNone(v2_shadow.report(Path(tmp, "empty")))


if __name__ == "__main__":
    unittest.main()
