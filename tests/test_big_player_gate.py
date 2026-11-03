import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

for k in list(os.environ):
    if k.startswith("APLUS_BIGPLAYER"):
        os.environ.pop(k)

import big_player_gate as bg
import big_prints as bp

IST = timezone(timedelta(hours=5, minutes=30))
NOW = datetime(2026, 10, 22, 10, 30, tzinfo=IST)


def write_snapshot(root, stocks, day="2026-10-22"):
    p = Path(root, "data", "ticks")
    p.mkdir(parents=True, exist_ok=True)
    (p / "big_prints_live.json").write_text(json.dumps({"day": day, "updated": "10:30:00", "tape": [], "stocks": stocks}), encoding="utf-8")
    bp._CACHE.update(mtime=None, data=None)


def stock(net15, net=0.0, n15=5):
    return {"ltp": 100, "buy_cr": 0, "sell_cr": 0, "net_cr": net, "n_buy": 1, "n_sell": 1, "net15_cr": net15, "n15": n15, "last": None}


class GateTests(unittest.TestCase):
    def test_mode_and_decision_thresholds(self):
        self.assertEqual(bg.mode(), "SHADOW")
        with mock.patch.dict(os.environ, {"APLUS_BIGPLAYER_GATE_MODE": "enforce"}):
            self.assertEqual(bg.mode(), "ENFORCE")
        with mock.patch.dict(os.environ, {"APLUS_BIGPLAYER_GATE_MODE": "x"}):
            self.assertEqual(bg.mode(), "SHADOW")
        self.assertEqual(bg.decide(1.0, 5), ("WITH", "WITH_BIG_PLAYERS"))
        self.assertEqual(bg.decide(-1.0, 5), ("AGAINST", "AGAINST_BIG_PLAYERS"))
        self.assertEqual(bg.decide(-0.1, 5), ("NONE", "NO_BIG_PRINTS"))            # too small a net
        self.assertEqual(bg.decide(-5.0, 1), ("NONE", "NO_BIG_PRINTS"))            # too few prints
        with mock.patch.dict(os.environ, {"APLUS_BIGPLAYER_AGAINST_CR": "0.05", "APLUS_BIGPLAYER_MIN_PRINTS": "1"}):
            self.assertEqual(bg.decide(-0.1, 1)[0], "AGAINST")

    def test_direction_flips_the_sign(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_snapshot(tmp, {"AAA": stock(net15=2.0, net=5.0), "BBB": stock(net15=-3.0, net=-1.0)})
            call_on_buying = bg.evaluate("AAA", "BULLISH", NOW, Path(tmp))
            self.assertEqual((call_on_buying["bp_align"], call_on_buying["bp_ok"], call_on_buying["bp_net15_dir_cr"]), ("WITH", 1, 2.0))
            put_on_buying = bg.evaluate("AAA", "BEARISH", NOW, Path(tmp))             # a put while big players are buying
            self.assertEqual((put_on_buying["bp_align"], put_on_buying["bp_ok"], put_on_buying["bp_net15_dir_cr"], put_on_buying["bp_reason"]), ("AGAINST", 0, -2.0, "AGAINST_BIG_PLAYERS"))
            put_on_selling = bg.evaluate("BBB", "BEARISH", NOW, Path(tmp))
            self.assertEqual((put_on_selling["bp_align"], put_on_selling["bp_ok"], put_on_selling["bp_net_dir_cr"]), ("WITH", 1, 1.0))
            call_on_selling = bg.evaluate("BBB", "BULLISH", NOW, Path(tmp))
            self.assertEqual(call_on_selling["bp_ok"], 0)

    def test_missing_data_never_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(bg.evaluate("AAA", "BULLISH", NOW, Path(tmp)), {"bp_ok": 1, "bp_reason": "NO_DATA"})
            write_snapshot(tmp, {"AAA": stock(net15=-9.0)}, day="2026-10-21")           # yesterday's file is not today's data
            self.assertEqual(bg.evaluate("AAA", "BULLISH", NOW, Path(tmp))["bp_reason"], "NO_DATA")
            write_snapshot(tmp, {"AAA": stock(net15=2.0)})
            self.assertEqual(bg.evaluate("ZZZ", "BULLISH", NOW, Path(tmp))["bp_reason"], "NO_DATA")


if __name__ == "__main__":
    unittest.main()
