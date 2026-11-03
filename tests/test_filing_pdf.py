import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import filing_pdf as fp
import filing_text as ft

IST = timezone(timedelta(hours=5, minutes=30))
NOW = datetime(2026, 10, 26, 10, 0, tzinfo=IST)

HPCL = """Statement of Standalone Financial Results
Particulars Quarter ended Six months ended
1 Income
(a) Revenue from Operations
(b) Other Operating Revenue 550.01 595.50 519.54 1,145.51 1,074.33
Total Income 1,39,887.18 1,46,407 .30 1,10,868.49 2,86,294.48 2,31,526 .14
7 Net Profit/(Loss) for the period (5-6) 3,482.62 {11,526.41) 3,830.37 (8,043.79) 8,201.24
(p) Net Profit Margin(%) 2.50% (7.94%)
"""
TECHM = """1 Revenue from Operations 161,802 157,119 139,949 318,921 273,461 568,154
3 Total Income (1 + 2) 161,728 156,055 140,349 317,783 276,044 568,473
11 Profit after tax (9 - 10) 16,097 14,863 12,017 30,960 23,305 48,055
"""
TURNAROUND = """Revenue from operations 2,100 1,900 1,800
Net Profit/(Loss) for the period 150 (40) (90)
"""
GARBLED = """Total Income 1,n;150 1,62",610 1,S3,453 3,35,360
Revenue from operations 10 9500 100 1 1
"""


class ParseTests(unittest.TestCase):
    def test_indian_results_layouts(self):
        r = fp.parse_results(HPCL)
        self.assertEqual((r["revenue_yoy_pct"], r["revenue_qoq_pct"]), (26.2, -4.5))     # 'Other Operating Revenue' is skipped; the stray space in '407 .30' is repaired
        self.assertEqual((r["pat_yoy_pct"], r["pat_cur"]), (-9.1, 3482.62))               # '{' read as '(', the (5-6) reference and the row number ignored; the margin row skipped
        self.assertNotIn("pat_qoq_pct", r)                                                  # the previous quarter was a loss: no meaningful %
        t = fp.parse_results(TECHM)
        self.assertEqual((t["revenue_yoy_pct"], t["pat_yoy_pct"], t["pat_qoq_pct"]), (15.6, 34.0, 8.3))

    def test_turnaround_and_garbage(self):
        r = fp.parse_results(TURNAROUND)
        self.assertEqual(r["pat_turnaround"], "loss_to_profit")
        self.assertNotIn("pat_yoy_pct", r)
        self.assertEqual(fp.parse_results(GARBLED), {})                                     # absurd changes are left out, not guessed
        self.assertEqual(fp.parse_results("nothing useful here"), {})


class FakeResponse:
    def __init__(self, content=b"%PDF", status=200, size=None):
        self.content, self.status_code = content, status
        self.headers = {"content-length": str(len(content) if size is None else size)}

    def iter_content(self, n):
        yield self.content


class FakeSession:
    def __init__(self, resp):
        self.resp, self.urls = resp, []

    def get(self, url, **kw):
        self.urls.append(url)
        return self.resp


class FetchTests(unittest.TestCase):
    def test_only_https_nse_archive_pdfs(self):
        s = FakeSession(FakeResponse())
        for bad in ("http://nsearchives.nseindia.com/corporate/a.pdf", "https://evil.example.com/a.pdf", "https://nsearchives.nseindia.com.evil.com/a.pdf", "https://nsearchives.nseindia.com/a.exe"):
            self.assertEqual(fp.fetch(bad, s), (None, "FETCH_FAILED"))
        self.assertEqual(s.urls, [])                                                        # never even requested
        self.assertEqual(fp.fetch("https://nsearchives.nseindia.com/corporate/a.pdf", s)[1], "OK")

    def test_size_cap_and_errors(self):
        url = "https://nsearchives.nseindia.com/corporate/a.pdf"
        self.assertEqual(fp.fetch(url, FakeSession(FakeResponse(size=40 * 1024 * 1024)))[1], "TOO_BIG")
        self.assertEqual(fp.fetch(url, FakeSession(FakeResponse(status=404)))[1], "FETCH_FAILED")


class ProcessTests(unittest.TestCase):
    def test_process_new_reads_each_filing_once_newest_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            d = root / "data" / "news_intelligence"
            d.mkdir(parents=True)
            base = "https://nsearchives.nseindia.com/corporate/"
            mk = lambda i, sym, desc, minutes, url: {"id": i, "symbol": sym, "desc": desc, "text": "", "published_at": (NOW - timedelta(minutes=minutes)).isoformat(), "url": base + url}
            rows = [mk("a", "AAA", "Outcome of Board Meeting", 120, "a.pdf"), mk("b", "BBB", "Outcome of Board Meeting", 30, "b.pdf"), mk("c", "CCC", "ESOP/ESOS/ESPS", 10, "c.pdf"),
                    mk("d", "DDD", "Outcome of Board Meeting", 60 * 24 * 10, "d.pdf"), mk("e", "EEE", "Outcome of Board Meeting", 5, "e.html")]
            (d / "announcements.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
            sess = FakeSession(FakeResponse(b"not really a pdf"))
            self.assertEqual(fp.process_new(root, limit=5, now=NOW, session=sess), 2)       # AAA and BBB only: ESOP is not wanted, DDD is too old, EEE is not a PDF
            self.assertEqual(sess.urls, [base + "b.pdf", base + "a.pdf"])                   # newest first
            facts = fp.load_facts(root)
            self.assertEqual({k: v["status"] for k, v in facts.items()}, {"a": "NO_TEXT", "b": "NO_TEXT"})
            self.assertEqual(fp.process_new(root, limit=5, now=NOW, session=sess), 0)       # already read


class TagTests(unittest.TestCase):
    def store(self, root, rows, facts):
        d = root / "data" / "news_intelligence"
        d.mkdir(parents=True)
        (d / "announcements.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
        (d / "pdf_facts.jsonl").write_text("\n".join(json.dumps(f) for f in facts) + "\n", encoding="utf-8")
        ft._CACHE.update(mtime=None, path=None, rows=[])
        ft._FACTS.update(mtime=None, path=None, data={})

    def row(self, i, sym, minutes=60):
        return {"id": i, "symbol": sym, "desc": "Outcome of Board Meeting", "text": "Outcome of the board meeting", "published_at": (NOW - timedelta(minutes=minutes)).isoformat()}

    def test_pdf_numbers_decide_the_results_view(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.store(root, [self.row("a", "UP"), self.row("b", "DOWN"), self.row("c", "FLAT"), self.row("d", "TURN"), self.row("e", "NONE")],
                       [{"id": "a", "status": "OK", "pat_yoy_pct": 24.0, "revenue_yoy_pct": 12.0}, {"id": "b", "status": "OK", "pat_yoy_pct": -31.0, "revenue_yoy_pct": 2.0},
                        {"id": "c", "status": "OK", "pat_yoy_pct": 4.3, "revenue_yoy_pct": 3.0}, {"id": "d", "status": "OK", "pat_turnaround": "loss_to_profit"},
                        {"id": "e", "status": "NO_TABLE"}])
            up = ft.tags("UP", "BULLISH", NOW, root)
            self.assertEqual((up["fl_kind"], up["fl_polarity"], up["fl_pat_yoy"], up["fl_rev_yoy"], up["fl_aligned"]), ("RESULTS_UP", 1, 24.0, 12.0, 1))
            down = ft.tags("DOWN", "BULLISH", NOW, root)
            self.assertEqual((down["fl_kind"], down["fl_polarity"], down["fl_aligned"]), ("RESULTS_DOWN", -1, 0))
            flat = ft.tags("FLAT", "BULLISH", NOW, root)
            self.assertEqual((flat["fl_kind"], flat["fl_polarity"], "fl_aligned" in flat), ("RESULTS_FLAT", 0, False))        # +4.3 % is not news either way (the COLPAL case)
            self.assertEqual(ft.tags("TURN", "BULLISH", NOW, root)["fl_pat_turnaround"], "loss_to_profit")
            self.assertEqual(ft.tags("NONE", "BULLISH", NOW, root), {"fl_n_24h": 1})                                           # no usable table, no view

    def test_order_amount_from_the_pdf(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            r = {"id": "o", "symbol": "ORD", "desc": "Bagging/Receiving of orders/contracts", "text": "received order", "published_at": (NOW - timedelta(minutes=30)).isoformat()}
            self.store(root, [r], [{"id": "o", "status": "OK", "order_cr": 1250.0}])
            t = ft.tags("ORD", "BULLISH", NOW, root)
            self.assertEqual((t["fl_kind"], t["fl_amount_cr"]), ("ORDER_WIN", 1250.0))

    def test_scanned_bank_table_is_marked_unaligned_not_missing(self):
        labels = "Particulars\nQuarter ended\nInterest Earned (a)+(b)\nOther income\nTotal Income (1)+(2)\nNet Profit for the period (12)-(13)\nunaudited financial results\n"
        figures = "\n".join(f"{i * 137 + 1:,}.{i % 100:02d}" for i in range(1, 80))          # a separate block of figures, none on a label line
        self.assertTrue(fp.unaligned_table(labels + figures))
        aligned = "Particulars\nRevenue from operations 1,200.50 1,100.25 1,000.10\nNet profit after tax 100.20 90.10 80.30\nunaudited financial results\n"
        self.assertFalse(fp.unaligned_table(aligned))
        self.assertFalse(fp.unaligned_table("order received worth 5.00 crore"))


if __name__ == "__main__":
    unittest.main()
