import unittest
from unittest import mock

import greeks as gk
import strategy_builder as sb

SPOT, DTE, LOT, VOL = 100.0, 20, 100, 0.30
STRIKES = [85.0, 90.0, 92.5, 95.0, 97.5, 100.0, 102.5, 105.0, 107.5, 110.0, 115.0]


def _rows(opt):
    t = (DTE + 0.5) / 365.0
    out = []
    for k in STRIKES:
        p = gk.bs_price(SPOT, k, t, VOL, opt == "CE")
        out.append({"strike": k, "ltp": round(p, 2), "bid": round(p * 0.995, 2), "ask": round(p * 1.005, 2), "iv": 30.0, "oi": 50000, "volume": 9000, "spread_pct": 1.0, "lot_size": LOT, "status": "ELIGIBLE"})
    return out


def fake_analyse(symbol, side="CE", expiry=""):
    return {"ok": True, "symbol": "ZZZ", "side": side, "expiry": "2026-11-18", "expiries": ["2026-11-18"], "scanner_expiry": "2026-11-18", "days_to_expiry": DTE, "spot": SPOT, "atm": 100.0,
            "captured_at": "2026-10-28T11:00:00", "rows": _rows(side)}


def ev(legs, **kw):
    with mock.patch.object(sb.contract_lab, "analyse", side_effect=fake_analyse):
        return sb.evaluate("ZZZ", "", legs, **kw)


def row(opt, k):
    return next(r for r in _rows(opt) if r["strike"] == k)


class ParseTests(unittest.TestCase):
    def test_valid_and_invalid_legs(self):
        legs = sb.parse_legs("B:CE:950:2, S:pe:900")
        self.assertEqual([(l["side"], l["opt"], l["strike"], l["lots"]) for l in legs], [(1, "CE", 950.0, 2), (-1, "PE", 900.0, 1)])
        for bad in ("X:CE:100:1", "B:XX:100:1", "B:CE", "B:CE:-5:1"):
            with self.assertRaises(ValueError):
                sb.parse_legs(bad)
        with self.assertRaises(ValueError):
            sb.parse_legs(",".join(["B:CE:100:1"] * 9))
        self.assertEqual(sb.parse_legs("B:CE:100:999")[0]["lots"], sb.MAX_LOTS)


class PayoffTests(unittest.TestCase):
    def test_long_call(self):
        w = ev("B:CE:100:1")
        ask = row("CE", 100.0)["ask"]
        self.assertTrue(w["ok"])
        self.assertAlmostEqual(w["net"]["cash"], ask * LOT, delta=1)
        self.assertTrue(w["net"]["max_profit_unlimited"] and not w["net"]["max_loss_unlimited"])
        self.assertAlmostEqual(w["net"]["max_loss"], -ask * LOT, delta=1)
        self.assertEqual(w["net"]["breakevens"], [round(100.0 + ask, 2)])
        self.assertEqual(w["net"]["kind"], "debit (you pay)")
        self.assertLess(w["net"]["pop_pct"], 50)                                       # needs a move past the premium
        self.assertAlmostEqual(w["net"]["mark_pnl_now"], -w["net"]["spread_cost"], delta=1)    # marked at mid: the loss is exactly the spread paid

    def test_bull_call_spread_is_capped_both_ways(self):
        w = ev("B:CE:100:1,S:CE:105:1")
        debit = (row("CE", 100.0)["ask"] - row("CE", 105.0)["bid"]) * LOT
        self.assertAlmostEqual(w["net"]["cash"], debit, delta=1)
        self.assertFalse(w["net"]["max_profit_unlimited"] or w["net"]["max_loss_unlimited"])
        self.assertAlmostEqual(w["net"]["max_profit"], 5 * LOT - debit, delta=1)
        self.assertAlmostEqual(w["net"]["max_loss"], -debit, delta=1)
        self.assertAlmostEqual(w["net"]["breakevens"][0], 100.0 + debit / LOT, delta=0.01)

    def test_short_straddle_has_unlimited_loss_and_a_credit(self):
        w = ev("S:CE:100:1,S:PE:100:1")
        self.assertEqual(w["net"]["kind"], "credit (you receive)")
        self.assertTrue(w["net"]["max_loss_unlimited"])
        credit = -w["net"]["cash"]
        self.assertAlmostEqual(w["net"]["max_profit"], credit, delta=1)
        self.assertEqual(len(w["net"]["breakevens"]), 2)
        self.assertTrue(any("margin" in x for x in w["warnings"]))
        self.assertTrue(any("unlimited" in x.lower() for x in w["warnings"]))

    def test_iron_condor_is_bounded_with_two_breakevens(self):
        w = ev("S:PE:95:1,B:PE:90:1,S:CE:105:1,B:CE:110:1")
        self.assertFalse(w["net"]["max_profit_unlimited"] or w["net"]["max_loss_unlimited"])
        self.assertGreater(w["net"]["max_profit"], 0)
        self.assertLess(w["net"]["max_loss"], 0)
        self.assertEqual(len(w["net"]["breakevens"]), 2)
        self.assertLess(w["net"]["breakevens"][0], 95.0)
        self.assertGreater(w["net"]["breakevens"][1], 105.0)
        self.assertGreater(w["net"]["pop_pct"], 50)                                    # a wide range around the money is the likely outcome

    def test_expiry_curve_matches_the_formula_and_today_curve_sits_above_it_for_a_long_option(self):
        w = ev("B:CE:100:1")
        s, c = w["curves"]["spots"], w["curves"]["expiry"]
        ask = row("CE", 100.0)["ask"]
        for x, y in zip(s, c):
            self.assertAlmostEqual(y, (max(0.0, x - 100.0) - ask) * LOT, delta=1)
        far_below = min(range(len(s)), key=lambda i: abs(s[i] - 88))
        self.assertGreater(w["curves"]["today"][far_below], c[far_below])             # time value left today

    def test_what_if_moves_the_right_way(self):
        base = ev("B:CE:100:1,B:PE:100:1")["scenario"]["pnl"]
        later = ev("B:CE:100:1,B:PE:100:1", days=10)["scenario"]["pnl"]
        self.assertLess(later, base)                                                     # a straddle bleeds time
        big = ev("B:CE:100:1,B:PE:100:1", move=10, days=10)["scenario"]["pnl"]
        self.assertGreater(big, later)
        self.assertGreater(ev("B:CE:100:1", iv=5)["scenario"]["pnl"], ev("B:CE:100:1", iv=-5)["scenario"]["pnl"])
        up = ev("B:CE:100:1", move=5)["scenario"]["pnl"]
        self.assertGreater(up, ev("B:CE:100:1", move=0)["scenario"]["pnl"])

    def test_net_greeks_add_up(self):
        w = ev("B:CE:100:1,B:PE:100:1")
        self.assertLess(abs(w["net"]["greeks"]["delta"]), 0.15 * LOT)                  # a straddle is close to delta-neutral
        self.assertLess(w["net"]["greeks"]["theta_day"], 0)
        self.assertGreater(w["net"]["greeks"]["vega_per_iv_pt"], 0)
        s = ev("S:CE:100:1,S:PE:100:1")
        self.assertAlmostEqual(s["net"]["greeks"]["theta_day"], -w["net"]["greeks"]["theta_day"], delta=1)

    def test_fill_modes_change_the_entry_price(self):
        worst, mid, last = (ev("B:CE:100:1", fill=f)["legs"][0]["entry"] for f in ("worst", "mid", "last"))
        self.assertGreater(worst, mid)
        self.assertAlmostEqual(last, row("CE", 100.0)["ltp"], places=2)


class ErrorAndTemplateTests(unittest.TestCase):
    def test_bad_inputs_give_messages(self):
        self.assertIn("at least one leg", ev("")["error"])
        self.assertIn("No CE 123 in this chain", ev("B:CE:123:1")["error"])
        self.assertIn("should look like", ev("B:CE")["error"])

    def test_wide_spread_warning(self):
        def wide(symbol, side="CE", expiry=""):
            d = fake_analyse(symbol, side, expiry)
            for r in d["rows"]:
                r["bid"] = round(r["ask"] * 0.8, 2)
            return d
        with mock.patch.object(sb.contract_lab, "analyse", side_effect=wide):
            w = sb.evaluate("ZZZ", "", "B:CE:100:1")
        self.assertTrue(any("spread" in x for x in w["warnings"]))

    def test_chain_and_templates_parse_and_evaluate(self):
        with mock.patch.object(sb.contract_lab, "analyse", side_effect=fake_analyse):
            c = sb.chain("ZZZ")
            self.assertTrue(c["ok"])
            self.assertEqual(c["lot_size"], LOT)
            self.assertEqual([s["strike"] for s in c["strikes"]], STRIKES)
            self.assertTrue(c["strikes"][0]["ce"]["ltp"] > 0 and c["strikes"][0]["pe"]["ltp"] >= 0)
            names = [t["name"] for t in c["templates"]]
            for want in ("Long call", "Bull call spread", "Long straddle", "Iron condor", "Call butterfly"):
                self.assertIn(want, names)
            for t in c["templates"]:
                sb.parse_legs(t["legs"])
                self.assertTrue(sb.evaluate("ZZZ", "", t["legs"])["ok"], t["name"])

    def test_chain_errors_pass_through(self):
        with mock.patch.object(sb.contract_lab, "analyse", return_value={"ok": False, "error": "no expiry"}):
            self.assertEqual(sb.chain("ZZZ")["error"], "no expiry")
            self.assertEqual(sb.evaluate("ZZZ", "", "B:CE:100:1")["error"], "no expiry")

    def test_page_text(self):
        self.assertIn("Strategy Builder", sb.STRATEGY_HTML)
        self.assertIn("/api/strategy-eval", sb.STRATEGY_HTML)


if __name__ == "__main__":
    unittest.main()
