import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

import money_flow
import sector_analysis as sa


def row(sym, sector, chg, gap=0.0, prev=100.0):
    return {"symbol": sym, "sector": sector, "from_prev_close_pct": chg, "gap_pct": gap, "previous_close": prev, "ltp": prev * (1 + chg / 100)}


class HeadlineTests(unittest.TestCase):
    def test_story_templates(self):
        self.assertEqual(sa.headline(0.1, 1.0, 0.8, 80)[0], "A quiet open, then a steady climb.")
        self.assertEqual(sa.headline(0.1, 1.0, 0.1, 80)[0], "A quiet open, then a late climb.")
        self.assertEqual(sa.headline(1.2, 0.1, 0.0, 50)[0], "A strong gap-up open, then a sideways session.")
        self.assertEqual(sa.headline(-0.5, -1.0, -0.8, 20)[0], "A gap-down open, then a steady slide.")
        self.assertEqual(sa.headline(0.0, 0.0, None, 80)[1], "broad strength")


class TableTests(unittest.TestCase):
    def test_sector_table_ranks_by_move_and_counts_breadth(self):
        rows = [row("A1", "IT", 3.0), row("A2", "IT", 2.0), row("B1", "Oil", -0.2), row("B2", "Oil", 0.4)]
        tab = sa.sector_table(rows, {"A1": 100.0, "A2": 50.0, "B1": 10.0})
        self.assertEqual([t["sector"] for t in tab], ["IT", "Oil"])
        self.assertEqual((tab[0]["breadth"], tab[1]["breadth"]), (100, 50))
        self.assertEqual(tab[0]["turnover_cr"], 150.0)


class PayloadTests(unittest.TestCase):
    def test_payload_end_to_end_with_order_book(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        for d in ("order_book", "reports", "reference", "market_context"):
            (root / "data" / d).mkdir(parents=True)
        rows = [row("AAA", "IT", 2.0, gap=1.5), row("BBB", "IT", 1.0), row("CCC", "Oil", -1.0)]
        (root / "data" / "reports" / "fno_market_watch_latest.json").write_text(json.dumps({"rows": rows}), encoding="utf-8")
        (root / "data" / "reference" / "fno_sector_map.csv").write_text("symbol,sector\nAAA,IT\nBBB,IT\nCCC,Oil\n", encoding="utf-8")
        lines = ["time,symbol,ltp,volume,imbalance\n"]
        for k in range(60):                                                 # 60 minutes of readings; enough stocks per minute is needed for the index series
            for sym, px in (("AAA", 100 + k * 0.05), ("BBB", 100 + k * 0.02), ("CCC", 100 - k * 0.02)):
                lines.append(f"2026-10-09T09:{15 + k // 60:02d}:00+05:30,{sym},{px},{k * 1000},0\n".replace("09:15:00", f"09:{15 + k % 45:02d}:00"))
        (root / "data" / "order_book" / "2026-10-09.csv").write_text("".join(lines), encoding="utf-8")
        money_flow._reset("t")
        out = sa.payload(root, date(2026, 10, 9))
        self.assertTrue(out["ok"])
        self.assertEqual((out["up"], out["down"]), (2, 1))
        self.assertEqual(out["strongest"]["sector"], "IT")
        self.assertEqual(out["weakest"]["sector"], "Oil")
        self.assertEqual(out["leading"] + out["lagging"], 3)
        self.assertEqual(len(out["stocks"]), 3)
        self.assertIn("AAA", out["active"])

    def test_missing_data(self):
        self.assertFalse(sa.payload(Path(tempfile.gettempdir(), "no_aplus_sector"), date(2026, 10, 9))["ok"])


if __name__ == "__main__":
    unittest.main()
