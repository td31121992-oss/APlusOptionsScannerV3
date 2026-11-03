import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import manual_paper as mp


class FakeClient:
    def __init__(self):
        self.q = {"bid": 100.0, "ask": 101.0}

    def get_market_quotes(self, instruments, mode="quote"):
        out = {}
        for sid in instruments["NSE_FNO"]:
            out[str(sid)] = {"last_price": self.q["bid"], "depth": {"buy": [{"price": self.q["bid"], "quantity": 500}] if self.q["bid"] else [], "sell": [{"price": self.q["ask"], "quantity": 500}] if self.q["ask"] else []}}
        return {"NSE_FNO": out}


def contract():
    return SimpleNamespace(derivative_security_id="9001", display_name="TCS 23 NOV 2000 CALL", expiry="2999-11-23", strike=2000.0, option_type="CE", lot_size=100)


class ManualPaperTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.client = FakeClient()
        u = SimpleNamespace(symbol="TCS", contracts=[contract()])
        loader = SimpleNamespace(get=lambda s: u if s == "TCS" else None)
        self.ps = [mock.patch.object(mp, "FILE", Path(self.tmp.name) / "t.json"), mock.patch.object(mp, "_runtime", lambda: (self.client, loader)),
                   mock.patch.object(mp, "market_open", lambda now=None: True), mock.patch.object(mp, "ensure_monitor", lambda: None)]
        for p in self.ps:
            p.start()
        self.now = datetime(2026, 10, 29, 11, 0, tzinfo=mp.IST)
        self.nowp = mock.patch.object(mp, "_now", lambda: self.now)
        self.nowp.start()
        self.sent = []
        self.sendp = mock.patch.object(mp, "_send", lambda event, text: self.sent.append((event, text)))      # nothing ever goes to Telegram in a test
        self.sendp.start()

    def tearDown(self):
        self.sendp.stop()
        self.nowp.stop()
        for p in self.ps:
            p.stop()
        self.tmp.cleanup()

    def enter(self, **kw):
        req = {"symbol": "TCS", "side": "CE", "strike": 2000, "expiry": "2999-11-23", "lots": 1, "stop_pct": 20, "ladder": True}
        req.update(kw)
        return mp.open_trade(req)

    def test_entry_at_ask_with_called_price(self):
        r = self.enter(called_price=95)
        self.assertTrue(r["ok"])
        t = r["trade"]
        self.assertEqual((t["entry_price"], t["quantity"], t["called_price"], t["paper_only"]), (101.0, 100, 95.0, True))
        self.assertEqual(mp.stop_price(t), 80.8)                      # 101 * 0.8

    def test_refusals(self):
        with mock.patch.object(mp, "market_open", lambda now=None: False):
            self.assertFalse(self.enter()["ok"])
        self.client.q = {"bid": 80.0, "ask": 101.0}                  # spread over 5%
        self.assertFalse(self.enter()["ok"])
        self.client.q = {"bid": 0.0, "ask": 101.0}
        self.assertFalse(self.enter()["ok"])
        self.client.q = {"bid": 100.0, "ask": 101.0}
        self.assertFalse(self.enter(symbol="NOPE")["ok"])
        self.assertFalse(self.enter(strike=1234)["ok"])

    def test_stop_hit_sells_at_bid(self):
        self.enter()
        self.client.q = {"bid": 80.0, "ask": 81.0}
        mp.update(force=True)
        t = mp.state()["trades"][0]
        self.assertEqual((t["status"], t["exit_reason"], t["exit_price"]), ("CLOSED", "STOP_OR_LADDER", 80.0))
        self.assertAlmostEqual(t["gross_pnl"], (80.0 - 101.0) * 100)
        self.assertLess(t["net_pnl"], t["gross_pnl"])                 # costs are charged

    def test_ladder_locks_profit(self):
        self.enter(ladder=True)
        self.client.q = {"bid": 125.0, "ask": 126.0}                  # +23.8% on 101 -> lock +13% = 114.13
        mp.update(force=True)
        t = mp.state()["trades"][0]
        self.assertEqual(t["status"], "OPEN")
        self.assertAlmostEqual(t["stop"], 114.13, places=2)
        self.client.q = {"bid": 114.0, "ask": 115.0}
        mp.update(force=True)
        t = mp.state()["trades"][0]
        self.assertEqual((t["status"], t["exit_price"]), ("CLOSED", 114.0))
        self.assertGreater(t["gross_pnl"], 0)

    def test_ladder_off_keeps_initial_stop_only(self):
        self.enter(ladder=False)
        self.client.q = {"bid": 125.0, "ask": 126.0}
        mp.update(force=True)
        self.client.q = {"bid": 100.0, "ask": 101.0}
        mp.update(force=True)
        self.assertEqual(mp.state()["trades"][0]["status"], "OPEN")

    def test_manual_stop_only_moves_up_and_below_bid(self):
        t = self.enter()["trade"]
        self.assertFalse(mp.set_stop(t["id"], 100.0)["ok"])           # not below the bid (100.0)
        self.assertTrue(mp.set_stop(t["id"], 90.0)["ok"])
        self.assertFalse(mp.set_stop(t["id"], 85.0)["ok"])            # cannot move down
        self.assertEqual(mp.stop_price(mp.state()["trades"][0]), 90.0)
        self.client.q = {"bid": 89.0, "ask": 90.0}
        mp.update(force=True)
        self.assertEqual(mp.state()["trades"][0]["exit_reason"], "MANUAL_MODE_STOP")

    def test_close_button_and_summary(self):
        t = self.enter()["trade"]
        self.client.q = {"bid": 110.0, "ask": 111.0}
        r = mp.close_trade(t["id"])
        self.assertTrue(r["ok"])
        self.assertEqual(r["trade"]["exit_price"], 110.0)
        self.assertFalse(mp.close_trade(t["id"])["ok"])               # already closed
        s = mp.state()["summary"]
        self.assertEqual((s["open"], s["closed"], s["win_rate"]), (0, 1, 100.0))

    def test_session_end_close_at_1515(self):
        self.enter(hold="INTRADAY")
        self.now = datetime(2026, 10, 29, 15, 15, tzinfo=mp.IST)
        self.client.q = {"bid": 105.0, "ask": 106.0}
        mp.update(force=True)
        t = mp.state()["trades"][0]
        self.assertEqual((t["exit_reason"], t["exit_price"]), ("SESSION_END_1515", 105.0))

    def test_open_pnl_is_marked_at_bid_after_costs(self):
        self.enter()
        self.client.q = {"bid": 110.0, "ask": 111.0}
        mp.update(force=True)
        t = mp.state()["trades"][0]
        self.assertAlmostEqual(t["gross_pnl"], 900.0)
        self.assertLess(t["net_pnl"], 900.0)
        self.assertEqual(t["best_pct"], round((110 / 101 - 1) * 100, 2))


if __name__ == "__main__":
    unittest.main()


class TelegramTests(ManualPaperTests):
    def test_entry_profit_levels_and_exit_each_sent_once(self):
        t = self.enter(target_price=130)["trade"]
        self.assertEqual([e for e, _ in self.sent], [t["id"] + "|ENTRY"])
        self.client.q = {"bid": 112.0, "ask": 113.0}                       # +10.9% on 101: levels 5 and 10
        mp.update(force=True)
        self.assertEqual(sorted(e for e, _ in self.sent if "PROFIT" in e), [t["id"] + "|PROFIT10", t["id"] + "|PROFIT5"])
        mp.update(force=True)                                              # the same prices again: nothing is announced twice
        self.assertEqual(len([e for e, _ in self.sent if "PROFIT" in e]), 2)
        self.client.q = {"bid": 132.0, "ask": 133.0}                       # +30.7%: levels 20 and 30, then the target exit
        mp.update(force=True)
        events = [e for e, _ in self.sent]
        self.assertIn(t["id"] + "|PROFIT30", events)
        self.assertEqual(events[-1], t["id"] + "|EXIT")
        text = dict(self.sent)[t["id"] + "|EXIT"]
        self.assertIn("target hit", text)
        self.assertIn("Net P&L", text)

    def test_stop_exit_and_cancel_messages(self):
        self.enter()
        self.client.q = {"bid": 70.0, "ask": 71.0}
        mp.update(force=True)
        self.assertTrue(any(e.endswith("|EXIT") and "stop / ladder hit" in t for e, t in self.sent))
        p = mp.open_trade({"symbol": "TCS", "side": "CE", "strike": 2000, "expiry": "2999-11-23", "lots": 1, "entry_price": 60})
        mp.update(force=True)
        self.now = datetime(2026, 10, 29, 15, 15, tzinfo=mp.IST)
        mp.update(force=True)
        self.assertTrue(any(e.endswith("|CANCEL") for e, _ in self.sent))

    def test_pending_fill_sends_entry_with_slippage(self):
        mp.open_trade({"symbol": "TCS", "side": "CE", "strike": 2000, "expiry": "2999-11-23", "lots": 1, "entry_price": 95})
        self.client.q = {"bid": 94.0, "ask": 95.5}
        mp.update(force=True)
        text = [t for e, t in self.sent if e.endswith("|ENTRY")][-1]
        self.assertIn("slippage", text)

    def test_a_failing_notifier_never_breaks_trading(self):
        class Boom:
            def _send(self, *a):
                raise RuntimeError("telegram down")
        self.sendp.stop()
        old, mp._notifier = mp._notifier, Boom()                           # a fake notifier: the real bot is never reached from a test
        try:
            r = self.enter()
            self.assertTrue(r["ok"])
            for th in __import__("threading").enumerate():
                if th.name == "manual-paper-telegram":
                    th.join(2)
        finally:
            mp._notifier = old
            self.sendp.start()


class PendingTests(ManualPaperTests):
    """Same fixtures; broker-terminal style: entry price, SL price, target price."""

    def place(self, **kw):
        req = {"symbol": "TCS", "side": "CE", "strike": 2000, "expiry": "2999-11-23", "lots": 1, "entry_price": 95, "sl_price": 85, "target_price": 120}
        req.update(kw)
        return mp.open_trade(req)

    def test_wait_for_fall_then_fill_at_ask_with_target_and_sl(self):
        r = self.place()                                           # ask is 101: wait for the price to FALL to 95
        self.assertTrue(r["ok"])
        self.assertEqual((r["trade"]["status"], r["trade"]["trigger_dir"]), ("PENDING", "FALL"))
        mp.update(force=True)
        self.assertEqual(mp.state()["trades"][0]["status"], "PENDING")        # 100 is not 95 yet
        self.client.q = {"bid": 94.0, "ask": 95.5}
        mp.update(force=True)
        t = mp.state()["trades"][0]
        self.assertEqual((t["status"], t["entry_price"], t["slippage_pct"]), ("OPEN", 95.5, round((95.5 / 95 - 1) * 100, 2)))
        self.assertEqual((t["stop"], t["target_price"]), (85.0, 120.0))
        self.client.q = {"bid": 121.0, "ask": 122.0}
        mp.update(force=True)
        t = mp.state()["trades"][0]
        self.assertEqual((t["status"], t["exit_reason"], t["exit_price"]), ("CLOSED", "TARGET_HIT", 121.0))

    def test_wait_for_rise_breakout(self):
        r = self.place(entry_price=105, sl_price=95, target_price=130)
        self.assertEqual(r["trade"]["trigger_dir"], "RISE")
        self.client.q = {"bid": 105.0, "ask": 105.5}
        mp.update(force=True)
        self.assertEqual(mp.state()["trades"][0]["status"], "OPEN")

    def test_sl_price_is_the_initial_stop(self):
        self.place()
        self.client.q = {"bid": 94.0, "ask": 95.0}
        mp.update(force=True)
        self.client.q = {"bid": 84.0, "ask": 85.0}
        mp.update(force=True)
        t = mp.state()["trades"][0]
        self.assertEqual((t["status"], t["exit_price"]), ("CLOSED", 84.0))

    def test_level_validation(self):
        self.assertFalse(self.place(sl_price=96)["ok"])            # SL above the entry price
        self.assertFalse(self.place(target_price=90)["ok"])        # target below the entry price
        self.assertFalse(self.place(entry_price=100.99)["ok"])      # already at the price: buy now instead

    def test_cancel_and_expiry(self):
        t = self.place()["trade"]
        self.assertTrue(mp.cancel_pending(t["id"])["ok"])
        self.assertEqual(mp.state()["trades"][0]["status"], "CANCELLED")
        self.assertFalse(mp.cancel_pending(t["id"])["ok"])
        t2 = self.place()["trade"]
        self.now = datetime(2026, 10, 29, 15, 15, tzinfo=mp.IST)  # valid_date is today (placed 11:00): expires at 15:15
        mp.update(force=True)
        row = [x for x in mp.state()["trades"] if x["id"] == t2["id"]][0]
        self.assertEqual((row["status"], row["cancel_reason"]), ("CANCELLED", "EXPIRED_UNFILLED"))

    def test_sl_already_breached_at_trigger_cancels(self):
        self.place(entry_price=95, sl_price=94)
        self.client.q = {"bid": 90.0, "ask": 93.0}                 # touched 95, but the ask is already under the SL
        mp.update(force=True)
        self.assertEqual(mp.state()["trades"][0]["cancel_reason"], "SL_ALREADY_BREACHED_AT_TRIGGER")

    def test_pending_can_be_placed_when_market_closed(self):
        with mock.patch.object(mp, "market_open", lambda now=None: False):
            r = self.place()
            self.assertTrue(r["ok"])
            self.assertEqual(r["trade"]["status"], "PENDING")
            mp.update(force=True)                                   # no fill while closed
            self.assertEqual(mp.state()["trades"][0]["status"], "PENDING")

    def test_market_buy_accepts_sl_and_target(self):
        r = self.enter(sl_price=90, target_price=130)
        self.assertEqual((r["trade"]["sl_price"], r["trade"]["target_price"]), (90.0, 130.0))
        self.assertEqual(mp.stop_price(r["trade"]), 90.0)
        self.assertFalse(self.enter(sl_price=105)["ok"])            # SL above the ask


class HoldTests(ManualPaperTests):
    def test_positional_trade_is_held_past_1515_and_next_day(self):
        self.enter(hold="POSITIONAL")
        self.now = datetime(2026, 10, 29, 15, 20, tzinfo=mp.IST)
        self.client.q = {"bid": 105.0, "ask": 106.0}
        mp.update(force=True)
        self.assertEqual(mp.state()["trades"][0]["status"], "OPEN")
        self.now = datetime(2026, 10, 30, 10, 0, tzinfo=mp.IST)          # next day: still open, still marked
        self.client.q = {"bid": 130.0, "ask": 131.0}
        mp.update(force=True)
        t = mp.state()["trades"][0]
        self.assertEqual((t["status"], t["last_bid"], t["high_bid"]), ("OPEN", 130.0, 130.0))

    def test_overnight_gap_down_fills_at_the_morning_bid(self):
        self.enter(sl_price=90, hold="POSITIONAL")
        self.now = datetime(2026, 10, 30, 9, 16, tzinfo=mp.IST)
        self.client.q = {"bid": 70.0, "ask": 71.0}                       # gapped far below the SL: the fill is the bid, not the SL
        mp.update(force=True)
        t = mp.state()["trades"][0]
        self.assertEqual((t["status"], t["exit_price"]), ("CLOSED", 70.0))

    def test_positional_closes_on_expiry_day_1515(self):
        with mock.patch.object(mp, "_find", wraps=mp._find):
            r = self.enter(hold="POSITIONAL")
        t = mp.state()["trades"][0]
        raw = mp._load()
        raw[0]["expiry"] = "2026-10-29"
        mp._save(raw)
        self.now = datetime(2026, 10, 29, 15, 15, tzinfo=mp.IST)
        self.client.q = {"bid": 100.0, "ask": 101.0}
        mp.update(force=True)
        self.assertEqual(mp.state()["trades"][0]["exit_reason"], "EXPIRY_DAY_1515")

    def test_expired_contract_is_settled_at_last_mark(self):
        self.enter(hold="POSITIONAL")
        raw = mp._load()
        raw[0]["expiry"] = "2026-10-28"
        mp._save(raw)
        mp.update(force=True)
        t = mp.state()["trades"][0]
        self.assertEqual((t["exit_reason"], t["exit_price"]), ("EXPIRED_LAST_MARK", 100.0))

    def test_pending_order_valid_for_days(self):
        r = mp.open_trade({"symbol": "TCS", "side": "CE", "strike": 2000, "expiry": "2999-11-23", "lots": 1, "entry_price": 95, "valid_days": 3, "hold": "POSITIONAL"})
        self.assertEqual(r["trade"]["valid_date"], "2026-11-02")        # Thu 29 Oct 11:00 -> Thu, Fri, Mon
        self.now = datetime(2026, 10, 30, 11, 0, tzinfo=mp.IST)
        mp.update(force=True)
        self.assertEqual(mp.state()["trades"][0]["status"], "PENDING")  # still waiting the next day
        self.now = datetime(2026, 11, 2, 15, 15, tzinfo=mp.IST)
        mp.update(force=True)
        self.assertEqual(mp.state()["trades"][0]["cancel_reason"], "EXPIRED_UNFILLED")


