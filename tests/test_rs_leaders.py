import csv
import json
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import rs_leaders as rs

IST = timezone(timedelta(hours=5, minutes=30))
NOW = datetime(2026, 10, 26, 10, 0, tzinfo=IST)


def tracker(n=120, prev=100.0):
    ref = {f"S{i}": {"prev_close": prev, "avg_vol20": 1_000_000.0} for i in range(n)}
    ref.update({"LEAD": {"prev_close": prev, "avg_vol20": 1_000_000.0}, "WEAK": {"prev_close": prev, "avg_vol20": 1_000_000.0}})
    return rs.RSTracker(ref, {"LEAD": "IT", "WEAK": "Banks"})


def feed(tr, base=99.0, lead=101.5, weak=96.0, ts="10:00:00.000", lead_vol=250_000, n=120):
    for i in range(n):
        tr.update(f"S{i}", ts, base, 150_000, base + 0.2)                      # the market: -1%, trading just under its VWAP
    tr.update("LEAD", ts, lead, lead_vol, lead - 0.7)                          # above its VWAP
    tr.update("WEAK", ts, weak, 250_000, weak + 0.7)                           # below its VWAP


class ReferenceTests(unittest.TestCase):
    def test_load_reference_uses_the_last_day_before_today(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp, "data", "nse_daily")
            p.mkdir(parents=True)
            rows = [{"day": f"2026-10-{d:02d}", "symbol": "AAA", "close": 100 + d, "ttl_qty": 1000 * d} for d in range(1, 24)]
            with (p / "stock_daily.csv").open("w", encoding="utf-8", newline="") as h:
                w = csv.DictWriter(h, fieldnames=["day", "symbol", "close", "ttl_qty"])
                w.writeheader()
                w.writerows(rows)
            ref = rs.load_reference(Path(tmp), "2026-10-24")
            self.assertEqual(ref["AAA"]["prev_close"], 123.0)                                   # 23 Oct is the previous trading day
            self.assertAlmostEqual(ref["AAA"]["avg_vol20"], sum(1000 * d for d in range(4, 24)) / 20)
            self.assertEqual(rs.load_reference(Path(tmp), "2026-10-01"), {})


class TrackerTests(unittest.TestCase):
    def test_red_market_leaders_and_laggards(self):
        tr = tracker()
        feed(tr)
        snap = tr.compute(10 * 3600)
        self.assertEqual((snap["market"]["median"], snap["market"]["red"], snap["market"]["n"]), (-1.0, True, 122))
        lead = snap["leaders"][0]
        self.assertEqual((lead["s"], lead["sec"]), ("LEAD", "IT"))
        self.assertAlmostEqual(lead["rs"], 2.5, places=2)
        self.assertGreater(lead["vs_vwap"], 0)
        self.assertGreaterEqual(lead["rvol"], 1.0)
        self.assertEqual([r["s"] for r in snap["laggards"]], ["WEAK"])
        self.assertAlmostEqual(snap["laggards"][0]["rs"], -3.0, places=2)

    def test_each_leader_condition_is_needed(self):
        weak_vol = tracker()
        feed(weak_vol, lead_vol=10_000)                                                         # ahead of the market but on no volume
        self.assertEqual(weak_vol.compute(10 * 3600)["leaders"], [])
        small = tracker()
        feed(small, lead=100.5)                                                                 # only +1.5% ahead
        self.assertEqual(small.compute(10 * 3600)["leaders"], [])
        under_vwap = tracker()
        feed(under_vwap)
        under_vwap.update("LEAD", "10:00:01.000", 101.5, 250_000, 102.5)                        # price below the exchange VWAP
        self.assertEqual(under_vwap.compute(10 * 3600)["leaders"], [])

    def test_green_market_flags_and_too_few_stocks(self):
        green = tracker()
        feed(green, base=100.6, lead=103.5, weak=98.0)
        snap = green.compute(10 * 3600)
        self.assertFalse(snap["market"]["red"])
        self.assertEqual([r["s"] for r in snap["leaders"]], ["LEAD"])
        few = tracker(n=20)
        feed(few, n=20)
        self.assertIsNone(few.compute(10 * 3600))                                               # fewer than 100 stocks: no market to measure
        tr = tracker()
        tr.update("UNKNOWN", "10:00:00.000", 100.0, 1, 0)                                      # a stock without a reference is ignored
        self.assertNotIn("UNKNOWN", tr.state)

    def test_momentum_over_15_minutes(self):
        tr = tracker()
        feed(tr, ts="09:45:00.000")
        feed(tr, lead=101.5, ts="10:00:00.000")
        snap = tr.compute(10 * 3600)
        self.assertAlmostEqual(next(r for r in snap["leaders"] if r["s"] == "LEAD")["mom15"], (101.5 / 101.5 - 1) * 100, places=2)


class WriteTests(unittest.TestCase):
    def setUp(self):
        rs._CACHE.update(mtime=None, data=None)

    def test_live_file_events_dedupe_and_tags(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tr = tracker()
            feed(tr)
            self.assertTrue(tr.maybe_write(root, "2026-10-26", wall=100.0, now_s=36000.0))
            self.assertFalse(tr.maybe_write(root, "2026-10-26", wall=100.5, now_s=36000.5))             # at most one write every 2 seconds
            self.assertTrue(tr.maybe_write(root, "2026-10-26", wall=102.5, now_s=36002.5))
            ev = list(csv.DictReader((root / "data" / "rs_events" / "2026-10-26.csv").open(encoding="utf-8")))
            self.assertEqual(sorted((r["symbol"], r["kind"]) for r in ev), [("LEAD", "LEADER"), ("WEAK", "STRONG_LAGGARD")])      # logged once, not on every write
            feed(tr, ts="10:31:00.000")                                                                 # fresh ticks (a stock whose last tick is old is hidden)
            self.assertTrue(tr.maybe_write(root, "2026-10-26", wall=105.0, now_s=36000.0 + 31 * 60))
            self.assertEqual(len(list(csv.DictReader((root / "data" / "rs_events" / "2026-10-26.csv").open(encoding="utf-8")))), 4)   # logged again after 30 minutes
            snap = rs.load(root, "2026-10-26")
            self.assertEqual((snap["market"]["red"], snap["leaders"][0]["s"]), (True, "LEAD"))
            self.assertIsNone(rs.load(root, "2026-10-27"))                                              # another day's file is not today's data
            call = rs.tags("LEAD", "BULLISH", NOW, root)
            self.assertEqual((call["rs_red"], call["rs_leader"], call["rs_rank"], call["rs_vs_market_dir"]), (1, 1, 1, 2.5))
            put = rs.tags("WEAK", "BEARISH", NOW, root)
            self.assertEqual((put["rs_laggard"], put["rs_rank"], put["rs_vs_market_dir"]), (1, 1, 3.0))      # weakness counts positive for a put
            self.assertEqual(rs.tags("LEAD", "BEARISH", NOW, root)["rs_vs_market_dir"], -2.5)                  # a put on a leader is against the strength
            other = rs.tags("S5", "BULLISH", NOW, root)
            self.assertEqual((other["rs_leader"], other["rs_laggard"], "rs_rank" in other), (0, 0, False))
            self.assertEqual(rs.tags("LEAD", "BULLISH", datetime(2026, 10, 27, 10, 0, tzinfo=IST), root), {})

    def test_laggards_are_not_logged_in_a_green_market(self):
        with tempfile.TemporaryDirectory() as tmp:
            tr = tracker()
            feed(tr, base=100.6, lead=103.5, weak=98.0)
            tr.maybe_write(Path(tmp), "2026-10-26", wall=1.0, now_s=36000.0)
            ev = list(csv.DictReader((Path(tmp) / "data" / "rs_events" / "2026-10-26.csv").open(encoding="utf-8")))
            self.assertEqual([(r["symbol"], r["kind"]) for r in ev], [("LEAD", "LEADER")])

    def test_payload_merges_big_prints_and_handles_no_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertFalse(rs.payload(root, date(2026, 10, 26))["ok"])
            tr = tracker()
            feed(tr)
            tr.maybe_write(root, "2026-10-26", wall=1.0, now_s=36000.0)
            (root / "data" / "ticks" / "big_prints_live.json").write_text(json.dumps({"day": "2026-10-26", "updated": "10:00:00", "tape": [], "stocks": {"LEAD": {"net15_cr": 4.2}}}), encoding="utf-8")
            import big_prints

            big_prints._CACHE.update(mtime=None, data=None)
            out = rs.payload(root, date(2026, 10, 26))
            self.assertTrue(out["ok"])
            self.assertEqual(out["leaders"][0]["big15"], 4.2)


class ValidationTests(unittest.TestCase):
    def sector_tracker(self):
        ref = {f"S{i}": {"prev_close": 100.0, "avg_vol20": 1_000_000.0} for i in range(120)}
        ref.update({n: {"prev_close": 100.0, "avg_vol20": 1_000_000.0} for n in ("LEAD", "IT1", "IT2", "IT3")})
        return rs.RSTracker(ref, {"LEAD": "IT", "IT1": "IT", "IT2": "IT", "IT3": "IT"})

    def run_feed(self, tr, lead=101.5, it=100.0, lead_ts="10:00:00.000", bid=101.45, ask=101.55):
        for i in range(120):
            tr.update(f"S{i}", "10:00:00.000", 99.0, 150_000, 99.2)
        for n in ("IT1", "IT2", "IT3"):
            tr.update(n, "10:00:00.000", it, 150_000, it + 0.2)
        tr.update("LEAD", lead_ts, lead, 250_000, lead - 0.7, bid, ask)

    def test_sector_acceleration_and_all_checks(self):
        tr = self.sector_tracker()
        for ts, px in (("09:57:50.000", 101.0), ("09:58:50.000", 101.2)):
            tr.update("LEAD", ts, px, 200_000, 100.5)
        self.run_feed(tr)
        lead = tr.compute(10 * 3600)["leaders"][0]
        self.assertAlmostEqual(lead["rs_sec"], 1.5, places=1)                               # IT peers sit at 0 %: ahead of its sector too
        self.assertGreater(lead["acc2"], 0)
        self.assertTrue(lead["ok"], lead["checks"])

    def test_checks_fail_but_stock_stays_listed(self):
        tr = self.sector_tracker()
        self.run_feed(tr, it=101.6, bid=101.0, ask=102.0)                                    # sector stronger than the stock, wide spread
        lead = next(r for r in tr.compute(10 * 3600)["leaders"] if r["s"] == "LEAD")
        self.assertFalse(lead["checks"]["sector"])
        self.assertFalse(lead["checks"]["spread"])
        self.assertFalse(lead["ok"])
        chased = self.sector_tracker()
        chased.update("LEAD", "09:45:00.000", 99.0, 100_000, 99.0)
        self.run_feed(chased)
        self.assertFalse(chased.compute(10 * 3600)["leaders"][0]["checks"]["chase"])         # +2.5 % in 15 minutes

    def test_stale_quote_is_hidden(self):
        tr = self.sector_tracker()
        self.run_feed(tr, lead_ts="09:59:30.000")                                            # 30 seconds old
        self.assertEqual(tr.compute(10 * 3600)["leaders"], [])

    def test_tags_and_chain_check(self):
        import gzip

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tr = self.sector_tracker()
            self.run_feed(tr)
            tr.maybe_write(root, "2026-10-26", wall=1.0, now_s=36000.0)
            rs._CACHE.update(mtime=None, data=None)
            t = rs.tags("LEAD", "BULLISH", NOW, root)
            self.assertEqual(t["rs_checks_pass"], 1)
            self.assertGreater(t["rs_vs_sector_dir"], 0)
            d = root / "data" / "options_intelligence_upstox" / "2026-10-26"
            d.mkdir(parents=True)
            head = "captured_at,symbol,underlying_security_id,expiry,spot,strike,side,option_security_id,ltp,oi,previous_oi,oi_change,volume,iv,delta,gamma,theta,vega,pop,bid,bid_qty,ask,ask_qty,previous_close\n"
            row = lambda cap, side, bid, ask: f"2026-10-26T{cap},LEAD,1,2026-10-27,101.5,100.0,{side},9,5,1,1,0,1,0,0,0,0,0,0,{bid},10,{ask},10,0\n"
            with gzip.open(d / "option_chain_rows.csv.gz", "wt", encoding="utf-8") as h:
                h.write(head + row("09:50:00+05:30", "CE", 1.0, 1.01) + row("10:00:00+05:30", "CE", 5.0, 5.05) + row("10:00:00+05:30", "PE", 1.0, 1.5))
            rs._CHAIN.update(at=0.0, day="", data={})
            lead = rs.payload(root, date(2026, 10, 26))["leaders"][0]
            self.assertEqual((lead["chain_ok"], lead["checks"]["chain"]), (True, True))     # the latest snapshot's call is 1 % wide
            self.assertEqual(rs.chain_check(root, "2026-10-26", wall=1.0)["LEAD"]["ok_pe"], False)   # the put is 33 % wide, served from cache


class NiftyTests(unittest.TestCase):
    def test_nifty_comparison_and_check(self):
        tr = tracker()
        feed(tr)
        self.assertIsNone(tr.compute(10 * 3600)["market"]["nifty"])                         # no index feed yet: the comparison is left out, nothing breaks
        tr.set_index(prev=22000.0)
        tr.set_index(ltp=21890.0)                                                           # -0.5 %
        snap = tr.compute(10 * 3600)
        self.assertEqual(snap["market"]["nifty"], -0.5)
        lead = snap["leaders"][0]
        self.assertAlmostEqual(lead["rs_nifty"], 2.0 + 0.5 - 0.5 + 0.0, places=0)           # +1.5 % stock vs -0.5 % NIFTY
        self.assertTrue(lead["checks"]["nifty"])
        tr.set_index(ltp=22440.0)                                                           # NIFTY +2 %: the stock is now behind the index
        self.assertFalse(tr.compute(10 * 3600)["leaders"][0]["checks"]["nifty"])
        self.assertTrue(tr.compute(10 * 3600)["laggards"][0]["checks"]["nifty"])            # and the weak stock lags it

    def test_recorder_takes_only_the_index_packet_for_nifty(self):
        import tick_recorder as tr_

        with tempfile.TemporaryDirectory() as tmp:
            rec = tr_.Recorder(Path(tmp), ("TCS",), {"TCS": "11536"}, "2026-10-26")
            rec.rs = tracker()
            rec.on_message(None, {"type": "Previous Close", "exchange_segment": 0, "security_id": 13, "prev_close": "22000.00", "prev_OI": 0})
            rec.on_message(None, {"type": "Ticker Data", "exchange_segment": 0, "security_id": 13, "LTP": "21890.00", "LTT": "10:00:00"})
            rec.on_message(None, {"type": "Previous Close", "exchange_segment": 1, "security_id": 13, "prev_close": "9999.00", "prev_OI": 0})   # a stock that shares the id 13
            self.assertEqual((rec.rs.nifty, rec.rs.nifty_prev), (21890.0, 22000.0))



class SectorIndexTests(unittest.TestCase):
    def test_sector_index_comparison_replaces_the_median_check(self):
        ref = {f"S{i}": {"prev_close": 100.0, "avg_vol20": 1_000_000.0} for i in range(120)}
        ref["LEAD"] = {"prev_close": 100.0, "avg_vol20": 1_000_000.0}
        tr = rs.RSTracker(ref, {"LEAD": "IT"})                                              # a one-stock sector: no median, only the index can judge it
        feed(tr, n=120)
        tr.set_index(prev=29000.0, sid=29)
        tr.set_index(ltp=29000.0 * 0.995, sid=29)                                            # NIFTY IT -0.5 %
        lead = tr.compute(10 * 3600)["leaders"][0]
        self.assertAlmostEqual(lead["rs_sidx"], 2.0, places=1)                              # +1.5 % against -0.5 %
        self.assertTrue(lead["checks"]["sector"])
        tr.set_index(ltp=29000.0 * 1.03, sid=29)                                             # the IT index jumps 3 %: the stock is behind its own sector
        snap = tr.compute(10 * 3600)
        self.assertFalse(snap["leaders"][0]["checks"]["sector"])
        self.assertEqual(snap["market"]["sector_idx"], {"IT": 3.0})

    def test_index_log_and_recorder_routing(self):
        import tick_recorder as tr_

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rec = tr_.Recorder(root, ("TCS",), {"TCS": "11536"}, "2026-10-26")
            rec.rs = tracker()
            rec.idxlog = rs.IndexLog(root, "2026-10-26")
            for pkt in ({"type": "Previous Close", "exchange_segment": 0, "security_id": 29, "prev_close": "30000.00"},
                        {"type": "Ticker Data", "exchange_segment": 0, "security_id": 29, "LTP": "29850.00"},
                        {"type": "Ticker Data", "exchange_segment": 0, "security_id": 29, "LTP": "29851.00"},       # within the same second: not logged again
                        {"type": "Ticker Data", "exchange_segment": 0, "security_id": 999, "LTP": "1.00"}):           # not an index we follow
                rec.on_message(None, pkt)
            rec.idxlog.close()
            lines = (root / "data" / "ticks" / "2026-10-26" / "index_ticks.csv").read_text(encoding="utf-8").splitlines()
            self.assertEqual(lines[0], "ts,id,kind,value")
            self.assertEqual([l.split(",")[1:] for l in lines[1:]], [["29", "P", "30000.0"], ["29", "L", "29850.0"]])
            self.assertAlmostEqual(rec.rs.index_move(29), -0.5, places=2)
            self.assertEqual(rs.INDEX_IDS[0], 13)


if __name__ == "__main__":
    unittest.main()
