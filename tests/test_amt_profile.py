import csv
import gzip
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import amt_profile as am

IST = timezone(timedelta(hours=5, minutes=30))
OPEN = am.OPEN_S


def ts(t):
    return f"{int(t // 3600):02d}:{int(t % 3600 // 60):02d}:{int(t % 60):02d}.000"


LEVELS = [99.6, 99.8, 100.0, 100.2, 100.4, 100.2, 100.0, 99.8]


def balanced_px(m, k, centre=100.0):
    """A smooth two-way market around 100 (a real profile is continuous, not two prices); the last minute of every half hour sits at the centre."""
    return centre if m % 30 == 29 else LEVELS[(m * 3 + k) % len(LEVELS)] - 100.0 + centre


def balance_hour(tr, sym="AAA", centre=100.0):
    """09:15-10:15: volume 100 a tick, half bought and half sold, price moving smoothly through 99.6-100.4."""
    evs = []
    for m in range(61):
        for k in range(3):
            evs += tr.update(sym, OPEN + m * 60 + k * 15, balanced_px(m, k, centre), 100, "B" if (m + k) % 2 else "S")
    return evs


class ValueAreaTests(unittest.TestCase):
    def test_poc_and_seventy_percent_area(self):
        prof = {0: 10.0, 1: 50.0, 2: 20.0, -1: 15.0, 3: 5.0}
        val, poc, vah = am.value_area(prof, 100.0, 0.5)
        self.assertEqual(poc, 100.5)                                                    # bucket 1 holds the most volume
        self.assertEqual((val, vah), (100.5, 101.5))                                    # 50 + the two buckets above (25) = 75 % >= 70 %
        self.assertIsNone(am.value_area({}, 100.0, 0.5))
        val2, poc2, vah2 = am.value_area({0: 100.0}, 100.0, 0.5)
        self.assertEqual((val2, poc2, vah2), (100.0, 100.0, 100.0))

    def test_area_grows_toward_the_heavier_side(self):
        prof = {0: 40.0, 1: 5.0, 2: 5.0, -1: 20.0, -2: 20.0, 5: 10.0}
        val, poc, vah = am.value_area(prof, 100.0, 1.0)
        self.assertEqual(poc, 100.0)
        self.assertEqual((val, vah), (98.0, 100.0))                                     # below holds 40 more volume than above: the area extends down first (40 + 40 = 80 %)


class EventTests(unittest.TestCase):
    def test_ib_break_then_acceptance(self):
        tr = am.AMTTracker()
        balance_hour(tr)
        evs = []
        for m in range(61, 125):                                                        # 10:16 ... 11:20: price sits at 101.2, thin volume
            evs += tr.update("AAA", OPEN + m * 60, 101.2, 5, "B")
        kinds = [e["kind"] for e in evs]
        self.assertIn("IB_BREAK_UP", kinds)
        self.assertEqual(kinds.count("IB_BREAK_UP"), 1)                                 # once
        self.assertIn("ACCEPT_ABOVE", kinds)
        brk = next(e for e in evs if e["kind"] == "IB_BREAK_UP")
        self.assertGreater(brk["price"], brk["ib_hi"])
        snap = tr.snapshot(0)["AAA"]
        self.assertEqual((snap["ib_break"], snap["accept"], snap["ib_done"]), (1, 1, True))
        self.assertIn(snap["daytype"], ("var_up", "trend_up"))
        self.assertGreaterEqual(snap["ib_up"], 0.25)

    def test_balanced_day_has_no_breaks(self):
        tr = am.AMTTracker()
        evs = balance_hour(tr)
        for m in range(61, 130):
            for k in range(3):
                evs += tr.update("AAA", OPEN + m * 60 + k * 15, balanced_px(m, k), 100, "B" if (m + k) % 2 else "S")
        self.assertEqual([e["kind"] for e in evs if e["kind"].startswith(("IB_", "ACCEPT"))], [])
        self.assertEqual(tr.snapshot(0)["AAA"]["daytype"], "range")

    def test_rejection_of_a_poke_above_value(self):
        tr = am.AMTTracker()
        balance_hour(tr)
        evs = []
        t = OPEN + 61 * 60
        evs += tr.update("AAA", t, 101.0, 1, "B")                                       # a poke 1 % above value
        for m in range(62, 100):
            evs += tr.update("AAA", OPEN + m * 60, 100.0, 50, "S")                      # then back inside, heavy volume there
        self.assertIn("REJECT_ABOVE", [e["kind"] for e in evs])

    def test_cvd_divergence_at_a_new_high(self):
        tr = am.AMTTracker()
        evs = []
        t = OPEN
        for k in range(40):                                                             # a rally on buying
            evs += tr.update("AAA", t + k * 15, 100.0 + k * 0.03, 500, "B")
        t += 40 * 15
        for k in range(30):                                                             # a pullback on selling
            evs += tr.update("AAA", t + k * 15, 101.2 - k * 0.02, 900, "S")
        t += 30 * 15
        for k in range(30):                                                             # a new high, but only sellers hit the bid on the way up: less cumulative buying than at the first high
            evs += tr.update("AAA", t + k * 15, 100.6 + k * 0.04, 600, "S")
        self.assertIn("DIV_HIGH", [e["kind"] for e in evs])
        self.assertEqual(tr.snapshot(0)["AAA"]["div"][0], -1)

    def test_pre_open_ignored_and_debounce(self):
        tr = am.AMTTracker()
        self.assertEqual(tr.update("AAA", 9 * 3600, 100.0, 100, "B"), [])
        self.assertNotIn("AAA", tr.state)


class TagTests(unittest.TestCase):
    def test_tags_flip_with_direction(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tr = am.AMTTracker()
            balance_hour(tr)
            for m in range(61, 125):
                tr.update("AAA", OPEN + m * 60, 101.2, 5, "B")
            tr.maybe_write(root, "2026-10-26", OPEN + 124 * 60, 100.0, [])
            am._CACHE.update(mtime=None, data=None)
            now = datetime(2026, 10, 26, 11, 20, tzinfo=IST)
            call, put = am.tags("AAA", "BULLISH", now, root), am.tags("AAA", "BEARISH", now, root)
            self.assertEqual((call["am_pos_dir"], put["am_pos_dir"]), (1, -1))
            self.assertEqual((call["am_ib_dir"], put["am_ib_dir"]), (1, -1))
            self.assertEqual((call["am_accept_dir"], put["am_accept_dir"]), (1, -1))
            self.assertGreater(call["am_poc_dist_dir"], 0)
            self.assertEqual(call["am_poc_dist_dir"], -put["am_poc_dist_dir"])
            self.assertEqual(call["am_daytype"], put["am_daytype"])
            self.assertEqual(am.tags("NOPE", "BULLISH", now, root), {})
            self.assertEqual(am.tags("AAA", "BULLISH", now + timedelta(days=1), root), {})


class ReplayTests(unittest.TestCase):
    def test_replay_and_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            d = root / "data" / "ticks" / "2026-10-26"
            d.mkdir(parents=True)
            lines = ["ts,sym,ltp,ltq,ltt,vol,tbq,tsq,bid,bq,ask,aq,bsum5,asum5,tq,side"]
            for m in range(61):
                for k in range(3):
                    px = 100.0 + (0.5 if (m + k) % 2 else -0.5)
                    lines.append(f"{ts(OPEN + m * 60 + k * 15)},AAA,{px},1,15:00:00,0,0,0,0,0,0,0,0,0,100,{'B' if (m + k) % 2 else 'S'}")
            for m in range(61, 125):
                lines.append(f"{ts(OPEN + m * 60)},AAA,101.2,1,15:00:00,0,0,0,0,0,0,0,0,0,5,B")
            with gzip.open(d / "AAA.csv.gz", "wt", encoding="utf-8") as h:
                h.write("\n".join(lines) + "\n")
            ev = am.replay_day(root, "2026-10-26")
            self.assertIn("IB_BREAK_UP", [e["kind"] for e in ev])
            tr = am.AMTTracker()
            tr.maybe_write(root, "2026-10-26", 40000.0, 100.0, ev)
            rows = list(csv.DictReader(root.joinpath("data", "amt_events", "2026-10-26.csv").open(encoding="utf-8")))
            self.assertEqual(rows[0]["symbol"], "AAA")
            self.assertIsNone(am.review(Path(tmp, "none"), "2026-10-26"))


if __name__ == "__main__":
    unittest.main()
