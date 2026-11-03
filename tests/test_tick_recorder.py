import csv
import gzip
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import footprint_lite as fl
import tick_recorder as tr

IST = timezone(timedelta(hours=5, minutes=30))


def packet(sid, ltp, vol, bid, ask, bq=100, aq=100, ltq=10):
    depth = [{"bid_quantity": bq, "ask_quantity": aq, "bid_orders": 1, "ask_orders": 1, "bid_price": f"{bid:.2f}", "ask_price": f"{ask:.2f}"}] * 5
    return {"type": "Full Data", "security_id": sid, "LTP": f"{ltp:.2f}", "LTQ": ltq, "LTT": "09:31:02", "volume": vol, "total_buy_quantity": 5000, "total_sell_quantity": 4000, "depth": depth}


class ClassifyTests(unittest.TestCase):
    def test_buy_at_the_ask_sell_at_the_bid_and_tick_rule(self):
        prev = {"vol": 1000, "ltp": 100.0, "bid": 99.95, "ask": 100.05, "side": ""}
        self.assertEqual(tr.classify(prev, 100.05, 1050), ("B", 50))
        self.assertEqual(tr.classify(prev, 99.95, 1020), ("S", 20))
        self.assertEqual(tr.classify(prev, 100.02, 1010), ("B", 10))          # inside the spread but up: tick rule
        self.assertEqual(tr.classify(prev, 99.98, 1010), ("S", 10))
        self.assertEqual(tr.classify(prev, 100.0, 1000), ("", 0))              # no volume change
        self.assertEqual(tr.classify(None, 100.0, 1000), ("", 0))              # nothing to compare with yet
        flat = {"vol": 1000, "ltp": 100.0, "bid": 99.90, "ask": 100.10, "side": "S"}
        self.assertEqual(tr.classify(flat, 100.0, 1007), ("S", 7))             # flat price keeps the last side

    def test_packet_row_and_state(self):
        now = datetime(2026, 10, 19, 9, 31, 2, 345000, tzinfo=IST)
        row, st = tr.packet_row(packet("11536", 2400.0, 5000, 2399.9, 2400.1, bq=300, aq=200), "TCS", None, now)
        self.assertEqual(row["ts"], "09:31:02.345")
        self.assertEqual((row["bid"], row["ask"], row["bq"], row["aq"], row["bsum5"], row["asum5"]), ("2399.90", "2400.10", 300, 200, 1500, 1000))
        self.assertEqual(row["side"], "")
        row2, st2 = tr.packet_row(packet("11536", 2400.1, 5040, 2400.0, 2400.2), "TCS", st, now)
        self.assertEqual((row2["tq"], row2["side"]), (40, "B"))
        self.assertEqual(st2["vol"], 5040)


class WriterAndFootprintTests(unittest.TestCase):
    def test_writer_roundtrip_and_candles(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rec = tr.Recorder(root, ("TCS",), {"TCS": "11536"}, "2026-10-19")
            base = datetime(2026, 10, 19, 9, 15, 0, tzinfo=IST)
            feed = None
            seq = [(2400.0, 1000, 2399.9, 2400.1), (2400.1, 1100, 2400.0, 2400.1), (2400.1, 1150, 2400.0, 2400.2), (2399.9, 1250, 2399.9, 2400.0), (2399.9, 1300, 2399.8, 2399.9)]
            for i, (ltp, vol, bid, ask) in enumerate(seq):
                row, rec.prev["TCS"] = tr.packet_row(packet("11536", ltp, vol, bid, ask), "TCS", rec.prev.get("TCS"), base + timedelta(seconds=40 * i))
                rec.writer.write(row)
            rec.writer.close()
            p = root / "data" / "ticks" / "2026-10-19" / "TCS.csv.gz"
            with gzip.open(p, "rt", encoding="utf-8", newline="") as h:
                rows = list(csv.DictReader(h))
            self.assertEqual(len(rows), 5)
            self.assertEqual(rows[1]["side"], "B")                                      # 100 lots at the ask
            bars = fl.candles_from_ticks(rows, "2026-10-19", "TCS")
            self.assertEqual(bars[0]["time"], "09:15")
            self.assertEqual(bars[0]["buy_vol"], 150)                                   # 100 + 50 bought
            self.assertEqual(bars[0]["sell_vol"], 150)                                  # 100 + 50 sold at the bid
            self.assertEqual(bars[0]["delta"], 0)
            self.assertEqual(bars[0]["high"], 2400.1)
            self.assertEqual(bars[0]["low"], 2399.9)
            out = fl.run("2026-10-19", root)
            self.assertTrue(out.exists())
            self.assertIsNone(fl.run("2026-10-20", root))

    def test_truncated_gzip_still_gives_the_rows_before_the_cut(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "data" / "ticks" / "2026-10-19"
            folder.mkdir(parents=True)
            lines = ["ts,sym,ltp,tq,side,bq,aq"] + [f"09:15:{i:02d}.000,TCS,100,10,B,5,5" for i in range(40)]
            raw = gzip.compress(("\n".join(lines) + "\n").encode())
            (folder / "TCS.csv.gz").write_bytes(raw[:-12])                      # cut off: no end-of-stream marker, like a recorder killed mid-write
            out = fl.run("2026-10-19", Path(tmp))
            self.assertIsNotNone(out)

    def test_symbol_setting_all_or_a_list(self):
        uni = {"TCS": 1, "INFY": 2, "SBIN": 3}
        self.assertEqual(tr.resolve_symbols("ALL", uni), ("INFY", "SBIN", "TCS"))
        self.assertEqual(tr.resolve_symbols("", uni), ("INFY", "SBIN", "TCS"))
        self.assertEqual(tr.resolve_symbols("tcs, nope ,SBIN", uni), ("TCS", "SBIN"))

    def test_candle_labels(self):
        rows = [{"ts": "09:15:01.000", "ltp": "100", "tq": "10", "side": "B", "bq": "5", "aq": "5"},
                {"ts": "09:16:01.000", "ltp": "102", "tq": "30", "side": "B", "bq": "5", "aq": "5"},
                {"ts": "09:17:01.000", "ltp": "99", "tq": "10", "side": "S", "bq": "5", "aq": "5"},
                {"ts": "09:19:01.000", "ltp": "101", "tq": "", "side": "", "bq": "5", "aq": "5"},
                {"ts": "09:20:01.000", "ltp": "101", "tq": "20", "side": "S", "bq": "5", "aq": "5"}]
        bars = fl.candles_from_ticks(rows, "d", "X")
        self.assertEqual(len(bars), 2)
        b = bars[0]
        self.assertEqual((b["buy_vol"], b["sell_vol"], b["delta"]), (40, 10, 30))
        self.assertAlmostEqual(b["coth"], (102 - 101) / 3, places=3)                   # closed 1 below the high, range 3
        self.assertAlmostEqual(b["cotl"], (101 - 99) / 3, places=3)
        self.assertEqual(bars[1]["cum_delta"], 10)                                      # 30 + (-20)


if __name__ == "__main__":
    unittest.main()
