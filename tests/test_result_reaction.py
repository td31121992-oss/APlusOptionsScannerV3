import csv
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import result_reaction as rr
import result_reaction_review as rv

IST = timezone(timedelta(hours=5, minutes=30))


def at(h, m, d=23):
    return datetime(2026, 10, d, h, m, tzinfo=IST)


def write_announcements(root, items):
    p = root / "data" / "news_intelligence"
    p.mkdir(parents=True, exist_ok=True)
    (p / "announcements.jsonl").write_text("\n".join(json.dumps(i) for i in items) + "\n", encoding="utf-8")
    rr._RES.update(mtime=None, path=None)
    rr._STATE.update(day=None, latest={}, first={}, logged={})


RES = {"symbol": "COLPAL", "desc": "Outcome of Board Meeting", "text": "Outcome of Board Meeting held on October 22, 2026", "published_at": "2026-10-22T16:38:00+05:30"}
NOISE = {"symbol": "COLPAL", "desc": "Copy of Newspaper Publication", "text": "Copy of Newspaper Publication", "published_at": "2026-10-23T08:00:00+05:30"}


class EvaluateTests(unittest.TestCase):
    def test_colpal_like_reaction_is_confirmed_without_a_gap(self):
        # 23 Oct 09:50: 1639.4 vs previous close 1686 (-2.76%), heavy volume, below VWAP 1665, previous-day low 1677.6 broken
        e = rr.evaluate(1639.4, 1686.0, 250_000, 400_000, 1665.0, 1719.9, 1677.6, at(9, 50), 17.2)
        self.assertEqual((e["direction"], e["confirmed"], e["pd_break"]), ("BEARISH", 1, 1))
        self.assertAlmostEqual(e["move_prev_pct"], -2.76, places=2)
        self.assertGreaterEqual(e["rvol"], 3.0)
        self.assertLess(e["vs_vwap_pct"], 0)

    def test_each_condition_is_needed(self):
        ok = dict(ltp=1639.4, prev_close=1686.0, volume=250_000, avg_vol20=400_000, vwap=1665.0, pdh=1719.9, pdl=1677.6, now=at(9, 50), age_h=17.2)
        self.assertEqual(rr.evaluate(**ok)["confirmed"], 1)
        self.assertEqual(rr.evaluate(**{**ok, "age_h": None})["confirmed"], 0)                       # results not out
        self.assertEqual(rr.evaluate(**{**ok, "volume": 30_000})["confirmed"], 0)                    # normal volume
        self.assertEqual(rr.evaluate(**{**ok, "ltp": 1670.0})["confirmed"], 0)                       # only -0.9% from the previous close
        self.assertEqual(rr.evaluate(**{**ok, "vwap": 1620.0})["confirmed"], 0)                      # a fall but still above VWAP
        up = rr.evaluate(**{**ok, "ltp": 1720.0, "vwap": 1700.0, "pdh": 1710.0})
        self.assertEqual((up["direction"], up["confirmed"], up["pd_break"]), ("BULLISH", 1, 1))     # a rise above VWAP and the previous high counts the same way
        self.assertEqual(rr.evaluate(**{**ok, "avg_vol20": 0})["confirmed"], 0)


class FilingTests(unittest.TestCase):
    def test_results_age_window_and_noise(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_announcements(root, [RES, NOISE, {"symbol": "OLD", "desc": "Financial Results", "text": "", "published_at": "2026-10-10T16:00:00+05:30"}])
            self.assertEqual(rr.results_age_h("COLPAL", at(9, 50), root), 17.2)
            self.assertIsNone(rr.results_age_h("COLPAL", datetime(2026, 10, 24, 12, 0, tzinfo=IST), root))             # 44 hours later: out of the window
            self.assertIsNone(rr.results_age_h("OLD", at(9, 50), root))
            self.assertIsNone(rr.results_age_h("COLPAL", datetime(2026, 10, 22, 10, 0, tzinfo=IST), root))             # before the filing existed
            self.assertIsNone(rr.results_age_h("NOPE", at(9, 50), root))


class ObserveTests(unittest.TestCase):
    def rows(self, ltp):
        return [{"symbol": "COLPAL", "ltp": ltp, "previous_close": 1686.0}, {"symbol": "ABC", "ltp": 100.0, "previous_close": 100.0}]

    def test_observe_logs_changes_and_tags_follow_the_direction(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_announcements(root, [RES])
            ind = {"COLPAL": {"avg_vol20": 400_000, "pdh": 1719.9, "pdl": 1677.6}, "ABC": {"avg_vol20": 1}}
            n1 = rr.observe(self.rows(1670.0), {"COLPAL": 250_000, "ABC": 5}, ind, {"COLPAL": 1665.0}, at(9, 40), root)        # -1%: results out but no reaction yet
            n2 = rr.observe(self.rows(1639.4), {"COLPAL": 250_000, "ABC": 5}, ind, {"COLPAL": 1665.0}, at(9, 50), root)        # reaction confirmed: logged because the state changed
            n3 = rr.observe(self.rows(1639.0), {"COLPAL": 260_000, "ABC": 5}, ind, {"COLPAL": 1665.0}, at(9, 51), root)        # same state, 1 minute later: not logged again
            self.assertEqual((n1, n2, n3), (1, 1, 0))                                                                         # ABC has no results: never watched
            with (root / "data" / "result_reaction" / "2026-10-23.csv").open(encoding="utf-8") as h:
                log = list(csv.DictReader(h))
            self.assertEqual([(r["symbol"], r["confirmed"]) for r in log], [("COLPAL", "0"), ("COLPAL", "1")])
            put = rr.tags("COLPAL", "BEARISH", at(9, 52), root)
            self.assertEqual((put["rx_confirmed"], put["rx_with"], put["rx_reaction"], put["rx_since"]), (1, 1, 1, "09:50"))
            self.assertGreater(put["rx_move_dir_pct"], 2)                                                                       # the fall is "with" a put
            call = rr.tags("COLPAL", "BULLISH", at(9, 52), root)
            self.assertEqual((call["rx_confirmed"], call["rx_with"], call["rx_reaction"]), (1, 0, 0))                           # the same reaction is against a call
            self.assertLess(call["rx_move_dir_pct"], 0)
            self.assertEqual(rr.tags("ABC", "BULLISH", at(9, 52), root), {})
            self.assertEqual(rr.tags("COLPAL", "BEARISH", at(9, 52, d=24), root), {})                                            # another day's state is not used


class ReviewTests(unittest.TestCase):
    def test_state_at_uses_only_bars_completed_before_the_signal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_announcements(root, [RES])
            minutes = [555 + 5 * i for i in range(8)]                                                                           # 09:15 .. 09:50 bars
            candles = {"symbols": {"COLPAL": {"minute": minutes, "open": [1680] * 8, "high": [1682, 1675, 1670, 1660, 1655, 1650, 1645, 1700], "low": [1670, 1665, 1655, 1650, 1640, 1638, 1630, 1600],
                                              "close": [1675, 1668, 1660, 1652, 1645, 1642, 1639, 1650], "volume": [30000] * 7 + [10 ** 7], "pdh": 1719.9, "pdl": 1677.6}}}
            daily = {"COLPAL": [(f"2026-10-{d:02d}", 1700.0, 400_000.0) for d in range(1, 23)]}
            daily["COLPAL"][-1] = ("2026-10-22", 1686.0, 400_000.0)
            ev = rv.state_at("COLPAL", "2026-10-23", "09:50", candles, daily, rr.results_filings(root))                        # the 09:50 bar itself is still forming and must not count
            self.assertAlmostEqual(ev["move_prev_pct"], (1639 / 1686 - 1) * 100, places=2)
            self.assertLess(ev["rvol"], 100)                                                                                   # the 10-million-share forming bar is not in the volume
            self.assertEqual(ev["age_h"], 17.2)
            self.assertIsNone(rv.state_at("COLPAL", "2026-10-23", "09:15", candles, daily, rr.results_filings(root)))           # no completed bar yet
            self.assertIsNone(rv.state_at("ZZZ", "2026-10-23", "09:50", candles, daily, rr.results_filings(root)))

    def test_summary_groups_signals(self):
        rows = [{"day": "d", "symbol": "A", "dir": "BEARISH", "group": "A+ late_vwap_extension", "fate": "x", "ready": "09:50", "ladder_pct": "10", "old_pct": "40", "hold_pct": "60",
                 "state": "reaction confirmed, with the signal", "age_h": 5, "rvol": 5, "move_prev_pct": -3, "vs_vwap_pct": -1, "pd_break": 1},
                {"day": "d", "symbol": "B", "dir": "BULLISH", "group": "TRADED", "fate": "TRADED", "ready": "10:00", "ladder_pct": "-20", "old_pct": "-20", "hold_pct": "-30",
                 "state": "no results in the last 30h", "age_h": "", "rvol": 1, "move_prev_pct": 0.5, "vs_vwap_pct": 0.1, "pd_break": 0}]
        text = "\n".join(rv.summary(rows))
        self.assertIn("reaction confirmed, with the signal", text)
        self.assertIn("| 1 | 100% / +10.0 |", text)
        self.assertIn("Every signal with a confirmed reaction on its side", text)


if __name__ == "__main__":
    unittest.main()
