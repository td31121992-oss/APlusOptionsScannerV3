import json
import struct
import threading
import time
import unittest

import upstox_feed as uf


# --- a tiny protobuf encoder, only for building test frames
def _v(n):
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)


def _key(field, wire):
    return _v((field << 3) | wire)


def f_d(field, x):
    return _key(field, 1) + struct.pack("<d", x)


def f_i(field, n):
    return _key(field, 0) + _v(n)


def f_m(field, payload):
    return _key(field, 2) + _v(len(payload)) + payload


def f_s(field, text):
    return f_m(field, text.encode())


def ltpc(ltp, ltt, ltq, cp):
    return f_d(1, ltp) + f_i(2, ltt) + f_i(3, ltq) + f_d(4, cp)


def quote(bq, bp, aq, ap):
    return f_i(1, bq) + f_d(2, bp) + f_i(3, aq) + f_d(4, ap)


def response(feeds, rtype=0):
    body = f_i(1, rtype) if rtype else b""
    for k, feed in feeds.items():
        body += f_m(2, f_s(1, k) + f_m(2, feed))
    return body + f_i(3, 1793131850846)


STOCK = "NSE_EQ|INE002A01018"
OPT = "NSE_FO|125987"
IDX = "NSE_INDEX|Nifty 50"
LTT_MS = 1793095798902        # 2026-10-27 15:39:58 IST


def stock_feed():
    levels = b"".join(f_m(1, quote(*q)) for q in [(500, 45.4, 1000, 45.75), (1000, 45.35, 6000, 45.8)])
    mff = f_m(1, ltpc(45.7, LTT_MS, 500, 48.8)) + f_m(2, levels) + f_d(5, 42.61) + f_i(6, 13171500) + f_d(7, 11068000.0) + f_d(9, 274000.0) + f_d(10, 286500.0)
    return f_m(2, f_m(1, mff)) + f_i(4, 1)           # Feed.fullFeed.marketFF, requestMode


class DecodeTests(unittest.TestCase):
    def resolver(self, key):
        return {STOCK: ("NSE_EQ", "2885"), OPT: ("NSE_FNO", "125987"), IDX: ("IDX_I", "13")}.get(key)

    def test_full_feed_becomes_a_dhan_shaped_packet(self):
        resp = uf.decode("FeedResponse", response({OPT: stock_feed()}))
        (p,) = uf.packets_from_response(resp, self.resolver)
        self.assertEqual((p["type"], p["exchange_segment"], p["security_id"]), ("Full Data", "NSE_FNO", "125987"))
        self.assertEqual((p["LTP"], p["LTQ"], p["LTT"], p["volume"], p["OI"]), (45.7, 500, "15:39:58", 13171500, 11068000))
        self.assertEqual((p["total_buy_quantity"], p["total_sell_quantity"], p["avg_price"], p["prev_close"]), (274000, 286500, 42.61, 48.8))
        self.assertEqual(len(p["depth"]), 2)
        self.assertEqual(p["depth"][0], {"bid_quantity": 500, "bid_price": 45.4, "ask_quantity": 1000, "ask_price": 45.75})

    def test_index_gives_a_ticker_and_one_previous_close(self):
        frame = response({IDX: f_m(1, ltpc(22749.75, 1793097000000, 0, 22753.2))})
        sent = set()
        first = uf.packets_from_response(uf.decode("FeedResponse", frame), self.resolver, sent)
        self.assertEqual([x["type"] for x in first], ["Ticker Data", "Previous Close"])
        self.assertEqual((first[0]["security_id"], first[0]["exchange_segment"], first[0]["LTP"], first[1]["prev_close"]), (13, 0, 22749.75, 22753.2))
        again = uf.packets_from_response(uf.decode("FeedResponse", frame), self.resolver, sent)
        self.assertEqual([x["type"] for x in again], ["Ticker Data"])                  # the previous close is sent once

    def test_market_info_and_unknown_keys_give_nothing(self):
        info = f_i(1, 2) + f_m(4, f_m(1, f_s(1, "NSE_EQ") + f_i(2, 5)))
        self.assertEqual(uf.packets_from_response(uf.decode("FeedResponse", info), self.resolver), [])
        stranger = uf.decode("FeedResponse", response({"NSE_EQ|UNKNOWN": stock_feed()}))
        self.assertEqual(uf.packets_from_response(stranger, self.resolver), [])

    def test_missing_fields_default_to_zero_and_garbage_does_not_raise(self):
        lonely = uf.decode("FeedResponse", response({STOCK: f_m(2, f_m(1, f_m(1, ltpc(10.0, 0, 0, 0.0))))}))
        (p,) = uf.packets_from_response(lonely, self.resolver)
        self.assertEqual((p["LTP"], p["volume"], p["total_sell_quantity"], p["depth"], p["LTT"]), (10.0, 0, 0, [], ""))
        with self.assertRaises(Exception):
            uf.decode("FeedResponse", b"\x0a\xff")                                     # truncated: the feed catches this per frame


class FakeClient:
    token = "t"
    _reverse = {STOCK: ("NSE_EQ", "2885"), OPT: ("NSE_FNO", "125987"), IDX: ("IDX_I", "13")}

    def _build_maps(self):
        return {}

    def instrument_key(self, segment, security_id):
        return {("NSE_EQ", "2885"): STOCK, ("NSE_FNO", "125987"): OPT, ("IDX_I", "13"): IDX}.get((segment, str(int(float(security_id)))))


class FakeSocket:
    def __init__(self, frames):
        self.frames, self.sent, self.closed = list(frames), [], False

    def send(self, data):
        self.sent.append(data)

    def recv(self, timeout=None):
        if self.frames:
            return self.frames.pop(0)
        time.sleep(0.02)
        raise TimeoutError

    def close(self):
        self.closed = True


class FeedTests(unittest.TestCase):
    def test_subscribes_receives_and_resubscribes_new_instruments(self):
        got, errors = [], []
        sock = FakeSocket([response({OPT: stock_feed()}), b"\x0a\xff", response({IDX: f_m(1, ltpc(22749.75, 1793097000000, 0, 22753.2))})])
        feed = uf.UpstoxMarketFeed([("NSE_EQ", "2885", "full"), ("IDX_I", "13", "ticker")], lambda f, d: got.append(d), lambda f, e: errors.append(e),
                                   client=FakeClient(), connect=lambda uri: sock)
        feed._authorize = lambda: "wss://example.invalid/feed"
        feed.start()
        for _ in range(100):
            if len(got) >= 3:
                break
            time.sleep(0.02)
        feed.subscribe_symbols([("NSE_FNO", "125987", "full")])
        feed.close_connection()
        self.assertEqual([p["type"] for p in got], ["Full Data", "Ticker Data", "Previous Close"])   # the bad frame was skipped, the connection survived
        self.assertTrue(errors)                                                                  # ...and reported
        subs = [json.loads(x) for x in sock.sent]
        self.assertTrue(all(isinstance(x, bytes) for x in sock.sent))                            # sent as binary frames
        full = [s for s in subs if s["data"]["mode"] == "full"]
        ltpc_ = [s for s in subs if s["data"]["mode"] == "ltpc"]
        self.assertEqual(full[0]["method"], "sub")
        self.assertIn(STOCK, full[0]["data"]["instrumentKeys"])
        self.assertEqual(ltpc_[0]["data"]["instrumentKeys"], [IDX])
        self.assertIn(OPT, [k for s in full for k in s["data"]["instrumentKeys"]])               # added after connecting
        self.assertTrue(sock.closed)

    def test_reconnects_after_the_connection_drops(self):
        opened = []

        class Dropping(FakeSocket):
            def recv(self, timeout=None):
                if not opened[1:]:
                    raise ConnectionError("dropped")
                return super().recv(timeout)

        def connect(uri):
            sock = Dropping([])
            opened.append(sock)
            return sock

        feed = uf.UpstoxMarketFeed([("NSE_EQ", "2885", "full")], lambda f, d: None, None, client=FakeClient(), connect=connect)
        feed._authorize = lambda: "wss://example.invalid/feed"
        original_wait = feed._closed.wait
        feed._closed.wait = lambda timeout=None: original_wait(0.01)                              # do not sit out the 2 s backoff in a test
        feed.start()
        for _ in range(200):
            if len(opened) >= 2:
                break
            time.sleep(0.02)
        feed.close_connection()
        self.assertGreaterEqual(len(opened), 2)
        self.assertGreaterEqual(feed.reconnects, 1)
        self.assertTrue(any(json.loads(x)["data"]["instrumentKeys"] == [STOCK] for x in opened[1].sent))   # everything is subscribed again on the new connection

    def test_provider_switch(self):
        import os
        from unittest import mock

        with mock.patch.dict(os.environ, {"APLUS_DATA_PROVIDER": "UPSTOX"}):
            self.assertEqual(uf.feed_provider(), "UPSTOX")
        with mock.patch.dict(os.environ, {"APLUS_DATA_PROVIDER": "DHAN"}):
            self.assertEqual(uf.feed_provider(), "DHAN")


if __name__ == "__main__":
    unittest.main()
