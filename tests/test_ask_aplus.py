import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import ask_aplus as a

ROWS = [{"symbol": "POWERGRID", "sector": "Power/Utilities", "ltp": 300.0, "previous_close": 290.0, "from_prev_close_pct": 3.4, "from_open_pct": 1.0},
        {"symbol": "TATAPOWER", "sector": "Power/Utilities", "ltp": 400.0, "previous_close": 400.0, "from_prev_close_pct": -0.5, "from_open_pct": -0.2},
        {"symbol": "NTPC", "sector": "Power/Utilities", "ltp": 350.0, "previous_close": 351.0, "from_prev_close_pct": -0.3, "from_open_pct": 0.1},
        {"symbol": "GVT&D", "sector": "Capital Goods", "ltp": 1.0, "previous_close": 1.0, "from_prev_close_pct": -2.0, "from_open_pct": -1.0}]


class FakeClient:
    def __init__(self):
        self.calls = []
        self.messages = self

    def create(self, **kw):
        self.calls.append(kw)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text="Answer.")], stop_reason="end_turn", usage=SimpleNamespace(input_tokens=1000, output_tokens=100))


class AskTests(unittest.TestCase):
    def test_market_facts_counts_and_sectors(self):
        m = a.market_facts({"generated_at": "2026-11-13T15:29:35+05:30", "rows": ROWS})
        self.assertEqual((m["advancing"], m["declining"], m["stocks"]), (1, 3, 4))
        self.assertEqual(m["best_sectors"][0]["sector"], "Power/Utilities")
        self.assertEqual(m["top_gainers"][0]["symbol"], "POWERGRID")

    def test_symbol_matching(self):
        syms = [r["symbol"] for r in ROWS]
        self.assertEqual(a.find_symbols("why is powergrid on top?", syms), ["POWERGRID"])
        self.assertEqual(a.find_symbols("why is power grid on top", syms), ["POWERGRID"])
        self.assertEqual(a.find_symbols("what about GVT&D and ntpc", syms), ["GVT&D", "NTPC"])
        self.assertEqual(a.find_symbols("why is the whole market red", syms), [])

    def test_ask_sends_facts_not_tools_and_records_spend(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data" / "reports").mkdir(parents=True)
            (root / "data" / "reports" / "fno_market_watch_latest.json").write_text(json.dumps({"generated_at": "2026-11-13T15:29:35+05:30", "rows": ROWS}), encoding="utf-8")
            c = FakeClient()
            r = a.ask("Why is powergrid on top?", [], root, client=c)
            self.assertTrue(r["ok"])
            self.assertEqual(r["answer"], "Answer.")
            sent = c.calls[0]
            self.assertNotIn("tools", sent)
            self.assertIn("POWERGRID", sent["messages"][-1]["content"])
            self.assertGreater(a.spent_today(root), 0)
            self.assertTrue((root / "data" / "ask_aplus" / "log.jsonl").exists())

    def test_daily_cap_blocks_the_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            a._add_spend(5.0, root)
            c = FakeClient()
            r = a.ask("anything", [], root, client=c)
            self.assertFalse(r["ok"])
            self.assertEqual(c.calls, [])

    def test_empty_question_and_missing_key(self):
        self.assertFalse(a.ask("   ")["ok"])


if __name__ == "__main__":
    unittest.main()
