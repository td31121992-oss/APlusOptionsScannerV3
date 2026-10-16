import json
import tempfile
import unittest
from pathlib import Path

import early_entry_review as eer


def bars(rise_at=30):
    """5-minute option bars from 09:15; flat at 10, then a climb starting at minute index `rise_at`."""
    out = []
    for i in range(70):
        m = 555 + 5 * i
        p = 10.0 if i < rise_at else 10.0 + 0.4 * (i - rise_at)
        out.append((m, p, p * 1.01, p * 0.99, p))
    return out


def setup(root: Path, delay_minutes=15):
    mo = root / "data" / "missed_opportunities" / "2026-10-15"
    mo.mkdir(parents=True)
    (mo / "option_returns.json").write_text(json.dumps([
        {"symbol": "AAA", "dir": "BULLISH", "kind": "ATM", "fate": "TRADED", "ready": "10:00"},
        {"symbol": "BBB", "dir": "BULLISH", "kind": "ATM", "fate": "V2_BLOCKED", "ready": "10:00"}]), encoding="utf-8")
    rep = root / "data" / "reports"
    rep.mkdir(parents=True)
    em = 10 * 60 + delay_minutes
    trades = {"paper_trades": [
        {"paper_trade_id": "T1", "symbol": "AAA", "option_type": "CE", "entry_time": f"2026-10-15T{em // 60:02d}:{em % 60:02d}:11+05:30", "option_security_id": "123", "return_percent": 5.0},
        {"paper_trade_id": "T2", "symbol": "BBB", "option_type": "CE", "entry_time": "2026-10-15T10:20:11+05:30", "option_security_id": "124"}]}
    (rep / "paper_trade_history.json").write_text(json.dumps(trades), encoding="utf-8")


class EarlyEntryTests(unittest.TestCase):
    def test_matches_only_traded_signals_and_measures_both_starts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            setup(root)
            path = eer.run("2026-10-15", root, lambda sid, day: bars(10))
            text = path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(text), 2)                                  # BBB was never traded, so it is not matched
            row = dict(zip(text[0].split(","), text[1].split(",")))
            self.assertEqual(row["symbol"], "AAA")
            self.assertEqual(row["delay_min"], "15")
            self.assertGreater(float(row["flag_close"]), float(row["act_close"]))       # an earlier start on a rising option closes better
            self.assertIn("Earlier-entry shadow", (root / "data" / "shadow_rules" / "early_entry.md").read_text(encoding="utf-8"))

    def test_missing_files_and_bars(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(eer.run("2026-10-01", Path(tmp), lambda s, d: []))
            root = Path(tmp) / "r"
            setup(root)
            eer.run("2026-10-15", root, lambda sid, day: [])
            self.assertEqual(len((root / "data" / "shadow_rules" / "early_entry" / "2026-10-15.csv").read_text(encoding="utf-8").splitlines()), 1)   # header only

    def test_verdict(self):
        self.assertFalse(eer.verdict([])[0])
        rows = [{"day": f"2026-10-0{1 + i % 6}", "flag_close": "10", "act_close": "2"} for i in range(40)]
        self.assertTrue(eer.verdict(rows)[0])
        self.assertFalse(eer.verdict([{**r, "flag_close": "3"} for r in rows])[0])


if __name__ == "__main__":
    unittest.main()
