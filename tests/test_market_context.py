from __future__ import annotations

import csv
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

import market_context as mc

IST = ZoneInfo("Asia/Kolkata")


def _qm(nifty_ltp=22776.1, nifty_prev=22700.0, nifty_open=22650.0, vix=13.6, vix_prev=14.0):
    return {mc.INDEX_SEGMENT: {
        "13": {"last_price": nifty_ltp, "ohlc": {"open": nifty_open, "close": nifty_prev}},
        "25": {"last_price": 55128.4, "ohlc": {"open": 54901.3, "close": 55000.0}},
        "21": {"last_price": vix, "ohlc": {"open": 14.78, "close": vix_prev}},
    }}


class RegimeTests(unittest.TestCase):
    def test_classification(self) -> None:
        self.assertEqual(mc.classify(0.5, 0.2, 0.3), "BULL")
        self.assertEqual(mc.classify(-0.5, -0.1, 0.3), "BEAR")
        self.assertEqual(mc.classify(0.1, 0.0, 0.3), "CHOP")
        self.assertEqual(mc.classify(0.6, -0.2, 0.3), "CHOP")     # up vs prev close but fading below open
        self.assertEqual(mc.classify(None, None, 0.3), "UNKNOWN")

    def test_summarize_computes_percentages_and_regime(self) -> None:
        ctx = mc.summarize(_qm(nifty_ltp=22814.0, nifty_prev=22700.0, nifty_open=22750.0))
        self.assertAlmostEqual(ctx["nifty_pct_prev"], 0.502, places=2)
        self.assertEqual(ctx["regime"], "BULL")
        self.assertAlmostEqual(ctx["vix_pct_prev"], (13.6 - 14.0) / 14.0 * 100, places=1)

    def test_summarize_handles_missing_index_data(self) -> None:
        self.assertIsNone(mc.summarize({"NSE_EQ": {}}))
        self.assertIsNone(mc.summarize({}))
        self.assertEqual(mc.summarize({mc.INDEX_SEGMENT: {"13": {}}})["regime"], "UNKNOWN")


class ModeTests(unittest.TestCase):
    def test_default_mode_is_shadow_and_never_blocks(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("APLUS_MARKET_REGIME_MODE", None)
            self.assertEqual(mc.mode(), "SHADOW")
            self.assertTrue(mc.direction_allowed("BEAR", "BULLISH"))
            self.assertTrue(mc.direction_allowed("BULL", "BEARISH"))

    def test_enforce_blocks_counter_trend_only(self) -> None:
        self.assertFalse(mc.direction_allowed("BEAR", "BULLISH", "ENFORCE"))
        self.assertFalse(mc.direction_allowed("BULL", "BEARISH", "ENFORCE"))
        self.assertTrue(mc.direction_allowed("BEAR", "BEARISH", "ENFORCE"))
        self.assertTrue(mc.direction_allowed("BULL", "BULLISH", "ENFORCE"))
        self.assertTrue(mc.direction_allowed("CHOP", "BULLISH", "ENFORCE"))
        self.assertTrue(mc.direction_allowed("UNKNOWN", "BEARISH", "ENFORCE"))   # unknown never blocks

    def test_invalid_mode_falls_back_to_shadow(self) -> None:
        with mock.patch.dict(os.environ, {"APLUS_MARKET_REGIME_MODE": "banana"}):
            self.assertEqual(mc.mode(), "SHADOW")

    def test_off_mode_requests_no_extra_instruments(self) -> None:
        req: dict = {"NSE_EQ": [1]}
        with mock.patch.dict(os.environ, {"APLUS_MARKET_REGIME_MODE": "OFF"}):
            mc.add_to_request(req)
        self.assertNotIn(mc.INDEX_SEGMENT, req)
        with mock.patch.dict(os.environ, {"APLUS_MARKET_REGIME_MODE": "SHADOW"}):
            mc.add_to_request(req)
        self.assertEqual(req[mc.INDEX_SEGMENT], [13, 25, 21])


class RecordTests(unittest.TestCase):
    def test_record_appends_rows_with_header_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            when = datetime(2026, 10, 7, 10, 0, tzinfo=IST)
            ctx = mc.summarize(_qm())
            mc.record(ctx, when, tmp)
            mc.record(ctx, when, tmp)
            rows = list(csv.DictReader(Path(tmp, "market_context", "2026-10-07.csv").open(encoding="utf-8")))
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["regime"], ctx["regime"])

    def test_record_never_raises_on_bad_path(self) -> None:
        mc.record({"regime": "X"}, datetime.now(IST), "Z:\\definitely\\not\\writable\\???")


if __name__ == "__main__":
    unittest.main()
