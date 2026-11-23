import gzip
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import chart_lab as cl

IST = timezone(timedelta(hours=5, minutes=30))


def bar(day, hh, mm, o, h, l, c, v=100):
    return {"t": int(datetime(*day, hh, mm, tzinfo=IST).timestamp()), "o": o, "h": h, "l": l, "c": c, "v": v}


class ResampleTests(unittest.TestCase):
    def test_15_minute_bars_align_to_the_session_open_and_do_not_cross_days(self):
        rows = [bar((2026, 10, 21), 9, 15, 100, 101, 99, 100.5), bar((2026, 10, 21), 9, 20, 100.5, 103, 100, 102), bar((2026, 10, 21), 9, 25, 102, 102.5, 98, 99),
                bar((2026, 10, 21), 9, 30, 99, 100, 98.5, 99.5), bar((2026, 10, 22), 9, 15, 120, 121, 119, 120.5)]
        out = cl.resample(rows, 15)
        self.assertEqual(len(out), 3)                                              # 09:15-09:29, 09:30-09:44 on the 21st and 09:15-09:29 on the 22nd
        first = out[0]
        self.assertEqual((first["o"], first["h"], first["l"], first["c"], first["v"]), (100, 103, 98, 99, 300))
        self.assertEqual(datetime.fromtimestamp(first["t"], IST).strftime("%H:%M"), "09:15")
        self.assertEqual(datetime.fromtimestamp(out[1]["t"], IST).strftime("%H:%M"), "09:30")
        self.assertEqual(datetime.fromtimestamp(out[2]["t"], IST).strftime("%d %H:%M"), "22 09:15")

    def test_hourly_bar_groups_twelve_five_minute_bars(self):
        rows = [bar((2026, 10, 21), 9 + (15 + 5 * i) // 60, (15 + 5 * i) % 60, 100 + i, 101 + i, 99 + i, 100.5 + i) for i in range(14)]
        out = cl.resample(rows, 60)
        self.assertEqual([datetime.fromtimestamp(b["t"], IST).strftime("%H:%M") for b in out], ["09:15", "10:15"])
        self.assertEqual(out[0]["v"], 1200)


class PayloadTests(unittest.TestCase):
    def test_candles_rejects_unknown_symbols_and_timeframes_and_shifts_times_to_ist(self):
        with mock.patch.object(cl, "symbols", return_value=["TCS"]):
            self.assertFalse(cl.candles("NOPE", "5m")["ok"])
            self.assertFalse(cl.candles("TCS", "7m")["ok"])
            rows = [bar((2026, 10, 22), 9, 15, 100, 101, 99, 100)]
            cl._CACHE.clear()
            with mock.patch.object(cl, "_intraday", return_value=rows):
                out = cl.candles("tcs", "5m")
            self.assertTrue(out["ok"])
            self.assertEqual(out["candles"][0]["t"], rows[0]["t"] + cl.SHIFT)

    def test_delta_payload_reads_recorded_ticks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / "data" / "ticks" / "2026-10-20"
            folder.mkdir(parents=True)
            head = "ts,sym,ltp,ltq,ltt,vol,tbq,tsq,bid,bq,ask,aq,bsum5,asum5,tq,side"
            rows = [head, "09:15:10.000,TCS,100,1,,1,1,1,99,1,101,1,1,1,300,B", "09:16:10.000,TCS,100,1,,1,1,1,99,1,101,1,1,1,100,S", "09:21:10.000,TCS,100,1,,1,1,1,99,1,101,1,1,1,50,S"]
            with gzip.open(folder / "TCS.csv.gz", "wt", encoding="utf-8") as h:
                h.write("\n".join(rows) + "\n")
            cl._CACHE.clear()
            out = cl.delta_payload("TCS", root)
            self.assertTrue(out["ok"])
            self.assertEqual([b["delta"] for b in out["bars"]], [200, -50])
            self.assertEqual(cl.delta_payload("INFY", root)["bars"], [])


class FreshnessTests(unittest.TestCase):
    def setUp(self):
        cl._CACHE.clear()
        cl._FAILED.clear()

    def test_a_cached_copy_keeps_its_real_fetch_time(self):
        calls = []
        with mock.patch.object(cl.time, "time", side_effect=[1000.0, 1000.0, 1010.0]):
            v1 = cl._ttl_meta(("k",), 20, lambda: calls.append(1) or "A")
            v2 = cl._ttl_meta(("k",), 20, lambda: calls.append(1) or "B")
        self.assertEqual(v1, ("A", 1000.0, False, ""))
        self.assertEqual(v2, ("A", 1000.0, False, ""))                                 # served from the cache: still stamped with the fetch time, not "now"
        self.assertEqual(len(calls), 1)

    def test_failed_refresh_serves_the_old_copy_marked_stale_with_the_reason(self):
        cl._CACHE[("k",)] = (1000.0, "OLD")

        def boom():
            raise RuntimeError("shared Upstox budget (chart) used up")

        with mock.patch.object(cl.time, "time", return_value=1100.0):
            val, at, stale, note = cl._ttl_meta(("k",), 20, boom)
        self.assertEqual((val, at, stale), ("OLD", 1000.0, True))
        self.assertIn("budget", note)
        with mock.patch.object(cl.time, "time", return_value=1103.0):                  # inside the retry pause: Upstox is not asked again
            calls = []
            val, at, stale, note = cl._ttl_meta(("k",), 20, lambda: calls.append(1) or "NEW")
        self.assertEqual((val, stale, calls), ("OLD", True, []))
        with mock.patch.object(cl.time, "time", return_value=1120.0):                  # after the pause it tries again and recovers
            val, at, stale, note = cl._ttl_meta(("k",), 20, lambda: "NEW")
        self.assertEqual((val, at, stale, note), ("NEW", 1120.0, False, ""))

    def test_nothing_held_means_the_error_is_raised(self):
        def boom():
            raise RuntimeError("down")

        with self.assertRaises(RuntimeError):
            cl._ttl_meta(("k",), 20, boom)

    def test_candles_reports_age_and_stale_flag(self):
        rows = [bar((2026, 10, 22), 9, 15, 100, 101, 99, 100)]
        with mock.patch.object(cl, "symbols", return_value=["TCS"]):
            with mock.patch.object(cl, "_intraday", return_value=rows):
                fresh = cl.candles("TCS", "5m")
            self.assertTrue(fresh["ok"] and not fresh["stale"])
            self.assertLessEqual(fresh["age_s"], 2)
            key = ("5m", "TCS")
            cl._CACHE[key] = (cl._CACHE[key][0] - 300, cl._CACHE[key][1])               # the held copy is now 5 minutes old
            with mock.patch.object(cl, "_intraday", side_effect=RuntimeError("UpstoxLimit: used up")):
                old = cl.candles("TCS", "5m")
        self.assertTrue(old["ok"])
        self.assertTrue(old["stale"])
        self.assertGreaterEqual(old["age_s"], 299)
        self.assertIn("UpstoxLimit", old["note"])
        self.assertEqual(old["candles"], fresh["candles"])                             # the chart keeps drawing, with a warning

    def test_page_has_the_freshness_label_and_surfaces_refresh_failures(self):
        self.assertIn('id="fresh"', cl.CHART_LAB_HTML)
        self.assertIn("function fresh()", cl.CHART_LAB_HTML)
        self.assertIn("S.fail=", cl.CHART_LAB_HTML)


if __name__ == "__main__":
    unittest.main()
