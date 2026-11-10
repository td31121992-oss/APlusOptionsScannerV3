import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from core import market_data as md
from core.upstox_client import IST, UpstoxClient, UpstoxError, UpstoxLimit, _Budget

MASTER = [
    {"segment": "NSE_EQ", "instrument_type": "EQ", "exchange_token": "11536", "instrument_key": "NSE_EQ|INE467B01029", "trading_symbol": "TCS"},
    {"segment": "NSE_EQ", "instrument_type": "EQ", "exchange_token": "2885", "instrument_key": "NSE_EQ|INE002A01018", "trading_symbol": "RELIANCE"},
    {"segment": "NSE_FO", "exchange_token": "94154", "instrument_key": "NSE_FO|94154", "trading_symbol": "MCX 3400 CE"},
    {"segment": "NSE_EQ", "instrument_type": "SG", "exchange_token": "999", "instrument_key": "NSE_EQ|IN2920250163"},     # not an equity
]


class Resp:
    def __init__(self, code, body):
        self.status_code, self._b, self.text = code, body, str(body)[:100]

    def json(self):
        return self._b


class FakeSession:
    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append((url, params, headers))
        for frag, resp in self.routes.items():
            if frag in url:
                return resp(url, params) if callable(resp) else resp
        return Resp(404, {})


def quote_body():
    return {"status": "success", "data": {
        "NSE_EQ:TCS": {"instrument_token": "NSE_EQ|INE467B01029", "last_price": 2300.5, "volume": 1000,
                       "average_price": 2290.0, "oi": 0, "net_change": 25.5, "total_buy_quantity": 10, "total_sell_quantity": 20,
                       "ohlc": {"open": 2280.0, "high": 2310.0, "low": 2275.0, "close": 2300.5},          # close == last: latest close
                       "depth": {"buy": [{"quantity": 5, "price": 2300.4, "orders": 2}], "sell": [{"quantity": 6, "price": 2300.6, "orders": 3}]}},
        "NSE_FO:MCX26OCT3400CE": {"instrument_token": "NSE_FO|94154", "last_price": 120.0, "volume": 50,
                                  "ohlc": {"open": 110.0, "high": 125.0, "low": 108.0, "close": 118.0}},
        "NSE_INDEX:Nifty 50": {"instrument_token": "NSE_INDEX|Nifty 50", "last_price": 22600.0,
                               "ohlc": {"open": 22700.0, "high": 22710.0, "low": 22590.0, "close": 22721.95}}}}


class QuoteTests(unittest.TestCase):
    def client(self, session):
        return UpstoxClient(token="tok", session=session, master=MASTER, budget=_Budget(per_second=1000))

    def test_maps_and_normalises_to_dhan_shape(self):
        s = FakeSession({"/v2/market-quote/quotes": Resp(200, quote_body())})
        out = self.client(s).get_market_quotes({"NSE_EQ": [11536], "NSE_FNO": ["94154"], "IDX_I": [13]})
        tcs = out["NSE_EQ"]["11536"]
        self.assertEqual(tcs["last_price"], 2300.5)
        self.assertAlmostEqual(tcs["ohlc"]["close"], 2275.0)                  # last_price - net_change = yesterday's close
        self.assertEqual(tcs["depth"]["buy"][0]["quantity"], 5)
        self.assertEqual(out["NSE_FNO"]["94154"]["ohlc"]["close"], 118.0)
        self.assertEqual(out["IDX_I"]["13"]["ohlc"]["close"], 22721.95)
        url, params, headers = s.calls[0]
        self.assertEqual(headers["Authorization"], "Bearer tok")
        self.assertEqual(params["instrument_key"].count("|"), 3)

    def test_unknown_ids_are_skipped_and_modes_validated(self):
        s = FakeSession({"/v2/market-quote/quotes": Resp(200, {"status": "success", "data": {}})})
        c = self.client(s)
        self.assertEqual(c.get_market_quotes({"NSE_EQ": [424242]}), {})
        self.assertEqual(s.calls, [])                                          # nothing asked for, nothing sent
        with self.assertRaises(ValueError):
            c.get_market_quotes({"NSE_EQ": [11536]}, mode="depth")

    def test_http_errors(self):
        c = self.client(FakeSession({"/v2/market-quote/quotes": Resp(401, {"status": "error"})}))
        with self.assertRaises(UpstoxError):
            c.get_market_quotes({"NSE_EQ": [11536]})
        c = self.client(FakeSession({"/v2/market-quote/quotes": Resp(429, {})}))
        with self.assertRaises(UpstoxLimit):
            c.get_market_quotes({"NSE_EQ": [11536]})
        with self.assertRaises(UpstoxError):
            UpstoxClient(token="", session=FakeSession({}), master=MASTER).get_market_quotes({"NSE_EQ": [11536]})

    def test_budget_stops_runaway_calls(self):
        b = _Budget(per_second=1000, per_minute=3, per_30min=100)
        for _ in range(3):
            b.take()
        with self.assertRaises(UpstoxLimit):
            b.take()


class CandleTests(unittest.TestCase):
    def test_today_uses_intraday_endpoint_and_is_sorted_ascending_in_epoch_seconds(self):
        today = datetime.now(IST).replace(hour=9, minute=15, second=0, microsecond=0)
        rows = [[(today + timedelta(minutes=5 * i)).isoformat(), 100 + i, 101 + i, 99 + i, 100.5 + i, 1000 + i, 0] for i in (2, 1, 0)]   # newest first
        s = FakeSession({"/v3/historical-candle/intraday/": Resp(200, {"status": "success", "data": {"candles": rows}})})
        c = UpstoxClient(token="", session=s, master=MASTER, budget=_Budget(per_second=1000))
        out = c.get_intraday_candles(security_id=11536, segment="NSE_EQ", instrument="EQUITY", interval=5,
                                     from_datetime=today.replace(hour=9, minute=0), to_datetime=today + timedelta(hours=1))
        self.assertEqual(len(out["timestamp"]), 3)
        self.assertEqual(out["timestamp"], sorted(out["timestamp"]))
        self.assertEqual(out["open"][0], 100.0)
        self.assertEqual(out["volume"][2], 1002.0)
        self.assertNotIn("Authorization", s.calls[0][2])                       # candles need no token
        self.assertIn("/minutes/5", s.calls[0][0])

    def test_history_plus_today_are_merged(self):
        now = datetime.now(IST)
        yday = (now - timedelta(days=1)).replace(hour=9, minute=15, second=0, microsecond=0)
        td = now.replace(hour=9, minute=15, second=0, microsecond=0)
        hist = Resp(200, {"data": {"candles": [[yday.isoformat(), 1, 2, 0.5, 1.5, 10, 0]]}})
        intr = Resp(200, {"data": {"candles": [[td.isoformat(), 3, 4, 2.5, 3.5, 20, 0]]}})
        s = FakeSession({"/v3/historical-candle/intraday/": intr, "/v3/historical-candle/NSE_EQ": hist})
        c = UpstoxClient(token="", session=s, master=MASTER, budget=_Budget(per_second=1000))
        out = c.get_intraday_candles(security_id=11536, segment="NSE_EQ", instrument="EQUITY", interval=5,
                                     from_datetime=yday.replace(hour=9, minute=0), to_datetime=now + timedelta(minutes=1), oi=True)
        self.assertEqual(out["close"], [1.5, 3.5])
        self.assertEqual(len(out["open_interest"]), 2)

    def test_bad_arguments(self):
        c = UpstoxClient(token="", session=FakeSession({}), master=MASTER)
        t = datetime.now(IST)
        with self.assertRaises(ValueError):
            c.get_intraday_candles(security_id=11536, segment="NSE_EQ", interval=7, from_datetime=t, to_datetime=t + timedelta(hours=1))
        with self.assertRaises(UpstoxError):
            c.get_intraday_candles(security_id=1, segment="NSE_EQ", interval=5, from_datetime=t, to_datetime=t + timedelta(hours=1))


class FakeDhan:
    def __init__(self):
        self.q, self.c = 0, 0
        self.config = "dhan-config"

    def get_market_quotes(self, instruments, mode="quote"):
        self.q += 1
        return {"NSE_EQ": {"11536": {"last_price": 2300.0, "ohlc": {"close": 2275.0}, "volume": 1000}}}

    def get_intraday_candles(self, **kw):
        self.c += 1
        return {"timestamp": [1], "open": [1], "high": [1], "low": [1], "close": [1], "volume": [1]}

    def get_option_chain(self, *a, **k):
        return "chain"


class FakeUp:
    def __init__(self, quotes=None, error=None, candles=None):
        self.quotes, self.error, self.candles = quotes, error, candles

    def get_market_quotes(self, instruments, mode="quote"):
        if self.error:
            raise self.error
        return self.quotes

    def get_intraday_candles(self, **kw):
        if self.error:
            raise self.error
        return self.candles


GOOD = {"NSE_EQ": {"11536": {"last_price": 2301.0, "ohlc": {"close": 2275.0}, "volume": 1010}}}


class HybridTests(unittest.TestCase):
    def test_uses_upstox_when_complete_and_falls_back_otherwise(self):
        dhan = FakeDhan()
        h = md.HybridClient(dhan, FakeUp(quotes=GOOD))
        self.assertEqual(h.get_market_quotes({"NSE_EQ": [11536]})["NSE_EQ"]["11536"]["last_price"], 2301.0)
        self.assertEqual(dhan.q, 0)
        h2 = md.HybridClient(dhan, FakeUp(error=UpstoxError("HTTP 401")))
        self.assertEqual(h2.get_market_quotes({"NSE_EQ": [11536]})["NSE_EQ"]["11536"]["last_price"], 2300.0)
        self.assertEqual((dhan.q, h2.stats["upstox_quote_fallback"]), (1, 1))
        h3 = md.HybridClient(dhan, FakeUp(quotes={"NSE_EQ": {}}))                      # empty answer
        self.assertEqual(h3.get_market_quotes({"NSE_EQ": [11536]})["NSE_EQ"]["11536"]["last_price"], 2300.0)

    def test_partial_answer_is_gap_filled_before_falling_back(self):
        class Partial:
            def __init__(self):
                self.calls = []

            def get_market_quotes(self, instruments, mode="quote"):
                self.calls.append({k: list(v) for k, v in instruments.items()})
                ids = [str(i) for i in instruments["NSE_EQ"]]
                # first call returns only the first half; later calls return what is asked for
                keep = ids[: len(ids) // 2] if len(self.calls) == 1 else ids
                return {"NSE_EQ": {i: {"last_price": 10.0} for i in keep}}

        dhan = FakeDhan()
        up = Partial()
        h = md.HybridClient(dhan, up)
        out = h.get_market_quotes({"NSE_EQ": list(range(1, 11))})
        self.assertEqual(len(out["NSE_EQ"]), 10)
        self.assertEqual(dhan.q, 0)                                               # Upstox completed it, no Dhan call
        self.assertEqual(len(up.calls), 2)
        self.assertEqual(sorted(up.calls[1]["NSE_EQ"]), sorted(str(i) for i in range(6, 11)))   # the second call asked only for the gaps
        self.assertEqual(h.stats["upstox_quote_gapfilled"], 1)

    def test_candles_fall_back_and_other_calls_stay_on_dhan(self):
        dhan = FakeDhan()
        h = md.HybridClient(dhan, FakeUp(candles={"timestamp": []}))
        self.assertEqual(h.get_intraday_candles(security_id=1)["timestamp"], [1])
        self.assertEqual(h.get_option_chain(2885, "2026-11-23"), "chain")                # FakeUp has no chain -> falls back to Dhan
        self.assertEqual(h.config, "dhan-config")

    def test_option_chain_comes_from_upstox_in_the_dhan_shape(self):
        rows = [{"strike": 100.0 + 5 * i, "pcr": 1.0,
                 "ce": {"security_id": str(1000 + i), "ltp": 12.5, "volume": 10, "oi": 500, "previous_oi": 400, "previous_close": 11.0, "bid": 12.4, "bid_qty": 50,
                        "ask": 12.6, "ask_qty": 60, "iv": 30.0, "delta": 0.5, "gamma": 0.01, "theta": -0.2, "vega": 0.1, "pop": 40.0},
                 "pe": None} for i in range(8)]

        class Chain:
            def __init__(self, data):
                self.data = data

            def get_option_chain(self, security_id, expiry=None, segment="NSE_EQ"):
                return self.data

        dhan = FakeDhan()
        h = md.HybridClient(dhan, Chain({"expiry": "2026-11-23", "underlying_ltp": 120.0, "rows": rows}))
        out = h.get_option_chain(2885, "2026-11-23")
        self.assertEqual(out["status"], "success")
        self.assertEqual(out["data"]["last_price"], 120.0)
        leg = out["data"]["oc"]["100.000000"]["ce"]
        self.assertEqual((leg["security_id"], leg["last_price"], leg["top_bid_price"], leg["top_ask_price"], leg["implied_volatility"]), (1000, 12.5, 12.4, 12.6, 30.0))
        self.assertNotIn("pe", out["data"]["oc"]["100.000000"])                           # a missing leg is left out, as Dhan does
        self.assertEqual(h.stats["upstox_chain_ok"], 1)
        # the scanner's own parser reads it unchanged
        with mock.patch.dict(os.environ, {}):                  # importing the scanner modules loads .env; put the environment back afterwards
            from core.option_chain import OptionChainService

            snap = OptionChainService(client=None).normalize(underlying=type("U", (), {"symbol": "ZZZ", "security_id": 2885, "contracts": []})(), expiry="2026-11-23", response=out)
        self.assertEqual((len(snap.strikes), snap.underlying_ltp, snap.strikes[0].call.bid, snap.strikes[0].call.security_id), (8, 120.0, 12.4, "1000"))

    def test_thin_or_failed_option_chain_falls_back_to_dhan(self):
        class Chain:
            def __init__(self, data=None, error=None):
                self.data, self.error = data, error

            def get_option_chain(self, security_id, expiry=None, segment="NSE_EQ"):
                if self.error:
                    raise self.error
                return self.data

        dhan = FakeDhan()
        thin = {"expiry": "2026-11-23", "underlying_ltp": 120.0, "rows": [{"strike": 100.0, "pcr": 1.0, "ce": None, "pe": None}]}
        self.assertEqual(md.HybridClient(dhan, Chain(thin)).get_option_chain(1, "2026-11-23"), "chain")
        h = md.HybridClient(dhan, Chain(error=UpstoxError("HTTP 429")))
        self.assertEqual(h.get_option_chain(1, "2026-11-23"), "chain")
        self.assertEqual(h.stats["upstox_chain_fallback"], 1)

    def test_provider_switch_defaults_to_dhan(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("APLUS_DATA_PROVIDER", None)
            os.environ.pop("APLUS_UPSTOX_SHADOW", None)
            self.assertEqual(md.provider(), "DHAN")
            self.assertFalse(md.shadow_enabled())
        with mock.patch.dict(os.environ, {"APLUS_DATA_PROVIDER": "nonsense"}):
            self.assertEqual(md.provider(), "DHAN")
        with mock.patch.dict(os.environ, {"APLUS_DATA_PROVIDER": "upstox", "APLUS_UPSTOX_SHADOW": "1"}):
            self.assertEqual((md.provider(), md.shadow_enabled()), ("UPSTOX", True))


class ShadowTests(unittest.TestCase):
    def test_returns_dhan_data_and_logs_the_difference(self):
        with tempfile.TemporaryDirectory() as tmp:
            dhan = FakeDhan()
            sh = md.ShadowClient(dhan, FakeUp(quotes=GOOD), out_dir=Path(tmp), min_gap_seconds=0)
            out = sh.get_market_quotes({"NSE_EQ": [11536]})
            self.assertEqual(out["NSE_EQ"]["11536"]["last_price"], 2300.0)             # trading still uses Dhan
            for _ in range(50):                                                          # wait for the background thread
                files = list(Path(tmp).glob("*.csv"))
                if files and len(files[0].read_text().splitlines()) >= 2:
                    break
                import time
                time.sleep(0.05)
            lines = files[0].read_text().splitlines()
            self.assertIn("median_ltp_diff_pct", lines[0])
            self.assertTrue(lines[1].split(",")[2] == "1")                              # matched
            self.assertAlmostEqual(float(lines[1].split(",")[4]), 0.0435, places=3)    # |2301/2300-1|*100


class OptionChainTests(unittest.TestCase):
    def client(self, routes):
        return UpstoxClient(token="t", session=FakeSession(routes), master=MASTER, budget=_Budget(1000, 100000, 100000))

    def test_expiries_and_nearest_chain(self):
        leg = {"instrument_key": "NSE_FO|129677", "market_data": {"ltp": 159.7, "volume": 10, "oi": 841050.0, "close_price": 167.9, "bid_price": 159.2, "bid_qty": 225,
                                                                  "ask_price": 161.6, "ask_qty": 450, "prev_oi": 931050.0},
               "option_greeks": {"vega": 0.5, "theta": -0.9, "gamma": 0.001, "delta": 0.93, "iv": 31.0, "pop": 47.8}}
        routes = {"/v2/option/contract": Resp(200, {"status": "success", "data": [{"expiry": "2026-11-23"}, {"expiry": "2026-10-27"}, {"expiry": "2020-01-01"}]}),
                  "/v2/option/chain": Resp(200, {"status": "success", "data": [
                      {"strike_price": 2400.0, "pcr": 1.5, "underlying_spot_price": 2460.9, "call_options": leg, "put_options": None},
                      {"strike_price": 2300.0, "pcr": 2.0, "underlying_spot_price": 2460.9, "call_options": None, "put_options": leg}]})}
        c = self.client(routes)
        self.assertEqual(c.get_expiries(11536), ["2020-01-01", "2026-10-27", "2026-11-23"])
        ch = c.get_option_chain(11536, "2026-10-27")
        self.assertEqual([r["strike"] for r in ch["rows"]], [2300.0, 2400.0])             # sorted
        self.assertEqual(ch["underlying_ltp"], 2460.9)
        ce = ch["rows"][1]["ce"]
        self.assertEqual((ce["security_id"], ce["bid_qty"], ce["ask_qty"], ce["previous_oi"], ce["delta"], ce["iv"]), ("129677", 225, 450, 931050, 0.93, 31.0))
        self.assertIsNone(ch["rows"][1]["pe"])
        params = c._session.calls[-1][1]
        self.assertEqual((params["instrument_key"], params["expiry_date"]), ("NSE_EQ|INE467B01029", "2026-10-27"))

    def test_unknown_underlying_and_no_token(self):
        with self.assertRaises(UpstoxError):
            self.client({}).get_option_chain(1)
        with self.assertRaises(UpstoxError):
            UpstoxClient(token="", session=FakeSession({"/v2/option/contract": Resp(200, {"data": []})}), master=MASTER).get_expiries(11536)


if __name__ == "__main__":
    unittest.main()


class UpstoxOnlyClientTests(unittest.TestCase):
    """Dhan plan expired (3 Nov 2026): with APLUS_DATA_PROVIDER=UPSTOX the scanner builds a client that never touches Dhan."""

    def test_build_client_is_upstox_only_unless_fallback_is_switched_on(self):
        import core.market_data as md

        class Cfg:
            dhan = object()                       # a Dhan client built from this would blow up: it must not be built

        fake = mock.Mock()
        fake.token = "t"
        with mock.patch.dict(os.environ, {"APLUS_DATA_PROVIDER": "UPSTOX"}, clear=False), mock.patch("core.upstox_client.UpstoxClient", return_value=fake):
            os.environ.pop("APLUS_DHAN_FALLBACK", None)
            client = md.build_client(Cfg())
        self.assertIsInstance(client, md.UpstoxOnlyClient)
        self.assertEqual(client.get_fund_limits(), {})
        self.assertEqual(client.get_positions(), [])

    def test_upstox_401_becomes_the_authorization_error_the_scanner_latches_on(self):
        import core.market_data as md
        from core.dhan_client import DhanMarketDataAuthorizationError
        from core.upstox_client import UpstoxError

        fake = mock.Mock()
        fake.get_market_quotes.side_effect = UpstoxError("HTTP 401: Invalid token")
        with self.assertRaises(DhanMarketDataAuthorizationError):
            md.UpstoxOnlyClient(fake).get_market_quotes({"NSE_EQ": ["2885"]})

    def test_empty_candles_and_thin_quotes_raise_instead_of_returning_nothing(self):
        import core.market_data as md

        fake = mock.Mock()
        fake.get_intraday_candles.return_value = {}
        with self.assertRaises(RuntimeError):
            md.UpstoxOnlyClient(fake).get_intraday_candles(security_id="1", segment="NSE_EQ", interval=5)
        fake.get_market_quotes.return_value = {}
        with mock.patch.object(md.time, "sleep"), self.assertRaises(RuntimeError):
            md.UpstoxOnlyClient(fake).get_market_quotes({"NSE_EQ": ["1"]})


class UpstoxRetryTests(unittest.TestCase):
    def test_a_timed_out_connection_is_retried_and_other_errors_are_not(self):
        class Timeout(Exception):
            pass

        class Resp:
            status_code = 200

            def json(self):
                return {"status": "success", "data": {}}

        class Session:
            calls = 0

            def get(self, *a, **k):
                Session.calls += 1
                if Session.calls < 3:
                    raise Timeout("slow")
                return Resp()

        client = UpstoxClient(token="t", session=Session(), master=[])
        with mock.patch("core.upstox_client.time.sleep"):
            self.assertEqual(client._get("/x", {}, auth=False)["status"], "success")
        self.assertEqual(Session.calls, 3)

        class Boom:
            def get(self, *a, **k):
                raise ValueError("not a network error")

        with self.assertRaises(ValueError):
            UpstoxClient(token="t", session=Boom(), master=[])._get("/x", {}, auth=False)


class PooledSessionTests(unittest.TestCase):
    def test_default_client_reuses_one_session_and_can_be_switched_off(self):
        import requests
        from unittest import mock

        c = UpstoxClient(token="t", master=[])
        first = c._http()
        self.assertIsInstance(first, requests.Session)
        self.assertIs(c._http(), first)
        with mock.patch.dict("os.environ", {"APLUS_UPSTOX_POOL": "0"}):
            self.assertIs(UpstoxClient(token="t", master=[])._http(), requests)

    def test_injected_session_is_still_used(self):
        s = object()
        self.assertIs(UpstoxClient(token="t", session=s, master=[])._http(), s)
