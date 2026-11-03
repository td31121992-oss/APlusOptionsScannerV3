import json
import tempfile
import unittest
from pathlib import Path

import key_level as kl


def bars(rows):
    return [{"open": o, "high": h, "low": l, "close": c, "volume": v} for o, h, l, c, v in rows]


# opening range 100.0-100.6, then a staircase of higher lows up to and through the previous-day high 101.0
UP = bars([(100, 100.6, 99.9, 100.4, 1000), (100.4, 100.6, 100.2, 100.5, 900), (100.5, 100.6, 100.3, 100.4, 900),
           (100.4, 100.6, 100.3, 100.55, 1000), (100.55, 100.8, 100.4, 100.75, 1200), (100.75, 100.95, 100.55, 100.9, 1300),
           (100.9, 101.2, 100.7, 101.1, 1800)])


class PushTests(unittest.TestCase):
    def test_push_shape_for_a_call(self):
        t = kl.push_tags(UP, "BULLISH", pdh=101.0, pdl=99.0, vol_x=1.8)
        self.assertEqual(t["kl_level"], "PDH+ORH")
        self.assertGreaterEqual(t["kl_higher_lows"], 3)
        self.assertGreater(t["kl_vwap_pct"], 0)
        self.assertTrue(t["kl_push"])

    def test_low_volume_or_no_level_means_no_push(self):
        self.assertFalse(kl.push_tags(UP, "BULLISH", pdh=101.0, vol_x=0.5)["kl_push"])
        far = kl.push_tags(UP, "BULLISH", pdh=105.0, pdl=99.0, vol_x=2.0)
        self.assertIn("ORH", far["kl_level"])                # opening-range high still broken, previous-day high far away
        self.assertNotIn("PDH", far["kl_level"])
        flat = bars([(100, 100.6, 99.4, 100.0, 1000)] * 8)
        self.assertEqual(kl.push_tags(flat, "BULLISH", pdh=102.0, vol_x=2.0)["kl_level"], "")

    def test_bearish_mirrors_with_lower_highs(self):
        down = bars([(100, 100.1, 99.4, 99.6, 1000), (99.6, 99.8, 99.3, 99.5, 900), (99.5, 99.7, 99.3, 99.45, 900),
                     (99.45, 99.6, 99.2, 99.3, 1000), (99.3, 99.45, 99.0, 99.1, 1200), (99.1, 99.25, 98.8, 98.9, 1300),
                     (98.9, 99.0, 98.5, 98.6, 1800)])
        t = kl.push_tags(down, "BEARISH", pdh=101, pdl=98.8, vol_x=1.5)
        self.assertIn("PDL", t["kl_level"])
        self.assertTrue(t["kl_push"])

    def test_too_few_bars_gives_nothing(self):
        self.assertEqual(kl.push_tags(UP[:2], "BULLISH", pdh=101.0), {})


class ReportTests(unittest.TestCase):
    def test_report_groups_by_fate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            day = "2026-10-14"
            sym = {"minute": [555 + 5 * i for i in range(7)], "pdh": 101.0, "pdl": 99.0, "typical": {str(555 + 5 * i): 1000 for i in range(7)},
                   "open": [b["open"] for b in UP], "high": [b["high"] for b in UP], "low": [b["low"] for b in UP],
                   "close": [b["close"] for b in UP], "volume": [b["volume"] * 2 for b in UP]}
            (root / "data" / "pattern_log" / "candles").mkdir(parents=True)
            (root / "data" / "pattern_log" / "candles" / f"{day}.json").write_text(json.dumps({"symbols": {"AAA": sym, "BBB": sym}}))
            mo = root / "data" / "missed_opportunities" / day
            mo.mkdir(parents=True)
            base = {"dir": "BULLISH", "kind": "ATM", "ready": "09:50", "strike": 100, "entry": 5, "best": 40, "worst": -8, "close": 25,
                    "stop_first": False}
            (mo / "option_returns.json").write_text(json.dumps([{**base, "symbol": "AAA", "fate": "TRADED"},
                                                               {**base, "symbol": "BBB", "fate": "V2_BLOCKED:NOT_IN_TOP5"}]))
            path = kl.write(root)
            text = path.read_text(encoding="utf-8")
            self.assertIn("PUSH", text)
            self.assertIn("BBB", text)                       # the push signal we did not trade is listed
            self.assertNotIn("| AAA |", text)                # a traded one is not in the "not traded" list


if __name__ == "__main__":
    unittest.main()
