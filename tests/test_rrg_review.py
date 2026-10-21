import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

import rrg_review as rr


def trade(sym, day, aligned, net, direction="BEARISH", status="CLOSED"):
    return {"symbol": sym, "entry_time": f"{day}T10:00:00+05:30", "rrg_aligned": aligned, "net_pnl": net, "direction": direction, "status": status}


class RrgReviewTests(unittest.TestCase):
    def test_review_splits_aligned_and_reports_what_the_rule_would_have_done(self):
        rows = [trade("A", "2026-10-20", True, 1000), trade("B", "2026-10-20", False, -500), trade("C", "2026-10-20", False, 300),
                trade("D", "2026-10-21", True, -200, "BULLISH"), trade("E", "2026-10-21", False, -900, "BULLISH"),
                trade("F", "2026-10-21", True, 50, status="OPEN"), trade("G", "2026-10-21", "", 10)]        # open trade and a trade without the tag are left out
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data" / "reports").mkdir(parents=True)
            (root / "data" / "intraday_movement").mkdir(parents=True)
            pd.DataFrame(rows[:3]).to_csv(root / "data" / "reports" / "paper_trade_history.csv", index=False)
            (root / "data" / "intraday_movement" / "paper_trade_journal.json").write_text(json.dumps({"trades": rows[3:]}), encoding="utf-8")
            path = rr.run(None, root)
            text = path.read_text(encoding="utf-8")
        self.assertIn("5 closed paper trades with the tag over 2 day(s)", text)
        self.assertIn("Trades skipped: **3** of 5 | P&L removed: **-1,100** | winners it would have lost: **1** (+300)", text)
        self.assertIn("P&L of the remaining aligned trades: **+800**", text)
        self.assertIn("Aligned had the better average on **2 of 2** days", text)

    def test_nothing_without_the_tag_or_without_trades(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(rr.run(None, Path(tmp)))


if __name__ == "__main__":
    unittest.main()
