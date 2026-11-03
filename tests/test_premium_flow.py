import csv
import gzip
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

for k in list(os.environ):
    if k.startswith("APLUS_PX_"):
        os.environ.pop(k)

import premium_flow as pf

IST = timezone(timedelta(hours=5, minutes=30))


def leg(stamp, sym, side, vol, ltp, strike=100.0, expiry="2026-10-27"):
    return {"captured_at": stamp, "symbol": sym, "expiry": expiry, "strike": strike, "side": side, "volume": vol, "ltp": ltp}


class AccumulatorTests(unittest.TestCase):
    def test_increments_first_capture_new_legs_and_resets(self):
        acc = pf.Accumulator()
        r1 = acc.update([leg("2026-10-22T09:16:00+05:30", "AAA", "CE", 1000, 10.0), leg("2026-10-22T09:16:00+05:30", "AAA", "PE", 500, 4.0)])
        self.assertEqual((r1[0]["ce_cr"], r1[0]["pe_cr"]), (round(1000 * 10 / 1e7, 4), round(500 * 4 / 1e7, 4)))     # first capture of the day counts all volume so far
        r2 = acc.update([leg("2026-10-22T09:19:00+05:30", "AAA", "CE", 1600, 11.0), leg("2026-10-22T09:19:00+05:30", "AAA", "PE", 500, 4.0),
                         leg("2026-10-22T09:19:00+05:30", "AAA", "CE", 900000, 1.0, strike=120.0)])                     # a leg newly inside the strike window: tracking starts, no burst
        self.assertEqual((r2[0]["ce_cr"], r2[0]["pe_cr"]), (round(600 * 11 / 1e7, 4), 0.0))
        r3 = acc.update([leg("2026-10-22T09:24:00+05:30", "AAA", "CE", 100, 11.0)])                                       # volume went down (reset / glitch): nothing counted
        self.assertEqual(r3[0]["ce_cr"], 0.0)


def write_day(root, day, rows):
    folder = pf.day_folder(root, day)
    folder.mkdir(parents=True, exist_ok=True)
    pf.append(folder, rows)


def row(t, sym, ce, pe):
    return {"captured_at": f"2026-10-22T{t}:00+05:30", "symbol": sym, "ce_cr": ce, "pe_cr": pe}


class TagTests(unittest.TestCase):
    def test_tags_with_history_and_without(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for d in ("2026-10-15", "2026-10-16", "2026-10-19"):                         # three earlier days: 4 cr by 10:00, 2 cr of it in the last 15 minutes
                stamps = [("09:15", 1.0, 0.0), ("09:50", 1.0, 0.0), ("09:55", 1.0, 1.0)]
                write_day(root, d, [{"captured_at": f"{d}T{t}:00+05:30", "symbol": "AAA", "ce_cr": c, "pe_cr": p} for t, c, p in stamps])
            write_day(root, "2026-10-22", [row("09:15", "AAA", 2.0, 0.0), row("09:50", "AAA", 4.0, 1.0), row("09:55", "AAA", 6.0, 1.0)])
            now = datetime(2026, 10, 22, 10, 0, tzinfo=IST)
            t = pf.tags("AAA", "BULLISH", now, root)
            self.assertEqual(t["px_cum_cr"], 14.0)
            self.assertEqual(t["px_days"], 3)
            self.assertEqual(t["px_x_avg"], 3.5)                                         # 14 cr against 4 cr usual by 10:00
            self.assertEqual(t["px_last15_cr"], 12.0)                                    # captures after 09:45
            self.assertEqual((t["px_dir_share"], t["px_dir_share15"]), (0.86, 0.83))
            self.assertEqual(pf.tags("AAA", "BEARISH", now, root)["px_dir_share"], 0.14)
            self.assertGreater(t["px_surge15_x"], 1)
            early = pf.tags("AAA", "BULLISH", datetime(2026, 10, 22, 9, 20, tzinfo=IST), root)
            self.assertEqual(early["px_cum_cr"], 2.0)

    def test_blank_baseline_until_enough_days_and_unknown_stock(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_day(root, "2026-10-21", [row("09:15", "BBB", 1.0, 1.0)])
            write_day(root, "2026-10-22", [row("09:15", "BBB", 2.0, 0.0)])
            t = pf.tags("BBB", "BULLISH", datetime(2026, 10, 22, 9, 30, tzinfo=IST), root)
            self.assertEqual((t["px_cum_cr"], t["px_days"]), (2.0, 1))
            self.assertNotIn("px_x_avg", t)
            self.assertEqual(pf.tags("ZZZ", "BULLISH", datetime(2026, 10, 22, 9, 30, tzinfo=IST), root), {})
            self.assertEqual(pf.tags("BBB", "BULLISH", datetime(2026, 10, 23, 9, 30, tzinfo=IST), root), {})

    def test_replay_rebuilds_the_day_from_raw_captures(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = pf.day_folder(Path(tmp), "2026-10-22")
            folder.mkdir(parents=True)
            fields = ["captured_at", "symbol", "expiry", "strike", "side", "ltp", "volume"]
            with gzip.open(folder / "option_chain_rows.csv.gz", "wt", encoding="utf-8", newline="") as h:
                w = csv.DictWriter(h, fieldnames=fields)
                w.writeheader()
                for stamp, vol in (("2026-10-22T09:16:00+05:30", 100), ("2026-10-22T09:19:00+05:30", 300)):
                    w.writerow(leg(stamp, "AAA", "CE", vol, 10.0))
            acc = pf.replay(folder, write=True)
            self.assertEqual(acc.captures, 2)
            with (folder / "premium_flow.csv").open(encoding="utf-8") as fh:
                rows = list(csv.DictReader(fh))
            self.assertEqual([float(r["ce_cr"]) for r in rows], [round(100 * 10 / 1e7, 4), round(200 * 10 / 1e7, 4)])
            self.assertEqual(pf.replay(folder, write=False).captures, 2)                  # restoring state does not rewrite the file


if __name__ == "__main__":
    unittest.main()


class PreOpenBaselineTests(unittest.TestCase):
    def test_a_pre_open_first_capture_only_sets_the_baseline(self):
        acc = pf.Accumulator()
        r0 = acc.update([leg("2026-10-22T09:14:01+05:30", "AAA", "CE", 14_000_000, 10.0)])      # yesterday's volume still showing before the open
        self.assertEqual((r0[0]["ce_cr"], r0[0]["pe_cr"]), (0.0, 0.0))
        r1 = acc.update([leg("2026-10-22T09:19:01+05:30", "AAA", "CE", 1_200_000, 11.0)])        # today's volume restarts lower: nothing counted, baseline reset
        self.assertEqual(r1[0]["ce_cr"], 0.0)
        r2 = acc.update([leg("2026-10-22T09:24:01+05:30", "AAA", "CE", 1_700_000, 11.0)])
        self.assertEqual(r2[0]["ce_cr"], round(500_000 * 11.0 / 1e7, 4))
        late = pf.Accumulator()                                                                  # a collector that starts after the open still counts the volume so far
        self.assertGreater(late.update([leg("2026-10-22T10:30:00+05:30", "AAA", "CE", 100_000, 10.0)])[0]["ce_cr"], 0)
