import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import shadow_scoreboard as sb


def trade(day, hhmm, direction, pnl, **tags):
    return {"status": "CLOSED", "symbol": "S", "direction": direction, "entry_time": f"{day}T{hhmm}:00+05:30", "net_pnl": pnl, "return_percent": pnl / 100.0, **tags}


class ScoreboardTests(unittest.TestCase):
    def build(self, rows):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            p = root / "data" / "reports"
            p.mkdir(parents=True)
            (p / "paper_trade_history.json").write_text(json.dumps({"paper_trades": rows}), encoding="utf-8")
            out = sb.run("2026-10-22", root)
            return out.read_text(encoding="utf-8"), sb.load_trades(p / "paper_trade_history.json", upto="2026-10-22")

    def test_truthy_and_stats(self):
        self.assertEqual([sb._truthy(x) for x in (1, "0", "1.0", "False", "", None, "x")], [True, False, True, False, None, None, None])
        t = [{"net_pnl": 100, "return_percent": 2}, {"net_pnl": -300, "return_percent": -6}]
        self.assertEqual(sb.stats(t), {"n": 2, "win": 50.0, "net": -200.0, "avg_ret": -2.0})

    def test_gate_rows_blocked_vs_allowed_and_baseline(self):
        rows = []
        for d in ("2026-10-19", "2026-10-21", "2026-10-22"):
            rows += [trade(d, "10:05", "BULLISH", -500, bp_ok=0.0), trade(d, "10:10", "BULLISH", -300, bp_ok=0.0), trade(d, "10:20", "BULLISH", 400, bp_ok=1.0),
                     trade(d, "10:30", "BEARISH", -100, bp_ok=0.0), trade(d, "10:40", "BEARISH", 200, bp_ok=0.0), trade(d, "11:00", "BEARISH", 900, bp_ok=1.0)]
        rows.append(trade("2026-09-29", "10:00", "BULLISH", -9999, bp_ok=0.0))                   # before the baseline: ignored
        rows.append({"status": "OPEN", "entry_time": "2026-10-22T11:00:00+05:30", "net_pnl": 5})
        trades = self.build(rows)[1]
        self.assertEqual(len(trades), 18)
        g = {r["rule"]: r for r in sb.gate_rows(trades)}["Big-player gate (not against big prints)"]
        self.assertEqual((g["blocked"]["n"], g["blocked"]["net"], g["allowed"]["n"], g["allowed"]["net"]), (12, -2100, 6, 3900))
        self.assertEqual((g["change_if_enforced"], g["days_blocked"], g["days_helped"], g["enough"]), (2100, 3, 3, False))   # 12 blocked < 15: not enough to judge
        self.assertIn("collecting", sb.verdict(g))
        with mock.patch.object(sb, "MIN_BLOCKED", 10):
            g2 = {r["rule"]: r for r in sb.gate_rows(trades)}["Big-player gate (not against big prints)"]
            self.assertIn("WOULD HAVE HELPED", sb.verdict(g2))

    def test_small_samples_say_collecting_and_missing_data_is_skipped(self):
        rows = [trade("2026-10-22", "10:05", "BULLISH", -500, bp_ok=0.0), trade("2026-10-22", "10:10", "BULLISH", 100)]
        text, trades = self.build(rows)
        g = {r["rule"]: r for r in sb.gate_rows(trades)}["Big-player gate (not against big prints)"]
        self.assertEqual((g["trades_with_data"], g["blocked"]["n"]), (1, 1))                       # the trade without a bp_ok tag is not counted either way
        self.assertIn("collecting", sb.verdict(g))
        self.assertIn("no data yet", text)                                                         # the quality gate has no tags at all
        self.assertIn("## B. Feature splits", text)

    def test_canary_is_recomputed_for_old_trades_and_splits_group(self):
        day = "2026-10-22"
        rows = [trade(day, "10:00", "BEARISH", -100), trade(day, "10:03", "BEARISH", -200), trade(day, "10:06", "BEARISH", -300)]
        for r in rows:
            r["highest_option_price"], r["entry_price"] = 10.0, 10.0
        _, trades = self.build(rows)
        sb.add_canary(trades)
        self.assertEqual([t["_cn_ok"] for t in trades], [True, False, False])                      # first of the window passes, the pile-on is refused
        for t, a in zip(trades, ("WITH", "WITH", "AGAINST")):
            t["bp_align"] = a
        groups = {s["tag"]: s for s in sb.split_rows(trades)}["bp_align (big prints with / against us)"]["groups"]
        self.assertEqual((groups["WITH"]["n"], groups["WITH"]["net"], groups["AGAINST"]["n"]), (2, -300.0, 1))



class ForwardOnlyTests(unittest.TestCase):
    RULE = "Big-player gate (not against big prints)"

    def test_wilson(self):
        lo, hi = sb.wilson(5, 10)
        self.assertTrue(lo < 50 < hi and hi - lo > 40)                                    # ten trades say very little
        self.assertEqual(sb.wilson(0, 0), None)
        lo, hi = sb.wilson(500, 1000)
        self.assertTrue(46 <= lo and hi <= 54)

    def test_registry_is_written_once_and_only_later_trades_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            p = root / "data" / "reports"
            p.mkdir(parents=True)
            before = [trade("2026-10-20", "10:00", "BULLISH", 100, bp_ok=1), trade("2026-10-20", "10:30", "BULLISH", -500, bp_ok=0)]
            (p / "paper_trade_history.json").write_text(json.dumps({"paper_trades": before}), encoding="utf-8")
            sb.run("2026-10-20", root)                                                   # first night: the rule is registered, nothing is forward yet
            reg = json.loads((root / "data" / "shadow_scoreboard" / "registry.json").read_text(encoding="utf-8"))
            self.assertEqual(reg[self.RULE], "2026-10-20")
            rows = list(before)
            for d in range(21, 30):                                                      # nine later days: blocked trades lose, allowed trades win
                for i in range(3):
                    rows.append(trade(f"2026-10-{d}", f"10:{i}0", "BULLISH", 800, bp_ok=1))
                    rows.append(trade(f"2026-10-{d}", f"11:{i}0", "BULLISH", -700, bp_ok=0))
            (p / "paper_trade_history.json").write_text(json.dumps({"paper_trades": rows}), encoding="utf-8")
            out = sb.run("2026-10-29", root).read_text(encoding="utf-8")
            reg2 = json.loads((root / "data" / "shadow_scoreboard" / "registry.json").read_text(encoding="utf-8"))
            self.assertEqual(reg2[self.RULE], "2026-10-20")                              # never moved
            self.assertIn("## C. Forward-only evidence", out)
            fwd = sb.forward_rows(sb.load_trades(p / "paper_trade_history.json", upto="2026-10-29"), reg2)
            r = next(x for x in fwd if x["rule"] == self.RULE)
            self.assertEqual((r["blocked"]["n"], r["allowed"]["n"]), (27, 27))           # the two 20 Oct trades are not forward evidence
            self.assertEqual(r["blocked"]["win"], 0.0)
            self.assertTrue(r["verdict"].startswith("HELPS"), r["verdict"])
            self.assertIn("HELPS", out)

    def test_verdict_collecting_and_chance(self):
        base = {"since": "2026-10-20", "days_blocked": 2, "blocked": {"n": 5}, "blocked_ci": (0.0, 40.0), "allowed_ci": (50.0, 90.0)}
        self.assertTrue(sb.forward_verdict(base).startswith("collecting"))
        enough = dict(base, days_blocked=4, blocked={"n": 20}, blocked_ci=(30.0, 60.0), allowed_ci=(45.0, 80.0))
        self.assertTrue(sb.forward_verdict(enough).startswith("not distinguishable"))
        hurts = dict(enough, blocked_ci=(70.0, 95.0), allowed_ci=(20.0, 55.0))
        self.assertTrue(sb.forward_verdict(hurts).startswith("HURTS"))


class BreadthSideTests(unittest.TestCase):
    def test_breadth_by_side(self):
        fn = sb.SPLITS["mkt_side (market breadth at entry against the side traded)"]
        self.assertEqual(fn({"rs_pct_down": 24.9, "direction": "BEARISH"}), "PUT, market rising (>=60% up)")
        self.assertEqual(fn({"rs_pct_down": 80.0, "direction": "BEARISH"}), "PUT, market weak (<=40% up)")
        self.assertEqual(fn({"rs_pct_down": 57.3, "direction": "BULLISH"}), "CALL, market mixed (40-60% up)")
        self.assertEqual(fn({"rs_pct_down": 50, "option_type": "PE"}), "PUT, market mixed (40-60% up)")
        self.assertIsNone(fn({"direction": "BEARISH"}))                                   # trades before the tag existed carry no breadth
        self.assertIsNone(fn({"rs_pct_down": "", "direction": "BEARISH"}))

    def test_gap_event_split(self):
        fn = sb.SPLITS["gap_event (opening gap in our direction, and whether results were filed since the last close)"]
        self.assertEqual(fn({"em_gap_dir": -8.8, "ev_reported": 1}), "gap against us 3%+, results filed")
        self.assertEqual(fn({"em_gap_dir": 3.4, "ev_reported": 0}), "gap with us 3%+")
        self.assertEqual(fn({"em_gap_dir": 0.2}), "gap under 3%")
        self.assertIsNone(fn({}))

    def test_entry_context_splits(self):
        last30 = sb.SPLITS["ctx_last30_pct (stock move over the 30 min before entry, in our direction)"]
        ext = sb.SPLITS["ctx_mins_since_ext (minutes since the day's extreme in our direction was set)"]
        self.assertEqual(last30({"ctx_last30_pct": 0.1}), "under 0.3% (paused)")
        self.assertEqual(last30({"ctx_last30_pct": 0.5}), "0.3 - 0.8% (moving)")
        self.assertEqual(last30({"ctx_last30_pct": 1.4}), "0.8%+ (fast)")
        self.assertIsNone(last30({}))
        self.assertEqual(ext({"ctx_mins_since_ext": 5}), "at the extreme (<= 10 min)")
        self.assertEqual(ext({"ctx_mins_since_ext": 125}), "45+ min ago")
        self.assertIsNone(ext({"ctx_mins_since_ext": ""}))


if __name__ == "__main__":
    unittest.main()
