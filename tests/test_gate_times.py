import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

import gate_times


def report(stamp, ready=True, rejected=None, v2_blocked=None, traded=False):
    cand = {"symbol": "AAA", "direction": "BULLISH", "shortlist": "ENTRY_READY" if ready else "WATCH", "ltp": 100}
    if traded:
        cand["paper_trade_id"] = "PT1"
    return {"generated_at": f"2026-10-09T{stamp}:00+05:30", "candidates": [cand],
            "aplus_selective_gate": {"rejected_symbols": rejected or []},
            "stock_selection_v2": {"blocked": v2_blocked or []}}


class GateTimesTests(unittest.TestCase):
    def test_since_times_follow_verdict_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp, "data", "reports")
            d.mkdir(parents=True)
            seq = [("09:25:01", report("09:25", rejected=[{"symbol": "AAA", "direction": "BULLISH", "status": "A_PLUS_WAIT_PIVOT"}])),
                   ("09:26:01", report("09:26", rejected=[{"symbol": "AAA", "direction": "BULLISH", "status": "A_PLUS_WAIT_PIVOT"}])),
                   ("09:27:01", report("09:27", v2_blocked=[{"symbol": "AAA", "direction": "BULLISH", "reasons": ["not top5(x)"]}])),
                   ("09:28:01", report("09:28", traded=True))]
            for stamp, rep in seq:
                (d / f"intraday_movement_20261009_{stamp.replace(':', '')}.json").write_text(json.dumps(rep), encoding="utf-8")
            rows = [{"symbol": "AAA", "direction": "BULLISH"}]
            gate_times.attach(rows, Path(tmp), date(2026, 10, 9))
            r = rows[0]
            self.assertEqual(r["first_ready"], "09:25")
            self.assertEqual(r["aplus_since"], "09:27")        # rejected 09:25-09:26, passed from 09:27
            self.assertEqual(r["v2_since"], "09:28")           # blocked at 09:27, passes again once traded
            self.assertEqual(r["traded_at"], "09:28")


if __name__ == "__main__":
    unittest.main()
