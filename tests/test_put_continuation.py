import json
import tempfile
import unittest
from pathlib import Path

import put_continuation as pc


def stock(open_px, closes, start=555, volume=1000.0):
    n = len(closes)
    minute = [start + 5 * i for i in range(n)]
    o = [open_px] + closes[:-1]
    return {"minute": minute, "open": o, "close": closes, "volume": [volume] * n,
            "high": [max(a, b) + 0.05 for a, b in zip(o, closes)], "low": [min(a, b) - 0.05 for a, b in zip(o, closes)]}


def falling(open_px=100.0, n=50, step=-0.06):
    c, out = open_px, []
    for i in range(n):
        c += step
        out.append(round(c, 3))
    return stock(open_px, out)


def rising(open_px=100.0, n=50, step=0.05):
    return stock(open_px, [round(open_px + step * (i + 1), 3) for i in range(n)])


class SignalTests(unittest.TestCase):
    def universe(self):
        syms = {f"W{i}": falling() for i in range(4)}                  # weak sector, falling
        syms.update({f"S{i}": rising() for i in range(3)})             # strong sector
        syms.update({f"M{i}": rising(step=0.001) for i in range(3)})   # flat sector
        syms.update({f"N{i}": rising(step=0.002) for i in range(3)})   # another flat sector
        sec = {**{f"W{i}": "Weak" for i in range(4)}, **{f"S{i}": "Strong" for i in range(3)}, **{f"M{i}": "Mid" for i in range(3)},
               **{f"N{i}": "Mid2" for i in range(3)}}
        return syms, sec

    def test_only_weak_sector_breakdowns_qualify(self):
        syms, sec = self.universe()
        sigs = pc.find_signals(syms, sec)
        self.assertEqual({s["symbol"] for s in sigs}, {"W0", "W1", "W2", "W3"})
        s = sigs[0]
        self.assertGreaterEqual(s["minute"], pc.DECIDE_FROM)
        self.assertLessEqual(s["move_pct"], pc.MIN_MOVE)

    def test_a_falling_stock_in_a_strong_sector_does_not_qualify(self):
        syms, sec = self.universe()
        syms["W0"] = falling()
        sec["W0"] = "Strong"
        sigs = pc.find_signals(syms, sec)
        self.assertNotIn("W0", {s["symbol"] for s in sigs})

    def test_forward_move_is_signed_for_puts(self):
        d = falling(n=60)
        fwd, mfe = pc.stock_forward(d, 600)
        self.assertGreater(fwd, 0)                                     # it kept falling
        self.assertGreaterEqual(mfe, fwd)
        self.assertEqual(pc.stock_forward(d, 800), (None, None))

    def test_option_outcome_with_a_fake_feed(self):
        import pandas as pd
        master = pd.DataFrame([{"SECURITY_ID": 1, "INSTRUMENT": "OPTSTK", "UNDERLYING_SYMBOL": "W0", "SM_EXPIRY_DATE": "2026-10-27",
                                "STRIKE_PRICE": 100.0, "OPTION_TYPE": "PE", "LOT_SIZE": 100}])
        bars = [(m, 10.0, 10.5, 9.8, 10.0) for m in range(600, 630, 5)] + [(630, 10.0, 12.5, 9.9, 12.0), (635, 12.0, 13.0, 11.5, 12.5), (640, 12.5, 13.0, 12.0, 12.8)]
        r = pc.option_outcome("W0", 620, 99.0, "2026-10-15", fetch=lambda sid, day: bars, master=master)
        self.assertEqual(r["strike"], 100.0)
        self.assertGreater(r["opt_best_pct"], 20)
        self.assertFalse(r["stop_first"])

    def test_run_and_summary_files(self):
        syms, sec = self.universe()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data" / "pattern_log" / "candles").mkdir(parents=True)
            (root / "data" / "reports").mkdir(parents=True)
            (root / "data" / "pattern_log" / "candles" / "2026-10-15.json").write_text(json.dumps({"symbols": syms}))
            (root / "data" / "reports" / "fno_market_watch_latest.json").write_text(
                json.dumps({"rows": [{"symbol": s, "sector": v} for s, v in sec.items()]}))
            p = pc.run("2026-10-15", root, with_options=False)
            self.assertTrue(p.exists())
            text = (root / "data" / "shadow_rules" / "put_continuation.md").read_text(encoding="utf-8")
            self.assertIn("4 signals on 1 day", text)
            self.assertIn("Verdict: not yet", text)


if __name__ == "__main__":
    unittest.main()
