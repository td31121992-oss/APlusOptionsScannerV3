import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

for k in list(os.environ):
    if k.startswith("APLUS_TD_"):
        os.environ.pop(k)

import tick_detector as td
import tick_event_review as rv

IST = timezone(timedelta(hours=5, minutes=30))


def ts(sec):
    h, rem = divmod(int(sec), 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}.000"


def quiet_minutes(det, sym, start_min=10 * 60, minutes=12, price=100.0):
    """Steady trading: 100 shares a tick, 6 ticks a minute, flat price."""
    for m in range(start_min, start_min + minutes):
        for k in range(6):
            det.update(sym, ts(m * 60 + k * 10), price, 100, "B" if k % 2 else "S")


class DetectorTests(unittest.TestCase):
    def test_burst_fires_once_with_cooldown(self):
        det = td.TickDetector()
        quiet_minutes(det, "AAA")                                                  # 12 quiet minutes: baseline 600 shares a minute
        t0 = 10 * 3600 + 12 * 60
        fired = []
        for k in range(12):                                                         # next 60 s: price +0.55 %, heavy buying (1500 shares a tick)
            ev = det.update("AAA", ts(t0 + k * 5), 100.0 + 0.05 * k, 1500, "B")
            if ev:
                fired.append(ev)
        self.assertEqual(len(fired), 1)
        e = fired[0]
        self.assertEqual((e["symbol"], e["direction"]), ("AAA", "BULLISH"))
        self.assertGreaterEqual(e["volx"], 3.0)
        self.assertGreaterEqual(e["buy_share"], 0.65)
        again = det.update("AAA", ts(t0 + 70), 100.7, 1500, "B")                    # same direction inside the cooldown: silent
        self.assertIsNone(again)

    def test_no_event_without_volume_surge_or_flow_or_baseline(self):
        det = td.TickDetector()
        quiet_minutes(det, "BBB")
        t0 = 10 * 3600 + 12 * 60
        for k in range(12):                                                         # price moves on ordinary volume
            self.assertIsNone(det.update("BBB", ts(t0 + k * 5), 100.0 + 0.05 * k, 100, "B"))
        det2 = td.TickDetector()
        quiet_minutes(det2, "CCC")
        for k in range(12):                                                         # surge and move, but half of it is selling: share below 0.65
            self.assertIsNone(det2.update("CCC", ts(t0 + k * 5), 100.0 + 0.05 * k, 1500, "B" if k % 2 else "S"))
        det3 = td.TickDetector()
        for k in range(12):                                                         # no baseline yet (first minutes of the stock)
            self.assertIsNone(det3.update("DDD", ts(10 * 3600 + k * 5), 100.0 + 0.1 * k, 5000, "B"))

    def test_bearish_burst_and_time_window(self):
        det = td.TickDetector()
        quiet_minutes(det, "EEE")
        t0 = 10 * 3600 + 12 * 60
        got = [det.update("EEE", ts(t0 + k * 5), 100.0 - 0.05 * k, 1500, "S") for k in range(12)]
        self.assertEqual([e["direction"] for e in got if e], ["BEARISH"])
        late = td.TickDetector()
        quiet_minutes(late, "FFF", start_min=15 * 60 + 5)                           # 15:05 onwards: outside the window
        t1 = 15 * 3600 + 17 * 60
        self.assertEqual([late.update("FFF", ts(t1 + k * 5), 100.0 + 0.05 * k, 1500, "B") for k in range(12)], [None] * 12)

    def test_event_log_and_tags(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log = td.EventLog(root, "2026-10-22")
            log.write({"time": "10:13:44", "symbol": "ABC", "direction": "BULLISH", "ltp": 100, "move_pct": 0.6, "volx": 3.2, "buy_share": 0.77, "vol_window": 1, "base_window": 1, "day_move_pct": 0.1})
            log.write({"time": "09:40:00", "symbol": "ABC", "direction": "BEARISH", "ltp": 99, "move_pct": -0.3, "volx": 3.0, "buy_share": 0.2, "vol_window": 1, "base_window": 1, "day_move_pct": -0.1})
            now = datetime(2026, 10, 22, 10, 20, tzinfo=IST)
            t = td.event_tags("ABC", "BULLISH", now, root)
            self.assertEqual((t["td_fired"], t["td_aligned"], t["td_ago_min"], t["td_n_today"]), (1, 1, 6.3, 2))
            self.assertEqual(td.event_tags("ABC", "BEARISH", now, root)["td_aligned"], 0)
            old = td.event_tags("ABC", "BULLISH", datetime(2026, 10, 22, 11, 30, tzinfo=IST), root)
            self.assertEqual((old["td_fired"], old["td_n_today"]), (0, 2))
            self.assertEqual(td.event_tags("XYZ", "BULLISH", now, root), {"td_fired": 0, "td_n_today": 0})
            self.assertEqual(td.event_tags("ABC", "BULLISH", datetime(2026, 10, 21, 10, 0, tzinfo=IST), root), {"td_fired": 0, "td_n_today": 0})

    def test_review_rows_summary_and_leads(self):
        events = [{"time": "10:13:44", "symbol": "ABC", "direction": "BULLISH", "ltp": 100, "move_pct": 0.6, "volx": 3.2, "buy_share": 0.77, "day_move_pct": 0.1}]
        bars = [(m, 10.0, 10.2, 9.9, 10.0) for m in range(10 * 60 + 10, 10 * 60 + 14)] + [(10 * 60 + 15, 10.0, 12.0, 10.0, 11.5), (10 * 60 + 16, 11.5, 12.5, 11.0, 12.0)]
        trades = [{"symbol": "ABC", "direction": "BULLISH", "entry_time": "2026-10-22T10:26:10+05:30"}, {"symbol": "ABC", "direction": "BULLISH", "entry_time": "2026-10-22T10:40:00+05:30"},
                  {"symbol": "OLD", "direction": "BULLISH", "entry_time": "2026-10-21T10:00:00+05:30"}]
        leads = rv.trade_leads(trades, "2026-10-22")
        self.assertEqual(leads, {("ABC", "BULLISH"): 10 * 60 + 26})
        rows = rv.review_events(events, "2026-10-22", lambda s, d: (bars, {"strike": 100}), leads)
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["hit10_first"], rows[0]["stop_first"], rows[0]["trade_lead_min"]), (1, 0, 13.0))
        text = "\n".join(rv.summarise(rows))
        self.assertIn("By volume surge", text)
        self.assertIn("a) 3-4x", text)
        self.assertIn("minutes before our own entry", text)
        self.assertEqual(rv.review_events(events, "d", lambda s, d: None, {}), [])


if __name__ == "__main__":
    unittest.main()
