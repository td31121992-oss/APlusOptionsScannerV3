import unittest
from datetime import datetime, timedelta

import trade_review as tr
from paper_trade_journal import PaperTradeJournal


class Holder:
    _number = staticmethod(lambda v: float(v or 0))
    _record_confirm5 = PaperTradeJournal._record_confirm5


class QualityTests(unittest.TestCase):
    def test_held_failed_and_rank(self):
        h = Holder()
        t0 = datetime(2026, 10, 15, 9, 30)
        a = {"entry_time": t0.isoformat()}
        b = {"entry_time": (t0 + timedelta(minutes=2)).isoformat()}
        h.trades = [a, b]
        h._record_confirm5(a, 0.2, t0 + timedelta(minutes=1))
        self.assertNotIn("confirm5", a)
        h._record_confirm5(a, -0.1, t0 + timedelta(minutes=3))
        h._record_confirm5(a, 0.4, t0 + timedelta(minutes=5))
        self.assertEqual((a["confirm5"], a["day_entry_rank"], a["confirm5_min_pct"]), ("HELD", 1, -0.1))
        h._record_confirm5(b, -0.5, t0 + timedelta(minutes=8))
        self.assertEqual((b["confirm5"], b["day_entry_rank"]), ("FAILED", 2))
        h._record_confirm5(a, -9, t0 + timedelta(minutes=30))
        self.assertEqual(a["confirm5"], "HELD")                 # decided once

    def test_day_cap_flag_is_set_with_the_entry_order_and_folds_into_the_quality_count(self):
        h = Holder()
        t0 = datetime(2026, 10, 15, 9, 30)
        trades = [{"entry_time": (t0 + timedelta(minutes=i)).isoformat()} for i in range(7)]
        trades[5].update(gs_q_block=1, gs_q_pass=False)                       # entry #6 already failed one gate at entry
        trades[6].update(gs_q_block=0, gs_q_pass=True)                        # entry #7 passed both entry-time gates
        h.trades = trades
        for tr_ in trades:
            h._record_confirm5(tr_, 0.1, t0 + timedelta(minutes=30))
        self.assertEqual([t["day_entry_rank"] for t in trades], [1, 2, 3, 4, 5, 6, 7])
        self.assertEqual([t["gs_day_cap_over"] for t in trades], [False] * 5 + [True, True])
        self.assertEqual((trades[5]["gs_q_block"], trades[5]["gs_q_pass"]), (2, False))
        self.assertEqual((trades[6]["gs_q_block"], trades[6]["gs_q_pass"]), (1, False))     # the cap alone blocks it
        self.assertNotIn("gs_q_block", trades[0])

    def test_confirm10_shadow_decided_once_after_ten_minutes(self):
        t0 = datetime(2026, 10, 15, 9, 30)
        a = {"entry_time": t0.isoformat()}
        PaperTradeJournal._record_confirm10(a, -0.3, t0 + timedelta(minutes=9))
        self.assertNotIn("confirm10", a)
        PaperTradeJournal._record_confirm10(a, 0.0, t0 + timedelta(minutes=10))
        self.assertEqual((a["confirm10"], a["confirm10_pct"]), ("FAILED", 0.0))      # above zero is required
        PaperTradeJournal._record_confirm10(a, 0.9, t0 + timedelta(minutes=20))
        self.assertEqual(a["confirm10"], "FAILED")                                   # decided once
        b = {"entry_time": t0.isoformat()}
        PaperTradeJournal._record_confirm10(b, 0.01, t0 + timedelta(minutes=12))
        self.assertEqual(b["confirm10"], "HELD")

    def test_split_caps_at_five(self):
        rows = [{"symbol": f"S{i}", "entry_time": f"09:{30 + i}", "confirm5": "HELD", "net": 10, "d_half10": 1} for i in range(7)]
        rows.append({"symbol": "F", "entry_time": "09:20", "confirm5": "FAILED", "net": -100, "d_half10": 0})
        taken, failed, over = tr.quality_split(rows)
        self.assertEqual((len(taken), len(failed), len(over)), (5, 1, 2))
        text = "\n".join(tr.quality_section(rows))
        self.assertIn("-100", text)
        self.assertEqual(tr.quality_section([{"confirm5": ""}]), [])


if __name__ == "__main__":
    unittest.main()
