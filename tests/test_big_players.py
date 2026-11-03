import json
import tempfile
import unittest
from pathlib import Path

import big_players as bpl
import big_prints as bp


def feed(tr, sym, n_small=300, big_qty=50000, side="B", price=100.0, start=33300):
    """n_small ordinary prints of 100 shares, then one big print."""
    t = start
    for i in range(n_small):
        h, rem = divmod(int(t), 3600)
        m, s = divmod(rem, 60)
        tr.update(sym, f"{h:02d}:{m:02d}:{s:02d}.000", price, 100, "B" if i % 2 else "S")
        t += 1
    h, rem = divmod(int(t), 3600)
    m, s = divmod(rem, 60)
    return tr.update(sym, f"{h:02d}:{m:02d}:{s:02d}.000", price, big_qty, side), t


class BigPrintTests(unittest.TestCase):
    def test_big_print_needs_history_size_and_value(self):
        tr = bp.BigPrintTracker()
        ev, t = feed(tr, "AAA", n_small=300, big_qty=50000, side="B")
        self.assertIsNotNone(ev)
        self.assertEqual((ev["side"], ev["qty"], ev["lakh"]), ("B", 50000, 50.0))        # 50,000 x 100 = 50 lakh
        young = bp.BigPrintTracker()
        ev2, _ = feed(young, "BBB", n_small=50, big_qty=50000)                            # fewer than 200 prints so far: no threshold yet
        self.assertIsNone(ev2)
        cheap = bp.BigPrintTracker()
        ev3, _ = feed(cheap, "CCC", n_small=300, big_qty=500, price=10.0)                 # big for the stock but only Rs 50,000
        self.assertIsNone(ev3)
        same = bp.BigPrintTracker()
        ev4, _ = feed(same, "DDD", n_small=300, big_qty=100, side="B")                    # an ordinary print is not big
        self.assertIsNone(ev4)

    def test_totals_window_and_file_round_trip(self):
        tr = bp.BigPrintTracker()
        _, t = feed(tr, "AAA", side="B")
        tr.update("AAA", "09:40:30.000", 100.0, 60000, "S")
        snap = tr.snapshot(t + 60)
        a = snap["stocks"]["AAA"]
        self.assertEqual((a["n_buy"], a["n_sell"], a["buy_cr"], a["sell_cr"], a["net_cr"]), (1, 1, 0.5, 0.6, -0.1))
        late = tr.snapshot(t + 3600)["stocks"]["AAA"]
        self.assertEqual((late["n15"], late["net15_cr"], late["net_cr"]), (0, 0.0, -0.1))   # off the 15-minute window, still in today's total
        self.assertEqual(len(snap["tape"]), 2)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertTrue(tr.maybe_write(root, "2026-10-22", t + 1, force=True))
            self.assertFalse(tr.maybe_write(root, "2026-10-22", t + 2))                     # rate limited
            self.assertEqual(bp.load(root, "2026-10-22")["stocks"]["AAA"]["n_buy"], 1)
            self.assertIsNone(bp.load(root, "2026-10-23"))                                  # another day's file is not today's data


class PageDataTests(unittest.TestCase):
    def test_future_labels_and_confirmations(self):
        self.assertEqual(bpl.classify_future(0.5, 1.0), "LONG_BUILDUP")
        self.assertEqual(bpl.classify_future(0.5, -1.0), "SHORT_COVERING")
        self.assertEqual(bpl.classify_future(-0.5, 1.0), "SHORT_BUILDUP")
        self.assertEqual(bpl.classify_future(-0.5, -1.0), "LONG_UNWINDING")
        self.assertEqual(bpl.classify_future(0.05, 5.0), "NEUTRAL")
        fut = {"label": "LONG_BUILDUP"}
        lean = {"ce_share": 0.8}
        self.assertEqual(bpl.confirmations("BUY", fut, lean, 0.3, 25), ["FUT", "OPT", "BOOK", "TICK"])
        self.assertEqual(bpl.confirmations("SELL", fut, lean, 0.3, 25), [])
        self.assertEqual(bpl.confirmations("SELL", {"label": "SHORT_BUILDUP"}, {"ce_share": 0.2}, -0.4, -30), ["FUT", "OPT", "BOOK", "TICK"])
        self.assertEqual(bpl.confirmations("BUY", None, None, None, None), [])
        self.assertEqual(bpl.premium_lean([(900, 1.0, 1.0), (1000, 3.0, 1.0), (1005, 1.0, 0.0)]), {"ce_share": 0.8, "prem15_cr": 5.0})   # only the last 15 minutes count

    def test_build_ranks_buyers_sellers_and_sectors(self):
        snap = {"updated": "10:30:00", "tape": [{"t": "10:29:00", "s": "AAA", "side": "B", "qty": 1, "px": 1, "lakh": 5}],
                "stocks": {"AAA": {"ltp": 100, "buy_cr": 5, "sell_cr": 1, "net_cr": 4, "n_buy": 5, "n_sell": 1, "net15_cr": 2.5, "n15": 3, "last": {"t": "10:29:00", "side": "B", "lakh": 5}},
                           "BBB": {"ltp": 50, "buy_cr": 0.2, "sell_cr": 3, "net_cr": -2.8, "n_buy": 1, "n_sell": 4, "net15_cr": -1.5, "n15": 2, "last": None},
                           "CCC": {"ltp": 10, "buy_cr": 0, "sell_cr": 0, "net_cr": 0, "n_buy": 0, "n_sell": 0, "net15_cr": 0, "n15": 0, "last": None}}}
        out = bpl.build(snap, {"AAA": {"label": "LONG_BUILDUP", "oi_pct": 2.0}}, {}, {"AAA": {"imbalance": 0.4, "flow_pct": 30, "chg_pct": 1.2}}, {"AAA": "IT", "BBB": "Banks"})
        self.assertEqual([r["s"] for r in out["buyers"]], ["AAA"])
        self.assertEqual([r["s"] for r in out["sellers"]], ["BBB"])                        # CCC had no big prints
        self.assertEqual(out["buyers"][0]["cb"], ["FUT", "BOOK", "TICK"])
        self.assertEqual((out["market"]["buy_cr"], out["market"]["sell_cr"], out["market"]["net_buying"], out["market"]["net_selling"]), (5.2, 4.0, 1, 1))
        self.assertEqual([s["sec"] for s in out["sectors"]], ["IT", "Banks"])
        self.assertTrue(out["futures_ok"])
        self.assertFalse(out["options_ok"])
        json.dumps(out)

    def test_payload_without_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = bpl.payload(Path(tmp))
            self.assertFalse(out["ok"])


if __name__ == "__main__":
    unittest.main()
