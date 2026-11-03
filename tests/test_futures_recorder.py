import gzip
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

import futures_recorder as fr


def ms(d):
    return int(datetime(d.year, d.month, d.day, 15, 30, tzinfo=fr.IST).timestamp() * 1000)


def fut(sym, exp, key, lot=100, under="NSE_EQ|X"):
    return {"segment": "NSE_FO", "instrument_type": "FUT", "underlying_symbol": sym, "expiry": ms(exp), "instrument_key": key, "lot_size": lot, "underlying_key": under}


TODAY = date(2026, 10, 22)
MASTER = [fut("TCS", date(2026, 10, 27), "NSE_FO|1"), fut("TCS", date(2026, 11, 23), "NSE_FO|2"), fut("TCS", date(2026, 12, 29), "NSE_FO|3"),
          fut("INFY", date(2026, 10, 23), "NSE_FO|4"), fut("INFY", date(2026, 11, 23), "NSE_FO|5"),
          fut("NIFTY", date(2026, 10, 23), "NSE_FO|6", under="NSE_INDEX|Nifty 50"), fut("NIFTY", date(2026, 11, 23), "NSE_FO|7", under="NSE_INDEX|Nifty 50"),
          fut("OTHER", date(2026, 10, 27), "NSE_FO|8"), {"segment": "NSE_FO", "instrument_type": "CE", "underlying_symbol": "TCS", "expiry": ms(date(2026, 10, 27)), "instrument_key": "NSE_FO|9"},
          fut("TCS", date(2026, 10, 20), "NSE_FO|0")]


class FuturesRecorderTests(unittest.TestCase):
    def test_pick_contracts_near_next_and_expiry_rule(self):
        c = {(x["symbol"], x["contract"]): x for x in fr.pick_contracts(MASTER, ["TCS", "INFY"], TODAY, 2)}
        self.assertEqual((c["TCS", "NEAR"]["key"], c["TCS", "NEXT"]["key"], c["TCS", "NEAR"]["dte"]), ("NSE_FO|1", "NSE_FO|2", 5))
        self.assertEqual(c["INFY", "NEAR"]["key"], "NSE_FO|5")                          # the 23 Oct future is one day out: skipped for stocks
        self.assertNotIn(("INFY", "NEXT"), c)
        self.assertEqual((c["NIFTY", "NEAR"]["key"], c["NIFTY", "NEAR"]["kind"]), ("NSE_FO|6", "IDX"))   # indices keep the nearest expiry
        self.assertNotIn(("OTHER", "NEAR"), c)                                          # not in our universe
        self.assertEqual(len([x for x in c if x[0] == "TCS"]), 2)                       # expired and option rows ignored

    def test_rows_basis_and_missing_quotes(self):
        cs = fr.pick_contracts(MASTER, ["TCS"], TODAY, 2)
        q = {"NSE_FO|1": {"last_price": 102.0, "oi": 5000, "volume": 900, "average_price": 101.5, "buy_quantity": 10, "sell_quantity": 20, "ohlc": {"close": 100.0, "open": 99, "high": 103, "low": 98},
                          "depth": {"buy": [{"price": 101.9, "quantity": 5}], "sell": [{"price": 102.1, "quantity": 7}]}},
             "NSE_EQ|X": {"last_price": 100.0}, fr.VIX_KEY: {"last_price": 13.5, "ohlc": {"close": 14.0}}}
        rows = fr.rows_from_quotes(cs, q, "2026-10-22T10:00:00+05:30")
        near = [r for r in rows if r["kind"] == "STK"]
        self.assertEqual(len(near), 1)                                                  # the NEXT contract had no quote
        self.assertEqual((near[0]["basis_pct"], near[0]["oi"], near[0]["bid"], near[0]["ask_qty"]), (2.0, 5000, 101.9, 7))
        self.assertEqual([r["symbol"] for r in rows if r["kind"] == "VIX"], ["INDIAVIX"])
        no_spot = fr.rows_from_quotes(cs, {"NSE_FO|1": {"last_price": 102.0}}, "t")
        self.assertEqual(no_spot[0]["basis_pct"], "")

    def test_append_rows_writes_header_once(self):
        with tempfile.TemporaryDirectory() as d:
            row = {"captured_at": "t", "symbol": "TCS", "kind": "STK", "fut_ltp": 1.0}
            fr.append_rows(Path(d), [row])
            fr.append_rows(Path(d), [row])
            fr.append_rows(Path(d), [])
            text = gzip.open(next(Path(d).glob("*.csv.gz")), "rt", encoding="utf-8").read().splitlines()
            self.assertEqual(len(text), 3)
            self.assertTrue(text[0].startswith("captured_at,symbol"))


if __name__ == "__main__":
    unittest.main()
