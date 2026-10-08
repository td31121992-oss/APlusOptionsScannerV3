from __future__ import annotations

import unittest

import aplus_live_pnl_dashboard as dash
import decision_desk as dd

CAND = {"symbol": "AAA", "direction": "BEARISH", "shortlist": "ENTRY_READY", "actionable": True, "trade_quality_score": 91.0,
        "setup_family": "HEALTHY_PULLBACK", "ltp": 100.0, "atr_5m": 0.4, "underlying_entry": 100.0, "underlying_stop": 100.5,
        "underlying_target1": 99.0, "underlying_risk_percent": 0.5, "paper_trade_status": "V2_STOCK_SELECTION_BLOCKED",
        "move_from_0915_open_percent": -1.2, "relative_volume": 1.8}
REPORT = {"candidates": [CAND, {**CAND, "symbol": "BBB", "direction": "BULLISH", "paper_trade_status": "OPEN", "paper_trade_id": "PT-1"},
                         {"symbol": "ZZZ", "direction": "BEARISH", "shortlist": "WATCH", "actionable": False}],
          "aplus_selective_gate": {"rejected_symbols": [{"symbol": "CCC", "direction": "BEARISH", "status": "A_PLUS_WAIT_OVEREXTENDED"}]},
          "stock_selection_v2": {"blocked": [{"symbol": "AAA", "direction": "BEARISH", "reasons": ["NOT_IN_DYNAMIC_TOP5_DIRECTION", "CURRENT_5M_REVERSING(-0.1%)"]}]},
          "entry_ready_count": 2, "paper_trades_today": 1, "session_phase": "OPENING_MOMENTUM", "generated_at": "2026-10-08T09:50:00"}


class DeskTests(unittest.TestCase):
    def test_rows_explain_each_gate_and_sort_traded_first(self) -> None:
        rows = dd.build_rows(REPORT, "BEAR")
        self.assertEqual([r["symbol"] for r in rows], ["BBB", "AAA"])                    # traded first; the non-candidate is dropped
        a = rows[1]
        self.assertEqual(a["gate_v2"], "BLOCK: NOT_IN_DYNAMIC_TOP5_DIRECTION, CURRENT_5M_REVERSING")
        self.assertEqual((a["side"], a["rr"], a["atr5_pct"], a["risk_pct"]), ("PE", 2.0, 0.4, 0.5))
        self.assertEqual(rows[0]["status"], "TRADED")

    def test_a_plus_rejection_row_is_listed_when_the_candidate_is_ready(self) -> None:
        rep = {**REPORT, "candidates": [{**CAND, "symbol": "CCC", "paper_trade_status": "A_PLUS_WAIT_OVEREXTENDED"}]}
        row = dd.build_rows(rep, "BEAR")[0]
        self.assertEqual(row["gate_aplus"], "REJECT: A_PLUS_WAIT_OVEREXTENDED")

    def test_page_and_routes_exist(self) -> None:
        self.assertIn("/api/decision-desk", dd.DECISION_DESK_HTML)
        self.assertIn('id="chips"', dd.DECISION_DESK_HTML)
        page = dash._mobileize_html('<html><head></head><body><a href="/fno-market-watch">x</a></body></html>')
        self.assertIn('href="/decision-desk"', page)

    def test_missing_report_is_handled(self) -> None:
        import tempfile
        from pathlib import Path

        self.assertFalse(dd.payload(Path(tempfile.mkdtemp()))["ok"])


if __name__ == "__main__":
    unittest.main()
