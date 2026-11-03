from __future__ import annotations

import json
import unittest
from pathlib import Path

import company_profiles as cp
import stock_analysis_tab as sat


class ProfileTests(unittest.TestCase):
    def test_every_fno_stock_has_a_complete_profile(self) -> None:
        report = Path(__file__).resolve().parent.parent / "data" / "reports" / "intraday_movement_latest.json"
        if not report.exists():
            self.skipTest("scanner report not available")
        symbols = {r["symbol"] for r in json.loads(report.read_text(encoding="utf-8"))["fno_market_watch"]["rows"]}
        missing = sorted(symbols - set(cp.PROFILES))
        self.assertEqual(missing, [])
        for sym in symbols:
            p = cp.PROFILES[sym]
            self.assertTrue(all(p[k] for k in ("name", "business", "owner", "founded")), sym)

    def test_lookup_is_case_insensitive_and_safe(self) -> None:
        self.assertEqual(cp.get("adanipower")["owner"].split(" ")[0], "Adani")
        self.assertIn("verify", cp.get("TCS")["note"])
        self.assertIsNone(cp.get("NOSUCHSTOCK"))
        self.assertIsNone(cp.get(""))

    def test_stock_analysis_page_has_a_company_card(self) -> None:
        self.assertIn('id="company"', sat.STOCK_ANALYSIS_HTML)
        self.assertIn("Owner / promoter", sat.STOCK_ANALYSIS_HTML)


if __name__ == "__main__":
    unittest.main()
