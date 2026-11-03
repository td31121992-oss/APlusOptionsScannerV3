import logging
import os
import unittest
from datetime import datetime, time as clock_time, timedelta
from types import SimpleNamespace as NS
from unittest import mock
from zoneinfo import ZoneInfo

import history_cache as hc
from opening_momentum_scanner import OpeningMomentumScanner

IST = ZoneInfo("Asia/Kolkata")


def setUpModule() -> None:
    logging.disable(logging.CRITICAL)                 # the scanner logger writes to logs/scanner.log: keep test chatter out of the live log


def tearDownModule() -> None:
    logging.disable(logging.NOTSET)


TODAY = datetime(2026, 10, 29, 10, 3, tzinfo=IST)


def candle_series(first_day: datetime, days: int, today_until: datetime, base: float) -> list[tuple[int, float, float, float, float, float]]:
    """5-minute candles (epoch, o, h, l, c, v): `days` completed sessions before today and today's session up to `today_until`."""
    rows = []
    d = first_day
    for k in range(days + 1):
        day = (first_day + timedelta(days=k)).replace(hour=9, minute=15)
        last = today_until if k == days else day.replace(hour=15, minute=25)
        t = day
        i = 0
        while t <= last:
            p = base + k + i * 0.01
            rows.append((int(t.timestamp()), p, p + 0.5, p - 0.5, p + 0.1, 1000.0 + i))
            t += timedelta(minutes=5)
            i += 1
    return rows


class FakeClient:
    def __init__(self, series_by_id: dict[str, list]) -> None:
        self.series = series_by_id
        self.calls: list[tuple[str, datetime, datetime]] = []
        self.fail = set()

    def get_intraday_candles(self, *, security_id, segment, instrument, interval, from_datetime, to_datetime, oi):
        self.calls.append((str(security_id), from_datetime, to_datetime))
        if str(security_id) in self.fail:
            raise RuntimeError("boom")
        rows = [r for r in self.series[str(security_id)] if from_datetime.timestamp() <= r[0] <= to_datetime.timestamp()]
        return {"timestamp": [r[0] for r in rows], "open": [r[1] for r in rows], "high": [r[2] for r in rows], "low": [r[3] for r in rows], "close": [r[4] for r in rows],
                "volume": [r[5] for r in rows]}


def make_scanner(ids=("1", "2", "3")) -> tuple[OpeningMomentumScanner, FakeClient]:
    series = {i: candle_series(datetime(2026, 10, 26, tzinfo=IST), 3, TODAY, 100.0 + int(i)) for i in ids}
    client = FakeClient(series)
    sc = OpeningMomentumScanner.__new__(OpeningMomentumScanner)
    sc.client = client
    sc.settings = NS(history_calendar_days=8, session_start=clock_time(9, 15), historical_workers=2)
    return sc, client


def quotes(ids=("1", "2", "3")):
    return [NS(symbol=f"S{i}", security_id=i) for i in ids]


def same(a, b):
    return [(c.timestamp, c.open, c.high, c.low, c.close, c.volume) for c in a] == [(c.timestamp, c.open, c.high, c.low, c.close, c.volume) for c in b]


class HelperTests(unittest.TestCase):
    def test_mode_defaults_to_off_and_rejects_garbage(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("INTRADAY_HISTORY_CACHE", None)
            self.assertEqual(hc.mode(), "OFF")
        for raw, want in (("enforce", "ENFORCE"), (" shadow ", "SHADOW"), ("yes", "OFF")):
            with mock.patch.dict(os.environ, {"INTRADAY_HISTORY_CACHE": raw}):
                self.assertEqual(hc.mode(), want)

    def test_windows_keep_the_past_request_out_of_today(self):
        pf, pt, tf, tt = hc.windows(TODAY, 8, clock_time(9, 15), IST)
        self.assertEqual(pf.date(), (TODAY - timedelta(days=8)).date())
        self.assertLess(pt.date(), TODAY.date())                      # the client then makes only the historical call
        self.assertEqual((tf.date(), tf.hour, tf.minute), (TODAY.date(), 9, 15))   # a start of today makes only the intraday call
        self.assertEqual(tt, TODAY + timedelta(minutes=1))

    def test_merge_is_ordered_unique_and_today_wins(self):
        a = [NS(timestamp=1, v="old"), NS(timestamp=2, v="old")]
        b = [NS(timestamp=2, v="new"), NS(timestamp=3, v="new")]
        m = hc.merge(a, b)
        self.assertEqual([(c.timestamp, c.v) for c in m], [(1, "old"), (2, "new"), (3, "new")])


class CachedFetchTests(unittest.TestCase):
    def test_cached_result_equals_the_full_result(self):
        sc, client = make_scanner()
        full, _ = sc._fetch_histories_full(quotes(), TODAY)
        with mock.patch.dict(os.environ, {"INTRADAY_HISTORY_CACHE": "ENFORCE"}):
            got, errors = sc._fetch_histories(quotes(), TODAY)
        self.assertEqual(errors, {})
        for sym in full:
            self.assertTrue(same(full[sym], got[sym]), sym)

    def test_past_sessions_are_fetched_once_a_day_then_only_today(self):
        sc, client = make_scanner()
        with mock.patch.dict(os.environ, {"INTRADAY_HISTORY_CACHE": "ENFORCE"}):
            sc._fetch_histories(quotes(), TODAY)
            first = len(client.calls)
            sc._fetch_histories(quotes(), TODAY + timedelta(minutes=1))
            second = len(client.calls) - first
            sc._fetch_histories(quotes(), TODAY + timedelta(minutes=2))
            third = len(client.calls) - first - second
        self.assertEqual((first, second, third), (8, 3, 3))            # first cycle: 2 calls per stock + the spot check of 2 stocks (1 call each); afterwards 1 call per stock (the old way: 3 calls every cycle, each doing two REST calls)
        today_calls = client.calls[-3:]
        self.assertTrue(all(c[1].date() == TODAY.date() for c in today_calls))

    def test_a_stock_new_to_the_shortlist_gets_its_past_once(self):
        sc, client = make_scanner(("1", "2", "3", "4"))
        with mock.patch.dict(os.environ, {"INTRADAY_HISTORY_CACHE": "ENFORCE"}):
            sc._fetch_histories(quotes(("1", "2")), TODAY)
            n = len(client.calls)
            sc._fetch_histories(quotes(("1", "2", "4")), TODAY + timedelta(minutes=1))
        self.assertEqual(len(client.calls) - n, 2 + 1 + 1)           # today for 1 and 2, past + today for 4

    def test_a_new_day_refetches_the_past(self):
        sc, client = make_scanner()
        with mock.patch.dict(os.environ, {"INTRADAY_HISTORY_CACHE": "ENFORCE"}):
            sc._fetch_histories(quotes(("1",)), TODAY)
            n = len(client.calls)
            nxt = TODAY + timedelta(days=1)
            client.series["1"] = candle_series(datetime(2026, 10, 27, tzinfo=IST), 3, nxt, 101.0)
            got, errors = sc._fetch_histories(quotes(("1",)), nxt)
        self.assertEqual(len(client.calls) - n, 2)                    # past and today again
        self.assertEqual(errors, {})
        self.assertTrue(got["S1"][-1].timestamp.date() == nxt.date())

    def test_a_failing_cached_call_falls_back_to_the_full_request_then_reports(self):
        sc, client = make_scanner()
        with mock.patch.dict(os.environ, {"INTRADAY_HISTORY_CACHE": "ENFORCE"}):
            sc._fetch_histories(quotes(("1",)), TODAY)
            client.fail.add("1")
            got, errors = sc._fetch_histories(quotes(("1",)), TODAY + timedelta(minutes=1))
        self.assertNotIn("S1", got)
        self.assertIn("S1", errors)
        sc2, client2 = make_scanner()
        flaky = {"n": 0}
        real = client2.get_intraday_candles

        def once_bad(**kw):                                           # the first (cached) call fails, the full fallback then works
            flaky["n"] += 1
            if flaky["n"] == 1:
                raise RuntimeError("transient")
            return real(**kw)
        client2.get_intraday_candles = once_bad
        with mock.patch.dict(os.environ, {"INTRADAY_HISTORY_CACHE": "ENFORCE"}):
            got2, errors2 = sc2._fetch_histories(quotes(("1",)), TODAY)
        self.assertEqual(errors2, {})
        self.assertTrue(same(got2["S1"], sc2._fetch_histories_full(quotes(("1",)), TODAY)[0]["S1"]))


class SpotCheckTests(unittest.TestCase):
    def test_every_tenth_cycle_compares_two_stocks_with_the_full_fetch(self):
        sc, client = make_scanner()
        with mock.patch.dict(os.environ, {"INTRADAY_HISTORY_CACHE": "ENFORCE"}):
            calls_per_cycle = []
            for i in range(11):
                before = len(client.calls)
                sc._fetch_histories(quotes(), TODAY + timedelta(minutes=i))
                calls_per_cycle.append(len(client.calls) - before)
        self.assertEqual(calls_per_cycle[0], 6 + 2)               # first cycle: past + today for 3 stocks, plus the spot check of 2 stocks (full request each)
        self.assertEqual(calls_per_cycle[1:10], [3] * 9)          # nine ordinary cycles: today's candles only
        self.assertEqual(calls_per_cycle[10], 3 + 2)              # the 11th cycle spot-checks again
        self.assertEqual(sc._hist_spot_stats, {"checks": 4, "different": 0})

    def test_a_difference_is_flagged_and_the_stock_is_rebuilt(self):
        sc, client = make_scanner()
        with mock.patch.dict(os.environ, {"INTRADAY_HISTORY_CACHE": "ENFORCE"}):
            sc._fetch_histories(quotes(), TODAY)
            sc._hist_cycles = 0                                    # the next cycle is a spot-check cycle
            held = sc._hist_past["S1"]
            sc._hist_past["S1"] = (held[0], [type(c)(timestamp=c.timestamp, open=c.open + 1, high=c.high + 1, low=c.low + 1, close=c.close + 1, volume=c.volume) for c in held[1]])
            sc._fetch_histories(quotes(), TODAY + timedelta(minutes=1))
        self.assertEqual(sc._hist_spot_stats["different"], 1)
        self.assertNotIn("S1", sc._hist_past)                      # dropped: rebuilt on the next cycle

    def test_the_spot_check_never_breaks_a_cycle(self):
        sc, client = make_scanner()
        with mock.patch.dict(os.environ, {"INTRADAY_HISTORY_CACHE": "ENFORCE"}):
            with mock.patch.object(type(sc), "_spot_check_history_cache", side_effect=RuntimeError("boom")):
                got, errors = sc._fetch_histories(quotes(), TODAY)
        self.assertEqual(errors, {})
        self.assertEqual(set(got), {"S1", "S2", "S3"})


class ShadowTests(unittest.TestCase):
    def test_shadow_decides_on_the_full_fetch_and_counts_matches(self):
        sc, client = make_scanner()
        full, _ = sc._fetch_histories_full(quotes(), TODAY)
        client.calls.clear()
        with mock.patch.dict(os.environ, {"INTRADAY_HISTORY_CACHE": "SHADOW"}):
            got, errors = sc._fetch_histories(quotes(), TODAY)
        self.assertTrue(all(same(full[k], got[k]) for k in full))
        self.assertEqual(sc._hist_shadow_stats, {"checks": 3, "identical": 3, "different": 0})

    def test_shadow_flags_a_difference(self):
        sc, client = make_scanner()
        real = client.get_intraday_candles

        def tampered(**kw):                                           # the "today" request returns a changed completed candle
            r = real(**kw)
            if kw["from_datetime"].date() == TODAY.date() and len(r["close"]) > 3:
                r["close"][1] += 5.0
            return r
        with mock.patch.dict(os.environ, {"INTRADAY_HISTORY_CACHE": "OFF"}):
            full, _ = sc._fetch_histories(quotes(("1",)), TODAY)
        client.get_intraday_candles = tampered
        with mock.patch.dict(os.environ, {"INTRADAY_HISTORY_CACHE": "SHADOW"}):
            sc._fetch_histories(quotes(("1",)), TODAY)
        self.assertEqual(sc._hist_shadow_stats["different"], 1)

    def test_off_is_the_old_behaviour(self):
        sc, client = make_scanner()
        os.environ.pop("INTRADAY_HISTORY_CACHE", None)
        sc._fetch_histories(quotes(), TODAY)
        sc._fetch_histories(quotes(), TODAY + timedelta(minutes=1))
        self.assertEqual(len(client.calls), 6)                        # a full request per stock every cycle
        self.assertFalse(hasattr(sc, "_hist_past"))


if __name__ == "__main__":
    unittest.main()
