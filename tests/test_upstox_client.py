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

    def test_candles_fall_back_and_other_calls_stay_on_dhan(self):
        dhan = FakeDhan()
        h = md.HybridClient(dhan, FakeUp(candles={"timestamp": []}))
        self.assertEqual(h.get_intraday_candles(security_id=1)["timestamp"], [1])
        self.assertEqual(h.get_option_chain(), "chain")
        self.assertEqual(h.config, "dhan-config")

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


if __name__ == "__main__":
    unittest.main()
