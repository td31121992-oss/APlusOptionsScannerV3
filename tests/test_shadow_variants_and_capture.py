import tempfile
import unittest
from pathlib import Path

import derived_tags
import supervisor_facts as sf
import trade_archive as ta


def trade(**kw):
    base = {"entry_time": "2026-11-13T10:00:00+05:30", "entry_price": 10.0, "quantity": 100, "net_pnl": -300.0, "gross_pnl": -100.0, "paper_trade_id": "T1"}
    base.update(kw)
    return base


class ShadowExitVariantTests(unittest.TestCase):
    def test_fired_rule_uses_its_exit_price_and_trade_cost(self):
        out = derived_tags.shadow_exit_variants(trade(shadow_secfade_exit_price=11.0))
        self.assertAlmostEqual(out["dx_x_secfade"], (11.0 - 10.0) * 100 - 200, places=2)       # cost = gross - net = 200

    def test_unfired_rule_equals_the_real_result(self):
        out = derived_tags.shadow_exit_variants(trade())
        self.assertEqual(out["dx_x_peak8_a20"], -300.0)

    def test_trades_from_before_the_rule_existed_are_none(self):
        out = derived_tags.shadow_exit_variants(trade(entry_time="2026-10-01T10:00:00+05:30", shadow_secfade_exit_price=11.0))
        self.assertIsNone(out["dx_x_secfade"])
        self.assertIsNone(out["dx_x_peak8_a20"])

    def test_variants_reach_the_forward_csv_rows(self):
        t = trade(shadow_peak8_a20_exit_price=12.0, _day="2026-11-13")
        t.update(derived_tags.shadow_exit_variants(t))
        rows = ta.exit_variant_rows([t])
        names = {r[1] for r in rows}
        self.assertIn("dx_x_peak8_a20", names)
        self.assertIn("dx_x_secfade", names)


class CaptureTests(unittest.TestCase):
    def test_capture_splits_winners_from_losers_and_counts_fall_through(self):
        hist = [
            {"entry_time": "2026-11-13T10:00:00", "status": "CLOSED", "net_pnl": 600, "mfe_amount": 1000, "exit_reason": "SESSION_END", "symbol": "A"},
            {"entry_time": "2026-11-13T10:05:00", "status": "CLOSED", "net_pnl": -500, "mfe_amount": 200, "exit_reason": "OPTION_STOP_LOSS", "symbol": "B",
             "option_stop": 9.0, "exit_price": 8.5, "quantity": 100},
        ]
        c = sf.capture_day("2026-11-13", hist)
        self.assertEqual(c["winners_peak"], 1000)
        self.assertEqual(c["winners_kept_pct"], 60)
        self.assertEqual(c["losers_net"], -500)
        self.assertEqual(c["stop_fall_through_rs"], 50)
        self.assertEqual(c["giveback_by_exit"][0]["exit"], "OPTION_STOP_LOSS")             # the biggest leak is listed first
        self.assertEqual(sf.capture_day("2026-11-14", hist), {})

    def test_blackouts_merge_gaps_across_trades(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp, "data", "option_trade_tape", "2026-11-13")
            d.mkdir(parents=True)
            head = "timestamp,trade_id,symbol,option_security_id,option_type,strike,expiry,price,entry_price,option_stop,status\n"
            rows = lambda times: "".join(f"2026-11-13T{t},X,S,1,CE,1,2026-11-24,10,10,9,OPEN\n" for t in times)       # noqa: E731
            (d / "a.csv").write_text(head + rows(["10:00:00", "10:00:03", "10:08:00", "10:08:03"]), encoding="utf-8")
            (d / "b.csv").write_text(head + rows(["10:01:00", "10:06:00", "10:06:03"]), encoding="utf-8")
            out = sf.blackouts("2026-11-13", Path(tmp))
            self.assertEqual(out["windows"], 1)                                                  # b's 10:01-10:06 sits inside a's 10:00-10:08
            self.assertEqual(out["minutes"], 8)


if __name__ == "__main__":
    unittest.main()
