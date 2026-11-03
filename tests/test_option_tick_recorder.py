import gzip
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import option_tick_recorder as otr

IST = timezone(timedelta(hours=5, minutes=30))
NOW = datetime(2026, 10, 23, 10, 0, 5, 123000, tzinfo=IST)


def packet(sid=124807, ltp="100.50", vol=1000, oi=5000, bid="100.0", ask="101.0", ltq=25):
    return {"type": "Full Data", "security_id": sid, "LTP": ltp, "LTQ": ltq, "LTT": "10:00:05", "volume": vol, "OI": oi, "total_buy_quantity": 900, "total_sell_quantity": 700,
            "depth": [{"bid_price": bid, "bid_quantity": 50, "ask_price": ask, "ask_quantity": 25}, {"bid_price": "99.5", "bid_quantity": 100, "ask_price": "101.5", "ask_quantity": 100}]}


class FakeFeed:
    def __init__(self):
        self.subscribed = []

    def subscribe_symbols(self, symbols):
        self.subscribed += list(symbols)


class OptionTickTests(unittest.TestCase):
    def test_open_contracts_reads_only_todays_open_trades(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp, "j.json")
            p.write_text(json.dumps({"trades": [
                {"option_security_id": "111", "symbol": "AAA", "option_type": "PE", "strike": 100, "status": "OPEN", "entry_time": "2026-10-23T09:40:00+05:30"},
                {"option_security_id": "222", "symbol": "BBB", "status": "CLOSED", "entry_time": "2026-10-23T09:41:00+05:30"},
                {"option_security_id": "333", "symbol": "CCC", "status": "OPEN", "entry_time": "2026-10-22T09:41:00+05:30"},
                {"symbol": "DDD", "status": "OPEN", "entry_time": "2026-10-23T09:50:00+05:30"}]}), encoding="utf-8")
            self.assertEqual(otr.open_contracts(p, "2026-10-23"), {"111": {"symbol": "AAA", "option_type": "PE", "strike": "100"}})
            self.assertEqual(otr.open_contracts(Path(tmp, "missing.json"), "2026-10-23"), {})

    def test_packet_row_adds_oi_mid_and_spread(self):
        row, state = otr.packet_row(packet(), None, NOW)
        self.assertEqual((row["ltp"], row["oi"], row["mid"], row["spread_pct"]), ("100.50", 5000, 100.5, 0.99))
        self.assertEqual(row["tq"], "")                                                    # the first packet has nothing to compare with
        row2, _ = otr.packet_row(packet(ltp="101.00", vol=1040, ask="101.0"), state, NOW)
        self.assertEqual((row2["tq"], row2["side"]), (40, "B"))                            # traded 40 at the ask: buyer-initiated
        self.assertEqual(set(row2), set(otr.FIELDS))

    def test_new_contracts_are_subscribed_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            rec = otr.Recorder(Path(tmp), "2026-10-23")
            feed = FakeFeed()
            added = otr.sync_subscriptions(rec, feed, {"111": {"symbol": "AAA"}}, "SEG", "FULL")
            self.assertEqual((added, feed.subscribed), (["111"], [("SEG", "111", "FULL")]))
            self.assertEqual(otr.sync_subscriptions(rec, feed, {"111": {"symbol": "AAA"}}, "SEG", "FULL"), [])      # already followed: no second subscription
            added2 = otr.sync_subscriptions(rec, feed, {"111": {"symbol": "AAA"}, "222": {"symbol": "BBB"}}, "SEG", "FULL")
            self.assertEqual((added2, len(feed.subscribed)), (["222"], 2))

    def test_messages_for_followed_contracts_are_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            rec = otr.Recorder(Path(tmp), "2026-10-23")
            rec.contracts = {"124807": {"symbol": "POWERINDIA", "option_type": "PE", "strike": "26500"}}
            rec.on_message(None, packet(sid=124807))
            rec.on_message(None, packet(sid=124807, ltp="102.00", vol=1050))
            rec.on_message(None, packet(sid=999999))                                       # not followed: ignored
            rec.on_message(None, {"type": "Ticker Data", "security_id": 124807})           # not a Full packet: ignored
            rec.writer.close()
            path = Path(tmp, "data", "option_ticks", "2026-10-23", "124807_POWERINDIA.csv.gz")
            lines = gzip.open(path, "rt", encoding="utf-8").read().splitlines()
            self.assertEqual(lines[0], ",".join(otr.FIELDS))
            self.assertEqual(len(lines), 3)
            self.assertEqual(rec.packets, 2)
            rec.write_health()
            self.assertEqual(json.loads(Path(tmp, "data", "option_ticks", "health.json").read_text())["contracts"], ["124807"])


class StaleTests(unittest.TestCase):
    def test_a_late_first_contract_is_not_stale_and_going_quiet_is(self):
        with tempfile.TemporaryDirectory() as tmp:
            rec = otr.Recorder(Path(tmp), "2026-10-26")
            self.assertFalse(otr.is_stale(rec, 5000.0))                                  # nothing followed yet
            class Feed:
                def subscribe_symbols(self, items):
                    self.items = items
            f = Feed()
            import time as _t
            otr.sync_subscriptions(rec, f, {"555": {"symbol": "AAA", "option_type": "CE", "strike": "100"}}, 2, 21)
            now = _t.monotonic()
            self.assertFalse(otr.is_stale(rec, now + 1))                                 # just subscribed, no packet yet: 20 minutes of process uptime must not make it look stale
            self.assertTrue(otr.is_stale(rec, now + otr.STALE_SECONDS + 5))              # a minute and more with no packet after the subscription: stale
            rec.last_packet = now + 100
            self.assertFalse(otr.is_stale(rec, now + 120))                               # a packet resets the clock

    def test_close_feed_does_not_hang_on_a_stuck_close(self):
        import time as _t

        class Stuck:
            def close_connection(self):
                _t.sleep(30)
        t0 = _t.monotonic()
        otr.close_feed(Stuck(), timeout=0.3)
        self.assertLess(_t.monotonic() - t0, 2.0)


if __name__ == "__main__":
    unittest.main()
