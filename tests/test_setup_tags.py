import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import setup_tags as stg

IST = timezone(timedelta(hours=5, minutes=30))


def bar(minute, o, h, l, c, v=1000):
    return SimpleNamespace(timestamp=datetime(2026, 10, 22, minute // 60, minute % 60, tzinfo=IST), open=o, high=h, low=l, close=c, volume=v)


def bearish_day(extra_after=True):
    """Opening range 100.0-98.0 (six bars), drift down under VWAP, then two closes under PDL 96.0 and a continuation bar."""
    cs = [bar(555 + 5 * i, 99.5, 100.0, 98.0, 99.0) for i in range(6)]
    px = [98.5, 97.8, 97.0, 96.4, 95.8, 95.5]                                     # bars from 09:45
    for k, c in enumerate(px):
        cs.append(bar(585 + 5 * k, c + 0.3, c + 0.4, c - 0.3, c))
    if extra_after:
        cs.append(bar(585 + 5 * len(px), 95.5, 95.6, 94.9, 95.0))
    return cs


class AnalyseTests(unittest.TestCase):
    def test_bearish_setup_fires_on_the_first_bar_with_everything_true(self):
        out = stg.analyse(bearish_day(), False, 105.0, 96.0)
        self.assertEqual((out["bs_setup"], out["bs_n"]), (1, 5))
        self.assertEqual(out["bs_first_time"], "10:15")                           # 10:05 and 10:10 both close under 96 x 0.9995; the 10:10 bar completes the setup at 10:15
        self.assertEqual(out["_first_close_minute"], 10 * 60 + 15)
        self.assertGreater(out["bs_since_signal_pct"], 0)                         # price is further down than the next bar's open: already moved our way

    def test_unconfirmed_and_partial_states(self):
        one_close = bearish_day(extra_after=False)[:-1]                           # stops at the first close under PDL: not yet confirmed
        out = stg.analyse(one_close, False, 105.0, 96.0)
        self.assertEqual((out["bs_pdl"], out["bs_confirm"], out["bs_setup"]), (1, 0, 0))
        self.assertNotIn("bs_first_time", out)
        early = stg.analyse(bearish_day()[:8], False, 105.0, 96.0)                # price still above the previous-day low
        self.assertEqual((early["bs_pdl"], early["bs_setup"]), (0, 0))

    def test_call_side_mirror_and_missing_data(self):
        mirror = [SimpleNamespace(timestamp=c.timestamp, open=200 - c.open, high=200 - c.low, low=200 - c.high, close=200 - c.close, volume=c.volume) for c in bearish_day()]
        out = stg.analyse(mirror, True, 104.0, 95.0)                              # PDH 104: the mirrored series closes above 104 twice
        self.assertEqual(out["bs_setup"], 1)
        self.assertEqual(stg.analyse(bearish_day(), False, 105.0, 0.0), {})        # no previous-day low
        self.assertEqual(stg.analyse(bearish_day()[:4], False, 105.0, 96.0), {})   # opening range not complete


def write_order_book(root, day, rows):
    folder = Path(root, "data", "order_book")
    folder.mkdir(parents=True)
    lines = ["time,symbol,ltp,volume,avg_price"] + [f"{day}T10:00:00+05:30,{s},{ltp},1,{avg}" for s, ltp, avg in rows]
    (folder / f"{day}.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")


class BreadthTests(unittest.TestCase):
    def setUp(self):
        stg._BREADTH.update(day=None, at=0.0, value=None)

    def test_breadth_counts_our_side_of_vwap(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows = [(f"S{i}", 99.0, 100.0) for i in range(80)] + [(f"U{i}", 101.0, 100.0) for i in range(20)]    # 80 below VWAP, 20 above
            write_order_book(tmp, "2026-10-22", rows)
            put = stg.breadth(Path(tmp), "2026-10-22", False)
            self.assertEqual((put["bs_breadth_pct"], put["bs_breadth70"]), (80.0, 1))
            stg._BREADTH.update(at=0.0)
            call = stg.breadth(Path(tmp), "2026-10-22", True)
            self.assertEqual((call["bs_breadth_pct"], call["bs_breadth70"]), (20.0, 0))

    def test_breadth_blank_without_enough_stocks_or_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(stg.breadth(Path(tmp), "2026-10-22", False), {})
            write_order_book(tmp, "2026-10-23", [("A", 1, 2)])
            stg._BREADTH.update(day=None, at=0.0)
            self.assertEqual(stg.breadth(Path(tmp), "2026-10-23", False), {})

    def test_setup_tags_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_order_book(root, "2026-10-22", [(f"S{i}", 99.0, 100.0) for i in range(60)])
            ind = root / "data" / "reports"
            ind.mkdir(parents=True)
            (ind / "daily_indicators.json").write_text('{"symbols": {"AAA": {"pdh": 105.0, "pdl": 96.0}}}', encoding="utf-8")
            stg._IND.update(mtime=None, data={})
            now = datetime(2026, 10, 22, 10, 30, tzinfo=IST)
            t = stg.setup_tags("AAA", bearish_day(), "BEARISH", now, root)
            self.assertEqual((t["bs_setup"], t["bs_first_time"], t["bs_first_ago_min"], t["bs_breadth70"]), (1, "10:15", 15, 1))
            self.assertEqual(stg.setup_tags("ZZZ", bearish_day(), "BEARISH", now, root).get("bs_setup"), None)     # unknown stock: no levels, only breadth
            self.assertEqual(stg.setup_tags("AAA", None, "BEARISH", now, root), {})


if __name__ == "__main__":
    unittest.main()
