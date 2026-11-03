import json
import tempfile
import unittest
from pathlib import Path

import option_runup as ou


def bar(minute, lo, hi, close):
    return {"minute": minute, "low": lo, "high": hi, "close": close}


BARS = [bar(9 * 60 + 15 + 5 * i, 10 + i, 12 + i, 11 + i) for i in range(20)]      # climbing 1 per bar; the entry minute is 10:39 (bar index 15 would start at 10:30)


class MetricTests(unittest.TestCase):
    def test_only_earlier_bars_count_and_ratios(self):
        m = ou.metrics(BARS, 10 * 60 + 39, 26.0)
        # bars starting before 10:39 are indexes 0..16 (last start 10:35 -> close 27, high 28); 15 min earlier = bar starting 10:20 (index 13, close 24)
        self.assertEqual(m["run15_pct"], round((26 / 24 - 1) * 100, 1))
        self.assertEqual(m["vs_high_pct"], round(26 / 28 * 100, 1))
        self.assertEqual(m["from_low_pct"], round((26 / 10 - 1) * 100, 1))

    def test_no_history(self):
        self.assertEqual(ou.metrics([], 600, 5.0), {})
        self.assertEqual(ou.metrics(BARS[:1], 600, 5.0), {})

    def test_bucket(self):
        self.assertEqual(ou.bucket(10), "run15 under 25 %")
        self.assertEqual(ou.bucket(97), "run15 75 % and over")
        self.assertEqual(ou.bucket(""), "no history")


class RunTests(unittest.TestCase):
    def test_end_to_end(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            p = root.joinpath(*ou.JOURNAL)
            p.parent.mkdir(parents=True)
            trades = [{"symbol": "AAA", "direction": "BEARISH", "entry_time": "2026-10-26T10:39:00+05:30", "entry_price": 26.0, "quantity": 100, "highest_option_price": 26.0,
                       "status": "CLOSED", "net_pnl": -500, "option_security_id": "1", "trading_symbol": "AAA-Nov-100-PE"},
                      {"symbol": "BBB", "direction": "BULLISH", "entry_time": "2026-10-25T10:39:00+05:30", "entry_price": 5, "quantity": 1, "option_security_id": "2"}]
            p.write_text(json.dumps({"trades": trades}), encoding="utf-8")
            out = ou.run("2026-10-26", root, fetch=lambda sid, day: BARS)
            text = out.read_text(encoding="utf-8")
            self.assertIn("zero-peak", text.lower())
            rows = list(__import__("csv").DictReader(root.joinpath(*ou.LEDGER).open(encoding="utf-8")))
            self.assertEqual(len(rows), 1)
            self.assertEqual((rows[0]["zero_peak"], rows[0]["result_rs"]), ("1", "-500"))


if __name__ == "__main__":
    unittest.main()
