import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

import breakout_board as bb
import rs_leaders as rs

DAY = "2026-10-26"


def row(**kw):
    r = {"m": 1.0, "rs": 2.0, "vw": 0.5, "rv": 3.0, "a2": 0.3, "ltp": 101.0, "sec": "IT", "rss": 0.5, "rsi": None}
    r.update(kw)
    return r


AMT = {"ib_done": True, "ib_hi": 100.5, "ib_lo": 98.0}
ML = {"1": {"or_status": 1.0}, "-1": {"or_status": 1.0}}                                     # directional: +1 = beyond the opening range in that side's direction
LV = {"pdh": 100.0, "pdl": 97.0}
CH = {"ce_spread": 1.2, "pe_spread": 3.5}


class EvaluateTests(unittest.TestCase):
    def test_full_breakout_scores_six(self):
        e = bb.evaluate("AAA", 1, row(), 0.2, AMT, ML, LV, CH)
        self.assertEqual(sorted(e["levels"]), ["IB", "OR", "PDH"])
        self.assertAlmostEqual(e["break_pct"], (101.0 / 100.5 - 1) * 100, places=2)             # beyond the HIGHEST level it broke (the IB high)
        self.assertEqual(e["score"], 6)
        self.assertTrue(all(e["checks"].values()))
        self.assertEqual(e["opt_spread"], 1.2)

    def test_each_check_can_fail(self):
        base = lambda **kw: bb.evaluate("AAA", 1, row(**kw), kw.pop("mk", 0.2) if False else 0.2, AMT, ML, LV, CH)
        self.assertFalse(base(rv=1.2)["checks"]["volume"])
        self.assertFalse(base(vw=-0.1)["checks"]["vwap"])
        self.assertFalse(base(rs=0.5)["checks"]["strength"])
        self.assertFalse(base(rss=-0.4)["checks"]["strength"])                                   # ahead of the market but behind its own sector
        self.assertFalse(base(ltp=100.55, rs=2.0)["checks"]["decisive"])                          # only 0.05 % beyond the IB high
        e = bb.evaluate("AAA", 1, row(), -1.0, AMT, ML, LV, CH)                                   # a falling market, but the stock is 2 % ahead: still allowed
        self.assertTrue(e["checks"]["market"])
        e = bb.evaluate("AAA", 1, row(rs=0.4, rss=0.4), -1.0, AMT, ML, LV, CH)
        self.assertFalse(e["checks"]["market"])
        self.assertFalse(bb.evaluate("AAA", 1, row(), 0.2, AMT, ML, LV, {"ce_spread": 3.0})["checks"]["options"])
        self.assertFalse(bb.evaluate("AAA", 1, row(), 0.2, AMT, ML, LV, None)["checks"]["options"])

    def test_no_level_no_row(self):
        self.assertIsNone(bb.evaluate("AAA", 1, row(ltp=99.0), 0.2, {"ib_done": False, "ib_hi": 100.5, "ib_lo": 98.0}, {"1": {"or_status": 0.0}}, LV, CH))
        self.assertIsNone(bb.evaluate("AAA", 1, row(ltp=0), 0.2, AMT, ML, LV, CH))

    def test_breakdown_mirror(self):
        r = row(ltp=96.5, m=-3.0, rs=-2.5, vw=-0.6, rss=-0.7, a2=-0.4)
        e = bb.evaluate("BBB", -1, r, -0.5, {"ib_done": True, "ib_hi": 101.0, "ib_lo": 97.5}, ML, LV, CH)
        self.assertEqual(sorted(e["levels"]), ["IB", "OR", "PDL"])
        self.assertAlmostEqual(e["break_pct"], (97.0 / 96.5 - 1) * 100, places=2)                 # beyond the lowest... the HIGHER of the two lows is the demanding one for a breakdown
        self.assertEqual((e["rs"], e["acc2"], e["rs_sector"]), (2.5, 0.4, 0.7))                   # shown in the trade's direction
        self.assertTrue(e["checks"]["vwap"])
        self.assertFalse(e["checks"]["options"])                                                  # the put side spread is 3.5 %


class PayloadTests(unittest.TestCase):
    def setUp(self):
        bb._CACHE.clear()

    def test_payload_from_live_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            t = root / "data" / "ticks"
            t.mkdir(parents=True)
            stocks = {"UP": row(), "DOWN": row(ltp=96.0, m=-4.0, rs=-3.0, vw=-0.5, rss=-1.0), "QUIET": row(ltp=99.0, rs=0.2)}
            (t / "rs_all.json").write_text(json.dumps({"day": DAY, "updated": "10:30:00", "market": {"median": -0.4, "pct_down": 60.0, "n": 213}, "stocks": stocks}), encoding="utf-8")
            (t / "amt_live.json").write_text(json.dumps({"day": DAY, "stocks": {"UP": AMT, "DOWN": {"ib_done": True, "ib_hi": 101.0, "ib_lo": 97.5}}}), encoding="utf-8")
            (t / "ml_features_live.json").write_text(json.dumps({"day": DAY, "stocks": {"UP": {"1": {"or_status": 1.0}, "-1": {"or_status": 0.0}}, "DOWN": {"1": {"or_status": 0.0}, "-1": {"or_status": 1.0}}}}), encoding="utf-8")
            r = root / "data" / "reports"
            r.mkdir(parents=True)
            (r / "daily_indicators.json").write_text(json.dumps({"symbols": {k: {"pdh": 100.0, "pdl": 97.0} for k in stocks}}), encoding="utf-8")
            out = bb.payload(root, date(2026, 10, 26))
            self.assertTrue(out["ok"])
            self.assertEqual([x["s"] for x in out["breakouts"]], ["UP"])
            self.assertEqual([x["s"] for x in out["breakdowns"]], ["DOWN"])
            self.assertEqual((out["n_breakouts"], out["n_breakdowns"]), (1, 1))
            self.assertFalse(bb.payload(root, date(2026, 10, 27))["ok"])                           # another day's file is not today's

    def test_missing_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(bb.payload(Path(tmp), date(2026, 10, 26))["ok"])


class WriterTests(unittest.TestCase):
    def test_tracker_writes_rs_all(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ref = {f"S{i}": {"prev_close": 100.0, "avg_vol20": 1_000_000.0} for i in range(120)}
            tr = rs.RSTracker(ref, {"S0": "IT"})
            for i in range(120):
                tr.update(f"S{i}", "10:00:00.000", 99.0 if i else 101.5, 150_000, 99.2)
            tr.maybe_write(root, DAY, wall=100.0, now_s=36000.0)
            d = json.loads(root.joinpath("data", "ticks", "rs_all.json").read_text(encoding="utf-8"))
            self.assertEqual((d["day"], len(d["stocks"])), (DAY, 120))
            self.assertEqual(set(d["stocks"]["S0"]), {"m", "rs", "vw", "rv", "a2", "ltp", "sec", "rss", "rsi"})
            self.assertEqual(d["stocks"]["S0"]["sec"], "IT")
            self.assertGreater(d["stocks"]["S0"]["rs"], 2.0)


if __name__ == "__main__":
    unittest.main()
