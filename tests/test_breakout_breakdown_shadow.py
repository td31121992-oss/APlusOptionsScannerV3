import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from breakout_breakdown_shadow import (
    MinuteBar, ThreeMinuteBar, aggregate_three_minute_bars, same_slot_relative_volume,
    classify_breakout_breakdown, evaluate_forward_outcome, append_shadow_record,
)

IST = ZoneInfo("Asia/Kolkata")
BASE = datetime(2026, 10, 25, 9, 15, tzinfo=IST)

def m(i, o, h, lo, c, v=100):
    return MinuteBar(BASE + timedelta(minutes=i), o, h, lo, c, v)

def b(i, o, h, lo, c, v=300):
    return ThreeMinuteBar(BASE + timedelta(minutes=3*i), o, h, lo, c, v)

class AggregationTests(unittest.TestCase):
    def test_ohlcv_aggregation(self):
        out = aggregate_three_minute_bars([m(0,100,102,99,101,10),m(1,101,103,100,102,20),
            m(2,102,104,101,103,30),m(3,103,104,102,103,40),m(4,103,105,102,104,50),m(5,104,106,103,105,60)])
        self.assertEqual(len(out),2)
        self.assertEqual((out[0].open,out[0].high,out[0].low,out[0].close,out[0].volume),(100,104,99,103,60))
        self.assertEqual(out[1].volume,150)

    def test_missing_minute_drops_bucket(self):
        out=aggregate_three_minute_bars([m(0,100,101,99,100),m(2,100,102,99,101),m(3,101,103,100,102),m(4,102,104,101,103),m(5,103,105,102,104)])
        self.assertEqual(len(out),1)
        self.assertEqual(out[0].timestamp,BASE+timedelta(minutes=3))

    def test_duplicate_timestamp_keeps_last(self):
        out=aggregate_three_minute_bars([m(0,100,101,99,100),m(1,100,101,99,100),m(2,100,101,99,100),m(1,100,103,99,102)])
        self.assertEqual((out[0].high,out[0].volume),(103,300))

class ClassifierTests(unittest.TestCase):
    def test_rvol_requires_history(self):
        self.assertIsNone(same_slot_relative_volume(600,[100,110,90,100],minimum_sessions=5))
        self.assertEqual(same_slot_relative_volume(600,[100,110,90,100,100],minimum_sessions=5),6)

    def test_bullish_signal_never_authorizes_trade(self):
        bars=[b(i,100+i*.1,101+i*.1,99+i*.1,100.5+i*.1) for i in range(5)]+[b(5,101,104,100.8,103.8,900)]
        s=classify_breakout_breakdown(symbol="tcs",bars=bars,relative_volume=2,vwap=102)
        self.assertEqual((s.direction,s.verdict),("BULLISH","SHADOW_CONFIRMED"))
        self.assertTrue(s.shadow_only); self.assertFalse(s.trade_authorized)

    def test_bearish_signal(self):
        bars=[b(i,100-i*.1,101-i*.1,99-i*.1,99.5-i*.1) for i in range(5)]+[b(5,99.5,99.7,96,96.2,900)]
        s=classify_breakout_breakdown(symbol="TCS",bars=bars,relative_volume=2,vwap=98.5)
        self.assertEqual((s.direction,s.verdict),("BEARISH","SHADOW_CONFIRMED"))

    def test_missing_rvol_blocks_confirmation(self):
        bars=[b(i,100,101,99,100.5) for i in range(5)]+[b(5,100.5,104,100,103.8)]
        self.assertEqual(classify_breakout_breakdown(symbol="TCS",bars=bars,relative_volume=None,vwap=101).verdict,"DATA_INSUFFICIENT")

    def test_low_rvol_rejected(self):
        bars=[b(i,100,101,99,100.5) for i in range(5)]+[b(5,100.5,104,100,103.8)]
        self.assertEqual(classify_breakout_breakdown(symbol="TCS",bars=bars,relative_volume=1,vwap=101).verdict,"LOW_VOLUME_REJECT")

    def test_chase_extension_rejected(self):
        bars=[b(i,100,101,99,100.5) for i in range(5)]+[b(5,100.5,108,100,107.8)]
        self.assertEqual(classify_breakout_breakdown(symbol="TCS",bars=bars,relative_volume=2,vwap=100).verdict,"CHASE_RISK_REJECT")

    def test_insufficient_bars(self):
        self.assertEqual(classify_breakout_breakdown(symbol="TCS",bars=[b(0,100,101,99,100)],relative_volume=2,vwap=100).verdict,"DATA_INSUFFICIENT")

    def test_outcome_and_jsonl_ledger(self):
        bars=[b(i,100,101,99,100.5) for i in range(5)]+[b(5,100.5,104,100,103.8)]
        s=classify_breakout_breakdown(symbol="TCS",bars=bars,relative_volume=2,vwap=101)
        out=evaluate_forward_outcome(signal=s,entry_price=103,future_bars=[b(6,103,106,102,105),b(7,105,106,101,102)],horizon_bars=2)
        self.assertEqual(out["outcome"],"OBSERVED")
        self.assertAlmostEqual(out["mfe_percent"],(106/103-1)*100,places=3)
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"shadow"/"events.jsonl"
            append_shadow_record(path,s,out)
            row=json.loads(path.read_text(encoding="utf-8"))
        self.assertTrue(row["shadow_only"]); self.assertFalse(row["trade_authorized"])
        self.assertTrue(row["outcome"]["horizon_complete"])

if __name__ == "__main__":
    unittest.main()
