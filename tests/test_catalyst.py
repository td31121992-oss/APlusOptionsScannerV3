import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import catalyst as cat

IST = cat.IST
NOW = datetime(2026, 10, 16, 9, 0, tzinfo=IST)


def write(root, ann=(), ev=()):
    d = Path(root) / "data" / "news_intelligence"
    d.mkdir(parents=True, exist_ok=True)
    (d / "announcements.jsonl").write_text("\n".join(json.dumps(a) for a in ann), encoding="utf-8")
    (d / "events.jsonl").write_text("\n".join(json.dumps(e) for e in ev), encoding="utf-8")


def ann(sym, desc, text, hours_ago, company="Alpha Industries Limited"):
    return {"symbol": sym, "company": company, "desc": desc, "text": text,
            "published_at": (NOW - timedelta(hours=hours_ago)).isoformat(), "url": "http://x"}


def ev(sym, title, hours_ago, source="Upstox"):
    t = NOW - timedelta(hours=hours_ago)
    return {"category": "STOCK_" + sym, "title": title, "source": source, "published_at_raw": t.strftime("%a, %d %b %Y %H:%M:%S +0530"), "url": "http://n"}


class NoLookAheadTests(unittest.TestCase):
    def test_replay_ignores_news_published_after_the_moment(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root, ann=[ann("AAA", "Financial Results", "Net profit jumps 40%", hours_ago=-6)])            # published 6 hours AFTER the replayed moment
            self.assertEqual(cat.bulk(root, NOW), {})
            later = NOW + timedelta(hours=7)
            self.assertEqual(cat.bulk(root, later).get("AAA", {}).get("direction"), "BULLISH")

    def test_replay_does_not_reuse_a_cached_read_of_another_moment(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root, ann=[ann("AAA", "Financial Results", "Net profit jumps 40%", hours_ago=-6)])
            self.assertEqual(cat.bulk(root, NOW + timedelta(hours=7)).get("AAA", {}).get("direction"), "BULLISH")
            self.assertEqual(cat.bulk(root, NOW), {})                                                          # an earlier moment must not see it


class ClassifyTests(unittest.TestCase):
    def test_key_phrases(self):
        self.assertEqual(cat.classify_text("Q2 results: Net profit jumps 45% YoY")[:2], ("RESULTS", 1))
        self.assertEqual(cat.classify_text("Net profit falls 20%, misses estimates")[:2], ("RESULTS", -1))
        self.assertEqual(cat.classify_text("Bagging/Receiving of orders/contracts", "Bagging/Receiving of orders/contracts")[:2], ("ORDER_WIN", 1))
        self.assertEqual(cat.classify_text("Brokerage downgrades stock, cuts target price")[:2], ("RATING", -1))
        self.assertEqual(cat.classify_text("SEBI order against promoter, penalty imposed")[:2], ("REGULATORY", -1))
        self.assertIsNone(cat.classify_text("routine", "Certificate under SEBI (Depositories and Participants) Regulations, 2018"))
        self.assertIsNone(cat.classify_text("Shares trade flat in a quiet session"))

    def test_resignation_weight_depends_on_the_role(self):
        self.assertGreater(cat.classify_text("CFO resigns with immediate effect")[2], cat.classify_text("Independent director resigns")[2])


class ReadTests(unittest.TestCase):
    def test_bullish_filing_is_high_confidence_and_supports_calls(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, ann=[ann("AAA", "Bagging/Receiving of orders/contracts", "Alpha bags order worth Rs 500 crore", 3)])
            r = cat.for_symbol("AAA", Path(tmp), NOW)
            self.assertEqual((r["direction"], r["confidence"], r["type"]), ("BULLISH", "HIGH", "ORDER_WIN"))
            self.assertIn("calls", r["impact"])
            self.assertEqual(r["items"][0]["source"], "NSE filing")

    def test_headline_only_is_medium_and_old_news_fades(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, ann=[ann("BBB", "Press Release", "x", 90, company="Beta Corp Limited")], ev=[ev("BBB", "Beta Corp Q2 results: net profit falls 18% YoY - Upstox", 2)])
            cat._CACHE["key"] = None
            r = cat.for_symbol("BBB", Path(tmp), NOW)
            self.assertEqual((r["direction"], r["confidence"]), ("BEARISH", "MEDIUM"))
            write(tmp, ann=[ann("BBB", "Press Release", "x", 90, company="Beta Corp Limited")], ev=[ev("BBB", "Beta Corp Q2 results: net profit falls 18% YoY - Upstox", 44)])
            cat._CACHE["key"] = None
            r2 = cat.for_symbol("BBB", Path(tmp), NOW)
            self.assertEqual(r2["direction"], "NEUTRAL")           # 44 hours old: weight 3 x 0.28 = 0.8, under the 1.5 bar

    def test_other_company_headlines_in_the_search_bucket_are_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, ann=[ann("AAA", "Press Release", "x", 90)],
                  ev=[ev("AAA", "Gamma Motors results: net profit jumps 30% - Upstox", 1)])
            cat._CACHE["key"] = None
            self.assertEqual(cat.for_symbol("AAA", Path(tmp), NOW)["direction"], "NEUTRAL")

    def test_conflict_and_event_risk(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, ann=[ann("AAA", "Outcome of Board Meeting", "Alpha net profit jumps 40%", 2),
                            ann("AAA", "Fraud/Default/Arrest", "Alpha informs default on loan repayment", 1),
                            ann("CCC", "Board Meeting Intimation", "board meeting to consider financial results for the quarter", 5)])
            cat._CACHE["key"] = None
            r = cat.for_symbol("AAA", Path(tmp), NOW)
            self.assertEqual(r["direction"], "MIXED")
            self.assertTrue(r["event_risk"])
            c = cat.for_symbol("CCC", Path(tmp), NOW)
            self.assertTrue(c["event_risk"])
            self.assertEqual(c["direction"], "NEUTRAL")

    def test_entry_tags_alignment(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, ann=[ann("AAA", "Bagging/Receiving of orders/contracts", "Alpha bags order", 3)])
            cat._CACHE["key"] = None
            now = datetime.now(IST)
            # entry_tags uses the real clock, so re-stamp the item to "now"
            write(tmp, ann=[{**ann("AAA", "Bagging/Receiving of orders/contracts", "Alpha bags order", 0), "published_at": now.isoformat()}])
            cat._CACHE["key"] = None
            t = cat.entry_tags("AAA", "BULLISH", Path(tmp))
            self.assertTrue(t["cat_aligned"] and not t["cat_against"])
            t2 = cat.entry_tags("AAA", "BEARISH", Path(tmp))
            self.assertTrue(t2["cat_against"])
            self.assertEqual(cat.entry_tags("ZZZ", "BULLISH", Path(tmp)), {"cat_dir": "NONE"})


if __name__ == "__main__":
    unittest.main()


class SurfaceTests(unittest.TestCase):
    def test_pages_and_review_carry_the_catalyst(self):
        import aplus_live_pnl_dashboard as dash
        import stock_analysis_tab as sa
        import trade_review as tr
        self.assertIn("<th>Catalyst</th>", dash.FNO_MARKET_WATCH_HTML)
        self.assertEqual(dash.FNO_MARKET_WATCH_HTML.count("`") % 2, 0)
        self.assertIn("/api/catalyst", sa.STOCK_ANALYSIS_HTML)
        rows = [{"cat_dir": "BULLISH", "cat_aligned": "True", "cat_against": "", "net": 700}, {"cat_dir": "BEARISH", "cat_aligned": "", "cat_against": "True", "net": -300},
                {"cat_dir": "NONE", "net": 50}]
        text = "\n".join(tr.verdict_section(rows))
        self.assertIn("News catalyst agreed with the trade | 1 | 1 | +700", text)
        self.assertIn("News catalyst was AGAINST the trade | 1 | 0 | -300", text)
        self.assertIn("No fresh news catalyst | 1 | 1 | +50", text)

    def test_rows_get_a_catalyst(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, ann=[{**ann("AAA", "Bagging/Receiving of orders/contracts", "Alpha bags order", 0), "published_at": datetime.now(IST).isoformat()}])
            cat._CACHE["key"] = None
            rows = [{"symbol": "AAA"}, {"symbol": "ZZZ"}]
            cat.attach(rows, Path(tmp))
            self.assertEqual(rows[0]["catalyst"]["direction"], "BULLISH")
            self.assertNotIn("catalyst", rows[1])
