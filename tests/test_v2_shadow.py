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

    def test_established_trend_scenario_is_logged_and_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            when = datetime(2026, 10, 8, 10, 0, tzinfo=IST)
            c = SimpleNamespace(symbol="AAA", direction="BULLISH", ltp=100.0, stage="S", setup_family="ESTABLISHED_TREND")
            v2_shadow.log_new([c], RANK, when, set(), root / "data" / "shadow_v2", scenario="est_trend")
            (root / "data" / "missed_opportunities" / "2026-10-08").mkdir(parents=True)
            opts = [{"symbol": "AAA", "dir": "BULLISH", "kind": "ATM", "fate": "V2_BLOCKED:x", "close": 8.0, "best": 31.0}]
            Path(root, "data", "missed_opportunities", "2026-10-08", "option_returns.json").write_text(json.dumps(opts), encoding="utf-8")
            text = v2_shadow.report(root).read_text(encoding="utf-8")
            self.assertIn("Established-trend setups V2 blocked", text)
            self.assertIn("before the 3-per-side cap):** n=1", text)

    def test_loosened_bounce_limit_lets_a_small_bounce_through_and_reports_it(self) -> None:
        from stock_selection_v2 import V2GateConfig, evaluate_entry_ready

        c = SimpleNamespace(symbol="BBB", direction="BEARISH", stage="S", setup_family="X", move_from_0915_open_percent=-2.0, recent_move_5m_percent=0.20,
                            recent_move_10m_percent=-0.3, recent_move_15m_percent=-0.5, completed_5m_bars=6, fresh_15m_high=False, fresh_15m_low=True,
                            relative_volume=3.0, recent_relative_volume_15m=2.0, tape_volume_acceleration_5m=1.0, tape_volume_acceleration_15m=1.0,
                            trend_retention_percent=80.0)
        when = datetime(2026, 10, 21, 10, 0, tzinfo=IST)
        ranking = {"top_up": [], "top_down": [{"symbol": "BBB", "v2_rank": 1, "from_open_pct": -2.0}]}
        live, blocked = evaluate_entry_ready(candidates=[c], mover_ranking=ranking, now=when, config=V2GateConfig())
        self.assertEqual(len(live), 0)                                              # the stock bounced 0.20% against the short: live rule blocks it
        self.assertTrue(any("CURRENT_5M_REVERSING" in r for r in blocked[0]["reasons"]))
        loose, _ = evaluate_entry_ready(candidates=[c], mover_ranking=ranking, now=when, config=V2GateConfig(maximum_opposing_5m_pct=0.30))
        self.assertEqual(len(loose), 1)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            v2_shadow.log_new(loose, ranking, when, set(), root / "data" / "shadow_v2", scenario="bounce30")
            (root / "data" / "missed_opportunities" / "2026-10-21").mkdir(parents=True)
            opts = [{"symbol": "BBB", "dir": "BEARISH", "kind": "ATM", "fate": "V2_BLOCKED:x", "close": 20.0, "best": 60.0}]
            Path(root, "data", "missed_opportunities", "2026-10-21", "option_returns.json").write_text(json.dumps(opts), encoding="utf-8")
            text = v2_shadow.report(root).read_text(encoding="utf-8")
            self.assertIn("5m bounce limit loosened to 0.30%:** n=1", text)


if __name__ == "__main__":
    unittest.main()
