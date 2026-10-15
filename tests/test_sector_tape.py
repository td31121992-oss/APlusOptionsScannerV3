import os
import tempfile
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

os.environ["TELEGRAM_ENABLED"] = "false"

import sector_tape
from tests.test_journal_costs_and_session_end import _journal, _open_trade

IST = ZoneInfo("Asia/Kolkata")


class Feed:
    def __init__(self):
        self.price = 100.0

    def __call__(self):
        return {29: {"ltp": self.price}}


class SectorTapeTests(unittest.TestCase):
    def test_tags_show_fade_from_high_and_15m_change(self):
        feed = Feed()
        tape = sector_tape.SectorTape(fetch=feed)
        tape.update(0, force=True)
        feed.price = 101.5
        tape.update(900, force=True)
        feed.price = 100.9
        tape.update(1000, force=True)
        tags = tape.tags_for("IT", "BULLISH")
        self.assertEqual(tags["sec_idx"], "IT")
        self.assertAlmostEqual(tags["sec_from_extreme_pct"], (101.5 - 100.9) / 101.5 * 100, places=2)
        self.assertEqual(tags["sec_state"], "FADING")                   # 0.59% off the best is >= 0.4%

    def test_unknown_sector_gives_no_tags(self):
        tape = sector_tape.SectorTape(fetch=Feed())
        tape.update(0, force=True)
        self.assertEqual(tape.tags_for("Nonsense", "BULLISH"), {})


class SecFadeShadowTests(unittest.TestCase):
    def test_fires_once_when_sector_fades_and_stock_is_below_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            j = _journal(tmp, "2026-10-14", [_open_trade(underlying_entry=100.0, option_type="CE",
                                                         entry_time="2026-10-14T10:00:00+05:30", option_stop=7.0, option_target1=50.0)])
            t = j.trades[0]
            t.update({"sec_idx": "IT", "sec_entry_ltp": 100.0, "direction": "BULLISH", "last_option_price": 10.0})
            when = datetime(2026, 10, 14, 10, 5, tzinfo=IST)
            j.record_sector_fade({"IT": 101.0}, when)
            self.assertEqual(t["sec_best_ltp"], 101.0)
            t["stock_move_fav_pct"] = 0.2
            j.record_sector_fade({"IT": 100.5}, when)                    # 0.5% off best but the stock is still above entry
            self.assertNotIn("shadow_secfade_exit_at", t)
            t["stock_move_fav_pct"] = -0.3
            t["last_option_price"] = 9.4
            j.record_sector_fade({"IT": 100.4}, when)
            self.assertEqual(t["shadow_secfade_exit_price"], 9.4)
            self.assertEqual(t["status"], "OPEN")


if __name__ == "__main__":
    unittest.main()
