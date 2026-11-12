import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from fast_monitor import FastPositionMonitor
from tests.test_journal_costs_and_session_end import IST, _journal, _open_trade


def closed_trade(**kw):
    base = _open_trade(option_stop=1.0, option_target1=50.0)
    base.update(status="CLOSED", exit_reason="OPTION_STOP_LOSS", exit_price=9.0, exit_time="2026-10-07T10:30:00+05:30")
    base.update(kw)
    return base


class PostExitTapeTests(unittest.TestCase):
    def test_closed_trade_keeps_being_recorded_until_1525(self):
        with tempfile.TemporaryDirectory() as tmp:
            j = _journal(tmp, "2026-10-07", [closed_trade()])
            self.assertEqual(j.post_exit_watch_ids(datetime(2026, 10, 7, 11, 0, tzinfo=IST)), ["123"])
            self.assertEqual(j.record_post_exit({"123": {"last_price": 8.5}}, datetime(2026, 10, 7, 11, 0, tzinfo=IST)), 1)
            self.assertEqual(j.record_post_exit({"123": {"last_price": 8.4}}, datetime(2026, 10, 7, 11, 0, 5, tzinfo=IST)), 0)     # throttled (15 s)
            self.assertEqual(j.record_post_exit({"123": {"last_price": 8.3}}, datetime(2026, 10, 7, 11, 0, 20, tzinfo=IST)), 1)
            tape = Path(tmp, "option_trade_tape", "2026-10-07", "PT-TEST-1.csv").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(tape), 3)
            self.assertIn("POST_EXIT", tape[1])
            self.assertEqual(j.post_exit_watch_ids(datetime(2026, 10, 7, 15, 25, tzinfo=IST)), [])
            self.assertEqual(j.record_post_exit({"123": {"last_price": 8.0}}, datetime(2026, 10, 7, 15, 26, tzinfo=IST)), 0)

    def test_session_end_exits_and_other_days_are_not_watched(self):
        with tempfile.TemporaryDirectory() as tmp:
            j = _journal(tmp, "2026-10-07", [closed_trade(exit_reason="SESSION_END"), closed_trade(exit_time="2026-10-06T10:30:00+05:30")])
            self.assertEqual(j.post_exit_watch_ids(datetime(2026, 10, 7, 11, 0, tzinfo=IST)), [])

    def test_trading_state_is_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            j = _journal(tmp, "2026-10-07", [closed_trade()])
            before = dict(j.trades[0])
            j.record_post_exit({"123": {"last_price": 2.0}}, datetime(2026, 10, 7, 11, 0, tzinfo=IST))
            self.assertEqual(dict(j.trades[0]), before)

    def test_fast_monitor_adds_ids_to_the_same_single_request_and_only_when_a_position_is_open(self):
        with tempfile.TemporaryDirectory() as tmp:
            open_t = _open_trade(option_stop=1.0, option_target1=50.0)
            open_t.update(paper_trade_id="PT-OPEN", trade_id="PT-OPEN", option_security_id="777")
            j = _journal(tmp, "2026-10-07", [open_t, closed_trade()])
            calls = []

            class Client:
                def get_market_quotes(self, req, mode="quote"):
                    calls.append(list(req["NSE_FNO"]))
                    return {"NSE_FNO": {"777": {"last_price": 10.1}, "123": {"last_price": 8.8}}}

            now = datetime(2026, 10, 7, 11, 0, tzinfo=IST)
            m = FastPositionMonitor(j, Client(), interval=3, clock=lambda: now)
            m.tick(now)
            self.assertEqual(len(calls), 1)
            self.assertEqual(sorted(calls[0]), ["123", "777"])
            self.assertTrue(Path(tmp, "option_trade_tape", "2026-10-07", "PT-TEST-1.csv").exists())
            # nothing open -> no request at all (so no extra API calls just for the research tape)
            j2 = _journal(tmp + "/b", "2026-10-07", [closed_trade()])
            calls.clear()
            FastPositionMonitor(j2, Client(), interval=3, clock=lambda: now).tick(now)
            self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
