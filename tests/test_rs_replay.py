import csv
import gzip
import json
import tempfile
import unittest
from pathlib import Path

import rs_replay as rp

HEADER = "ts,sym,ltp,ltq,ltt,vol,tbq,tsq,bid,bq,ask,aq,bsum5,asum5,tq,side"


def write_ticks(root, day, sym, rows):
    d = root / "data" / "ticks" / day
    d.mkdir(parents=True, exist_ok=True)
    lines = [HEADER] + [f"{ts},{sym},{ltp},1,15:00:00,{vol},0,0,{ltp - 0.05},1,{ltp + 0.05},1,0,0,{tq},B" for ts, ltp, vol, tq in rows]
    with gzip.open(d / f"{sym}.csv.gz", "wt", encoding="utf-8") as h:
        h.write("\n".join(lines) + "\n")


class SampleTests(unittest.TestCase):
    def test_load_samples_thins_merges_and_builds_the_vwap(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_ticks(root, "2026-10-26", "AAA", [("10:00:00.100", 100.0, 1000, ""), ("10:00:01.000", 101.0, 1100, 100), ("10:00:02.000", 103.0, 1300, 300), ("10:00:07.000", 104.0, 1400, 100)])
            write_ticks(root, "2026-10-26", "BBB", [("10:00:03.000", 50.0, 10, 10)])
            s = rp.load_samples(root, "2026-10-26")
            self.assertEqual([(round(r[0], 1), r[1]) for r in s], [(2.0 + 36000, "AAA"), (36003.0, "BBB"), (36007.0, "AAA")])      # one per stock per 5 s, in time order
            self.assertAlmostEqual(s[0][4], (101.0 * 100 + 103.0 * 300) / 400)                                             # VWAP = sum(price x qty) / sum(qty)
            self.assertAlmostEqual(s[2][4], (101.0 * 100 + 103.0 * 300 + 104.0 * 100) / 500)


class ReviewMathTests(unittest.TestCase):
    def series(self):
        flat = [(36000.0 + i * 60, 100.0) for i in range(60)]
        out = {f"M{i}": list(flat) for i in range(60)}                                       # 60 stocks that do not move: the market is flat
        out["UP"] = [(36000.0 + i * 60, 100.0 + i) for i in range(60)]                       # +1 per minute
        return out

    def test_price_at_and_market_return(self):
        s = self.series()
        self.assertEqual(rp.price_at(s["UP"], 36000.0 + 5 * 60 + 30), 105.0)
        self.assertIsNone(rp.price_at(s["UP"], 35000.0))
        self.assertEqual(rp.market_return(s, 36000.0, 36000.0 + 600), 0.0)
        self.assertIsNone(rp.market_return({"A": s["UP"]}, 36000.0, 36600.0))                # fewer than 50 stocks: no market

    def test_forward_moves_are_signed_by_side_and_excess_over_the_market(self):
        s = self.series()
        ev = [{"time": "10:00:00", "symbol": "UP", "kind": "LEADER"}, {"time": "10:00:00", "symbol": "UP", "kind": "STRONG_LAGGARD"}]
        rows = rp.forward_moves(ev, s, "2026-10-26")
        self.assertAlmostEqual(rows[0]["fwd_5m"], 5.0, places=2)                              # a leader that kept rising
        self.assertAlmostEqual(rows[0]["exc_15m"], 15.0, places=2)
        self.assertAlmostEqual(rows[1]["fwd_5m"], -5.0, places=2)                             # a laggard that rose is a miss
        late = rp.forward_moves([{"time": "15:25:00", "symbol": "UP", "kind": "LEADER"}], s, "2026-10-26")
        self.assertIsNone(late[0]["fwd_30m"])                                                 # beyond the close

    def test_grouping_and_latency(self):
        rows = [{"kind": "LEADER", "fwd_5m": 1.0, "exc_5m": 1.0, "fwd_15m": 2.0, "exc_15m": 1.5, "fwd_30m": None, "exc_30m": None, "lag_s": "0.5", "compute_ms": "2", "since_rs1_s": "40", "first": "1"},
                {"kind": "LEADER", "fwd_5m": -1.0, "exc_5m": -0.5, "fwd_15m": 0.0, "exc_15m": -0.5, "fwd_30m": None, "exc_30m": None, "lag_s": "1.5", "compute_ms": "4", "since_rs1_s": "9000", "first": "0"}]
        g = rp._group(rows, lambda r: r["kind"])["LEADER"]
        self.assertEqual((g["n"], g["15m"]["mean_excess"], g["15m"]["beat_market_pct"], g["30m"]["mean_excess"]), (2, 0.5, 50.0, None))
        lat = rp.latency_summary(rows)
        self.assertEqual(lat["since_rs1_s"]["max"], 40.0)                                    # a repeat flag does not count as detection latency
        self.assertEqual((lat["lag_s"]["n"], lat["compute_ms"]["median"]), (2, 3.0))


class LedgerTests(unittest.TestCase):
    def test_trades_are_grouped_by_what_the_board_said_at_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            p = root / "data" / "intraday_movement"
            p.mkdir(parents=True)
            mk = lambda sym, d, minute, pnl, ret: {"symbol": sym, "direction": d, "status": "CLOSED", "entry_time": f"2026-10-26T{minute}:30+05:30", "net_pnl": pnl, "return_percent": ret}
            (p / "paper_trade_journal.json").write_text(json.dumps({"trades": [
                mk("LEAD", "BULLISH", "10:05", 500, 5), mk("LEAD", "BEARISH", "10:05", -300, -4), mk("WEAK", "BEARISH", "10:05", 200, 2), mk("OTHER", "BULLISH", "10:05", -100, -1),
                mk("GONE", "BULLISH", "10:05", 50, 1), {"symbol": "LEAD", "direction": "BULLISH", "status": "OPEN", "entry_time": "2026-10-26T10:06:00+05:30"}]}), encoding="utf-8")
            minutes = {10 * 60 + 5: {"LEAD": {"leader": True, "laggard": False, "ok": True, "red": True}, "WEAK": {"leader": False, "laggard": True, "ok": False, "red": True},
                                     "OTHER": {"leader": False, "laggard": False, "ok": None, "red": True}}}
            out = rp.ledger_join(root, "2026-10-26", minutes)
            g = out["groups"]
            self.assertEqual(out["n_trades"], 5)
            self.assertEqual(g["with the board (call on leader / put on laggard) - checks pass"]["net_pnl"], 500)
            self.assertEqual(g["against the board (call on laggard / put on leader)"]["n"], 1)
            self.assertEqual(g["with the board (call on leader / put on laggard) - a check failed"]["win_pct"], 100.0)
            self.assertEqual((g["not on the board"]["n"], g["no board data"]["n"]), (1, 1))


class ReplayTests(unittest.TestCase):
    def test_replay_flags_the_leader_with_latency_columns(self):
        from datetime import date  # noqa: F401

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data" / "nse_daily").mkdir(parents=True)
            with (root / "data" / "nse_daily" / "stock_daily.csv").open("w", encoding="utf-8", newline="") as h:
                w = csv.DictWriter(h, fieldnames=["day", "symbol", "close", "ttl_qty"])
                w.writeheader()
                for i in range(120):
                    w.writerow({"day": "2026-10-23", "symbol": f"S{i}", "close": 100.0, "ttl_qty": 1_000_000})
                w.writerow({"day": "2026-10-23", "symbol": "LEAD", "close": 100.0, "ttl_qty": 1_000_000})
            for i in range(120):
                write_ticks(root, "2026-10-26", f"S{i}", [("10:00:00.000", 99.0, 150_000, 150_000), ("10:10:00.000", 99.0, 160_000, 10_000)])
            write_ticks(root, "2026-10-26", "LEAD", [("10:00:00.000", 100.0, 250_000, 250_000), ("10:03:00.000", 101.5, 300_000, 50_000), ("10:10:00.000", 102.0, 350_000, 50_000)])
            rep = rp.replay(root, "2026-10-26")
            lead = [e for e in rep["events"] if e["symbol"] == "LEAD"]
            self.assertTrue(lead)
            self.assertEqual(lead[0]["kind"], "LEADER")
            self.assertEqual(str(lead[0]["first"]), "1")
            self.assertGreaterEqual(float(lead[0]["since_rs1_s"]), 0.0)
            out = rp.review(root, "2026-10-26", force_replay=True)
            self.assertEqual(out["source"], "replayed from ticks")
            self.assertTrue((root / "data" / "rs_review" / "2026-10-26.json").exists())
            self.assertIn("2026-10-26", (root / "data" / "rs_review" / "summary.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
