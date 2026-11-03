import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import pipeline_view as pv


def cand(sym, direction, shortlist, stage, status="", score=80.0, move=1.0):
    return {"symbol": sym, "direction": direction, "shortlist": shortlist, "stage": stage, "paper_trade_status": status,
            "trade_quality_score": score, "move_from_open_percent": move, "relative_volume": 1.5}


class ClassifyTests(unittest.TestCase):
    def test_each_stage(self):
        self.assertEqual(pv.classify(cand("A", "BULLISH", "ENTRY_READY", "CONTINUATION_BULLISH_ENTRY_READY"))[0], "READY")
        st, why = pv.classify(cand("A", "BULLISH", "ENTRY_READY", "CONTINUATION_BULLISH_ENTRY_READY", "A_PLUS_WAIT_LATE_VWAP_EXTENSION"))
        self.assertEqual(st, "GATED")
        self.assertIn("late vwap extension", why)
        self.assertEqual(pv.classify(cand("A", "BULLISH", "STRONG_TREND_WAIT_FOR_PULLBACK", "BULLISH_TREND_WAIT_FOR_PULLBACK"))[0], "BUILDING")
        self.assertEqual(pv.classify(cand("A", "BULLISH", "", "EXTENDED_NO_ENTRY"))[0], "INVALIDATED")
        self.assertEqual(pv.classify(cand("A", "BULLISH", "FRESH_MOVEMENT", "FRESH_INTRADAY_BULLISH_BREAKOUT"))[0], "EARLY WARNING")
        self.assertEqual(pv.classify(cand("A", "BULLISH", "", "", "OPEN"))[0], "IN TRADE")

    def test_build_stages_dedupes_and_adds_v2_blocks_and_watch(self):
        rep = {"candidates": [cand("AAA", "BULLISH", "ENTRY_READY", "X_ENTRY_READY"), cand("BBB", "BEARISH", "STRONG_TREND_WAIT_FOR_PULLBACK", "P")],
               "stock_selection_v2": {"blocked": [{"symbol": "CCC", "direction": "BULLISH", "reasons": ["NOT_IN_TOP5"]}]},
               "quote_shortlist": [{"symbol": "DDD", "direction": "BULLISH", "radar_score": 55.0}, {"symbol": "AAA", "direction": "BULLISH"}]}
        open_t = [{"symbol": "EEE", "option_type": "CE", "stage": "S", "momentum_score": 70}]
        out = pv.build_stages(rep, open_t)
        self.assertEqual([c["symbol"] for c in out["READY"]], ["AAA"])
        self.assertEqual([c["symbol"] for c in out["BUILDING"]], ["BBB"])
        self.assertEqual([c["symbol"] for c in out["GATED"]], ["CCC"])
        self.assertEqual([c["symbol"] for c in out["WATCH"]], ["DDD"])
        self.assertEqual([c["symbol"] for c in out["IN TRADE"]], ["EEE"])


class TapeAndBannerTests(unittest.TestCase):
    def test_tape_merges_entries_exits_blocks_and_manual(self):
        trades = [{"symbol": "ICICIBANK", "strike": 1350, "option_type": "CE", "entry_time": "2026-10-15T09:39:00+05:30", "entry_price": 28.95,
                   "status": "CLOSED", "exit_time": "2026-10-15T14:30:00+05:30", "exit_price": 40.0, "exit_reason": "RUNNER_TRAIL_EXIT",
                   "net_pnl": 7000, "kl_push": True, "stage": "HEALTHY_BULLISH_PULLBACK"}]
        manual = [{"ts": "2026-10-15T12:00:05", "trade_id": "PT-20261015-093000-CAMS-AB", "kind": "EXIT", "source": "dashboard:127.0.0.1"}]
        blocked = {("UNOMINDA", "BULLISH", "A_PLUS_WAIT_LATE_VWAP_EXTENSION"): {"first": "10:05", "last": "10:35", "cycles": 7}}
        tape = pv.build_tape(trades, manual, blocked)
        kinds = [e["kind"] for e in tape]
        self.assertEqual(sorted(kinds), ["BLOCKED", "ENTRY", "EXIT", "MANUAL"])
        self.assertEqual(tape[0]["time"], "14:30")               # newest first
        self.assertIn("key-level push", next(e for e in tape if e["kind"] == "ENTRY")["detail"])
        self.assertIn("7 cycles", next(e for e in tape if e["kind"] == "BLOCKED")["detail"])

    def test_fold_report_counts_cycles(self):
        blocked = {}
        rep = {"generated_at": "2026-10-15T10:05:00+05:30",
               "aplus_selective_gate": {"rejected_symbols": [{"symbol": "X", "direction": "BULLISH", "status": "A_PLUS_WAIT_PIVOT_TO_R1"}]}}
        pv._fold_report(blocked, rep)
        rep["generated_at"] = "2026-10-15T10:07:00+05:30"
        pv._fold_report(blocked, rep)
        e = blocked[("X", "BULLISH", "A_PLUS_WAIT_PIVOT_TO_R1")]
        self.assertEqual((e["first"], e["last"], e["cycles"]), ("10:05", "10:07", 2))

    def test_banner_headline_and_attention(self):
        trades = [{"status": "CLOSED", "net_pnl": -3000, "entry_time": "2026-10-15T09:30:00"} for _ in range(3)]
        with tempfile.TemporaryDirectory() as tmp:
            import entry_pause
            entry_pause.heartbeat(tmp, datetime.now())
            b = pv.day_verdict(trades, Path(tmp), datetime(2026, 10, 15, 11, 0), report_age_s=30, nifty_pct_open=0.5)
            self.assertIn("Down on the day", b["headline"])
            self.assertEqual(b["verdict"], "NO_TRADE")
            self.assertFalse(b["ok"])
            ok = pv.day_verdict([], Path(tmp), datetime(2026, 10, 15, 11, 0), report_age_s=30, nifty_pct_open=0.5)
            self.assertTrue(ok["ok"])
            self.assertEqual(ok["message"], "Nothing needs attention right now.")
            stale = pv.day_verdict([], Path(tmp), datetime(2026, 10, 15, 11, 0), report_age_s=900, nifty_pct_open=0.5)
            self.assertIn("scanner has not reported", stale["message"])


if __name__ == "__main__":
    unittest.main()


class TapeCapTests(unittest.TestCase):
    def test_blocked_are_capped_but_entries_and_exits_never_are(self):
        blocked = {(f"S{i}", "BULLISH", "A_PLUS_WAIT_PIVOT_TO_R1"): {"first": f"10:{i % 60:02d}", "last": "10:59", "cycles": 1} for i in range(400)}
        trades = [{"symbol": "ZZZ", "strike": 100, "option_type": "CE", "entry_time": "2026-10-15T09:20:00+05:30", "entry_price": 5.0,
                   "status": "CLOSED", "exit_time": "2026-10-15T09:40:00+05:30", "exit_price": 6.0, "exit_reason": "X", "net_pnl": 100}]
        tape = pv.build_tape(trades, [], blocked, limit=50)
        kinds = [e["kind"] for e in tape]
        self.assertEqual((kinds.count("BLOCKED"), kinds.count("ENTRY"), kinds.count("EXIT")), (50, 1, 1))
