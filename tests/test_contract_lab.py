import unittest
from types import SimpleNamespace as NS

import contract_lab as cl
from analytics.enums import OptionSide
from analytics.models import OptionChainSnapshot, OptionLeg, StrikeData
from option_selector import OptionSelectionConfig, OptionSelector

EXPIRY = "2026-11-23"
SPOT = 100.0


def leg(strike, side, ltp, bid, ask, oi=20000, vol=3000, sid=None, iv=30.0):
    return OptionLeg(security_id=str(sid or int(strike * 10) + (1 if side == OptionSide.CALL else 2)), side=side, strike=strike, ltp=ltp, oi=oi, volume=vol, iv=iv, bid=bid, ask=ask)


def contract(strike, kind):
    sid = str(int(strike * 10) + (1 if kind == "CE" else 2))
    return NS(derivative_security_id=sid, expiry=EXPIRY, strike=strike, option_type=kind, lot_size=100, tick_size=0.05, trading_symbol=f"ZZZ-{strike}-{kind}",
              display_name=f"ZZZ {strike} {kind}", exchange_segment="NSE_FNO")


def chain():
    """Calls: 99.5 is the ideal strike (0.5% in the money), others are good, wide, thin or too far."""
    calls = {
        99.5: leg(99.5, OptionSide.CALL, 3.0, 2.95, 3.00),                 # ideal, tight
        99.0: leg(99.0, OptionSide.CALL, 3.4, 3.40, 3.45),                 # fine (1.4% spread), a little further from the ideal strike
        100.0: leg(100.0, OptionSide.CALL, 2.8, 2.60, 3.00, oi=40000, vol=9000),   # wide spread (13.3%)
        101.0: leg(101.0, OptionSide.CALL, 2.4, 2.38, 2.40, oi=900),       # open interest too low
        103.5: leg(103.5, OptionSide.CALL, 2.2, 2.18, 2.20),               # 3.5% from spot: too far
        98.0: leg(98.0, OptionSide.CALL, 1.0, 0.95, 1.00),                 # premium below the minimum
    }
    strikes = [StrikeData(strike=k, call=v, put=leg(k, OptionSide.PUT, 3.0, 2.95, 3.0)) for k, v in sorted(calls.items())]
    snap = OptionChainSnapshot(symbol="ZZZ", underlying_security_id="1", expiry=EXPIRY, underlying_ltp=SPOT, captured_at="2026-10-28T10:00:00Z", strikes=strikes)
    contracts = [contract(k, "CE") for k in calls] + [contract(k, "PE") for k in calls]
    return snap, NS(symbol="ZZZ", security_id=1, contracts=contracts)


class ContractLabTests(unittest.TestCase):
    def setUp(self):
        self.selector = OptionSelector(OptionSelectionConfig())
        self.snap, self.under = chain()
        self.out = cl.build_rows(self.selector, self.snap, self.under, "CE")
        self.by = {r["strike"]: r for r in self.out["rows"]}

    def test_lab_agrees_with_the_selector_it_wraps(self):
        sel = self.selector.select(snapshot=self.snap, underlying=self.under, recommendation=__import__("analytics.enums", fromlist=["x"]).RecommendationType.BUY,
                                   bias=__import__("analytics.enums", fromlist=["x"]).MarketBias.BULLISH)
        self.assertEqual(self.out["chosen"]["strike"], sel.strike)
        self.assertEqual(self.by[sel.strike]["status"], "CHOSEN")
        self.assertEqual(self.by[sel.strike]["rank"], 1)
        self.assertEqual(self.out["chosen"]["limit_price"], sel.limit_price)
        self.assertEqual(self.out["chosen"]["lots"], sel.lots)

    def test_every_check_agrees_with_the_selectors_verdict(self):
        for r in self.out["rows"]:
            all_ok = all(c["ok"] for c in r["checks"])
            self.assertEqual(all_ok, r["status"] in ("ELIGIBLE", "CHOSEN"), f"strike {r['strike']}: checks and selector disagree")

    def test_rejections_say_why_in_numbers(self):
        self.assertEqual(self.by[100.0]["status"], "REJECTED")
        self.assertIn("spread 13.33%", self.by[100.0]["why"])                 # (3.00 - 2.60) / 3.00
        self.assertIn("limit 2.0%", self.by[100.0]["why"])
        self.assertIn("open interest 900", self.by[101.0]["why"])
        self.assertIn("3.50% from the stock price", self.by[103.5]["why"])
        self.assertIn("price ₹1.00", self.by[98.0]["why"])
        self.assertEqual(self.out["rejection_counts"].get("WIDE_SPREAD"), 1)
        self.assertEqual(self.out["rejected"] + self.out["eligible"], len(self.out["rows"]))

    def test_score_parts_add_up_to_the_selectors_score(self):
        for r in self.out["rows"]:
            if r["parts"]:
                self.assertAlmostEqual(sum(p["points"] for p in r["parts"]), r["score"], delta=0.35)     # parts are rounded to 0.1 each
                self.assertEqual([p["weight"] for p in r["parts"]], [0.35, 0.30, 0.20, 0.15])

    def test_the_ideal_strike_ranks_first_and_is_described(self):
        self.assertEqual(self.by[99.5]["rank"], 1)
        self.assertIn("Chosen", self.by[99.5]["why"])
        self.assertTrue(self.by[99.5]["itm"])
        self.assertFalse(self.by[100.0]["itm"] and False)                 # 100.0 vs spot 100: not in the money
        self.assertEqual(self.by[99.5]["premium_pct_of_stock"], 3.0)
        self.assertEqual(self.out["atm"], 100.0)

    def test_nothing_passes_gives_a_reason_not_a_crash(self):
        strict = OptionSelector(OptionSelectionConfig(minimum_oi=10_000_000))
        out = cl.build_rows(strict, self.snap, self.under, "CE")
        self.assertIsNone(out["chosen"])
        self.assertIn("No executable CE contract", out["no_choice_reason"])
        self.assertTrue(all(r["status"] == "REJECTED" for r in out["rows"]))

    def test_puts_use_the_put_side(self):
        out = cl.build_rows(self.selector, self.snap, self.under, "PE")
        self.assertTrue(out["rows"])
        self.assertTrue(all(r["security_id"] == str(int(r["strike"] * 10) + 2) for r in out["rows"]))     # the put contract ids, not the calls'

    def test_page_and_config_text(self):
        self.assertIn("Contract Lab", cl.CONTRACT_LAB_HTML)
        self.assertIn("/api/contract-lab", cl.CONTRACT_LAB_HTML)
        cfg = {c["label"]: c["value"] for c in cl._config_view(self.selector.config)}
        self.assertEqual(cfg["Largest bid-ask spread"], "2.0% of the ask")

    def test_unknown_stock_and_blank_symbol_are_handled(self):
        self.assertFalse(cl.analyse("")["ok"])
        self.assertEqual(cl.analyse("")["error"], "Pick a stock.")


if __name__ == "__main__":
    unittest.main()
