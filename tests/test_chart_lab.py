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


if __name__ == "__main__":
    unittest.main()
