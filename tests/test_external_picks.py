import csv
import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

import external_picks as ep


def stock(start, path):
    closes = (list(path) + [path[-1]] * 48)[:48]
    opens = [start] + closes[:-1]
    return {"minute": [555 + 5 * i for i in range(48)], "open": opens, "close": closes,
            "high": [max(o, c) * 1.002 for o, c in zip(opens, closes)], "low": [min(o, c) * 0.998 for o, c in zip(opens, closes)], "volume": [1000.0] * 48}


def master():
    rows = []
    for sid, s in ((1, "UP"), (3, "DOWN")):
        for k, side in ((0, "CE"), (1, "PE")):
            rows.append({"SECURITY_ID": sid + k, "INSTRUMENT": "OPTSTK", "UNDERLYING_SYMBOL": s, "SM_EXPIRY_DATE": "2026-10-27", "STRIKE_PRICE": 100.0, "OPTION_TYPE": side})
    return pd.DataFrame(rows)


def fetch(sid, day):
    return [(555 + 5 * i, 10, 10 + i * 0.3, 9.9, 10 + i * 0.25) for i in range(60)]


class ExternalPickTests(unittest.TestCase):
    def test_add_replaces_the_same_pick_and_normalises_the_side(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ep.add("2026-10-16", "QuantElite", "techm", "buy", "09:39", 1738, root=root)
            ep.add("2026-10-16", "QuantElite", "TECHM", "BULLISH", "09:40", 1740, root=root)
            rows = ep.load("2026-10-16", root)
            self.assertEqual(len(rows), 1)
            self.assertEqual((rows[0]["symbol"], rows[0]["dir"], rows[0]["time"]), ("TECHM", "BULLISH", "09:40"))
            ep.add("2026-10-16", "TradeLab", "ANGELONE", "sell", root=root)
            self.assertEqual({r["dir"] for r in ep.load("2026-10-16", root)}, {"BULLISH", "BEARISH"})

    def test_review_measures_stock_option_and_our_fate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cd = root / "data" / "pattern_log" / "candles"
            cd.mkdir(parents=True)
            (cd / "2026-10-16.json").write_text(json.dumps({"symbols": {"UP": stock(100, [101, 102, 103, 104, 105, 106]), "DOWN": stock(100, [99, 98, 97, 96, 95])}}), encoding="utf-8")
            mo = root / "data" / "missed_opportunities" / "2026-10-16"
            mo.mkdir(parents=True)
            (mo / "option_returns.json").write_text(json.dumps([{"symbol": "UP", "dir": "BULLISH", "kind": "ATM", "fate": "A_PLUS:late_vwap_extension", "ready": "09:40"}]), encoding="utf-8")
            ep.add("2026-10-16", "QuantElite", "UP", "BULLISH", "09:30", 101, root=root)
            ep.add("2026-10-16", "QuantElite", "DOWN", "BEARISH", "", 99, root=root)
            ep.add("2026-10-16", "TradeLab", "NOSUCH", "BULLISH", root=root)
            path = ep.run("2026-10-16", root, fetch, master())
            with path.open(encoding="utf-8") as h:
                rows = {r["symbol"]: r for r in csv.DictReader(h)}
            self.assertEqual(set(rows), {"UP", "DOWN"})                              # a stock with no candles is skipped
            self.assertGreater(float(rows["UP"]["stock_to_close_pct"]), 0)
            self.assertGreater(float(rows["DOWN"]["stock_to_close_pct"]), 0)         # fell, and the pick was a sell
            self.assertEqual(rows["UP"]["our_fate"], "A_PLUS:late_vwap_extension")
            self.assertEqual(rows["UP"]["first_signal"], "09:40")
            self.assertEqual(rows["DOWN"]["our_fate"], "NO_SIGNAL")
            self.assertIn("(default)", rows["DOWN"]["time"])                          # no listing time given: measured from 09:25
            self.assertIn("opt_close_pct", rows["UP"])
            md = (root / "data" / "external_picks" / "review.md").read_text(encoding="utf-8")
            self.assertIn("External picks", md)
            self.assertIn("QuantElite", md)

    def test_no_picks_no_candles(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(ep.run("2026-10-16", Path(tmp)))
            ep.add("2026-10-16", "X", "UP", "BULLISH", root=Path(tmp))
            self.assertIsNone(ep.run("2026-10-16", Path(tmp)))                        # picks but no candle file yet


if __name__ == "__main__":
    unittest.main()
