import unittest
from datetime import datetime, timedelta

import home_page as hp

LIVE = datetime(2026, 11, 17, 11, 0, 0)            # a Tuesday inside market hours
SAT = datetime(2026, 11, 14, 11, 0, 0)


def run(ages, cycle_age=30, limit=0, fast=0, used=500, cap=1900, entries=None, now=LIVE):
    log = {"last_cycle": now - timedelta(seconds=cycle_age), "limit_errors_5m": limit, "fast_failures_1m": fast}
    return hp.health(now, ages, log, {"used": used, "cap": cap, "top": [{"who": "main.py", "calls": used}]}, entries if entries is not None else {"paused": False})


class HomeHealthTests(unittest.TestCase):
    def test_everything_fresh_is_ok(self):
        h = run([2, 5])
        self.assertEqual(h["level"], "ok")
        self.assertIn("All live", h["message"])

    def test_stale_prices_with_a_full_budget_say_why(self):
        h = run([400], used=1900, limit=5, fast=20)
        self.assertEqual(h["level"], "bad")
        self.assertIn("DATA STALE", h["message"])
        self.assertIn("allowance", h["message"])

    def test_stale_prices_alone_are_still_bad(self):
        h = run([200])
        self.assertEqual(h["level"], "bad")
        self.assertIn("DATA STALE", h["message"])

    def test_nearly_full_budget_with_fresh_prices_explains_the_risk(self):
        h = run([3], used=1850)
        self.assertEqual(h["level"], "bad")
        self.assertIn("still updating", h["message"])

    def test_warn_levels(self):
        self.assertEqual(run([30])["level"], "warn")               # price 30 s old
        self.assertEqual(run([3], used=1600)["level"], "warn")      # 84% of the budget
        self.assertEqual(run([3], entries={"paused": True, "reason": "paused by hand"})["level"], "warn")

    def test_no_open_positions_is_fine_and_no_tape_is_not(self):
        self.assertEqual(run([])["level"], "ok")
        self.assertEqual(run([None])["level"], "bad")

    def test_a_dead_scanner_is_bad(self):
        self.assertEqual(run([3], cycle_age=900)["level"], "bad")

    def test_market_closed_is_idle_and_never_alarms_on_feeds(self):
        h = run([None, 9999], cycle_age=99999, limit=9, now=SAT)
        self.assertEqual(h["level"], "idle")
        self.assertFalse(h["market_open"])

    def test_age_text(self):
        self.assertEqual(hp._age_text(45), "45s")
        self.assertEqual(hp._age_text(300), "5 min")
        self.assertEqual(hp._age_text(None), "unknown")

    def test_capital_is_shown_per_open_trade_and_closed_trades_drop_out(self):
        rows = [{"id": "a", "symbol": "X", "status": "OPEN", "capital": 12000.0, "entry_time": "09:50"},
                {"id": "b", "symbol": "Y", "status": "OPEN", "capital": 8000.0, "entry_time": "09:55"},
                {"id": "c", "symbol": "Z", "status": "CLOSED", "capital": 5000.0}]
        p = hp.payload(lambda: {"rows": rows}, None, now=SAT)
        self.assertEqual([x["capital"] for x in p["positions"]], [12000.0, 8000.0])
        self.assertEqual(p["capital_open"], 20000.0)
        rows[0]["status"] = "CLOSED"
        self.assertEqual(hp.payload(lambda: {"rows": rows}, None, now=SAT)["capital_open"], 8000.0)

    def test_payload_survives_missing_pieces(self):
        p = hp.payload(lambda: {"rows": [], "trade_count": 0}, None, now=SAT)
        self.assertTrue(p["ok"])
        self.assertEqual(p["positions"], [])


if __name__ == "__main__":
    unittest.main()
