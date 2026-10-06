from __future__ import annotations

import json
import tempfile
import threading
import unittest
import urllib.request
from datetime import datetime, time as clock_time
from http.server import ThreadingHTTPServer
from pathlib import Path
from zoneinfo import ZoneInfo

import dashboard_intel as di

IST = ZoneInfo("Asia/Kolkata")


def ist(y, mo, d, h, mi) -> datetime:
    return datetime(y, mo, d, h, mi, tzinfo=IST)


def _write(base: Path, rel: str, content) -> None:
    path = base / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content if isinstance(content, str) else json.dumps(content), encoding="utf-8")


class MarketTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        _write(self.base, "data/safety/nse_holidays.csv", "date,description\n2026-10-20,Dussehra\n")

    def test_states(self) -> None:
        self.assertEqual(di.market_status(ist(2026, 10, 7, 10, 0), self.base)["state"], "OPEN")
        self.assertTrue(di.market_status(ist(2026, 10, 7, 10, 0), self.base)["entries_open"])
        late = di.market_status(ist(2026, 10, 7, 14, 0), self.base)
        self.assertEqual(late["state"], "OPEN")
        self.assertFalse(late["entries_open"])
        self.assertEqual(di.market_status(ist(2026, 10, 7, 8, 0), self.base)["state"], "PRE_OPEN")
        self.assertEqual(di.market_status(ist(2026, 10, 7, 16, 0), self.base)["state"], "CLOSED")
        self.assertEqual(di.market_status(ist(2026, 10, 3, 10, 0), self.base)["state"], "CLOSED")    # Saturday
        hol = di.market_status(ist(2026, 10, 20, 10, 0), self.base)
        self.assertEqual(hol["state"], "CLOSED")
        self.assertIn("Dussehra", hol["note"])


class DiagnoseTests(unittest.TestCase):
    OPEN = {"state": "OPEN", "note": "", "entries_open": True, "last_new_entry": "13:00"}

    def test_priority_and_messages(self) -> None:
        d = di.diagnose
        self.assertIn("closed", d({}, {"state": "CLOSED", "note": "WEEKEND"}, None).lower())
        self.assertIn("not produced a cycle", d({}, self.OPEN, 900))
        self.assertIn("circuit breaker", d({"paper_native_circuit_breaker": {"blocked": True, "reasons": ["X"]}}, self.OPEN, 10))
        self.assertIn("2 new paper trade", d({"new_paper_trades_this_cycle": 2}, self.OPEN, 10))
        closed_entries = {**self.OPEN, "entries_open": False}
        self.assertIn("New entries are closed after 13:00", d({}, closed_entries, 10))
        self.assertIn("No stock is entry-ready", d({"entry_ready_count": 0, "candles_analysed": 30}, self.OPEN, 10))
        rejected = {"aplus_selective_gate": {"entry_ready_before_selective": 5, "passed_selective": 0,
                                             "rejection_counts": {"A_PLUS_WAIT_LATE_VWAP_EXTENSION": 4, "A_PLUS_WAIT_OVEREXTENDED": 1}}}
        msg = d(rejected, self.OPEN, 10)
        self.assertIn("All 5 entry-ready setups were rejected", msg)
        self.assertIn("late vwap extension (4)", msg)
        blocked = {"aplus_selective_gate": {"entry_ready_before_selective": 5, "passed_selective": 3}, "option_trade_plans": 0, "safety_blocked_count": 3}
        self.assertIn("blocked by safety checks", d(blocked, self.OPEN, 10))


class HealthAndPositionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)

    def test_token_expiry_parsed_and_token_never_returned(self) -> None:
        _write(self.base, "data/cache/dhan_access_token.json",
               {"accessToken": "SECRET-TOKEN-XYZ", "expiryTime": "08/10/2026 01:43"})
        now = ist(2026, 10, 7, 10, 0)
        result = di.health(self.base, now, {"state": "OPEN"})
        token = next(i for i in result["items"] if i["key"] == "Dhan token")
        self.assertEqual(token["level"], "ok")
        self.assertIn("h left", token["value"])
        self.assertNotIn("SECRET-TOKEN-XYZ", json.dumps(result))

    def test_expired_token_and_stale_heartbeat_are_bad_in_market(self) -> None:
        _write(self.base, "data/cache/dhan_access_token.json", {"expiryTime": "06/10/2026 01:43"})
        _write(self.base, "data/reports/intraday_movement_latest.json", {"generated_at": "2026-10-07T09:00:00+05:30"})
        result = di.health(self.base, ist(2026, 10, 7, 10, 0), {"state": "OPEN"})
        levels = {i["key"]: i["level"] for i in result["items"]}
        self.assertEqual(levels["Dhan token"], "bad")
        self.assertEqual(levels["Scanner heartbeat"], "bad")
        self.assertEqual(result["overall"], "bad")

    def test_previous_session_open_trades_are_flagged(self) -> None:
        _write(self.base, "data/intraday_movement/paper_trade_journal.json", {
            "trading_date": "2026-10-06",
            "trades": [{"status": "OPEN", "symbol": "KAYNES", "direction": "BEARISH", "option_type": "PE", "entry_price": 220.6,
                        "last_option_price": 163.2, "quantity": 150, "option_stop": 154.45, "entry_time": "2026-10-06T09:25:10+05:30"}],
        })
        pos = di.positions(self.base, ist(2026, 10, 7, 9, 0))
        self.assertTrue(pos["stale_session"])
        self.assertIn("2026-10-06", pos["note"])
        self.assertEqual(pos["rows"][0]["symbol"], "KAYNES")
        self.assertLess(pos["rows"][0]["pnl"], 0)
        self.assertAlmostEqual(pos["rows"][0]["stop_distance_pct"], (163.2 - 154.45) / 163.2 * 100, places=1)


class PerformanceTests(unittest.TestCase):
    def test_summary(self) -> None:
        rows = [{"_net": x, "_gross": x + 100, "_costs": 100, "exit_reason": r, "direction": "BULLISH", "_entry_clock": clock_time(10, 0)}
                for x, r in [(1000, "RUNNER_TRAIL_EXIT"), (-500, "OPTION_STOP_LOSS"), (-500, "OPTION_STOP_LOSS"), (1000, "RUNNER_TRAIL_EXIT")]]
        s = di.summarize_performance(rows)
        self.assertEqual((s["n"], s["win_pct"], s["net"], s["costs"]), (4, 50.0, 1000, 400))
        self.assertEqual(s["profit_factor"], 2.0)
        self.assertEqual(s["max_drawdown"], 1000)
        self.assertEqual(s["curve"][-1], 1000)
        self.assertEqual({g["name"] for g in s["by_exit"]}, {"RUNNER_TRAIL_EXIT", "OPTION_STOP_LOSS"})

    def test_empty(self) -> None:
        self.assertEqual(di.summarize_performance([]), {"n": 0})


class PayloadIsolationTests(unittest.TestCase):
    def test_empty_folder_never_raises_and_returns_every_section(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            payload = di.control_room_payload(Path(tmp), ist(2026, 10, 7, 10, 0))
        for key in ("market", "health", "funnel", "positions", "performance", "news"):
            self.assertIn(key, payload)
        json.dumps(payload)   # must be serialisable


class NewsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)

    def test_heartbeats_alive_vs_stalled_vs_missing(self) -> None:
        now = ist(2026, 10, 7, 10, 0)
        _write(self.base, "data/news_intelligence/announcement_health.json",
               {"updated_at": "2026-10-07T09:58:00+05:30", "status": "ok", "fno": 75})
        _write(self.base, "data/news_intelligence/overnight_intelligence_health.json",
               {"updated_at": "2026-10-05T18:22:08+00:00", "events_added": 26})
        levels = {i["key"]: i for i in di.health(self.base, now, {"state": "OPEN"})["items"]}
        self.assertEqual(levels["Announcement feed"]["level"], "ok")
        self.assertEqual(levels["News collector"]["level"], "bad")           # two days old -> stalled
        self.assertIn("stalled", levels["News collector"]["value"])
        empty = {i["key"]: i for i in di.health(Path(self.tmp.name, "nowhere"), now, {"state": "OPEN"})["items"]}
        self.assertEqual(empty["Announcement feed"]["level"], "bad")

    def test_news_section_lists_recent_high_and_headlines(self) -> None:
        now = ist(2026, 10, 7, 12, 0)
        ann = [
            {"id": "1", "symbol": "TCS", "desc": "Acquisition", "severity": "HIGH", "published_at": "2026-10-07T10:00:00+05:30", "session_date": "2026-10-07", "text": "deal"},
            {"id": "2", "symbol": "INFY", "desc": "Newspaper", "severity": "LOW", "published_at": "2026-10-07T10:00:00+05:30", "session_date": "2026-10-07", "text": "x"},
        ]
        nl = chr(10)
        _write(self.base, "data/news_intelligence/announcements.jsonl", nl.join(json.dumps(a) for a in ann) + nl)
        _write(self.base, "data/news_intelligence/events.jsonl", json.dumps({"title": "Nifty rises", "source": "ET", "fetched_at": "2026-10-07T09:00:00+00:00"}) + nl)
        n = di.news(self.base, now)
        self.assertEqual([a["symbol"] for a in n["announcements"]], ["TCS"])
        self.assertEqual(n["high_24h"], 1)
        self.assertEqual(n["headlines"][0]["title"], "Nifty rises")
        self.assertEqual(di.news(Path(self.tmp.name, "nowhere"), now)["announcements"], [])


class ServerTests(unittest.TestCase):
    def test_pages_and_api_over_http(self) -> None:
        import aplus_live_pnl_dashboard as dash

        server = ThreadingHTTPServer(("127.0.0.1", 0), dash.Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.shutdown)
        port = server.server_address[1]
        get = lambda p: urllib.request.urlopen(f"http://127.0.0.1:{port}{p}", timeout=20)

        page = get("/control-room")
        self.assertEqual(page.status, 200)
        self.assertIn("APlus Control Room", page.read().decode("utf-8"))

        api = json.loads(get("/api/control-room").read().decode("utf-8"))
        for key in ("market", "health", "funnel", "positions", "performance"):
            self.assertIn(key, api)

        main = get("/").read().decode("utf-8")
        self.assertIn('href="/control-room"', main)         # nav link injected on existing pages
        self.assertEqual(json.loads(get("/api/snapshot").read().decode("utf-8")).get("trade_count") is not None, True)


if __name__ == "__main__":
    unittest.main()
