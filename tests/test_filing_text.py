import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import filing_text as ft

IST = timezone(timedelta(hours=5, minutes=30))
NOW = datetime(2026, 10, 26, 10, 0, tzinfo=IST)


class ReadTests(unittest.TestCase):
    def test_kinds_and_polarity(self):
        cases = [
            ("Bagging/Receiving of orders/contracts", "XYZ has received an order worth Rs. 450 crore from Indian Railways", "ORDER_WIN", 1),
            ("Outcome of Board Meeting", "approved buy back of equity shares at Rs 500 per share", "BUYBACK", 1),
            ("Outcome of Board Meeting", "approved raising of funds through Qualified Institutions Placement", "FUND_RAISE", -1),
            ("Press Release", "Net profit increased by 24% YoY to Rs 320 crore; revenue grew 12%", "RESULTS_UP", 1),
            ("Outcome of Board Meeting", "Consolidated net loss of Rs 55 crore for the quarter", "RESULTS_DOWN", -1),
            ("Credit Rating", "ICRA has downgraded the long term rating to AA-", "RATING_DOWN", -1),
            ("Credit Rating", "CRISIL upgraded rating to AAA with stable outlook", "RATING_UP", 1),
            ("Action(s) taken or orders passed", "SEBI order imposing penalty of Rs 25 lakh", "REGULATORY_ACTION", -1),
            ("General Updates", "USFDA issued Form 483 with 5 observations for the Baddi plant", "FDA_NEGATIVE", -1),
            ("General Updates", "Received USFDA approval for generic version", "FDA_POSITIVE", 1),
            ("Resignation of Director/KMP/SMP", "resignation of the Chief Financial Officer", "KEY_EXIT", -1),
            ("Acquisition", "Acquisition of 51% stake in ABC Ltd", "ACQUISITION", 0),
            ("General Updates", "Initial Public Offer of Jio Platforms Limited", "OTHER", 0),
            ("ESOP/ESOS/ESPS", "Exercise of 61,135 Shares under Employees Stock Purchase Scheme", "OTHER", 0),
        ]
        for desc, text, kind, pol in cases:
            self.assertEqual(ft.read(desc, text), (kind, pol), (desc, text))

    def test_amounts(self):
        self.assertEqual(ft.amount_cr("order worth Rs. 450 crore"), 450.0)
        self.assertEqual(ft.amount_cr("penalty of Rs 25 lakh"), 0.25)
        self.assertEqual(ft.amount_cr("Rs 1,200 Cr and Rs 5 crore"), 1200.0)
        self.assertEqual(ft.amount_cr("INR 2 billion"), 200.0)
        self.assertIsNone(ft.amount_cr("no amount here"))


class TagTests(unittest.TestCase):
    def store(self, root, rows):
        p = root / "data" / "news_intelligence"
        p.mkdir(parents=True)
        (p / "announcements.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
        ft._CACHE.update(mtime=None, path=None, rows=[])

    def row(self, sym, desc, text, minutes_ago):
        return {"symbol": sym, "desc": desc, "text": text, "published_at": (NOW - timedelta(minutes=minutes_ago)).isoformat()}

    def test_tags_for_a_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.store(root, [self.row("AAA", "Bagging/Receiving of orders/contracts", "received order worth Rs. 450 crore", 90), self.row("AAA", "ESOP/ESOS/ESPS", "Exercise of shares", 20),
                              self.row("BBB", "Credit Rating", "downgraded", 60), self.row("CCC", "Press Release", "Net profit increased 10%", 30 * 60)])      # CCC's is 30 hours old
            t = ft.tags("AAA", "BULLISH", NOW, root)
            self.assertEqual((t["fl_kind"], t["fl_polarity"], t["fl_amount_cr"], t["fl_age_min"], t["fl_aligned"], t["fl_n_24h"]), ("ORDER_WIN", 1, 450.0, 90, 1, 2))     # the newer ESOP filing has no view
            self.assertEqual(ft.tags("AAA", "BEARISH", NOW, root)["fl_aligned"], 0)                    # a put against good news
            self.assertEqual(ft.tags("BBB", "BEARISH", NOW, root)["fl_aligned"], 1)
            self.assertEqual(ft.tags("CCC", "BULLISH", NOW, root), {})                                  # too old
            self.assertEqual(ft.tags("ZZZ", "BULLISH", NOW, root), {})                                  # no filing

    def test_only_no_view_filings(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.store(root, [self.row("AAA", "ESOP/ESOS/ESPS", "Exercise of shares", 20)])
            self.assertEqual(ft.tags("AAA", "BULLISH", NOW, root), {"fl_n_24h": 1})                     # filed, but nothing the words say either way
            self.assertEqual(ft.tags("AAA", "BULLISH", NOW, Path(tmp, "missing")), {})


if __name__ == "__main__":
    unittest.main()
