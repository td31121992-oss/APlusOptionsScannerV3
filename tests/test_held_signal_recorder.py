import tempfile
import unittest
from datetime import date
from pathlib import Path

import held_signal_recorder as hs


def master_rows():
    from datetime import datetime, timezone, timedelta
    ist = timezone(timedelta(hours=5, minutes=30))
    ms = lambda y, m, d: datetime(y, m, d, 15, 29, tzinfo=ist).timestamp() * 1000
    rows = []
    for exp in (ms(2026, 11, 24), ms(2026, 12, 29)):          # one expiry too close, one usable
        for typ in ("CE", "PE"):
            for strike in (90, 95, 100, 105, 110):
                rows.append({"segment": "NSE_FO", "instrument_type": typ, "underlying_symbol": "ABC", "expiry": exp, "strike_price": strike, "instrument_key": f"K|{typ}{strike}|{int(exp)}", "lot_size": 100})
    return rows


class PickTests(unittest.TestCase):
    def setUp(self):
        self.idx = hs.index_options(master_rows())["ABC"]
        self.today = date(2026, 11, 23)

    def test_call_picks_atm_and_the_strike_below(self):
        p = hs.pick_contracts(self.idx, "BULLISH", 101.0, self.today)
        self.assertEqual([(c["kind"], c["side"], c["strike"], c["expiry"]) for c in p], [("ATM", "CE", 100.0, "2026-12-29"), ("ITM1", "CE", 95.0, "2026-12-29")])

    def test_put_picks_atm_and_the_strike_above(self):
        p = hs.pick_contracts(self.idx, "BEARISH", 101.0, self.today)
        self.assertEqual([(c["kind"], c["strike"]) for c in p], [("ATM", 100.0), ("ITM1", 105.0)])

    def test_the_expiry_two_days_away_or_less_is_skipped_and_the_edge_has_no_itm(self):
        self.assertEqual(hs.pick_contracts(self.idx, "BULLISH", 90.0, self.today)[0]["expiry"], "2026-12-29")
        self.assertEqual(len(hs.pick_contracts(self.idx, "BULLISH", 90.0, self.today)), 1)
        self.assertEqual(hs.pick_contracts(self.idx, "BULLISH", 0.0, self.today), [])


class SignalTests(unittest.TestCase):
    def test_first_signal_per_stock_and_side_in_a_tracked_group_before_1430(self):
        rows = [{"time": "2026-11-23T09:45:00", "symbol": "TCS", "direction": "BULLISH", "status": "A_PLUS_WAIT_LATE_10M_OVERHEAT", "ltp": "2443"},
                {"time": "2026-11-23T09:50:00", "symbol": "TCS", "direction": "BULLISH", "status": "PASSED_ALL_GATES", "ltp": "2450"},     # second signal, ignored
                {"time": "2026-11-23T09:50:00", "symbol": "TCS", "direction": "BEARISH", "status": "PASSED_ALL_GATES", "ltp": "2450"},
                {"time": "2026-11-23T14:35:00", "symbol": "SBIN", "direction": "BULLISH", "status": "PASSED_ALL_GATES", "ltp": "800"},    # too late
                {"time": "2026-11-23T10:00:00", "symbol": "INFY", "direction": "BULLISH", "status": "SOMETHING_ELSE", "ltp": "1500"}]
        got = hs.new_signals(rows, set())
        self.assertEqual([(s["symbol"], s["direction"], s["group"]) for s in got], [("TCS", "BULLISH", "EXTENDED_WAIT"), ("TCS", "BEARISH", "PASSED")])
        self.assertEqual(hs.new_signals(rows, {("TCS", "BULLISH"), ("TCS", "BEARISH")}), [])


class RowTests(unittest.TestCase):
    def test_rows_carry_bid_ask_and_the_stock_price(self):
        tracked = [{"symbol": "TCS", "direction": "BULLISH", "group": "EXTENDED_WAIT", "status": "S", "time": "2026-11-23T09:45:00", "spot": 2443.0, "spot_key": "NSE_EQ|X",
                    "contracts": [{"kind": "ATM", "side": "CE", "strike": 2440.0, "expiry": "2026-12-29", "lot": 225, "key": "NSE_FO|1"}]}]
        quotes = {"NSE_FO|1": {"last_price": 112.0, "volume": 5, "oi": 9, "depth": {"buy": [{"price": 110.35, "quantity": 225}], "sell": [{"price": 110.9, "quantity": 450}]}},
                  "NSE_EQ|X": {"last_price": 2460.0}}
        r = hs.rows_from_quotes(tracked, quotes, "2026-11-23T09:46:00+05:30")
        self.assertEqual(len(r), 1)
        self.assertEqual((r[0]["bid"], r[0]["ask"], r[0]["spot"], r[0]["signal_spot"]), (110.35, 110.9, 2460.0, 2443.0))
        self.assertEqual(hs.rows_from_quotes(tracked, {}, "x"), [])

    def test_append_writes_a_header_once(self):
        import gzip
        with tempfile.TemporaryDirectory() as tmp:
            row = {k: "" for k in hs.FIELDS}
            hs.append_rows(Path(tmp), [row], "2026-11-23")
            hs.append_rows(Path(tmp), [row], "2026-11-23")
            text = gzip.open(Path(tmp, "2026-11-23.csv.gz"), "rt").read().splitlines()
        self.assertEqual(len(text), 3)
        self.assertTrue(text[0].startswith("captured_at,symbol"))


if __name__ == "__main__":
    unittest.main()
