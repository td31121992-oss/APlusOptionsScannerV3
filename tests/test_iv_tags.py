import csv
import math
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS

import iv_tags as iv


def leg(iv_):
    return NS(oi=1, volume=1, iv=iv_, oi_change=0, previous_oi=0)


def snap(call_iv=30.0, put_iv=34.0, sym="AAA"):
    return NS(symbol=sym, underlying_ltp=100.0, strikes=[NS(strike=k, call=leg(call_iv), put=leg(put_iv)) for k in (95, 100, 105)])


def setup(root: Path, hist_ivs, closes):
    (root / "data" / "iv_history").mkdir(parents=True)
    with (root / "data" / "iv_history" / "AAA.csv").open("w", encoding="utf-8", newline="") as h:
        h.write("day,iv\n" + "".join(f"2026-09-{i + 1:02d},{v}\n" for i, v in enumerate(hist_ivs)))
    (root / "data" / "nse_daily").mkdir(parents=True)
    with (root / "data" / "nse_daily" / "stock_daily.csv").open("w", encoding="utf-8", newline="") as h:
        w = csv.DictWriter(h, fieldnames=["day", "symbol", "close", "ttl_qty"])
        w.writeheader()
        for i, c in enumerate(closes):
            w.writerow({"day": f"2026-10-{i + 1:02d}", "symbol": "AAA", "close": c, "ttl_qty": 1})


class IvTagTests(unittest.TestCase):
    def test_rank_realised_vol_skew_and_expensive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            setup(root, [20 + i for i in range(12)], [100.0] + [100.0 * (1.005 if i % 2 else 0.995) for i in range(1, 22)])      # +-0.5 % about 100: daily moves of 1 %, about 16 % a year
            t = iv.tags(snap(), "BEARISH", 100.0, root, today="2026-10-26")
            self.assertEqual(t["iv_atm"], 32.0)
            self.assertEqual(t["iv_rank"], 100.0)                                         # dearer than all 12 recorded days
            self.assertEqual((t["iv_skew"], t["iv_vs_dir"]), (4.0, 4.0))                  # puts dearer than calls: for a put that is the market paying up on our side
            self.assertEqual(iv.tags(snap(), "BULLISH", 100.0, root, today="2026-10-26")["iv_vs_dir"], -4.0)
            self.assertGreater(t["iv_vs_hv"], 1.5)                                         # 32 % against about 16 % realised
            self.assertEqual(t["iv_expensive"], 1)

    def test_cheap_option_and_missing_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            setup(root, [40 + i for i in range(12)], [100.0] + [100.0 * (1.02 if i % 2 else 0.98) for i in range(1, 22)])
            t = iv.tags(snap(30.0, 30.0), "BULLISH", 100.0, root, today="2026-10-26")
            self.assertEqual(t["iv_rank"], 0.0)
            self.assertLess(t["iv_vs_hv"], 1.5)
            self.assertEqual(t["iv_expensive"], 0)
        with tempfile.TemporaryDirectory() as tmp:
            t = iv.tags(snap(), "BULLISH", 100.0, Path(tmp), today="2026-10-26")        # no history files at all
            self.assertEqual(t, {"iv_atm": 32.0, "iv_skew": 4.0, "iv_vs_dir": -4.0})
        self.assertEqual(iv.tags(NS(symbol="X", strikes=[]), "BULLISH", 100.0), {})
        self.assertEqual(iv.tags(snap(0.0, 0.0), "BULLISH", 100.0), {})

    def test_change_since_the_first_reading_today(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            setup(root, [30.0] * 12, [100.0] * 22)
            with (root / "data" / "iv_history" / "AAA.csv").open("a", encoding="utf-8") as h:
                h.write("2026-10-26,25.0\n")
            self.assertEqual(iv.tags(snap(), "BULLISH", 100.0, root, today="2026-10-26")["iv_chg_day_pct"], 28.0)      # 32 against 25 this morning
            self.assertTrue(math.isclose(iv.realised_vol("AAA", "2026-10-26", root) or 0.0, 0.0, abs_tol=1e-9))     # flat closes: no volatility


if __name__ == "__main__":
    unittest.main()
