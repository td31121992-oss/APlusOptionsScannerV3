import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

import intraday_alert as ia

NOW = datetime(2026, 11, 12, 11, 0, 0)                                    # a Thursday


def write_log(root, lines):
    (root / "logs").mkdir(parents=True, exist_ok=True)
    (root / "logs" / "scanner.log").write_text("\n".join(lines), encoding="utf-8")


def cycle(hhmm):
    return f"2026-11-12 {hhmm}:05 | INFO     | opening_momentum_scanner | MainThread       | Intraday movement cycle phase=MORNING universe=218"


class EvaluateTests(unittest.TestCase):
    def run_eval(self, root, now=NOW):
        with mock.patch.object(ia, "in_session", return_value=True):
            return ia.evaluate(now, root)

    def test_healthy_scanner_has_no_problems(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_log(root, [cycle("10:57"), cycle("10:58"), cycle("10:59")])
            self.assertEqual(self.run_eval(root), {})

    def test_stalled_cycles_failing_cycles_and_stale_open_position(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fails = [f"2026-11-12 10:5{i}:05 | ERROR   | opening_momentum_scanner | MainThread       | Intraday market-data cycle failed category=ConnectTimeout" for i in (3, 4, 5)]
            write_log(root, [cycle("10:40")] + fails)
            (root / "data" / "intraday_movement").mkdir(parents=True)
            (root / "data" / "intraday_movement" / "paper_trade_journal.json").write_text(json.dumps({"trades": [
                {"symbol": "ABB", "status": "OPEN", "last_quote_time": "2026-11-12T10:50:00+05:30"}, {"symbol": "TCS", "status": "CLOSED", "last_quote_time": "2026-11-12T09:30:00"}]}), encoding="utf-8")
            problems = self.run_eval(root)
            self.assertEqual(set(problems), {"CYCLES_STALLED", "CYCLES_FAILING", "POSITIONS_UNMANAGED"})
            self.assertIn("ABB", problems["POSITIONS_UNMANAGED"])
            self.assertNotIn("TCS", problems["POSITIONS_UNMANAGED"])

    def test_nothing_is_checked_outside_the_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(ia.evaluate(datetime(2026, 11, 12, 20, 0), Path(tmp)), {})
            self.assertFalse(ia.in_session(datetime(2026, 11, 14, 11, 0)))                              # a Saturday


class DecideTests(unittest.TestCase):
    def test_sent_once_repeated_after_30_minutes_and_recovery_is_announced(self):
        msgs, state = ia.decide({}, {"CYCLES_STALLED": "no cycle for 7 minutes"}, NOW)
        self.assertEqual(len(msgs), 1)
        self.assertIn("ALERT CYCLES_STALLED", msgs[0])
        msgs2, state2 = ia.decide(state, {"CYCLES_STALLED": "no cycle for 12 minutes"}, datetime(2026, 11, 12, 11, 10))
        self.assertEqual(msgs2, [])                                                                    # still the same episode, not due again
        self.assertEqual(state2["CYCLES_STALLED"], state["CYCLES_STALLED"])
        msgs3, _ = ia.decide(state, {"CYCLES_STALLED": "still"}, datetime(2026, 11, 12, 11, 31))
        self.assertEqual(len(msgs3), 1)                                                                # 31 minutes later: repeated
        msgs4, state4 = ia.decide(state, {}, datetime(2026, 11, 12, 11, 12))
        self.assertEqual((len(msgs4), state4), (1, {}))
        self.assertIn("recovered", msgs4[0])


if __name__ == "__main__":
    unittest.main()
