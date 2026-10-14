import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import index_strip as ix

IST = ZoneInfo("Asia/Kolkata")


def quotes():
    return {13: {"ltp": 22600.0, "open": 22700.0, "close": 22500.0}, 21: {"ltp": 15.0, "open": 14.0, "close": 14.5}}


class IndexStripTests(unittest.TestCase):
    def test_rows_use_prev_close_cache_and_open(self):
        rows = {r["id"]: r for r in ix.build_rows(quotes(), {13: 22400.0}, market_open=False)}
        r = rows[13]
        self.assertAlmostEqual(r["pct_open"], -0.44, places=2)
        self.assertAlmostEqual(r["pct_prev"], 0.89, places=2)
        self.assertEqual(r["change"], 200.0)

    def test_quote_close_is_only_used_while_the_market_is_open(self):
        after = {r["id"]: r for r in ix.build_rows(quotes(), None, market_open=False)}[13]
        self.assertIsNone(after["pct_prev"])                       # after hours the quote close is today's close: not trusted
        live = {r["id"]: r for r in ix.build_rows(quotes(), None, market_open=True)}[13]
        self.assertAlmostEqual(live["pct_prev"], 0.44, places=2)

    def test_missing_quotes_give_none(self):
        r = {x["id"]: x for x in ix.build_rows({}, None, True)}[25]
        self.assertEqual((r["ltp"], r["pct_open"], r["pct_prev"]), (0.0, None, None))

    def test_groups_and_names(self):
        rows = ix.build_rows(quotes(), None, True)
        self.assertEqual({r["group"] for r in rows}, {"main", "sector"})
        self.assertIn("BANK NIFTY", [r["name"] for r in rows])
        self.assertIn("NIFTY IT", [r["name"] for r in rows])

    def test_payload_uses_injected_fetch_and_reports_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            ix._state.update({"quote": None, "quote_at": 0.0, "prev": {13: 22400.0}, "prev_day": "2026-10-14", "prev_thread": None, "error": ""})
            out = ix.payload(Path(tmp), fetch_quotes=lambda root: quotes(), now=datetime(2026, 10, 14, 11, 0, tzinfo=IST))
            self.assertTrue(out["ok"] and out["market_open"] and out["prev_ready"])
            self.assertEqual(len(out["rows"]), len(ix.ALL))
            ix._state.update({"quote": None, "quote_at": 0.0})

            def boom(root):
                raise RuntimeError("quote HTTP 429")
            bad = ix.payload(Path(tmp), fetch_quotes=boom, now=datetime(2026, 10, 14, 11, 0, tzinfo=IST))
            self.assertFalse(bad["ok"])
            self.assertIn("429", bad["error"])

    def test_inject_once_above_header(self):
        page = '<body><div class="header"><div><div class="brandrow">X</div></div></div></body>'
        out = ix.inject(page)
        self.assertLess(out.index("aplus-index-strip"), out.index('class="header"'))
        self.assertEqual(ix.inject(out), out)
        self.assertEqual(ix.inject("<html>nothing</html>"), "<html>nothing</html>")


if __name__ == "__main__":
    unittest.main()
