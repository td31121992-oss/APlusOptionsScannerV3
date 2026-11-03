import csv
import gzip
import tempfile
import unittest
from pathlib import Path

import upstox_chain_collector as uc


def leg(sid, ltp=10.0, oi=1000, prev=900):
    return {"security_id": sid, "ltp": ltp, "volume": 5, "oi": oi, "previous_oi": prev, "previous_close": 9.0, "bid": 9.9, "bid_qty": 100, "ask": 10.1, "ask_qty": 200,
            "iv": 30.0, "delta": 0.5, "gamma": 0.01, "theta": -1.0, "vega": 0.2, "pop": 40.0}


def chain(n=30, spot=1000.0):
    return {"expiry": "2026-10-27", "underlying_ltp": spot, "rows": [{"strike": 500.0 + 20 * k, "pcr": 1.0, "ce": leg(f"c{k}"), "pe": leg(f"p{k}") if k % 2 == 0 else None} for k in range(n)]}


class FakeClient:
    def __init__(self, fail=()):
        self.fail, self.calls = set(fail), []

    def get_option_chain(self, sid, expiry=None):
        self.calls.append((sid, expiry))
        if sid in self.fail:
            raise RuntimeError("boom")
        return chain()


class CollectorTests(unittest.TestCase):
    def test_rows_keep_strikes_around_the_money(self):
        rows = uc.rows_from_chain("TCS", 11536, chain(), "t", 3)
        strikes = sorted({r["strike"] for r in rows})
        self.assertEqual(len(strikes), 7)
        self.assertEqual(strikes[3], 1000.0)                                # the at-the-money strike is the middle one
        ce = [r for r in rows if r["side"] == "CE"][0]
        self.assertEqual((ce["oi_change"], ce["bid_qty"], ce["ask_qty"]), (100, 100, 200))
        self.assertEqual(uc.rows_from_chain("X", 1, {"rows": [], "underlying_ltp": 5}, "t", 3), [])

    def test_capture_survives_one_failing_stock_and_remembers_expiry(self):
        c = FakeClient(fail={2})
        exp = {}
        rows, failed, err = uc.capture(c, {"A": 1, "B": 2, "C": 3}, 2, 2, exp)
        self.assertEqual(failed, 1)
        self.assertIn("B", err)
        self.assertEqual({r["symbol"] for r in rows}, {"A", "C"})
        self.assertEqual(exp, {"A": "2026-10-27", "C": "2026-10-27"})
        c2 = FakeClient()
        uc.capture(c2, {"A": 1}, 2, 1, exp)
        self.assertEqual(c2.calls, [(1, "2026-10-27")])                     # next pass reuses the expiry (no lookup)

    def test_append_twice_reads_back_as_one_file_with_one_header(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows = uc.rows_from_chain("TCS", 11536, chain(), "t1", 1)
            uc.append_rows(Path(tmp), rows)
            uc.append_rows(Path(tmp), rows)
            with gzip.open(Path(tmp) / "option_chain_rows.csv.gz", "rt", encoding="utf-8", newline="") as h:
                got = list(csv.DictReader(h))
            self.assertEqual(len(got), 2 * len(rows))
            self.assertEqual(got[0]["symbol"], "TCS")


if __name__ == "__main__":
    unittest.main()
