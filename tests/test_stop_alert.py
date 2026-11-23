import unittest
from datetime import datetime
from datetime import time as T

import stop_alert as sa

IST = sa.IST


class StepTests(unittest.TestCase):
    def test_no_message_until_down_for_the_grace_period(self):
        e, a = sa.step({}, False, True, 1000.0, "gone")
        self.assertIsNone(a)
        e, a = sa.step(e, False, True, 1000.0 + sa.GRACE_SECONDS - 1, "gone")
        self.assertIsNone(a)
        e, a = sa.step(e, False, True, 1000.0 + sa.GRACE_SECONDS, "gone")
        self.assertEqual(a, "stopped")

    def test_one_message_then_reminders_then_back(self):
        e, a = sa.step({"down_since": 0.0}, False, True, 200.0, "gone")
        self.assertEqual(a, "stopped")
        e["alerted_at"] = e["reminded_at"] = 200.0                      # what run() records after a successful send
        e, a = sa.step(e, False, True, 260.0, "gone")
        self.assertIsNone(a)                                            # no repeat every minute
        e, a = sa.step(e, False, True, 200.0 + sa.REMIND_SECONDS, "gone")
        self.assertEqual(a, "remind")
        e, a = sa.step(e, True, True, 2400.0, "ok")
        self.assertEqual(a, "back")
        self.assertEqual(e["back_after"], 2400)
        e2, a = sa.step({"last_ok": 1.0}, True, True, 2500.0, "ok")
        self.assertIsNone(a)                                            # healthy and never alerted: silent

    def test_a_blip_shorter_than_the_grace_period_is_never_reported(self):
        e, _ = sa.step({}, False, True, 0.0, "gone")
        e, a = sa.step(e, True, True, 60.0, "ok")
        self.assertIsNone(a)
        self.assertNotIn("down_since", e)

    def test_outside_the_window_nothing_is_reported_and_state_clears(self):
        e, a = sa.step({"down_since": 0.0, "alerted_at": 1.0}, False, False, 99999.0, "gone")
        self.assertEqual((e, a), ({}, None))

    def test_messages_name_the_item_and_the_time(self):
        now = datetime(2026, 10, 28, 11, 30, tzinfo=IST)
        down = datetime(2026, 10, 28, 11, 4, tzinfo=IST).timestamp()
        m = sa.message("stopped", "News collector", {"down_since": down, "detail": "process not found"}, now)
        self.assertIn("STOPPED: News collector", m)
        self.assertIn("11:04", m)
        self.assertIn("26 min", m)
        self.assertIn("process not found", m)
        self.assertIn("BACK: News collector", sa.message("back", "News collector", {"back_after": 1500}, now))


class WindowTests(unittest.TestCase):
    def test_trading_day_windows(self):
        comp = sa.Component("x", lambda c: (True, ""), (T(9, 16), T(15, 30)))
        wed = datetime(2026, 10, 28, 10, 0, tzinfo=IST)
        self.assertTrue(sa.in_window(comp, wed, set()))
        self.assertFalse(sa.in_window(comp, wed.replace(hour=16), set()))
        self.assertFalse(sa.in_window(comp, datetime(2026, 10, 31, 10, 0, tzinfo=IST), set()))          # Saturday
        self.assertFalse(sa.in_window(comp, wed, {"2026-10-28"}))                                       # holiday
        always = sa.Component("y", lambda c: (True, ""))
        self.assertTrue(sa.in_window(always, datetime(2026, 10, 31, 3, 0, tzinfo=IST), set()))          # 24x7 items run on weekends too

    def test_process_match_does_not_confuse_the_two_tick_recorders(self):
        procs = [r'"C:\x\python.exe" "C:\APlus\option_tick_recorder.py"']
        ctx = sa.Context(procs, datetime.now(IST))
        self.assertEqual(ctx.running(r"\\option_tick_recorder\.py"), 1)
        self.assertEqual(ctx.running(r"\\tick_recorder\.py"), 0)

    def test_every_item_has_a_name_and_a_check(self):
        names = [c.name for c in sa.COMPONENTS]
        self.assertEqual(len(names), len(set(names)))
        self.assertIn("News collector", names)


class DataFreshnessTests(unittest.TestCase):
    def setUp(self):
        import json
        import os
        import tempfile
        from pathlib import Path
        from unittest import mock

        self.json, self.os = json, os
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self.tmp.name)
        p = mock.patch.object(sa, "ROOT", self.root)
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(self.tmp.cleanup)
        self.now = datetime(2026, 11, 23, 11, 0, tzinfo=IST)
        self.ctx = sa.Context([], self.now)

    def write(self, rel, text="x", age=0):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        t = self.now.timestamp() - age
        self.os.utime(path, (t, t))

    def test_dated_file_fresh_stale_and_missing(self):
        check = sa.dated_file("data/order_book/{d}.csv", 300)
        self.assertFalse(check(self.ctx)[0])                                           # missing today
        self.write("data/order_book/2026-11-23.csv", age=60)
        self.assertTrue(check(self.ctx)[0])
        self.write("data/order_book/2026-11-23.csv", age=900)
        ok, detail = check(self.ctx)
        self.assertFalse(ok)
        self.assertIn("limit 300s", detail)
        self.write("data/order_book/2026-11-22.csv", age=0)                             # yesterday's file never counts for today
        self.assertFalse(check(self.ctx)[0])

    def test_chain_data_needs_fresh_health_and_at_least_one_stock(self):
        check = sa.chain_data(1500)
        rel = "data/options_intelligence_upstox/health.json"
        self.write(rel, self.json.dumps({"symbols": 50, "symbols_ok": 0, "last_error": "UpstoxLimit: budget"}), age=120)
        ok, detail = check(self.ctx)
        self.assertFalse(ok)
        self.assertIn("0 of 50", detail)
        self.assertIn("UpstoxLimit", detail)
        self.write(rel, self.json.dumps({"symbols": 50, "symbols_ok": 48}), age=120)
        self.assertTrue(check(self.ctx)[0])
        self.write(rel, self.json.dumps({"symbols": 50, "symbols_ok": 48}), age=4000)
        self.assertFalse(check(self.ctx)[0])                                           # captured but long ago
        (self.root / rel).unlink()
        self.assertFalse(check(self.ctx)[0])

    def test_data_messages_say_data_not_stopped(self):
        down = datetime(2026, 11, 23, 10, 20, tzinfo=IST).timestamp()
        m = sa.message("stopped", "Smart Flow data (order book)", {"down_since": down, "detail": "x updated 900s ago"}, self.now, data=True)
        self.assertIn("DATA NOT UPDATING: Smart Flow data (order book)", m)
        self.assertIn("since 10:20", m)
        self.assertNotIn("STOPPED", m)
        self.assertIn("DATA BACK", sa.message("back", "Futures data", {"back_after": 1200}, self.now, data=True))
        self.assertIn("APlus STOPPED", sa.message("stopped", "News collector", {"down_since": down}, self.now))     # process alerts keep their wording

    def test_the_data_checks_are_registered_in_the_trading_window(self):
        data = {c.name: c for c in sa.COMPONENTS if c.data}
        self.assertEqual(set(data), {"Smart Flow data (order book)", "Futures data", "Option chain data", "1-minute price history"})
        for c in data.values():
            self.assertIsNotNone(c.window)


if __name__ == "__main__":
    unittest.main()
