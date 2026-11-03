import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

import ml_shadow as ml

IST = timezone(timedelta(hours=5, minutes=30))
NOW = datetime(2026, 10, 26, 10, 30, tzinfo=IST)


def fill_bars(mb, n=60, drift=0.001, stocks=60, minute=10 * 60 + 30):
    for i in range(stocks):
        px = 100.0
        for m in range(ml.OPEN_MIN, minute + 1):
            px *= 1 + drift * (1 if i % 2 else -1)
            mb.update(f"S{i}", m * 60 + 5, px)


def synthetic_dataset(root: Path):
    rng = np.random.default_rng(1)
    n = 4000
    df = pd.DataFrame({k: rng.normal(size=n) for k in ml.FEATURES})
    df["minute"] = rng.choice([600, 630, 660, 690, 720], n)
    df["side"] = rng.choice([1, -1], n)
    df["weekday"] = rng.integers(0, 5, n)
    df["date"] = [f"2026-09-{1 + i % 25:02d}" for i in range(n)]
    df["ret_pct"] = np.where(df["rs_dir"] + rng.normal(scale=0.5, size=n) > 0.3, 12.0, -22.0)        # a learnable signal: strong relative strength wins
    p = root / "data" / "data_science"
    p.mkdir(parents=True)
    df.to_csv(p / "dataset.csv.gz", index=False, compression="gzip")


class BarTests(unittest.TestCase):
    def test_minute_bars_pad_forward_fill_and_ignore_pre_open(self):
        mb = ml.MinuteBars()
        mb.update("A", 9 * 3600 + 14 * 60, 99.0)                                       # before 09:15: ignored
        self.assertEqual(mb.bars, {})
        mb.update("A", (ml.OPEN_MIN + 3) * 60 + 2, 100.0)                              # first tick at 09:18: padded back to the open
        self.assertEqual(mb.bars["A"], [100.0] * 4)
        mb.update("A", (ml.OPEN_MIN + 3) * 60 + 30, 101.0)                             # same minute: the bar's close moves
        mb.update("A", (ml.OPEN_MIN + 6) * 60 + 1, 103.0)                              # two quiet minutes are filled forward
        self.assertEqual(mb.bars["A"], [100.0, 100.0, 100.0, 101.0, 101.0, 101.0, 103.0])

    def test_live_features_signs_and_market_numbers(self):
        mb = ml.MinuteBars()
        fill_bars(mb)
        out = ml.live_features(mb.bars, 10 * 60 + 30)
        self.assertEqual(out["n"], 60)
        up, down = out["stocks"]["S1"], out["stocks"]["S0"]                            # S1 drifts up, S0 down
        self.assertGreater(up["1"]["d_ret_open"], 0)
        self.assertAlmostEqual(up["1"]["d_ret_open"], -up["-1"]["d_ret_open"], places=3)   # same series, opposite side: directional numbers flip
        self.assertEqual(up["1"]["rs_dir"], -up["-1"]["rs_dir"])
        self.assertGreater(up["1"]["rs_dir"], 0)
        self.assertLess(down["1"]["rs_dir"], 0)
        self.assertEqual(out["breadth"], 0.5)
        few = ml.MinuteBars()
        fill_bars(few, stocks=10)
        self.assertIsNone(ml.live_features(few.bars, 630))

    def test_live_file_is_throttled(self):
        with tempfile.TemporaryDirectory() as tmp:
            mb = ml.MinuteBars()
            fill_bars(mb)
            self.assertTrue(mb.maybe_write(Path(tmp), "2026-10-26", 10 * 3600 + 30 * 60 + 5, wall=100.0))
            self.assertFalse(mb.maybe_write(Path(tmp), "2026-10-26", 10 * 3600 + 30 * 60 + 9, wall=105.0))
            d = json.loads(Path(tmp, *ml.LIVE_PATH).read_text(encoding="utf-8"))
            self.assertEqual((d["day"], d["minute"], d["asof_minute"], d["n"]), ("2026-10-26", 625, 630, 60))      # the latest COMPLETE 5-minute bar is the 10:25 bar; now is 10:30


class FiveMinuteTests(unittest.TestCase):
    def test_five_minute_closes_are_the_last_minute_of_each_complete_bucket(self):
        closes = [float(i) for i in range(12)]                                          # minutes 09:15 ... 09:26
        self.assertEqual(ml.five_min(closes), [4.0, 9.0])                                # buckets 09:15-19 and 09:20-24 are complete; 09:25-26 is not
        self.assertEqual(ml.five_min([1.0, 2.0, 3.0]), [])


class ModelTests(unittest.TestCase):
    def setUp(self):
        ml._CACHE.update(mtime=None, obj=None, live_mtime=None, live=None)
        ml._LOGGED.clear()

    def test_train_score_and_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            synthetic_dataset(root)
            meta = ml.train(root)
            self.assertGreater(meta["holdout_auc"], 0.7)                               # the planted signal is learnt
            self.assertTrue(root.joinpath(*ml.MODEL_PATH).exists())
            mb = ml.MinuteBars()
            fill_bars(mb)
            self.assertTrue(mb.maybe_write(root, "2026-10-26", 10 * 3600 + 30 * 60 + 5, wall=100.0))
            rec = {"ltp": 100.0, "oc_k_ltp": 3.0, "iv_atm": 28.0}
            up = ml.tags("S1", "BULLISH", NOW, rec, root)
            down = ml.tags("S1", "BEARISH", NOW, rec, root)
            self.assertEqual((up["ml_in_range"], up["ml_complete"], up["ml_version"]), (1, 1, ml.VERSION))
            self.assertGreater(up["ml_p"], down["ml_p"])                               # a riser is a better call than a put
            self.assertIn(up["ml_top10"], (0, 1))
            self.assertEqual(ml.tags("S1", "BULLISH", NOW, {"ltp": 100.0}, root)["ml_complete"], 0)      # no option numbers: scored, but flagged incomplete
            lines = root.joinpath("data", "ml_shadow", "scores_2026-10-26.csv").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 3)                                            # header + the two directions; the repeat inside 5 minutes is not logged again
            self.assertEqual(ml.tags("NOPE", "BULLISH", NOW, rec, root), {})            # unknown stock
            self.assertEqual(ml.tags("S1", "BULLISH", NOW + timedelta(days=1), rec, root), {})      # another day's features
            self.assertEqual(ml.tags("S1", "BULLISH", NOW + timedelta(minutes=10), rec, root), {})  # features older than 2 minutes
            self.assertEqual(ml.tags("S1", "BULLISH", NOW, rec, Path(tmp, "elsewhere")), {})        # no model

    def test_out_of_hours_is_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            synthetic_dataset(root)
            ml.train(root)
            mb = ml.MinuteBars()
            fill_bars(mb, minute=13 * 60)
            mb.maybe_write(root, "2026-10-26", 13 * 3600 + 5, wall=100.0)
            late = datetime(2026, 10, 26, 13, 0, tzinfo=IST)
            self.assertEqual(ml.tags("S1", "BULLISH", late, {"ltp": 100.0, "oc_k_ltp": 3.0, "iv_atm": 28.0}, root)["ml_in_range"], 0)


class ReviewTests(unittest.TestCase):
    def test_auc(self):
        self.assertEqual(ml._auc([0.9, 0.8], [0.1, 0.2]), 1.0)
        self.assertEqual(ml._auc([0.1], [0.9]), 0.0)
        self.assertEqual(ml._auc([0.5], [0.5]), 0.5)
        self.assertIsNone(ml._auc([], [0.5]))

    def test_review_against_candidate_outcomes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data" / "ml_shadow").mkdir(parents=True)
            (root / "data" / "missed_opportunities" / "2026-10-26").mkdir(parents=True)
            rows = [("AAA", "BULLISH", 0.40, 1, 35.0), ("BBB", "BULLISH", 0.30, 0, 10.0), ("CCC", "BEARISH", 0.20, 0, -40.0), ("DDD", "BEARISH", 0.15, 0, -30.0), ("EEE", "BULLISH", 0.30, 0, None)]
            with (root / "data" / "ml_shadow" / "scores_2026-10-26.csv").open("w", encoding="utf-8", newline="") as h:
                h.write("time,symbol,direction,ml_p,ml_top10,ml_in_range,ml_complete\n" + "".join(f"10:00:00,{s},{d},{p},{t},1,1\n" for s, d, p, t, _ in rows))
            (root / "data" / "missed_opportunities" / "2026-10-26" / "option_returns.json").write_text(
                json.dumps([{"symbol": s, "dir": d, "close": c} for s, d, _, _, c in rows if c is not None]), encoding="utf-8")
            out = ml.review(root)
            text = out.read_text(encoding="utf-8")
            self.assertIn("AUC of ml_p on them: 1.0", text)                              # winners were scored above losers
            self.assertIn("Candidates with an outcome: 4", text)
            self.assertIsNone(ml.review(Path(tmp, "none")))


if __name__ == "__main__":
    unittest.main()
