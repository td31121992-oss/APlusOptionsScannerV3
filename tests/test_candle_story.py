import csv
import gzip
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import candle_story as cs

IST = timezone(timedelta(hours=5, minutes=30))
OPEN = cs.OPEN_S


def candle(o, h, l, c, v=1000, buy=None, sell=None, t0=OPEN):
    k = cs.Candle(t0, o)
    k.o, k.h, k.l, k.c, k.v = o, h, l, c, v
    k.buy = v * 0.5 if buy is None else buy
    k.sell = v * 0.5 if sell is None else sell
    return k


def quiet_history(n=6, price=100.0, v=1000):
    return [candle(price, price + 0.3, price - 0.3, price + 0.05 * (i % 2), v=v, t0=OPEN + i * 300) for i in range(n)]


class LabelTests(unittest.TestCase):
    def test_single_candle_stories(self):
        h = quiet_history()
        lab = lambda c, ctx=None: cs.label_candle(c, h, ctx or {})[0]
        self.assertEqual(lab(candle(100.0, 101.9, 99.9, 101.8, v=3000)), "BURST_UP")                              # range ~3x the quiet average, 3x volume, closes at the high
        self.assertEqual(lab(candle(100.0, 100.1, 98.1, 98.2, v=3000)), "BURST_DOWN")
        self.assertEqual(lab(candle(100.0, 100.9, 99.95, 100.1)), "REJECTION_HIGH")                               # a long upper wick and a close in the lower part
        self.assertEqual(lab(candle(100.0, 100.05, 99.1, 99.95)), "REJECTION_LOW")
        self.assertEqual(lab(candle(100.0, 100.6, 99.95, 100.55, v=1500)), "MOMENTUM_UP")
        self.assertEqual(lab(candle(100.0, 100.05, 99.4, 99.45, v=1500)), "MOMENTUM_DOWN")
        self.assertEqual(lab(candle(100.0, 100.3, 99.7, 100.02)), "INDECISION")
        self.assertEqual(lab(candle(100.0, 100.4, 99.8, 100.2)), "DRIFT_UP")
        self.assertEqual(cs.label_candle(candle(100.0, 100.0, 100.0, 100.0), h, {})[0], "FLAT")
        # absorption: heavy volume near the day's high with a small body
        self.assertEqual(lab(candle(100.05, 100.18, 99.95, 100.12, v=2500), {"day_hi": 100.2}), "ABSORPTION_HIGH")
        self.assertEqual(lab(candle(99.92, 99.97, 99.84, 99.88, v=2500), {"day_lo": 99.85}), "ABSORPTION_LOW")

    def test_levels_break_and_failed_break(self):
        h = quiet_history(price=99.6)
        ctx = {"pdh": 100.0}
        self.assertEqual(cs.label_candle(candle(99.7, 100.6, 99.65, 100.5, v=2000), h, ctx)[0], "BREAK_UP")        # closed beyond yesterday's high, real body
        self.assertEqual(cs.label_candle(candle(99.7, 100.5, 99.65, 99.8, v=2000), h, ctx)[0], "FAILED_BREAK_UP")  # pierced it, closed back under with a long wick
        h2 = quiet_history(price=100.4)
        self.assertEqual(cs.label_candle(candle(100.3, 100.35, 99.3, 100.2, v=2000), h2, {"pdl": 100.0})[0], "FAILED_BREAK_DOWN")
        self.assertEqual(cs.label_candle(candle(100.3, 100.35, 99.4, 99.45, v=2000), h2, {"pdl": 100.0})[0], "BREAK_DOWN")

    def test_volume_multiple_and_delta(self):
        h = quiet_history()
        lab, vx, delta = cs.label_candle(candle(100.0, 100.6, 99.95, 100.55, v=3000, buy=2400, sell=600), h, {})
        self.assertEqual((vx, delta), (3.0, 0.6))


class SequenceTests(unittest.TestCase):
    def build(self, specs, ctx=None):
        cs_, labels = [], []
        for i, (o, h, l, c, v) in enumerate(specs):
            k = candle(o, h, l, c, v=v, t0=OPEN + i * 300)
            lab, *_ = cs.label_candle(k, cs_, ctx or {})
            k.label = lab
            cs_.append(k)
            labels.append(lab)
        return cs_, labels

    def run_up(self):
        out, p = [], 100.0
        for i in range(8):                                                         # eight rising candles on decent volume: +1.9 %
            out.append((p, p + 0.3, p - 0.02, p + 0.25, 1500))
            p += 0.25
        return out, p

    def test_pullback_and_resume(self):
        up, p = self.run_up()
        pull = [(p, p + 0.05, p - 0.3, p - 0.25, 500), (p - 0.25, p - 0.2, p - 0.5, p - 0.45, 400)]                # two small counter candles on light volume
        pb_c, pb_l = self.build(up + pull)
        self.assertEqual(cs.sequence_story(pb_c, pb_l, None), "PULLBACK_UP")
        resume = pull + [(p - 0.45, p + 0.2, p - 0.46, p + 0.15, 2200)]
        r_c, r_l = self.build(up + resume)
        self.assertEqual(cs.sequence_story(r_c, r_l, None), "PULLBACK_UP_RESUMES")
        down = [(200.0 - o, 200.0 - l, 200.0 - h, 200.0 - c, v) for o, h, l, c, v in up + resume]      # the same shape inverted
        d_c, d_l = self.build(down)
        self.assertEqual(cs.sequence_story(d_c, d_l, None), "PULLBACK_DOWN_RESUMES")
        self.assertEqual(cs.sequence_story(pb_c, pb_l, 90.0), "PULLBACK_UP")                                            # price above VWAP keeps it valid
        self.assertEqual(cs.sequence_story(pb_c, pb_l, 150.0), "")                                                      # price under VWAP: not a healthy pullback

    def test_base_break_and_coiling_and_exhaustion(self):
        flat = [(100.0, 100.25, 99.8, 100.05 if i % 2 else 99.95, 1000 - 30 * i) for i in range(7)]
        c0, l0 = self.build(flat)
        self.assertEqual(cs.sequence_story(c0, l0, None), "COILING")
        brk = flat[:6] + [(100.0, 100.9, 99.98, 100.85, 2500)]
        c1, l1 = self.build(brk)
        self.assertEqual(cs.sequence_story(c1, l1, None), "BASE_BREAK_UP")
        up, p = self.run_up()
        ex_c, ex_l = self.build(up + [(p, p + 0.9, p - 0.05, p + 0.05, 2000)])                                         # after a 2 % run a long upper wick
        self.assertEqual(cs.sequence_story(ex_c, ex_l, None), "EXHAUSTION_UP")
        self.assertEqual(cs.sequence_story(c0[:5], l0[:5], None), "")                                                    # too few candles

    def test_breakout_retest(self):
        pre = [(99.5, 99.8, 99.3, 99.55 + 0.02 * i, 1000) for i in range(6)]
        specs = pre + [(99.6, 100.5, 99.58, 100.4, 2200), (100.4, 100.6, 100.3, 100.55, 1200), (100.55, 100.58, 99.95, 100.2, 600)]
        c, labs = self.build(specs, {"pdh": 99.8})
        self.assertEqual(labs[6], "BREAK_UP")
        self.assertEqual(cs.sequence_story(c, labs, None), "BREAKOUT_RETEST_UP")                                        # came back to the broken high (99.8) region and held above it


class TrackerTests(unittest.TestCase):
    def feed(self, tr, sym, prices, per_candle=4, side="B", qty=100, start=OPEN):
        evs = []
        for i, p in enumerate(prices):
            for k in range(per_candle):
                evs += tr.update(sym, start + i * 300 + k * 60, p + 0.01 * k, qty, side)
        return evs

    def test_candles_build_and_close_on_the_boundary(self):
        tr = cs.StoryTracker()
        self.feed(tr, "AAA", [100.0, 100.5, 101.0])
        s = tr.state["AAA"]
        self.assertEqual(len(s.done), 2)                                                 # the third candle is still forming
        c = s.done[0]
        self.assertEqual((c.o, round(c.h, 2), c.l, c.v, c.buy, c.sell), (100.0, 100.03, 100.0, 400.0, 400.0, 0.0))
        self.assertEqual(c.t0, OPEN)
        self.assertEqual(tr.update("AAA", 9 * 3600, 100.0, 100, "B"), [])                # before the open: ignored

    def test_events_logged_once_per_label_per_15_minutes_and_quiet_labels_skipped(self):
        tr = cs.StoryTracker({"AAA": (100.0, 0.0)})
        evs = self.feed(tr, "AAA", [99.5, 99.55, 99.6, 99.58, 99.62, 99.6])
        evs += self.feed(tr, "AAA", [100.9], start=OPEN + 6 * 300)                       # a candle that closes above yesterday's high
        evs += self.feed(tr, "AAA", [101.0], start=OPEN + 7 * 300)
        evs += self.feed(tr, "AAA", [101.1], start=OPEN + 8 * 300)
        kinds = [(e["kind"], e["label"]) for e in evs]
        self.assertTrue(all(lab not in cs.QUIET for _k, lab in kinds))
        last = {}
        for e in evs:                                                                      # a label already logged is not logged again inside 15 minutes
            k = (e["kind"], e["label"])
            self.assertGreaterEqual(e["t"] - last.get(k, -1e9), 900)
            last[k] = e["t"]
        self.assertIn(("candle", "BREAK_UP"), kinds)

    def test_snapshot_write_and_tags(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tr = cs.StoryTracker()
            evs = self.feed(tr, "AAA", [100 + 0.2 * i for i in range(10)], side="B")
            self.assertTrue(tr.maybe_write(root, "2026-10-26", OPEN + 3000, 100.0, evs))
            live = json.loads(root.joinpath(*cs.LIVE_PATH).read_text(encoding="utf-8"))
            a = live["stocks"]["AAA"]
            self.assertEqual(len(a["candles"]), cs.KEEP if len(a["candles"]) > cs.KEEP else len(a["candles"]))
            self.assertGreaterEqual(a["candles"][-1]["d"], 0.9)                           # all buyer-initiated
            cs._CACHE.update(mtime=None, data=None)
            now = datetime(2026, 10, 26, 10, 5, tzinfo=IST)
            call, put = cs.tags("AAA", "BULLISH", now, root), cs.tags("AAA", "BEARISH", now, root)
            self.assertEqual(call["cs_delta_dir"], -put["cs_delta_dir"])
            self.assertEqual(call["cs_with"], -put["cs_with"])
            self.assertEqual(len(call["cs_last3"].split("|")), 3)
            self.assertEqual(cs.tags("ZZZ", "BULLISH", now, root), {})
            self.assertEqual(cs.tags("AAA", "BULLISH", now + timedelta(days=1), root), {})
            self.assertTrue(cs.payload(root, now.date())["ok"])
            self.assertFalse(cs.payload(root, now.date() + timedelta(days=1))["ok"])
            rows = list(csv.DictReader(root.joinpath("data", "candle_story", "2026-10-26.csv").open(encoding="utf-8"))) if root.joinpath("data", "candle_story", "2026-10-26.csv").exists() else []
            for r in rows:
                self.assertIn(r["kind"], ("candle", "story"))

    def test_direction_map(self):
        self.assertEqual((cs.direction_of("BREAK_UP"), cs.direction_of("EXHAUSTION_UP"), cs.direction_of("INDECISION"), cs.direction_of("PULLBACK_DOWN_RESUMES")), (1, -1, 0, -1))
        self.assertEqual(cs.BULL & cs.BEAR, set())


class ReplayTests(unittest.TestCase):
    def test_replay_and_levels(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data" / "reports").mkdir(parents=True)
            (root / "data" / "reports" / "daily_indicators.json").write_text(json.dumps({"symbols": {"AAA": {"pdh": 100.0, "pdl": 98.0}}}), encoding="utf-8")
            self.assertEqual(cs.load_levels(root), {"AAA": (100.0, 98.0)})
            d = root / "data" / "ticks" / "2026-10-26"
            d.mkdir(parents=True)
            lines = ["ts,sym,ltp,ltq,ltt,vol,tbq,tsq,bid,bq,ask,aq,bsum5,asum5,tq,side"]
            prices = [99.5, 99.55, 99.6, 99.58, 99.62, 99.6, 100.9, 101.0]
            for i, p in enumerate(prices):
                for k in range(4):
                    t = OPEN + i * 300 + k * 60
                    lines.append(f"{int(t // 3600):02d}:{int(t % 3600 // 60):02d}:{int(t % 60):02d}.000,AAA,{p + 0.01 * k},1,15:00:00,0,0,0,0,0,0,0,0,0,100,B")
            with gzip.open(d / "AAA.csv.gz", "wt", encoding="utf-8") as h:
                h.write("\n".join(lines) + "\n")
            with gzip.open(d / "OLD.csv.gz", "wt", encoding="utf-8") as h:
                h.write("ts,sym,ltp\n10:00:00.000,OLD,100\n")
            ev = cs.replay_day(root, "2026-10-26")
            self.assertIn("BREAK_UP", [e["label"] for e in ev])
            self.assertIsNone(cs.review(Path(tmp, "none"), "2026-10-26"))


if __name__ == "__main__":
    unittest.main()
