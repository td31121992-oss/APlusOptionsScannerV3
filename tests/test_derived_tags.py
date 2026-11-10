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
