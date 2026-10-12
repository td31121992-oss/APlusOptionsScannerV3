import json
import tempfile
import unittest
from pathlib import Path

import voice_commands as vc


def trade(i, symbol, side, entry, exit_, status, mfe, ret, net, exit_reason="", entry_time="09:30", exit_time="", day="20261012"):
    return {"paper_trade_id": f"PT-{day}-0930{i:02d}-{symbol}", "symbol": symbol, "direction": "BULLISH" if side == "CE" else "BEARISH", "setup_family": "ESTABLISHED_TREND",
            "status": status, "entry_time": f"2026-10-12T{entry_time}:00+05:30", "exit_time": f"2026-10-12T{exit_time}:00+05:30" if exit_time else "",
            "entry_price": str(entry), "exit_price": str(exit_), "highest_option_price": str(entry * (1 + mfe / 100)), "lowest_option_price": str(min(entry, exit_)),
            "quantity": "100", "exit_reason": exit_reason, "capital_deployed": str(entry * 100), "spread_percent": "1.0", "option_stop": str(entry * 0.8),
            "trading_symbol": f"{symbol}-Oct2026-100-{side}", "last_option_price": str(exit_), "selection_tier": "WAIT_FOR_RETEST", "safety_decision": "PASS",
            "momentum_score": "90", "trend_alignment_score": "80", "clean_trend_score": "85", "chase_risk_score": "5"}


class VoiceTests(unittest.TestCase):
    def _root(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        for d in ("intraday_movement", "reference", "reports", "missed_opportunities/2026-10-12"):
            (root / "data" / d).mkdir(parents=True)
        trades = [trade(1, "MCX", "CE", 100, 80, "CLOSED", 0.0, -20, -2000, "OPTION_STOP_LOSS", "09:30", "09:33"),
                  trade(2, "ITC", "PE", 5, 7, "OPEN", 44, 40, 1000, "", "10:15"),
                  trade(3, "RECLTD", "CE", 8, 7, "OPEN", 10, -12, -500, "", "09:30")]
        (root / "data" / "intraday_movement" / "paper_trade_journal.json").write_text(json.dumps({"trades": trades}), encoding="utf-8")
        (root / "data" / "reference" / "fno_sector_map.csv").write_text("symbol,sector\nMCX,Financial\nITC,FMCG\nRECLTD,Financial\nBAJAJ-AUTO,Auto\nTCS,IT\nM&M,Auto\n", encoding="utf-8")
        rows = [{"symbol": "TCS", "ltp": 2200.0, "from_prev_close_pct": 3.1, "from_open_pct": 2.0, "sector": "IT", "day_high": 2210.0, "day_low": 2100.0},
                {"symbol": "ITC", "ltp": 260.0, "from_prev_close_pct": 1.0, "from_open_pct": 0.5, "sector": "FMCG", "day_high": 262.0, "day_low": 255.0}]
        (root / "data" / "reports" / "fno_market_watch_latest.json").write_text(json.dumps({"rows": rows}), encoding="utf-8")
        (root / "data" / "missed_opportunities" / "2026-10-12" / "report.md").write_text("# x\n\n- INOXWIND BULLISH first ready 10:00: close +1.67% - fate: V2_BLOCKED\n", encoding="utf-8")
        vc._UNIVERSE.update(t=0.0, map={})
        return root

    def test_pnl_count_open_best_worst(self):
        root = self._root()
        a = vc.answer("what's my p&l today", root, "2026-10-12")
        self.assertEqual(a["intent"], "pnl")
        import trade_journal
        total = sum(t["net"] for t in trade_journal.payload("2026-10-12", "2026-10-12", root)["trades"])      # the journal subtracts costs
        self.assertIn(f"{'-' if total < 0 else '+'}₹{abs(total):,}", a["reply"])
        self.assertIn(f"{'minus' if total < 0 else 'plus'} rupees {abs(total):,}", a["speech"])
        self.assertIn("3 trades", vc.answer("how many trades", root, "2026-10-12")["reply"])
        self.assertEqual(len(vc.answer("open trades", root, "2026-10-12")["rows"]), 2)
        self.assertIn("ITC", vc.answer("best trade", root, "2026-10-12")["reply"])

    def test_stopped_trades_report_duration_and_mfe(self):
        root = self._root()
        a = vc.answer("which trades are stopped", root, "2026-10-12")
        self.assertTrue(any("after 3 minutes" in r for r in a["rows"]))
        m = vc.answer("mfe of all trades", root, "2026-10-12")
        self.assertEqual(m["intent"], "mfe")
        self.assertIn("never got above 5", m["reply"])

    def test_why_and_stock_with_name_matching(self):
        root = self._root()
        self.assertIn("RECLTD", vc.answer("why was rec ltd traded", root, "2026-10-12")["reply"])
        self.assertIn("TCS is at 2200.00", vc.answer("how is TCS", root, "2026-10-12")["reply"])
        self.assertEqual(vc.find_symbol("bajaj auto", root)[0], "BAJAJ-AUTO")
        self.assertEqual(vc.find_symbol("m and m", root)[0], "M&M")

    def test_missing_unknown_and_empty(self):
        root = self._root()
        self.assertIn("INOXWIND", vc.answer("what are we missing", root, "2026-10-12")["reply"] + " ".join(vc.answer("what are we missing", root, "2026-10-12")["rows"]))
        self.assertEqual(vc.answer("blah blah", root, "2026-10-12")["intent"], "unknown")
        self.assertEqual(vc.answer("", root)["intent"], "empty")
        self.assertEqual(vc.answer("help", root)["intent"], "help")

    def test_nothing_in_the_module_can_change_trading(self):
        src = Path(vc.__file__).read_text(encoding="utf-8")
        for banned in ("set_mode(", "place_order", "requests.post", "os.environ[", ".write_text(", "unlink("):
            self.assertNotIn(banned, src.split("VOICE_WIDGET_HTML")[0])


if __name__ == "__main__":
    unittest.main()
