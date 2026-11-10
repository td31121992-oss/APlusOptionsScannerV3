import csv
import gzip
import tempfile
import unittest
from pathlib import Path

import derived_tags as dt


def trade(**kw):
    base = {"paper_trade_id": "a", "symbol": "ABB", "option_security_id": "11", "entry_time": "2026-11-09T10:00:00", "exit_time": "2026-11-09T13:00:00", "entry_price": 10.0,
            "spread_percent": 0.8}
    base.update(kw)
    return base


def ticks(*rows):                                            # (seconds_since_midnight, ltp, ask)
    return list(rows)


T0 = 10 * 3600


class SpreadTests(unittest.TestCase):
    def test_over_one_percent_is_wide_and_unknown_is_none(self):
        self.assertIs(dt.spread_wide(trade(spread_percent=1.2)), True)
        self.assertIs(dt.spread_wide(trade(spread_percent=1.0)), False)
        self.assertIsNone(dt.spread_wide(trade(spread_percent="")))


class MomentumTests(unittest.TestCase):
    def test_confirmed_when_at_or_above_entry_at_the_check(self):
        tk = ticks((T0 + 10, 10.0, 10.1), (T0 + 290, 10.4, 10.5), (T0 + 400, 9.0, 9.1))
        self.assertIs(dt.momentum_block(trade(), tk), False)

    def test_blocked_when_below_entry_at_the_check(self):
        tk = ticks((T0 + 10, 10.0, 10.1), (T0 + 290, 9.5, 9.6), (T0 + 400, 12.0, 12.1))
        self.assertIs(dt.momentum_block(trade(), tk), True)

    def test_closed_before_the_check_would_not_have_been_taken(self):
        tk = ticks((T0 + 10, 10.0, 10.1), (T0 + 400, 10.0, 10.1))
        self.assertIs(dt.momentum_block(trade(exit_time="2026-11-09T10:03:00"), tk), True)

    def test_no_ticks_is_unknown(self):
        self.assertIsNone(dt.momentum_block(trade(), None))
        self.assertIsNone(dt.momentum_block(trade(), ticks((T0 + 10, 10.0, 10.1))))      # nothing recorded at or after the check


class EnrichTests(unittest.TestCase):
    def test_enrich_reads_recorded_ticks_and_combines_the_two(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "data" / "option_ticks" / "2026-11-09"
            folder.mkdir(parents=True)
            with gzip.open(folder / "11_ABB.csv.gz", "wt", encoding="utf-8", newline="") as h:
                w = csv.writer(h)
                w.writerow(["ts", "ltp", "ask"])
                w.writerow(["10:00:10.0", "10.0", "10.1"])
                w.writerow(["10:04:55.0", "10.5", "10.6"])
                w.writerow(["10:06:00.0", "10.2", "10.3"])
            rows = [trade(), trade(paper_trade_id="b", spread_percent=2.0), trade(paper_trade_id="c", option_security_id="999")]
            dt.enrich(rows, Path(tmp))
            self.assertEqual((rows[0]["dx_spread_wide"], rows[0]["dx_mom5_block"], rows[0]["dx_would_block"]), (False, False, False))
            self.assertEqual((rows[1]["dx_spread_wide"], rows[1]["dx_would_block"]), (True, True))
            self.assertEqual((rows[2]["dx_mom5_block"], rows[2]["dx_would_block"]), (None, False))


if __name__ == "__main__":
    unittest.main()


class ExitVariantTests(unittest.TestCase):
    def trade(self, **kw):
        return trade(quantity=100, gross_pnl=0, net_pnl=-214, **kw)

    def test_wide_stop_exits_at_minus_25_percent_and_pays_the_cost(self):
        tk = ticks((T0 + 10, 10.0, 10.1), (T0 + 100, 8.0, 8.1), (T0 + 200, 7.4, 7.5), (T0 + 300, 12.0, 12.1))
        out = dt.exit_variants(self.trade(), tk)
        self.assertAlmostEqual(out["dx_x_wide25"], (7.4 - 10.0) * 100 - 214, places=2)          # first tick at or below 7.5 is 7.4

    def test_late_trail_keeps_most_of_a_big_gain_and_runs_to_the_close_without_it(self):
        tk = ticks((T0 + 10, 10.0, 10.1), (T0 + 100, 14.0, 14.1), (T0 + 200, 11.0, 11.1), (T0 + 300, 12.0, 12.1))
        out = dt.exit_variants(self.trade(), tk)
        self.assertAlmostEqual(out["dx_x_wide25_t30g30"], (11.0 - 10.0) * 100 - 214, places=2)  # trail floor = 10 + 4 * 0.7 = 12.8, hit by 11.0
        self.assertAlmostEqual(out["dx_x_wide25"], (12.0 - 10.0) * 100 - 214, places=2)         # no trail: held to the last tick

    def test_no_ticks_gives_none_for_every_variant(self):
        self.assertEqual(set(dt.exit_variants(self.trade(), None).values()), {None})


class ExitVariantReportTests(unittest.TestCase):
    def test_rows_are_per_day_and_rewriting_a_day_keeps_the_others(self):
        import trade_archive as ta

        rows_a = ta.exit_variant_rows([{"_day": "2026-11-11", "net_pnl": -100, "dx_x_wide25": 50, "dx_x_wide25_t30g30": None, "dx_x_wide25_t30g40": None},
                                       {"_day": "2026-11-11", "net_pnl": 20, "dx_x_wide25": 10}])
        self.assertEqual(rows_a, [["2026-11-11", "dx_x_wide25", 2, -80.0, 60.0]])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "exit_variants.csv"
            ta.write_exit_variants(rows_a, path)
            ta.write_exit_variants([["2026-11-12", "dx_x_wide25", 1, 5.0, 9.0]], path)
            ta.write_exit_variants([["2026-11-11", "dx_x_wide25", 2, -80.0, 70.0]], path)
            lines = path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 3)                                                     # header + one row per day
            self.assertIn("2026-11-11,dx_x_wide25,2,-80.0,70.0", lines)
            self.assertIn("Forward only", ta.render_exit_variants(path))


class Sector945Tests(unittest.TestCase):
    SECTORS = {**{f"A{i}": "SecA" for i in range(4)}, **{f"B{i}": "SecB" for i in range(4)}, **{f"C{i}": "SecC" for i in range(4)}, **{f"D{i}": "SecD" for i in range(4)},
               **{f"E{i}": "SecE" for i in range(4)}}

    def candles(self, moves):
        """symbol -> 5-minute candles: opens at 100 at 09:15, closes at 100 * (1 + move) in the 09:40 bar."""
        return {s: {"minute": [555, 580, 585], "open": [100.0, 100.0, 100.0], "close": [100.0, 100.0 * (1 + m / 100), 100.0], "high": [100.0] * 3, "low": [100.0] * 3}
                for s, m in moves.items()}

    def test_picks_and_trade_tags(self):
        import json
        from sector_rank945 import allowed, day_picks

        # SecA +2%, SecB +1%, SecC 0%, SecD -1%, SecE -2%; inside SecA the stocks move +2.4, +2.2, +1.8, +1.6
        moves = {f"A{i}": v for i, v in enumerate((2.4, 2.2, 1.8, 1.6))}
        moves.update({f"B{i}": 1.0 for i in range(4)}); moves.update({f"C{i}": 0.0 for i in range(4)})
        moves.update({f"D{i}": -1.0 for i in range(4)}); moves.update({f"E{i}": v for i, v in enumerate((-2.4, -2.2, -1.8, -1.6))})
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / "data" / "pattern_log" / "candles"
            folder.mkdir(parents=True)
            (folder / "2026-11-11.json").write_text(json.dumps({"day": "2026-11-11", "symbols": self.candles(moves)}), encoding="utf-8")
            picks = day_picks("2026-11-11", root, self.SECTORS)
            self.assertEqual((picks["open"]["gain"], picks["open"]["lose"]), (["SecA", "SecB"], ["SecD", "SecE"]))
            ok = lambda sym, side, minute, n=None: allowed(sym, side, minute, picks["open"], self.SECTORS, n)           # noqa: E731
            self.assertFalse(ok("A0", "CE", 9 * 60 + 40))                    # before 09:45
            self.assertTrue(ok("A0", "CE", 9 * 60 + 50))                     # call in a gaining sector
            self.assertFalse(ok("A0", "PE", 9 * 60 + 50))                    # put in a gaining sector
            self.assertFalse(ok("C0", "CE", 9 * 60 + 50))                    # middle sector
            self.assertTrue(ok("E0", "PE", 9 * 60 + 50, 3))                  # put in the weakest sector, one of its 3 weakest stocks
            self.assertFalse(ok("E3", "PE", 9 * 60 + 50, 3))                 # its 4th weakest stock is outside the top 3

    def test_no_candles_means_no_tag(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = dt.sector_tags({"symbol": "A0", "option_type": "CE", "entry_time": "2026-11-11T10:00:00"}, Path(tmp))
            self.assertEqual(set(out.values()), {None})


class Wait5Tests(unittest.TestCase):
    def closed(self, **kw):
        return trade(quantity=100, gross_pnl=0, net_pnl=-214, exit_price=12.0, **kw)

    def test_live_record_held_buys_at_the_recorded_ask(self):
        out = dt.wait5_pnl(self.closed(opt5="HELD", opt5_ask=10.5, opt5_price=10.4), None)
        self.assertAlmostEqual(out, (12.0 - 10.5) * 100 - 214, places=2)

    def test_live_record_failed_means_not_taken(self):
        self.assertEqual(dt.wait5_pnl(self.closed(opt5="FAILED"), None), 0.0)

    def test_without_a_live_record_the_ticks_decide(self):
        tk = ticks((T0 + 10, 10.0, 10.1), (T0 + 290, 10.4, 10.5), (T0 + 310, 10.6, 10.7))
        self.assertAlmostEqual(dt.wait5_pnl(self.closed(), tk), (12.0 - 10.7) * 100 - 214, places=2)       # first ask at or after minute 5
        self.assertIsNone(dt.wait5_pnl(self.closed(), None))

    def test_forward_variants_include_the_new_line(self):
        self.assertIn("dx_e_wait5", dt.FORWARD_VARIANTS)


class RecordOpt5Tests(unittest.TestCase):
    def test_records_once_after_five_minutes_and_never_touches_the_trade_otherwise(self):
        from datetime import datetime, timedelta, timezone
        import paper_trade_journal as ptj

        ist = timezone(timedelta(hours=5, minutes=30))
        t0 = datetime(2026, 11, 11, 10, 0, 0, tzinfo=ist)
        tr = {"entry_time": t0.isoformat(), "last_ask": 10.6, "status": "OPEN"}
        ptj.record_opt5(tr, 10.0, 10.4, t0 + timedelta(minutes=4, seconds=59))
        self.assertNotIn("opt5", tr)                                                        # too early
        ptj.record_opt5(tr, 10.0, 10.4, t0 + timedelta(minutes=5, seconds=2))
        self.assertEqual((tr["opt5"], tr["opt5_price"], tr["opt5_ask"]), ("HELD", 10.4, 10.6))
        ptj.record_opt5(tr, 10.0, 9.0, t0 + timedelta(minutes=9))
        self.assertEqual(tr["opt5"], "HELD")                                                # set once
        failed = {"entry_time": t0.isoformat()}
        ptj.record_opt5(failed, 10.0, 9.8, t0 + timedelta(minutes=6))
        self.assertEqual((failed["opt5"], failed["opt5_ask"]), ("FAILED", ""))
        self.assertEqual(failed["entry_time"], t0.isoformat())                              # nothing else changed


class LagTests(unittest.TestCase):
    def setUp(self):
        dt._SIGNALS.clear()

    def write_signals(self, root):
        folder = root / "data" / "missed_opportunities" / "2026-11-11"
        folder.mkdir(parents=True)
        with (folder / "signals.csv").open("w", encoding="utf-8", newline="") as h:
            w = csv.writer(h)
            w.writerow(["symbol", "direction", "first_ready", "entry_price"])
            w.writerow(["ABB", "BULLISH", "10:00", "100"])
            w.writerow(["ABB", "BULLISH", "10:20", "101"])                                   # a later row for the same stock: the earliest wins
            w.writerow(["TCS", "BEARISH", "09:50", "200"])

    def test_minutes_since_first_signal_and_the_two_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_signals(root)
            tag = lambda sym, hhmm, **kw: dt.lag_tags({"symbol": sym, "entry_time": f"2026-11-11T{hhmm}:00", "option_type": "CE", **kw}, root)      # noqa: E731
            early, ok, late = tag("ABB", "10:05"), tag("ABB", "10:15"), tag("ABB", "10:45")
            self.assertEqual((early["dx_lag_min"], early["dx_lag_early_block"], early["dx_lag_window_block"]), (5, True, True))
            self.assertEqual((ok["dx_lag_min"], ok["dx_lag_early_block"], ok["dx_lag_window_block"]), (15, False, False))
            self.assertEqual((late["dx_lag_min"], late["dx_lag_early_block"], late["dx_lag_window_block"]), (45, False, True))
            self.assertEqual(tag("TCS", "10:10", direction="BEARISH", option_type="PE")["dx_lag_min"], 20)

    def test_no_signal_row_or_entry_before_it_gives_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_signals(root)
            for sym, hhmm in (("INFY", "10:30"), ("ABB", "09:30")):
                out = dt.lag_tags({"symbol": sym, "entry_time": f"2026-11-11T{hhmm}:00", "option_type": "CE"}, root)
                self.assertEqual(set(out.values()), {None})

    def test_missing_signals_file_is_not_cached(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(dt.first_ready_minutes("2026-11-11", root), {})
            self.write_signals(root)
            self.assertEqual(dt.first_ready_minutes("2026-11-11", root)[("ABB", "BULLISH")], 600)


class RvolTests(unittest.TestCase):
    def setUp(self):
        dt._OPENING.clear()

    def build(self, root, today_volume):
        import json

        cache = root / "data" / "cache"
        cache.mkdir(parents=True)
        days = [f"2026-10-{d:02d}" for d in range(1, 15)]                                       # 14 earlier sessions, first-bar volume 1,000 each
        (cache / "rvol_first_bars.json").write_text(json.dumps({"ABB": {d: {"v5": 1000.0, "o5": 100.0, "c5": 101.0, "v15": 3000.0} for d in days}}), encoding="utf-8")
        folder = root / "data" / "pattern_log" / "candles"
        folder.mkdir(parents=True)
        candles = {"ABB": {"minute": [555, 560, 565], "open": [100.0] * 3, "close": [101.0] * 3, "volume": [today_volume, 500.0, 500.0]}}
        (folder / "2026-11-11.json").write_text(json.dumps({"day": "2026-11-11", "symbols": candles}), encoding="utf-8")

    def test_quiet_normal_and_in_play(self):
        for vol, quiet, three in ((500.0, True, True), (1500.0, False, True), (3500.0, False, False)):
            dt._OPENING.clear()
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                self.build(root, vol)
                out = dt.rvol_tags({"symbol": "ABB", "entry_time": "2026-11-11T10:00:00"}, root)
                self.assertAlmostEqual(out["dx_rvol"], vol / 1000.0, places=2)
                self.assertEqual((out["dx_rvol_quiet_block"], out["dx_rvol3_block"]), (quiet, three))

    def test_unknown_stock_or_short_history_gives_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.build(root, 1000.0)
            self.assertEqual(set(dt.rvol_tags({"symbol": "TCS", "entry_time": "2026-11-11T10:00:00"}, root).values()), {None})
            self.assertEqual(set(dt.rvol_tags({"symbol": "ABB", "entry_time": "2026-10-03T10:00:00"}, root).values()), {None})      # only 2 earlier sessions
