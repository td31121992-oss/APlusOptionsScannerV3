import csv
import gzip
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import delta_flow as df

IST = timezone(timedelta(hours=5, minutes=30))
T0 = 10 * 3600                       # 10:00:00


def feed(tr, sym, minutes, side, qty=100, start=T0, per_min=5, ltp=100.0):
    evs = []
    t = start
    for m in range(minutes):
        for k in range(per_min):
            ev = tr.update(sym, t + m * 60 + k * 10, ltp, qty, side)
            if ev:
                evs.append(ev)
    return evs


class TrackerTests(unittest.TestCase):
    def test_flip_from_selling_to_buying(self):
        tr = df.DeltaTracker()
        a = feed(tr, "AAA", 20, "S")                                         # 20 minutes of seller-initiated volume
        self.assertEqual(a, [])                                              # the first reading is a start, not a flip
        self.assertEqual(tr.state["AAA"].state, -1)
        b = feed(tr, "AAA", 25, "B", start=T0 + 20 * 60, ltp=101.0)          # then buyers take over
        self.assertEqual(len(b), 1)
        self.assertEqual(b[0]["direction"], 1)
        self.assertGreaterEqual(b[0]["imbalance"], df.FLIP_IMB)
        self.assertEqual(b[0]["price"], 101.0)
        c = feed(tr, "AAA", 25, "S", start=T0 + 45 * 60)                     # and back to sellers: a bear flip
        self.assertEqual([e["direction"] for e in c], [-1])

    def test_balanced_flow_never_flips_and_pre_open_is_ignored(self):
        tr = df.DeltaTracker()
        t = T0
        for m in range(40):
            for k in range(4):
                tr.update("BBB", t + m * 60 + k * 10, 100.0, 100, "B" if (m + k) % 2 else "S")
        self.assertEqual(tr.state["BBB"].state, 0)
        self.assertIsNone(tr.update("BBB", 9 * 3600, 100.0, 100, "B"))
        self.assertNotIn("CCC", tr.state)
        self.assertIsNone(tr.update("CCC", 9 * 3600 + 10 * 60, 100.0, 100, "B"))                 # 09:10 is before the open
        self.assertNotIn("CCC", tr.state)

    def test_thin_stretch_does_not_flip(self):
        tr = df.DeltaTracker()
        feed(tr, "AAA", 20, "S", qty=1000)                                   # a busy start sets the pace
        ev = feed(tr, "AAA", 25, "B", qty=1, start=T0 + 20 * 60)             # then a near-dead tape of tiny buy prints
        self.assertEqual(ev, [])                                             # window volume is far below half the usual pace: no flip

    def test_untagged_ticks_count_volume_not_delta(self):
        tr = df.DeltaTracker()
        feed(tr, "AAA", 5, "")
        s = tr.state["AAA"]
        self.assertEqual((s.cum, s.vol > 0), (0.0, True))

    def test_snapshot_and_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tr = df.DeltaTracker()
            feed(tr, "AAA", 20, "S")
            evs = feed(tr, "AAA", 25, "B", start=T0 + 20 * 60)
            self.assertTrue(tr.maybe_write(root, "2026-10-26", T0 + 45 * 60, 100.0, evs))
            self.assertFalse(tr.maybe_write(root, "2026-10-26", T0 + 45 * 60 + 5, 105.0, []))          # throttled
            live = json.loads(root.joinpath(*df.LIVE_PATH).read_text(encoding="utf-8"))
            s = live["stocks"]["AAA"]
            self.assertEqual((s["state"], s["flip"]["direction"]), (1, 1))
            self.assertLess(s["day_imb"], 0.5)                                                          # half the day was selling
            rows = list(csv.DictReader(root.joinpath("data", "delta_flips", "2026-10-26.csv").open(encoding="utf-8")))
            self.assertEqual((rows[0]["symbol"], rows[0]["direction"]), ("AAA", "1"))


class TagTests(unittest.TestCase):
    def test_tags_direction_and_freshness(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tr = df.DeltaTracker()
            feed(tr, "AAA", 20, "S")
            evs = feed(tr, "AAA", 25, "B", start=T0 + 20 * 60)
            t_flip = evs[0]["t"]
            tr.maybe_write(root, "2026-10-26", T0 + 45 * 60, 100.0, evs)
            df._CACHE.update(mtime=None, data=None)
            now = datetime(2026, 10, 26, 10, 45, tzinfo=IST)
            call = df.tags("AAA", "BULLISH", now, root)
            put = df.tags("AAA", "BEARISH", now, root)
            self.assertEqual((call["dl_flip_dir"], put["dl_flip_dir"]), (1, -1))
            self.assertGreater(call["dl_imb15_dir"], 0)
            self.assertEqual(call["dl_imb15_dir"], -put["dl_imb15_dir"])
            self.assertLessEqual(call["dl_flip_age_min"], 30)
            late = datetime(2026, 10, 26, 12, 0, tzinfo=IST)
            self.assertEqual(df.tags("AAA", "BULLISH", late, root)["dl_flip_dir"], 0)                  # an old flip no longer counts
            self.assertEqual(df.tags("ZZZ", "BULLISH", now, root), {})
            self.assertEqual(df.tags("AAA", "BULLISH", now + timedelta(days=1), root), {})
            self.assertGreater(t_flip, 0)


class ReplayTests(unittest.TestCase):
    def test_replay_from_tick_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            d = root / "data" / "ticks" / "2026-10-26"
            d.mkdir(parents=True)
            lines = ["ts,sym,ltp,ltq,ltt,vol,tbq,tsq,bid,bq,ask,aq,bsum5,asum5,tq,side"]
            for m in range(45):
                side = "S" if m < 20 else "B"
                for k in range(5):
                    ts = T0 + m * 60 + k * 10
                    lines.append(f"{ts // 3600:02d}:{ts % 3600 // 60:02d}:{ts % 60:02d}.000,AAA,100.0,1,15:00:00,0,0,0,99.9,1,100.1,1,0,0,100,{side}")
            with gzip.open(d / "AAA.csv.gz", "wt", encoding="utf-8") as h:
                h.write("\n".join(lines) + "\n")
            with gzip.open(d / "OLD.csv.gz", "wt", encoding="utf-8") as h:                                # a tick file from before the side / tq columns existed
                h.write("ts,sym,ltp\n10:00:00.000,OLD,100\n")
            ev = df.replay_day(root, "2026-10-26")
            self.assertEqual([(e["symbol"], e["direction"]) for e in ev], [("AAA", 1)])

    def test_review_with_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(df.review(Path(tmp), "2026-10-26"))


if __name__ == "__main__":
    unittest.main()
