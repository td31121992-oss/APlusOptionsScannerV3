"""Dhan's intraday history drops the 09:15 minute when fromDate is exactly 09:15:00, so the day's first candle loses the real open and
opening low (TATAELXSI 14 Oct: chart showed day low 3577.2 while the stock opened and traded at 3467.1). Charts and shadows must ask
from 09:00:00. Static guard so nobody 'tidies' it back."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FILES = ["trade_chart.py", "chart_zones.py", "chirag_shadow.py", "missed_option_returns.py", "stock_analysis_tab.py"]


class FirstCandleFromDateTests(unittest.TestCase):
    def test_single_day_requests_start_before_the_open(self):
        for name in FILES:
            src = (ROOT / name).read_text(encoding="utf-8")
            self.assertNotRegex(src, r'09:15:00', f"{name} requests candles from 09:15:00")
            self.assertRegex(src, r'09:00:00', f"{name} should request from 09:00:00")


if __name__ == "__main__":
    unittest.main()
