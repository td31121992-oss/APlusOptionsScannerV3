import gzip
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import tick_tags as tt

HEAD = "ts,sym,ltp,ltq,ltt,vol,tbq,tsq,bid,bq,ask,aq,bsum5,asum5,tq,side"


def fs(h, m, s=0):
    return h * 3600 + m * 60 + s


def prints(spec):
    """spec = (minute of day, count, qty, side) -> evenly spread prints inside that minute"""
    out = []
    for minute, n, q, side in spec:
        for i in range(n):
            out.append((minute * 60 + i * (60 / max(n, 1)), q, side))
    return sorted(out)


class DeltaTests(unittest.TestCase):
    def test_selling_pressure_is_positive_for_a_put_and_negative_for_a_call(self):
        # 10:00-10:14 heavy selling, the last 5 minutes (10:10-10:14) heaviest
        p = prints([(600 + k, 10, 100, "S") for k in range(10)] + [(610 + k, 10, 100, "S") for k in range(5)] + [(600 + k, 3, 100, "B") for k in range(15)])
        now = fs(10, 15)
        put = tt.tags_from_prints(p, "BEARISH", now)
        call = tt.tags_from_prints(p, "BULLISH", now)
        self.assertGreater(put["tk_delta15_dir"], 0.5)
        self.assertEqual(call["tk_delta15_dir"], -put["tk_delta15_dir"])
        self.assertLess(put["tk_buy_pct15"], 25)

    def test_acceleration_compares_the_last_5_minutes_with_the_10_before(self):
        slow = [(600 + k, 10, 100, "S") for k in range(10)] + [(600 + k, 8, 100, "B") for k in range(10)]            # mild selling early
        fast = [(610 + k, 10, 100, "S") for k in range(5)]                                                           # pure selling late
        t = tt.tags_from_prints(prints(slow + fast), "BEARISH", fs(10, 15))
        self.assertGreater(t["tk_delta_accel"], 0.5)

    def test_too_few_prints_gives_nothing(self):
        self.assertEqual(tt.tags_from_prints(prints([(600, 5, 10, "B")]), "BULLISH", fs(10, 15)), {})


class BigPrintTests(unittest.TestCase):
    def test_big_prints_threshold_direction_and_last_print(self):
        small = [(555 + (k % 60), 1, 100, "B" if k % 2 else "S") for k in range(400)]                             # 400 small prints, 09:15-10:14
        big = [(612, 1, 9000, "S"), (613, 1, 8000, "S"), (614, 1, 7000, "B")]
        t = tt.tags_from_prints(prints(small + big), "BEARISH", fs(10, 15))
        self.assertGreaterEqual(t["tk_big_threshold"], 100)
        self.assertEqual(t["tk_big_n15"], 3)
        self.assertAlmostEqual(t["tk_big_dir15"], (17000 - 7000) / 24000, places=2)       # big sells 17k vs big buy 7k: with a put
        self.assertEqual(t["tk_big_last_dir"], "against")                # the latest big print was a buy
        self.assertAlmostEqual(t["tk_big_last_ago"], 0.0, delta=1.5)

    def test_prints_after_now_are_ignored(self):
        p = prints([(600 + k, 5, 100, "S") for k in range(10)] + [(700, 50, 5000, "B")])
        t = tt.tags_from_prints(p, "BEARISH", fs(10, 10))
        self.assertGreater(t["tk_delta5_dir"], 0.9)


class FileTests(unittest.TestCase):
    def test_reads_a_file_still_being_written_and_skips_the_closing_auction(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            day = datetime(2026, 10, 22, 10, 20)
            folder = root / "data" / "ticks" / "2026-10-22"
            folder.mkdir(parents=True)
            rows = [HEAD] + [f"10:{10 + (i % 9):02d}:{i % 60:02d}.000,TCS,100,1,,1,1,1,99,1,101,1,1,1,{100 + i},S" for i in range(60)]
            rows.append("15:29:19.000,TCS,100,1,,1,1,1,99,1,101,1,1,1,999999,B")
            raw = gzip.compress(("\n".join(rows) + "\n").encode())
            (folder / "TCS.csv.gz").write_bytes(raw[:-10])                   # cut mid-stream like a live file
            t = tt.tick_tags("TCS", "BEARISH", day, root)
            self.assertIn("tk_delta15_dir", t)
            self.assertGreater(t["tk_delta15_dir"], 0.9)
            self.assertEqual(tt.tick_tags("NOPE", "BEARISH", day, root), {})


if __name__ == "__main__":
    unittest.main()
