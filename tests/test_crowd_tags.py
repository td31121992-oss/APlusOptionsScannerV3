import unittest
from pathlib import Path
from unittest import mock

import derived_tags as dt


def t(i, hhmm, sym="A", side="CE", day="2026-11-12"):
    return {"paper_trade_id": i, "symbol": sym, "option_type": side, "entry_time": f"{day}T{hhmm}:00"}


class CrowdTagTests(unittest.TestCase):
    def test_fourth_same_sector_same_side_trade_is_crowded_and_early_entries_flagged(self):
        labels = {"A": "NBFC", "B": "NBFC", "C": "NBFC", "D": "NBFC", "E": "Auto"}
        trades = [t(1, "09:28", "A"), t(2, "09:29", "B"), t(3, "09:36", "C"), t(4, "09:40", "D"), t(5, "09:41", "E"), t(6, "09:50", "D", "PE"), t(7, "09:51", "A", day="2026-11-13")]
        with mock.patch.object(dt, "sector_labels", return_value=labels), mock.patch.dict(dt._LABELS, {}, clear=True):
            dt.crowd_tags(trades, Path("x"))
        self.assertEqual([x["dx_crowd4"] for x in trades], [False, False, False, True, False, False, False])   # only the 4th NBFC call of 12 Nov; PE and next day count separately
        self.assertEqual([x["dx_early0935"] for x in trades], [True, True, False, False, False, False, False])

    def test_unknown_sector_gives_none(self):
        trades = [t(1, "10:00", "ZZZ")]
        with mock.patch.object(dt, "sector_labels", return_value={}), mock.patch.dict(dt._LABELS, {}, clear=True):
            dt.crowd_tags(trades, Path("y"))
        self.assertIsNone(trades[0]["dx_crowd4"])


if __name__ == "__main__":
    unittest.main()
