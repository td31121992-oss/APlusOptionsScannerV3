import csv
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import base_break as bb

IST = timezone(timedelta(hours=5, minutes=30))


def series(n_flat=24, base=100.0, wobble=0.2, breakout=1.0):
    """09:15 onwards in 5-minute closes: a drift up to the base, a 30-minute base, then a break bar."""
    s = [100.0 + 0.1 * i for i in range(n_flat - 8)]
    top = s[-1]
    s += [top + wobble * (1 if i % 2 else -1) for i in range(8)]
    s += [max(s[-8:]) * (1 + breakout / 100.0)]
    return s


class CheckTests(unittest.TestCase):
    def test_bull_break_in_a_red_market(self):
        s = series()
        n = len(s)
        self.assertEqual(bb.OPEN_MIN + bb.BAR_MIN * (n - 1) >= bb.FIRST_MIN, True)
        e = bb.check(s, 1, -2.0, 0.1)
        self.assertIsNotNone(e)
        self.assertEqual(e["side"], 1)
        self.assertGreaterEqual(e["break_pct"], bb.BREAK_PCT)
        self.assertGreaterEqual(e["rs"], bb.MIN_RS)

    def test_each_condition_is_needed(self):
        s = series()
        self.assertIsNone(bb.check(s, 1, -0.2, 0.1))                                    # the market is not red enough
        self.assertIsNone(bb.check(s, 1, -2.0, 0.6))                                    # too many stocks are up
        self.assertIsNone(bb.check(series(wobble=2.0), 1, -2.0, 0.1))                   # no tight base
        self.assertIsNone(bb.check(series(breakout=0.05), 1, -2.0, 0.1))                # no break
        self.assertIsNone(bb.check(series()[:-1], 1, -2.0, 0.1))                        # the last bar is still inside the base
        weak = [110.0] + series()[1:]                                                   # opened high and fell: down on the day, not ahead of the market
        self.assertIsNone(bb.check(weak, 1, -2.0, 0.1))                                 # not ahead of the market
        self.assertIsNotNone(bb.check(s, 1, -0.2, 0.1, gate=False))                     # the market gate can be switched off (back-test variant)

    def test_bear_mirror_in_a_green_market(self):
        s = [200.0 - x for x in series()]                                               # the same shape downward
        e = bb.check(s, -1, 2.0, 0.9)
        self.assertIsNotNone(e)
        self.assertEqual(e["side"], -1)

    def test_time_window(self):
        early = series(n_flat=12)[:12]
        self.assertIsNone(bb.check(early, 1, -2.0, 0.1))                                # before 10:00 / too few bars


def market_bars(n_stocks=120, bars=30, drift=-0.12):
    out = {f"S{i}": [100.0 * (1 + drift / 100.0 * k) for k in range(bars)] for i in range(n_stocks)}
    return out


class LiveTests(unittest.TestCase):
    def test_evaluate_and_live_detector(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bars = market_bars()
            bars["LEAD"] = series(n_flat=25)[:] + []
            bars["LEAD"] = [100.0 + 0.05 * i for i in range(len(bars["S0"]) - 9)] + [100.0 + 0.05 * (len(bars["S0"]) - 10) + 0.1 * (1 if i % 2 else -1) for i in range(8)]
            top = max(bars["LEAD"][-8:])
            bars["LEAD"].append(top * 1.01)
            n = len(bars["LEAD"])
            for k in list(bars):
                if k != "LEAD":
                    bars[k] = bars[k][:n]
            minute = bb.OPEN_MIN + bb.BAR_MIN * (n - 1)
            ev = bb.evaluate(bars, minute)
            self.assertEqual([e["symbol"] for e in ev], ["LEAD"])
            det = bb.LiveDetector()
            new = det.update(root, "2026-10-26", bars, minute, 10 * 3600 + 30 * 60)
            self.assertEqual(len(new), 1)
            self.assertEqual(det.update(root, "2026-10-26", bars, minute + 5, 10 * 3600 + 31 * 60), [])        # the same stock and side fire once a day
            rows = list(csv.DictReader(root.joinpath("data", "base_breaks", "2026-10-26.csv").open(encoding="utf-8")))
            self.assertEqual((rows[0]["symbol"], rows[0]["side"]), ("LEAD", "1"))
            live = json.loads(root.joinpath(*bb.LIVE_PATH).read_text(encoding="utf-8"))
            self.assertEqual(live["events"][0]["symbol"], "LEAD")
            now = datetime(2026, 10, 26, 10, 40, tzinfo=IST)
            t = bb.tags("LEAD", "BULLISH", now, root)
            self.assertEqual((t["bb_fired"], t["bb_age_min"]), (1, 10))
            self.assertEqual(bb.tags("LEAD", "BEARISH", now, root)["bb_fired"], 0)
            self.assertEqual(bb.tags("LEAD", "BULLISH", now + timedelta(days=1), root), {})
            self.assertTrue(bb.payload(root, now.date())["ok"])

    def test_no_events_without_enough_stocks(self):
        self.assertEqual(bb.evaluate({"A": [100.0] * 40}, 700), [])


if __name__ == "__main__":
    unittest.main()
