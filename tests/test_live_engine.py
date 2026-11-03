import json
import tempfile
import unittest
from datetime import datetime, time as clock, timedelta, timezone
from pathlib import Path

import live_broker as lb
import live_engine as le

IST = timezone(timedelta(hours=5, minutes=30))
DAY = "2026-10-26"


class Clock:
    def __init__(self, hh=10, mm=0):
        self.t = datetime(2026, 10, 26, hh, mm, 0, tzinfo=IST)
        self.m = 1000.0

    def now(self):
        return self.t

    def mono(self):
        return self.m

    def advance(self, s):
        self.m += s
        self.t += timedelta(seconds=s)


class FakeBroker(lb.DryRunBroker):
    """DryRunBroker with scripted behaviour: orders can be held PENDING, partially filled, or rejected, and the quote is mutable."""

    def __init__(self):
        super().__init__()
        self.q = (14.9, 15.1)
        self.hold_buy = False
        self.partial_buy = 0
        self.reject_stop = False
        self.reject_buy = False
        self.fail_exit_limits = 0
        self.fail_positions = False
        self.cancelled: list[str] = []

    def quote(self, sid):
        return self.q

    def place(self, req):
        if req.side == "BUY" and self.reject_buy:
            st = lb.OrderState("R1", "REJECTED", message="margin")
            self.orders["R1"] = st
            return st
        if req.order_type == "STOP_LOSS" and self.reject_stop:
            return lb.OrderState("R2", "REJECTED", message="no")
        if req.side == "BUY" and (self.hold_buy or self.partial_buy):
            st = super().place(lb.OrderRequest(req.correlation_id, "SELL", "HOLD", req.quantity, "STOP_LOSS", symbol=req.symbol))   # registers an id, stays PENDING
            self.sent[-1] = req
            self.requests[st.order_id] = req
            if self.partial_buy:
                st.status, st.filled_qty, st.avg_price = "PART_TRADED", self.partial_buy, req.price
                self.net[req.security_id] = self.net.get(req.security_id, 0) + self.partial_buy
            return st
        if req.side == "SELL" and req.order_type == "LIMIT" and self.fail_exit_limits > 0:
            self.fail_exit_limits -= 1
            st = super().place(lb.OrderRequest(req.correlation_id, "SELL", "HOLD", req.quantity, "STOP_LOSS", symbol=req.symbol))
            self.sent[-1] = req
            return st
        return super().place(req)

    def cancel(self, order_id):
        self.cancelled.append(order_id)
        return super().cancel(order_id)

    def positions(self):
        if self.fail_positions:
            raise RuntimeError("down")
        return super().positions()


def trade(pid="PT1", status="OPEN", **kw):
    t = {"paper_trade_id": pid, "status": status, "symbol": "AAA", "trading_symbol": "AAA26OCT100CE", "option_security_id": "555", "lot_size": 100, "lots": 3, "entry_price": 15.0, "limit_price": 15.0,
         "option_stop": 12.0, "entry_time": f"{DAY}T10:00:05+05:30", "exit_reason": ""}
    t.update(kw)
    return t


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.clock = Clock()
        self.broker = FakeBroker()
        self.alerts: list[str] = []

    def tearDown(self):
        self.tmp.cleanup()

    def journal(self, *trades):
        p = self.root / "data" / "intraday_movement"
        p.mkdir(parents=True, exist_ok=True)
        (p / "paper_trade_journal.json").write_text(json.dumps({"trades": list(trades)}), encoding="utf-8")

    def engine(self, mode="DRY_RUN", **cfg):
        c = le.LiveConfig(mode=mode, **cfg)
        return le.LiveEngine(self.root, self.broker, c, now_fn=self.clock.now, notify=self.alerts.append, sleep=lambda s: None, mono=self.clock.mono)

    def arm(self):
        d = self.root / "data" / "control"
        d.mkdir(parents=True, exist_ok=True)
        (d / "live_armed.json").write_text(json.dumps({"date": DAY}), encoding="utf-8")


class FlowTests(Base):
    def test_off_does_nothing(self):
        self.journal(trade())
        e = self.engine("OFF")
        e.step()
        self.assertEqual(self.broker.sent, [])
        self.assertFalse((self.root / "data" / "live").exists())

    def test_dry_run_entry_stop_and_paper_exit(self):
        self.journal(trade())
        e = self.engine()
        e.step()
        buy, stop = self.broker.sent[0], self.broker.sent[1]
        self.assertEqual((buy.side, buy.order_type, buy.quantity), ("BUY", "LIMIT", 100))                 # lots capped to 1 (paper had 3)
        self.assertEqual(buy.price, le.tick_round(15.1 * 1.01))                                           # ask + 1 % buffer
        self.assertEqual((stop.side, stop.order_type, stop.trigger_price, stop.quantity), ("SELL", "STOP_LOSS", 12.0, 100))
        self.assertEqual(stop.price, le.tick_round(12.0 * 0.97, up=False))
        rec = e.recs["PT1"]
        self.assertEqual((rec.status, rec.qty), ("OPEN", 100))
        self.journal(trade(status="CLOSED", exit_reason="USER_LADDER_EXIT"))
        self.broker.q = (19.9, 20.1)
        e.step()
        sell = self.broker.sent[2]
        self.assertEqual((sell.side, sell.order_type), ("SELL", "LIMIT"))
        self.assertEqual(sell.price, le.tick_round(19.9 * 0.99, up=False))
        self.assertIn(rec_stop := e.recs["PT1"].sl_order, self.broker.cancelled)                           # the protective stop was taken off before selling
        self.assertEqual(e.recs["PT1"].status, "CLOSED")
        self.assertAlmostEqual(e.recs["PT1"].realized, (le.tick_round(19.9 * 0.99, up=False) - le.tick_round(15.1 * 1.01)) * 100, places=2)
        self.assertIsNotNone(rec_stop)
        self.assertEqual(self.broker.positions(), {})
        audit = (self.root / "data" / "live" / f"orders_{DAY}.jsonl").read_text(encoding="utf-8")
        self.assertIn('"kind": "request"', audit)
        self.assertTrue(any("ENTRY FILLED" in a for a in self.alerts))

    def test_broker_stop_fills_first(self):
        self.journal(trade())
        e = self.engine()
        e.step()
        self.broker.trigger(e.recs["PT1"].sl_order, 11.6)
        e.step()
        r = e.recs["PT1"]
        self.assertEqual((r.status, r.exit_price, r.reason), ("CLOSED", 11.6, "broker stop filled"))
        self.journal(trade(status="CLOSED"))
        n = len(self.broker.sent)
        e.step()
        self.assertEqual(len(self.broker.sent), n)                                                        # the later paper exit sends nothing

    def test_restart_does_not_resend(self):
        self.journal(trade())
        self.engine().step()
        n = len(self.broker.sent)
        e2 = self.engine()
        e2.step()
        self.assertEqual(len(self.broker.sent), n)
        self.assertEqual(e2.recs["PT1"].status, "OPEN")                                                   # state came back from disk

    def test_a_paper_trade_opened_by_hand_later_is_still_mirrored_once(self):
        self.journal(trade(), trade("PT2", option_security_id="777"))
        e = self.engine()
        e.step()
        e.step()
        self.assertEqual([r.side for r in self.broker.sent].count("BUY"), 2)


class EntryRailTests(Base):
    def skipped(self, e, pid="PT1"):
        return e.recs[pid].reason

    def test_live_needs_todays_arming(self):
        self.journal(trade())
        e = self.engine("LIVE")
        e.step()
        self.assertEqual(self.skipped(e), "not armed")
        self.assertEqual(self.broker.sent, [])
        self.arm()
        self.journal(trade("PT2"))
        e.step()
        self.assertEqual(e.recs["PT2"].status, "OPEN")

    def test_old_arming_file_does_not_count(self):
        d = self.root / "data" / "control"
        d.mkdir(parents=True)
        (d / "live_armed.json").write_text(json.dumps({"date": "2026-10-25"}), encoding="utf-8")
        self.journal(trade())
        e = self.engine("LIVE")
        e.step()
        self.assertEqual(self.skipped(e), "not armed")

    def test_slippage_guard_value_cap_window_and_quote(self):
        self.journal(trade())
        self.broker.q = (15.9, 16.4)                                                                      # ask 9 % above the paper entry
        e = self.engine()
        e.step()
        self.assertIn("above the paper entry", self.skipped(e))
        self.broker.q = (14.9, 15.1)
        self.journal(trade("PT2"))
        e2 = self.engine(max_order_value=1000)
        e2.step()
        self.assertIn("order value", e2.recs["PT2"].reason)
        self.clock.t = self.clock.t.replace(hour=15, minute=30)
        self.journal(trade("PT3"))
        e3 = self.engine()
        e3.step()
        self.assertEqual(e3.recs["PT3"].reason, "outside the entry window")
        self.clock.t = self.clock.t.replace(hour=10)
        self.broker.q = None
        self.journal(trade("PT4"))
        e4 = self.engine()
        e4.step()
        self.assertEqual(e4.recs["PT4"].reason, "no live quote")
        self.assertEqual([s for s in self.broker.sent if s.side == "BUY"], [])

    def test_incomplete_paper_trade_is_skipped(self):
        self.journal(trade(lot_size=0))
        e = self.engine()
        e.step()
        self.assertIn("incomplete", self.skipped(e))

    def test_entry_not_filled_in_time_is_cancelled(self):
        self.broker.hold_buy = True
        self.journal(trade())
        e = self.engine()
        e.step()
        self.assertEqual(e.recs["PT1"].status, "ENTRY_SENT")
        self.clock.advance(20)
        e.step()
        r = e.recs["PT1"]
        self.assertEqual(r.status, "FAILED")
        self.assertIn(r.entry_order, self.broker.cancelled)
        self.assertEqual([s.order_type for s in self.broker.sent if s.side == "SELL"], [])                # no stop for a position that does not exist

    def test_partial_fill_keeps_what_filled_and_stops_exactly_that(self):
        self.broker.partial_buy = 40
        self.journal(trade())
        e = self.engine()
        e.step()
        self.clock.advance(20)
        e.step()
        r = e.recs["PT1"]
        self.assertEqual((r.status, r.qty), ("OPEN", 40))
        stop = [s for s in self.broker.sent if s.order_type == "STOP_LOSS" and s.security_id == "555"][0]
        self.assertEqual(stop.quantity, 40)

    def test_rejected_entry(self):
        self.broker.reject_buy = True
        self.journal(trade())
        e = self.engine()
        e.step()
        self.assertEqual(e.recs["PT1"].status, "FAILED")


class RailTests(Base):
    def test_kill_switch_flattens_and_blocks(self):
        self.journal(trade())
        e = self.engine()
        e.step()
        (self.root / "data" / "control").mkdir(parents=True, exist_ok=True)
        (self.root / "data" / "control" / "LIVE_KILL").write_text("x", encoding="utf-8")
        self.journal(trade(), trade("PT2", option_security_id="777"))
        e.step()
        self.assertEqual(e.recs["PT1"].status, "CLOSED")
        self.assertEqual(e.recs["PT2"].status, "SKIPPED")
        self.assertIn("KILL", e.halted)
        self.assertEqual(self.broker.positions(), {})

    def test_daily_loss_cap_halts_and_flattens(self):
        self.journal(trade())
        e = self.engine(max_daily_loss=500)
        e.step()
        self.broker.q = (9.0, 9.2)                                                                        # open loss (9 - 15.2) * 100 = -620
        e.step()
        self.assertIn("daily loss cap", e.halted)
        self.assertEqual(e.recs["PT1"].status, "CLOSED")
        self.journal(trade("PT2", option_security_id="777"))
        e.step()
        self.assertEqual(e.recs["PT2"].status, "SKIPPED")                                                 # no new entries after the cap

    def test_exit_reprices_then_goes_to_market(self):
        self.journal(trade())
        e = self.engine(exit_wait_s=5)
        e.step()
        self.broker.fail_exit_limits = 2
        self.journal(trade(status="CLOSED"))
        e.step()
        self.assertEqual(e.recs["PT1"].status, "EXIT_SENT")
        self.clock.advance(6)
        e.step()
        self.clock.advance(6)
        e.step()
        r = e.recs["PT1"]
        self.assertEqual(r.status, "CLOSED")
        types = [(s.order_type, s.correlation_id[-2:]) for s in self.broker.sent if s.side == "SELL" and s.order_type != "STOP_LOSS"]
        self.assertEqual([t[0] for t in types], ["LIMIT", "LIMIT", "MARKET"])
        self.assertEqual([t[1] for t in types], ["X0", "X1", "X2"])
        prices = [s.price for s in self.broker.sent if s.order_type == "LIMIT" and s.side == "SELL"]
        self.assertLess(prices[1], prices[0])                                                             # the second attempt is priced lower

    def test_rejected_stop_flattens_and_halts(self):
        self.broker.reject_stop = True
        self.journal(trade())
        e = self.engine()
        e.step()
        self.assertIn("protective stop rejected", e.halted)
        self.assertEqual(e.recs["PT1"].status, "CLOSED")                                                  # never left unprotected
        self.assertEqual(self.broker.positions(), {})

    def test_reconcile_mismatch_halts(self):
        self.journal(trade())
        e = self.engine(reconcile_s=0)
        e.step()
        self.assertEqual(e.halted, "")
        self.broker.net["555"] = 0                                                                        # the broker no longer shows our position
        e.step()
        self.assertIn("position mismatch", e.halted)

    def test_end_of_day_flatten(self):
        self.journal(trade())
        e = self.engine()
        e.step()
        self.clock.t = self.clock.t.replace(hour=15, minute=21)
        e.step()
        self.assertEqual(e.recs["PT1"].status, "CLOSED")

    def test_status_summary(self):
        self.journal(trade())
        e = self.engine()
        e.step()
        s = e.status()
        self.assertEqual((s["mode"], s["armed"], s["halted"]), ("DRY_RUN", True, ""))
        self.assertIn("PT1", s["recs"])


class BrokerTests(unittest.TestCase):
    def test_dhan_payload_and_parsing(self):
        class Cfg:
            client_id = "1100"
            api_base_url = "https://api.dhan.co/v2"
            connect_timeout_seconds, read_timeout_seconds, verify_tls = 5, 30, True

        class Client:
            config = Cfg()

            def place_order(self, payload):
                self.payload = payload
                return {"orderId": "123", "orderStatus": "TRANSIT"}

            def get_positions(self):
                return [{"securityId": "555", "netQty": 100, "exchangeSegment": "NSE_FNO"}, {"securityId": "9", "netQty": 0, "exchangeSegment": "NSE_FNO"}]

            def get_quote(self, sid, seg):
                return {"data": {"NSE_FNO": {sid: {"depth": {"buy": [{"price": 14.9}], "sell": [{"price": 15.1}]}}}}}

        c = Client()
        b = lb.DhanBroker(c)
        st = b.place(lb.OrderRequest("PT1-E", "BUY", "555", 100, "LIMIT", price=15.123))
        self.assertEqual((st.order_id, st.status), ("123", "TRANSIT"))
        p = c.payload
        self.assertEqual((p["transactionType"], p["exchangeSegment"], p["productType"], p["orderType"], p["validity"], p["securityId"], p["quantity"], p["price"]),
                         ("BUY", "NSE_FNO", "INTRADAY", "LIMIT", "DAY", "555", 100, 15.12))
        sl = b.payload(lb.OrderRequest("PT1-S", "SELL", "555", 100, "STOP_LOSS", price=11.6, trigger_price=12.0))
        self.assertEqual((sl["orderType"], sl["triggerPrice"], sl["price"]), ("STOP_LOSS", 12.0, 11.6))
        mk = b.payload(lb.OrderRequest("PT1-X", "SELL", "555", 100, "MARKET"))
        self.assertEqual((mk["price"], mk["triggerPrice"]), (0, 0))
        self.assertEqual(b.positions(), {"555": 100})
        self.assertEqual(b.quote("555"), (14.9, 15.1))
        self.assertEqual(lb.parse_order({"orderId": "7", "orderStatus": "PART_TRADED", "tradedQuantity": 40, "averageTradedPrice": 15.2}).filled_qty, 40)
        self.assertEqual(lb.parse_order({"orderStatus": "TRADED"}).final, True)

    def test_dhan_response_without_order_id_is_a_rejection(self):
        class Cfg:
            client_id = "1"
            api_base_url = "x"

        class Client:
            config = Cfg()

            def place_order(self, payload):
                return {"status": "failure"}

        self.assertEqual(lb.DhanBroker(Client()).place(lb.OrderRequest("a", "BUY", "1", 1, "MARKET")).status, "REJECTED")

    def test_config_from_env(self):
        import os

        old = {k: os.environ.get(k) for k in ("APLUS_LIVE_MODE", "APLUS_LIVE_LOTS_CAP")}
        try:
            os.environ["APLUS_LIVE_MODE"], os.environ["APLUS_LIVE_LOTS_CAP"] = "live", "2"
            c = le.LiveConfig.from_env()
            self.assertEqual((c.mode, c.lots_cap), ("LIVE", 2))
            os.environ["APLUS_LIVE_MODE"] = "banana"
            self.assertEqual(le.LiveConfig.from_env().mode, "OFF")                                         # anything unrecognised is OFF
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    def test_tick_round(self):
        self.assertEqual(le.tick_round(15.131), 15.15)
        self.assertEqual(le.tick_round(15.139, up=False), 15.10)


if __name__ == "__main__":
    unittest.main()
