from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

import missed_opportunities as mo

DAY = "2026-10-06"


def _cycle(base: Path, hhmmss: str, ltps: dict, ready: list, rejected: list, v2_blocked: list) -> None:
    rep = {
        "shortlists": {"ENTRY_READY": [{"symbol": s, "direction": d, "ltp": ltps[s], "stage": "X_ENTRY_READY"} for s, d in ready]},
        "aplus_selective_gate": {"rejected_symbols": [{"symbol": s, "direction": d, "status": st} for s, d, st in rejected]},
        "stock_selection_v2": {"blocked": [{"symbol": s, "direction": d} for s, d in v2_blocked], "passed_symbols": []},
        "fno_market_watch": {"rows": [{"symbol": s, "ltp": p} for s, p in ltps.items()]},
    }
    path = base / "data" / "reports" / f"intraday_movement_{DAY.replace('-', '')}_{hhmmss}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rep), encoding="utf-8")


def _make_day(base: Path) -> None:
    ready = [("AAA", "BULLISH"), ("BBB", "BEARISH"), ("CCC", "BULLISH"), ("DDD", "BULLISH")]
    _cycle(base, "093000", {"AAA": 100, "BBB": 200, "CCC": 50, "DDD": 80}, ready,
           rejected=[("BBB", "BEARISH", "A_PLUS_WAIT_LATE_VWAP_EXTENSION")], v2_blocked=[("CCC", "BULLISH")])
    _cycle(base, "120000", {"AAA": 102, "BBB": 199, "CCC": 49.5, "DDD": 82}, ready,
           rejected=[("BBB", "BEARISH", "A_PLUS_WAIT_LATE_VWAP_EXTENSION")], v2_blocked=[("CCC", "BULLISH")])
    _cycle(base, "152500", {"AAA": 103, "BBB": 198, "CCC": 49, "DDD": 84}, [], [], [])
    # AAA was traded
    hist = base / "data" / "reports" / "paper_trade_history.csv"
    with hist.open("w", newline="", encoding="utf-8") as h:
        w = csv.writer(h)
        w.writerow(["paper_trade_id", "symbol", "direction", "status"])
        w.writerow(["PT-20261006-093001-AAA-X1", "AAA", "BULLISH", "CLOSED"])
    # DDD failed conversion on the open-position limit
    log = base / "logs" / f"scanner.log.{DAY}"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(
        f"{DAY} 09:30:05 | INFO | x | MainThread | PAPER conversion audit symbol=DDD direction=BULLISH plan=FAIL safety=BLOCK "
        "option_error=SAFETY_BLOCKED: PORTFOLIO_RISK: Maximum open-position count has been reached\n", encoding="utf-8")


class AnalysisTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        _make_day(self.base)

    def test_days_and_cycle_loading(self) -> None:
        self.assertEqual(mo.report_days(self.base), [DAY])
        cycles = mo.load_cycles(DAY, self.base)
        self.assertEqual([c["time"] for c in cycles], ["09:30:00", "12:00:00", "15:25:00"])

    def test_fates_and_outcomes(self) -> None:
        r = mo.analyze_day(DAY, self.base)
        by = {s["symbol"]: s for s in r["signals"]}
        self.assertEqual(by["AAA"]["fate"], "TRADED")
        self.assertEqual(by["BBB"]["fate"], "A_PLUS:late_vwap_extension")
        self.assertEqual(by["CCC"]["fate"], "V2_BLOCKED")
        self.assertEqual(by["DDD"]["fate"], "CONVERSION_BLOCKED:open-position limit")
        # direction-signed moves from the first ready price to the last price
        self.assertAlmostEqual(by["AAA"]["close_pct"], 3.0, places=2)          # long, +3%
        self.assertAlmostEqual(by["BBB"]["close_pct"], 1.0, places=2)          # short, price fell 1% -> right
        self.assertAlmostEqual(by["CCC"]["close_pct"], -2.0, places=2)         # long, -2%
        self.assertAlmostEqual(by["CCC"]["worst_pct"], -2.0, places=2)
        self.assertAlmostEqual(by["DDD"]["best_pct"], 5.0, places=2)
        self.assertEqual(by["BBB"]["ready_cycles"], 2)

    def test_group_summary_compares_filters(self) -> None:
        r = mo.analyze_day(DAY, self.base)
        groups = {g["fate"]: g for g in r["by_group"]}
        self.assertEqual(set(groups), {"TRADED", "A_PLUS", "V2_BLOCKED", "CONVERSION_BLOCKED"})
        self.assertEqual(groups["V2_BLOCKED"]["right_at_close_pct"], 0.0)
        self.assertEqual(groups["CONVERSION_BLOCKED"]["right_at_close_pct"], 100.0)
        self.assertEqual(groups["V2_BLOCKED"]["went_1pct_against"], 100.0)
        overall = r["overall"][0]
        self.assertEqual(overall["n"], 4)
        self.assertEqual(overall["right_at_close_pct"], 75.0)

    def test_outputs_and_cumulative(self) -> None:
        r = mo.analyze_day(DAY, self.base)
        out_root = self.base / "out"
        folder = mo.write_day(r, out_root)
        for name in ("signals.csv", "summary.json", "report.md"):
            self.assertTrue((folder / name).exists(), name)
        text = (folder / "report.md").read_text(encoding="utf-8")
        self.assertIn("Missed opportunities - 2026-10-06", text)
        self.assertIn("Biggest missed winners", text)
        self.assertIn("DDD", text)                                       # the conversion-blocked winner is listed
        cum = mo.update_cumulative([r], out_root)
        self.assertEqual((cum["days"], cum["signals"]), ([DAY], 4))
        self.assertTrue((out_root / "cumulative.json").exists())

    def test_day_without_reports_is_empty_not_an_error(self) -> None:
        r = mo.analyze_day("2026-01-02", self.base)
        self.assertEqual((r["cycles"], r["signals"]), (0, []))


if __name__ == "__main__":
    unittest.main()
