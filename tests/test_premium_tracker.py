import tempfile
import unittest
from pathlib import Path

import premium_tracker as pt


def q(volume, avg):
    return {"volume": volume, "average_price": avg}


class PremiumTests(unittest.TestCase):
    def data(self):
        meta = {1: ("AAA", "CE"), 2: ("AAA", "PE"), 3: ("BBB", "CE"), 4: ("BBB", "PE"), 5: ("CCC", "PE")}
        quotes = {1: q(1_000_000, 50.0), 2: q(500_000, 20.0), 3: q(100_000, 10.0), 4: q(400_000, 100.0), 5: q(0, 0)}
        return pt.aggregate(quotes, meta, {"AAA": 1.5, "BBB": -2.0})

    def test_aggregate_in_crore_sorted_with_share(self):
        rows = self.data()
        self.assertEqual([r["symbol"] for r in rows], ["AAA", "BBB"])          # CCC traded nothing
        a = rows[0]
        self.assertEqual((a["ce_cr"], a["pe_cr"], a["total_cr"]), (5.0, 1.0, 6.0))      # 10,00,000 x 50 = Rs 5 Cr
        self.assertAlmostEqual(a["ce_share"], 83.3, places=1)
        self.assertEqual(a["stock_pct"], 1.5)

    def test_overall_and_heavy_lists(self):
        o = pt.overall(self.data())
        self.assertAlmostEqual(o["ce_cr"], 5.1)
        self.assertEqual(o["top"]["symbol"], "AAA")
        self.assertEqual(o["ce_heavy"]["symbol"], "AAA")                       # only stocks with 5+ Cr total are ranked
        self.assertEqual(o["pe_heavy"]["symbol"], "AAA")

    def test_history_average_and_ratio(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for i, total in enumerate((4.0, 5.0, 6.0)):
                pt.record(f"2026-10-0{i + 1}", [{"symbol": "AAA", "ce_cr": total, "pe_cr": 0, "total_cr": total, "ce_share": 100, "stock_pct": 0}], root)
            rows = pt.enrich([{"symbol": "AAA", "total_cr": 10.0}, {"symbol": "ZZZ", "total_cr": 1.0}], root, "2026-10-09")
            self.assertEqual(rows[0]["x_avg"], 2.0)                            # 10 / mean(4,5,6)
            self.assertNotIn("x_avg", rows[1])
            self.assertEqual(len(pt.history_means(root, before="2026-10-03")), 1)

    def test_few_days_gives_no_ratio(self):
        with tempfile.TemporaryDirectory() as tmp:
            pt.record("2026-10-01", [{"symbol": "AAA", "ce_cr": 1, "pe_cr": 1, "total_cr": 2, "ce_share": 50, "stock_pct": 0}], Path(tmp))
            self.assertNotIn("x_avg", pt.enrich([{"symbol": "AAA", "total_cr": 4.0}], Path(tmp), "2026-10-05")[0])

    def test_telegram_lines(self):
        rows = pt.enrich(self.data(), Path(tempfile.gettempdir()) / "no_such_root", "2026-10-15")
        text = "\n".join(pt.telegram_lines(rows))
        self.assertIn("PREMIUM TRACKER", text)
        self.assertIn("1. AAA", text)
        self.assertIn("calls", text)

    def test_page_has_what_it_needs(self):
        for key in ("/api/premium-tracker", "CE premium", "OVERALL CE vs PE", "x avg"):
            self.assertIn(key, pt.PREMIUM_HTML)


if __name__ == "__main__":
    unittest.main()
