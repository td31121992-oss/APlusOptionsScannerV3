import csv
import json
import pickle
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

import chart_opportunity as co
import ml_shadow

IST = timezone(timedelta(hours=5, minutes=30))
NOW = datetime(2026, 10, 26, 10, 30, tzinfo=IST)


def path_arrays(highs, lows, closes, start=600):
    n = len(closes)
    return np.arange(start, start + n), np.array(highs, float), np.array(lows, float), np.array(closes, float)


class LabelTests(unittest.TestCase):
    def test_hit_flags_stop_and_best(self):
        m, h, l, c = path_arrays([10, 12, 16, 21, 22], [10, 11, 12, 15, 20], [10, 11.5, 15, 20, 21])        # entry 10.1; best high 22 -> +118 %
        lab = co.labels(m, h, l, c, 0)
        self.assertEqual((lab["hit50"], lab["hit100"]), (1, 1))
        self.assertAlmostEqual(lab["run_pct"], (22 / 10.1 - 1) * 100, places=1)
        m, h, l, c = path_arrays([10, 11, 16, 25], [10, 7, 15, 24], [10, 9, 15, 24])                         # the second bar trades down to 7 (< 8.08 stop) before the run
        lab = co.labels(m, h, l, c, 0)
        self.assertEqual((lab["hit50"], lab["hit100"]), (0, 0))
        self.assertLess(lab["ret_pct"], -15)
        self.assertIsNone(co.labels(*path_arrays([10], [10], [10]), 0))                                       # nothing after the entry bar


def synthetic_model(root: Path):
    from sklearn.ensemble import HistGradientBoostingClassifier

    rng = np.random.default_rng(3)
    n = 3000
    df = pd.DataFrame({k: rng.normal(size=n) for k in co.FEATURES})
    df["minute"] = rng.choice(list(co.ENTRY_MINUTES), n)
    df["side"] = rng.choice([1, -1], n)
    df["weekday"] = rng.integers(0, 5, n)
    y = ((df["rs_dir"] + df["d_ret_12"]) > 1.2).astype(int)
    clf = HistGradientBoostingClassifier(max_depth=3, max_iter=60, random_state=0).fit(df[co.FEATURES], y)
    p = clf.predict_proba(df[co.FEATURES])[:, 1]
    q = {k: float(np.quantile(p, v)) for k, v in (("q50", 0.5), ("q90", 0.9), ("q95", 0.95), ("q99", 0.99))}
    path = root.joinpath(*co.MODEL_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as h:
        pickle.dump({"model": clf, "meta": {"version": "test", "holdout_auc": 0.6, "p_quantiles": q}}, h)
    co._CACHE.update(mtime=None, obj=None, live_mtime=None, live=None)


def bars(mb, stocks=60, minute=10 * 60 + 30):
    for i in range(stocks):
        px = 100.0
        for m in range(ml_shadow.OPEN_MIN, minute + 1):
            px *= 1 + 0.0015 * (1 if i % 2 else -1) * (3 if i == 1 else 1)          # S1 rises fastest
            mb.update(f"S{i}", m * 60 + 5, px)


class LiveTests(unittest.TestCase):
    def test_scoring_files_tags_and_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            synthetic_model(root)
            mb = ml_shadow.MinuteBars()
            bars(mb)
            self.assertTrue(mb.maybe_write(root, "2026-10-26", 10 * 3600 + 30 * 60 + 5, wall=100.0))     # the 1-minute writer hands its features to the scorer
            d = json.loads(root.joinpath(*co.LIVE_PATH).read_text(encoding="utf-8"))
            self.assertEqual((d["day"], d["n"], d["version"]), ("2026-10-26", 120, "test"))
            self.assertEqual(d["calls"][0]["s"], "S1")                                                      # the fastest riser leads the calls
            self.assertGreaterEqual(len(d["calls"]), 1)
            self.assertEqual(len(d["calls"]), co.TOP_N)
            up = co.tags("S1", "BULLISH", NOW, root)
            down = co.tags("S1", "BEARISH", NOW, root)
            self.assertGreater(up["co_p"], down["co_p"])
            self.assertEqual(up["co_top1"], 1)
            self.assertEqual(co.tags("NOPE", "BULLISH", NOW, root), {})
            self.assertEqual(co.tags("S1", "BULLISH", NOW + timedelta(days=1), root), {})
            self.assertTrue(co.payload(root, NOW.date())["ok"])
            self.assertNotIn("p", co.payload(root, NOW.date()))                                             # the page does not get the full score table
            self.assertFalse(co.payload(root, NOW.date() + timedelta(days=1))["ok"])
            log = list(csv.DictReader(root.joinpath("data", "chart_opps", "2026-10-26.csv").open(encoding="utf-8")))
            self.assertTrue(any(r["symbol"] == "S1" and r["side"] == "1" for r in log))
            n0 = len(log)
            sc = mb._scorer
            sc.score(root, json.loads(root.joinpath(*ml_shadow.LIVE_PATH).read_text(encoding="utf-8")), "2026-10-26", 10 * 3600 + 30 * 60 + 25)
            log2 = list(csv.DictReader(root.joinpath("data", "chart_opps", "2026-10-26.csv").open(encoding="utf-8")))
            self.assertEqual(len(log2), n0)                                                                  # the same flags are not logged again within 30 minutes

    def test_no_model_is_quiet(self):
        with tempfile.TemporaryDirectory() as tmp:
            co._CACHE.update(mtime=None, obj=None, live_mtime=None, live=None)
            self.assertFalse(co.LiveScorer().score(Path(tmp), {"minute": 630, "stocks": {"A": {}}}, "2026-10-26", 36000.0))
            self.assertEqual(co.tags("A", "BULLISH", NOW, Path(tmp)), {})


if __name__ == "__main__":
    unittest.main()
