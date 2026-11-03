from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import trading_mode as tm

IST = ZoneInfo("Asia/Kolkata")


def at(day: int, hour: int = 10) -> datetime:
    return datetime(2026, 10, day, hour, 0, tzinfo=IST)


OK = lambda: {"connected": True, "client": "11**22", "available_balance": 1000.0}      # noqa: E731
DOWN = lambda: {"connected": False, "error": "profile HTTP 401"}                         # noqa: E731


class ModeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name, "mode.json")
        self.addCleanup(os.environ.pop, "APLUS_LIVE_TRADING_ALLOWED", None)
        os.environ.pop("APLUS_LIVE_TRADING_ALLOWED", None)
        self._audit = tm.AUDIT_PATH
        tm.AUDIT_PATH = Path(self.tmp.name, "audit.log")
        self.addCleanup(setattr, tm, "AUDIT_PATH", self._audit)

    def go(self, target, confirm="LIVE", remote="127.0.0.1", check=OK, now=None):
        return tm.set_mode(target, confirm=confirm, remote_addr=remote, check=check, now=now or at(8), path=self.path)

    def test_default_is_paper_and_routing_is_never_on(self) -> None:
        s = tm.get_state(at(8), self.path)
        self.assertEqual((s["mode"], s["order_routing"]), ("PAPER", "NOT_IMPLEMENTED"))
        self.assertFalse(tm.should_route_orders())

    def test_live_refused_unless_enabled_on_this_machine(self) -> None:
        ok, s, msg = self.go("LIVE")
        self.assertFalse(ok)
        self.assertEqual(s["mode"], "PAPER")

    def test_live_refused_from_the_network_or_without_confirmation_or_broker(self) -> None:
        os.environ["APLUS_LIVE_TRADING_ALLOWED"] = "1"
        self.assertFalse(self.go("LIVE", remote="192.168.1.20")[0])
        self.assertFalse(self.go("LIVE", confirm="yes")[0])
        self.assertFalse(self.go("LIVE", check=DOWN)[0])
        self.assertEqual(tm.get_state(at(8), self.path)["mode"], "PAPER")

    def test_live_armed_then_expires_next_day_and_paper_always_works(self) -> None:
        os.environ["APLUS_LIVE_TRADING_ALLOWED"] = "1"
        ok, s, msg = self.go("LIVE")
        self.assertTrue(ok)
        self.assertEqual((s["mode"], s["order_routing"]), ("LIVE", "NOT_IMPLEMENTED"))
        self.assertIn("no real order", msg)
        self.assertEqual(tm.get_state(at(8, 15), self.path)["mode"], "LIVE")
        self.assertEqual(tm.get_state(at(9), self.path)["mode"], "PAPER")        # next day: reverted
        self.go("LIVE")
        self.assertEqual(self.go("PAPER")[1]["mode"], "PAPER")
        self.assertFalse(tm.should_route_orders())

    def test_dashboard_page_gets_the_mode_bar(self) -> None:
        import aplus_live_pnl_dashboard as dash
        page = dash._mobileize_html("<html><head></head><body>x</body></html>")
        self.assertIn('id="aplus-mode-bar"', page)
        self.assertIn("/api/mode", page)


if __name__ == "__main__":
    unittest.main()
