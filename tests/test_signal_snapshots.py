import csv
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace as NS

import signal_snapshots as ss


def cand(symbol="AAA", direction="BULLISH", status="A_PLUS_WAIT_LATE_VWAP_EXTENSION", **kw):
    base = dict(symbol=symbol, direction=direction, stage="ENTRY_READY", setup_family="ESTABLISHED_TREND", selection_tier="TREND_MONITOR", pivot_state="R1_TO_R2", score=80.5,
                trade_quality_score=70.0, movement_capture_score=60.0, trend_alignment_score=75.0, clean_trend_score=90.0, chase_risk_score=15.0, ltp=100.0,
                day_change_percent=1.2, move_from_0915_open_percent=1.0, gap_percent=0.2, relative_volume=2.0, recent_relative_volume_15m=1.5,
                tape_volume_acceleration_5m=1.1, tape_volume_acceleration_15m=1.0, vwap_distance_percent=0.9, rsi14_5m=65.0, adx14_5m=30.0,
                recent_move_5m_percent=0.2, recent_move_10m_percent=0.4, recent_move_15m_percent=0.6, recent_move_30m_percent=1.0, completed_5m_bars=8,
                range_position_percent=88.0, below_day_high_percent=0.1, above_day_low_percent=1.5, trend_retention_percent=80.0, atr_5m=0.4, extension_atr=1.2,
                fresh_15m_high=True, fresh_15m_low=False, fresh_30m_high=False, fresh_30m_low=False, fresh_day_high=True, fresh_day_low=False, opening_range_breakout=True,
                r1=101.0, s1=99.0, paper_trade_status=status, reasons=["one", "two"])
    base.update(kw)
    return NS(**base)


def rows(path):
    with open(path, encoding="utf-8") as h:
        return list(csv.DictReader(h))


class SnapshotTests(unittest.TestCase):
    def test_row_has_features_and_status(self):
        r = ss.signal_row(cand(), datetime(2026, 10, 16, 9, 40), False)
        self.assertEqual(r["status"], "A_PLUS_WAIT_LATE_VWAP_EXTENSION")
        self.assertEqual(r["rel_volume"], 2.0)
        self.assertEqual(r["fresh_15m"], 1)
        self.assertEqual(r["fresh_day"], 1)
        self.assertEqual(r["reasons"], "one | two")
        self.assertEqual(ss.signal_row(cand(), datetime(2026, 10, 16, 9, 40), True)["status"], "PASSED_ALL_GATES")
        self.assertEqual(ss.signal_row(NS(symbol="Z", direction="BEARISH"), datetime(2026, 10, 16, 9, 40), False)["status"], "HELD_BACK")      # missing attributes are tolerated

    def test_dedup_by_status_and_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            w = ss.SnapshotWriter(tmp)
            t0 = datetime(2026, 10, 16, 9, 40)
            self.assertEqual(w.signals(t0, [cand(), cand("BBB")], set()), 2)
            self.assertEqual(w.signals(t0 + timedelta(seconds=60), [cand(), cand("BBB")], set()), 0)                 # same status, under 5 minutes
            self.assertEqual(w.signals(t0 + timedelta(seconds=120), [cand(status="V2_STOCK_SELECTION_BLOCKED")], set()), 1)       # status changed
            self.assertEqual(w.signals(t0 + timedelta(seconds=400), [cand("BBB")], {("BBB", "BULLISH")}), 1)         # passed now
            got = rows(Path(tmp) / "signal_snapshots" / "2026-10-16.csv")
            self.assertEqual(len(got), 4)
            self.assertEqual(got[-1]["status"], "PASSED_ALL_GATES")

    def test_chain_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            w = ss.SnapshotWriter(tmp)
            t0 = datetime(2026, 10, 16, 9, 40)
            self.assertTrue(w.chain(t0, "AAA", "BULLISH", {"oc_pcr_oi": 0.8, "oc_wall_close": False}))
            self.assertFalse(w.chain(t0 + timedelta(seconds=30), "AAA", "BULLISH", {"oc_pcr_oi": 0.9}))             # inside 5 minutes
            self.assertFalse(w.chain(t0, "BBB", "BULLISH", {}))                                                         # nothing to record
            got = rows(Path(tmp) / "signal_snapshots" / "chain_2026-10-16.csv")
            self.assertEqual(len(got), 1)
            self.assertEqual(got[0]["oc_pcr_oi"], "0.8")

    def test_errors_are_swallowed(self):
        w = ss.SnapshotWriter("Z:/definitely/not/writable/\0")
        self.assertEqual(w.signals(datetime(2026, 10, 16, 9, 40), [cand()], set()), 0)
        self.assertFalse(w.chain(datetime(2026, 10, 16, 9, 40), "A", "BULLISH", {"oc_pcr_oi": 1}))


class AnalysedAndRadarTests(unittest.TestCase):
    def test_rejected_candidates_are_recorded_with_their_reason(self):
        with tempfile.TemporaryDirectory() as d:
            w = ss.SnapshotWriter(Path(d))
            t0 = datetime(2026, 10, 26, 14, 28, 0)
            ready = cand("RDY")
            rejected = cand("ATHERENERG", stage="EXTENDED_NO_ENTRY", rejection_reason="trend is strong but entry is overextended", actionable=False, paper_trade_status="")
            n = w.analysed(t0, [ready, rejected], {("RDY", "BULLISH")}, {"ATHERENERG": 3, "RDY": 1})
            self.assertEqual(n, 1)                                                     # the entry-ready candidate is in the signals file, not here
            r = rows(Path(d) / "signal_snapshots" / "analysed_2026-10-26.csv")
            self.assertEqual((r[0]["symbol"], r[0]["stage"], r[0]["radar_rank"]), ("ATHERENERG", "EXTENDED_NO_ENTRY", "3"))
            self.assertIn("overextended", r[0]["rejection"])
            self.assertEqual(w.analysed(t0 + timedelta(seconds=60), [rejected], set(), {"ATHERENERG": 3}), 0)      # same stage and reason: throttled
            self.assertEqual(w.analysed(t0 + timedelta(seconds=301), [rejected], set(), {"ATHERENERG": 2}), 1)     # five minutes on: written again
            changed = cand("ATHERENERG", stage="VWAP_CONFLICT", rejection_reason="price is on the wrong side of VWAP")
            self.assertEqual(w.analysed(t0 + timedelta(seconds=330), [changed], set(), {}), 1)                    # a new reason is written at once

    def test_radar_top_list_with_analysed_flag(self):
        with tempfile.TemporaryDirectory() as d:
            w = ss.SnapshotWriter(Path(d))
            t0 = datetime(2026, 10, 26, 14, 28, 0)
            ranked = [NS(symbol=f"S{i}", radar_score=100.0 - i, direction="BULLISH", change_percent=1.0) for i in range(1, 121)]
            n = w.radar(t0, ranked, {"S1", "S2"})
            self.assertEqual(n, ss.RADAR_TOP)                                          # only the top 80 are listed
            r = rows(Path(d) / "signal_snapshots" / "radar_2026-10-26.csv")
            self.assertEqual((r[0]["symbol"], r[0]["rank"], r[0]["analysed"]), ("S1", "1", "1"))
            self.assertEqual(r[5]["analysed"], "0")
            self.assertEqual(w.radar(t0 + timedelta(seconds=60), ranked, {"S1", "S2"}), 0)

    def test_bad_input_never_raises(self):
        w = ss.SnapshotWriter(__file__ + "/not_a_folder")
        self.assertEqual(w.analysed(datetime(2026, 10, 26, 10, 0), None, set(), {}), 0)
        self.assertEqual(w.radar(datetime(2026, 10, 26, 10, 0), None, set()), 0)


if __name__ == "__main__":
    unittest.main()
