import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

import rupee_report as rr


def trade(pid, day="2026-10-26", status="CLOSED", entry=10.0, peak=12.0, qty=1000, net=500.0, direction="BULLISH", costs=100.0, **kw):
    t = {"paper_trade_id": pid, "status": status, "symbol": "AAA", "direction": direction, "entry_time": f"{day}T10:00:00+05:30", "highest_option_price_at": f"{day}T10:20:00+05:30", "entry_price": entry,
         "highest_option_price": peak, "lowest_option_price": entry - 1.0, "quantity": qty, "net_pnl": net, "estimated_costs": costs, "exit_price": entry + 0.5, "exit_reason": "OPTION_STOP_LOSS",
         "unrealized_pnl": 300.0, "last_option_price": 10.3}
    t.update(kw)
    return t


class RowTests(unittest.TestCase):
    def test_rupees_not_percent(self):
        r = rr.trade_row(trade("1"))
        self.assertEqual((r["peak_rs"], r["final_rs"], r["gave_back"], r["worst_rs"], r["capital"], r["minutes_to_peak"], r["side"]), (2000, 500, 1500, -1000, 10000, 20.0, "CALL"))
        o = rr.trade_row(trade("2", status="OPEN", direction="BEARISH"))
        self.assertEqual((o["status"], o["final_rs"], o["side"], o["now_or_exit"]), ("OPEN", 300, "PUT", 10.3))      # an open trade shows its open profit and the last price
        self.assertIsNone(rr.trade_row(trade("3", qty=0)))
        self.assertIsNone(rr.trade_row(trade("4", entry=0)))
        self.assertIsNone(rr.trade_row({"paper_trade_id": "5"}))

    def test_peak_below_entry_is_a_negative_peak(self):
        r = rr.trade_row(trade("1", peak=9.5, net=-2000.0))
        self.assertEqual((r["peak_rs"], r["gave_back"]), (-500, 1500))


class SummaryTests(unittest.TestCase):
    def rows(self):
        # peaks 2000 / 600 / 0 / 8000 (rupees); finals 500 / -1500 / -800 / 7000
        specs = [("a", 12.0, 500.0), ("b", 10.6, -1500.0), ("c", 10.0, -800.0), ("d", 18.0, 7000.0)]
        return [rr.trade_row(trade(i, peak=p, net=n)) for i, p, n in specs]

    def test_summary_and_thresholds(self):
        s = rr.summary(self.rows())
        self.assertEqual((s["n"], s["closed"], s["peak_median"], s["banked_total"], s["offered_total"]), (4, 4, 1300, 5200, 10600))
        self.assertEqual(s["reached"], {"500": 75, "1000": 50, "2000": 50, "3000": 25, "5000": 25})
        self.assertEqual((s["in_profit_pct"], s["lost_anyway_pct"]), (75, 33))                  # 3 of 4 were in profit at some point; 1 of those 3 closed at a loss
        self.assertEqual(s["gave_back_median"], 1500)

    def test_target_table_is_feasible_and_ignores_trades_that_never_got_there(self):
        t = {x["target"]: x for x in rr.summary(self.rows())["targets"]}
        self.assertEqual(t[0]["total"], 5200)
        # target 1000: a and d reach it (2000, 8000): 2 x (1000 - 100 costs); b (600 peak) and c (0) keep their real result: -1500 + -800
        self.assertEqual((t[1000]["total"], t[1000]["hit"]), (2 * 900 - 1500 - 800, 2))
        self.assertEqual(t[3000]["hit"], 1)                                                      # only d reached 3000
        self.assertEqual(t[3000]["total"], (3000 - 100) + 500 - 1500 - 800)

    def test_empty(self):
        self.assertEqual(rr.summary([]), {"n": 0})
        self.assertIn("No trades", rr.render("2026-10-26", []))


class FileTests(unittest.TestCase):
    def test_payload_report_and_dedupe(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data" / "reports").mkdir(parents=True)
            (root / "data" / "intraday_movement").mkdir(parents=True)
            hist = [trade("h1", day="2026-10-23", peak=13.0, net=1500.0), trade("h2", day="2026-10-23", peak=10.2, net=-600.0), trade("dup", day="2026-10-26", status="OPEN", net=0.0)]
            (root / "data" / "reports" / "paper_trade_history.json").write_text(json.dumps({"paper_trades": hist}), encoding="utf-8")
            (root / "data" / "intraday_movement" / "paper_trade_journal.json").write_text(json.dumps({"trades": [trade("dup", day="2026-10-26", status="CLOSED", net=-400.0, peak=11.0)]}), encoding="utf-8")
            p = rr.payload(root, date(2026, 10, 26))
            self.assertEqual((p["ok"], len(p["today"]), p["today"][0]["final_rs"], p["today"][0]["status"]), (True, 1, -400, "CLOSED"))     # the journal's newer copy replaces the history copy
            self.assertEqual(p["today_summary"], {"peaks": 1000, "final": -400, "n": 1})
            self.assertEqual([d["day"] for d in p["per_day"]], ["2026-10-23", "2026-10-26"])
            self.assertEqual(p["all"]["n"], 3)
            self.assertFalse(any(k.startswith("_") for k in p["today"][0]))                      # no private fields leak to the page
            rr.run("2026-10-26", root)
            md = (root / "data" / "reports" / "rupee_report" / "2026-10-26.md").read_text(encoding="utf-8")
            self.assertIn("Profit in rupees after entry", md)
            self.assertIn("| 10:00 | AAA | CALL | 10.00 | 11.00 |", md)
            self.assertTrue((root / "data" / "reports" / "rupee_report" / "2026-10-26.csv").exists())

    def test_no_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = rr.payload(Path(tmp), date(2026, 10, 26))
            self.assertEqual((p["today"], p["all"]), ([], {"n": 0}))


if __name__ == "__main__":
    unittest.main()
