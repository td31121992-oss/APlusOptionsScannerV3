import json
import tempfile
import unittest
from pathlib import Path

import trade_journal as tj


def trade(i, entry, exit_, high, low, reason="OPTION_STOP_LOSS", status="CLOSED", direction="BULLISH", qty=100, day="20261007", extra=None):
    t = {"paper_trade_id": f"PT-{day}-0930{i:02d}-AAA", "symbol": "AAA", "direction": direction, "setup_family": "ESTABLISHED_TREND", "status": status,
         "entry_time": f"{day[:4]}-{day[4:6]}-{day[6:]}T09:3{i}:00+05:30", "exit_time": f"{day[:4]}-{day[4:6]}-{day[6:]}T10:3{i}:00+05:30",
         "entry_price": str(entry), "exit_price": str(exit_), "highest_option_price": str(high), "lowest_option_price": str(low), "quantity": str(qty),
         "exit_reason": reason, "capital_deployed": str(entry * qty), "spread_percent": "0.5", "option_stop": str(entry * 0.8), "trading_symbol": "AAA-Oct2026-100-CE"}
    t.update(extra or {})
    return t


class JournalTests(unittest.TestCase):
    def _root(self, trades):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / "data" / "intraday_movement").mkdir(parents=True)
        (root / "data" / "intraday_movement" / "paper_trade_journal.json").write_text(json.dumps({"trades": trades}), encoding="utf-8")
        return root

    def test_stats_lessons_and_breakdowns(self):
        root = self._root([trade(1, 50, 58, 76, 49, "PROFIT_PROTECTION_EXIT"), trade(2, 50, 40, 52, 39), trade(3, 50, 60, 62, 49, "RUNNER_TRAIL_EXIT")])
        out = tj.payload(root=root)
        s = out["stats"]
        self.assertEqual((s["closed"], s["wins"]), (3, 2))
        self.assertEqual(s["win_rate"], 66.7)
        self.assertGreater(s["profit_factor"], 1)
        first = next(t for t in out["trades"] if t["return_pct"] == 16.0)
        self.assertTrue(any("gave back" in x.lower() or "Peaked" in x for x in first["lessons"]))
        self.assertEqual(out["curve"][-1]["day"], "2026-10-07")
        self.assertTrue(out["by_setup"] and out["by_hour"] and out["by_exit"])

    def test_drawdown_and_losing_streak(self):
        root = self._root([trade(1, 50, 40, 52, 39), trade(2, 50, 42, 51, 41), trade(3, 50, 60, 62, 49)])
        s = tj.payload(root=root)["stats"]
        self.assertEqual(s["max_losing_streak"], 2)
        self.assertGreater(s["max_drawdown"], 0)

    def test_notes_roundtrip_and_clear(self):
        root = self._root([trade(1, 50, 58, 60, 49)])
        tid = tj.payload(root=root)["trades"][0]["id"]
        tj.save_note(tid, "good entry, early exit", ["good entry", "exit too early"], 4, root)
        j = tj.payload(root=root)["trades"][0]["journal"]
        self.assertEqual((j["note"], j["rating"], j["tags"]), ("good entry, early exit", 4, ["good entry", "exit too early"]))
        tj.save_note(tid, "", [], 0, root)                         # empty note removes the entry
        self.assertEqual(tj.payload(root=root)["trades"][0]["journal"]["rating"], 0)
        with self.assertRaises(ValueError):
            tj.save_note("", "x", [], 1, root)

    def test_date_filter_and_csv_export(self):
        root = self._root([trade(1, 50, 58, 60, 49, day="20261006"), trade(2, 50, 40, 52, 39, day="20261007")])
        self.assertEqual(len(tj.payload("2026-10-07", "2026-10-07", root)["trades"]), 1)
        text = tj.export_csv(root=root)
        self.assertIn("lessons", text.splitlines()[0])
        self.assertEqual(len(text.strip().splitlines()), 3)

    def test_old_open_trade_is_unresolved_not_pnl(self):
        root = self._root([trade(1, 50, 0, 60, 49, status="OPEN", day="20260922"), trade(2, 50, 58, 60, 49)])
        out = tj.payload(root=root)
        self.assertEqual(out["stats"]["unresolved"], 1)
        self.assertEqual(out["stats"]["closed"], 1)

    def test_missing_data_is_safe(self):
        out = tj.payload(root=Path(tempfile.gettempdir(), "no_aplus_journal"))
        self.assertTrue(out["ok"] and out["trades"] == [])


if __name__ == "__main__":
    unittest.main()
