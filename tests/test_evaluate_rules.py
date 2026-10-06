from __future__ import annotations

import unittest
from datetime import time as clock_time

from evaluate_rules import RULESETS, metrics, prepare


def _trade(tid: str, entry: float, exit_: float, qty: int = 100, spread: float = 1.0, hhmm: str = "10:00", ask: float | None = None):
    return {
        "paper_trade_id": tid, "status": "CLOSED", "entry_price": entry, "exit_price": exit_, "quantity": qty,
        "spread_percent": spread, "ask": entry - 0.1 if ask is None else ask,
        "entry_time": f"2026-09-10T{hhmm}:00+05:30", "estimated_costs": 0, "gross_pnl": (exit_ - entry) * qty,
    }


class PrepareTests(unittest.TestCase):
    def test_filters_open_old_and_rounded_fill_trades(self) -> None:
        trades = [
            _trade("PT-20260910-100000-AAA-1", 31.3, 33.0),
            {**_trade("PT-20260910-100000-BBB-2", 31.3, 33.0), "status": "OPEN"},
            _trade("PT-20260819-100000-CCC-3", 31.3, 33.0),                  # before --since
            _trade("PT-20260910-100000-DDD-4", 15.0, 12.4, ask=12.5),        # rounded-up fake fill
        ]
        out = prepare(trades, "2026-08-28")
        self.assertEqual([t["paper_trade_id"] for t in out], ["PT-20260910-100000-AAA-1"])

    def test_costs_are_applied_when_recorded_as_zero(self) -> None:
        t = prepare([_trade("PT-20260910-100000-AAA-1", 101.3, 110.2)], "2026-08-28")[0]
        self.assertGreater(t["_costs"], 40.0)
        self.assertAlmostEqual(t["_net"], t["_gross"] - t["_costs"], places=6)
        self.assertLess(t["_net"], t["_gross"])


class MetricsTests(unittest.TestCase):
    def test_metrics_basic(self) -> None:
        rows = [{"_net": x} for x in (100, -50, 100, -50)]
        m = metrics(rows, resamples=200)
        self.assertEqual((m["n"], m["win%"], m["net"]), (4, 50.0, 100))
        self.assertEqual(m["PF"], 2.0)
        self.assertEqual(m["maxDD"], 50)

    def test_empty_is_safe(self) -> None:
        self.assertEqual(metrics([])["n"], 0)

    def test_rule_predicates(self) -> None:
        early = {"_entry_clock": clock_time(10, 0), "_spread": 1.0, "_entry": 20.0}
        late = {"_entry_clock": clock_time(14, 0), "_spread": 1.0, "_entry": 20.0}
        wide = {"_entry_clock": clock_time(10, 0), "_spread": 2.5, "_entry": 20.0}
        rule = RULESETS["before 13:00 AND spread <= 2.0%"]
        self.assertTrue(rule(early))
        self.assertFalse(rule(late))
        self.assertFalse(rule(wide))


if __name__ == "__main__":
    unittest.main()
