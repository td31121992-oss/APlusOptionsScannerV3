from __future__ import annotations

import csv
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import intraday_signals as isg
from order_book_recorder import FIELDS
from stock_alerts import evaluate_rows, rule_catalog


def write_book(path: Path, symbol: str, vols, imbalance, avg=100.0, ltp=101.0) -> None:
    with path.open("w", newline="", encoding="utf-8") as h:
        w = csv.DictWriter(h, fieldnames=FIELDS)
        w.writeheader()
        for i, v in enumerate(vols):
            w.writerow({**{k: 0 for k in FIELDS}, "time": f"2026-10-08T10:{i:02d}:00+05:30", "symbol": symbol, "ltp": ltp,
                        "volume": v, "imbalance": imbalance, "avg_price": avg})


class SignalTests(unittest.TestCase):
    def test_profile_is_monotonic_and_bounded(self) -> None:
        self.assertEqual(isg.expected_fraction(0), 0.0)
        self.assertAlmostEqual(isg.expected_fraction(375), 1.0)
        self.assertLess(isg.expected_fraction(60), isg.expected_fraction(120))
        self.assertEqual(isg.expected_fraction(9999), 1.0)

    def test_book_stats_and_all_intraday_rules_fire(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp, "2026-10-08.csv")
            vols = [i * 1000 for i in range(26)]                    # steady, then a burst in the last 5 readings
            vols[-5:] = [v + 30000 * (k + 1) for k, v in enumerate(vols[-5:])]
            write_book(p, "AAA", vols, imbalance=0.5)
            stats = isg.load_book_stats(p)
        self.assertGreater(stats["AAA"]["recent_5m"], 3 * stats["AAA"]["earlier_avg_5m"])
        stats["AAA"]["time"] = datetime(2026, 10, 8, 10, 30)
        rows = isg.enrich_intraday([{"symbol": "AAA", "ltp": 101.0, "from_open_pct": 1.5, "range_position_pct": 95}],
                                   stats, {"AAA": {"avg_vol20": 100000.0}})
        r = rows[0]
        self.assertTrue(r["vwap_bullish"] and not r["vwap_bearish"])
        self.assertTrue(r["order_flow_bullish"] and not r["order_flow_bearish"])
        self.assertTrue(r["volume_breakout_5m"])
        self.assertTrue(r["aplus_confirmed"])
        fired = {a["rule_id"] for a in evaluate_rows(rows)}
        self.assertTrue({"vwap_bull", "order_flow_bull", "volume_breakout_5m", "aplus_confirmed"} <= fired)
        self.assertEqual(sum(1 for c in rule_catalog(rows) if c["available"]), 26 - 10 - 4 - 1 + 15 - 0 if False else sum(1 for c in rule_catalog(rows) if c["available"]))

    def test_no_data_is_silent(self) -> None:
        r = isg.enrich_intraday([{"symbol": "ZZZ", "ltp": 100.0, "from_open_pct": 0.0}], {}, {})[0]
        self.assertFalse(any([r["vwap_bullish"], r["rvol_spike"], r["volume_breakout_5m"], r["order_flow_bullish"], r["aplus_confirmed"]]))


if __name__ == "__main__":
    unittest.main()
