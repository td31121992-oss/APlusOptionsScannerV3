import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import filing_text
import gap_watch as gw
import stock_study as ss

IST = timezone(timedelta(hours=5, minutes=30))


class ScoreTests(unittest.TestCase):
    def test_score_and_strength(self):
        self.assertEqual(gw.score(0, None), (0.0, 0, "", 0.0))
        self.assertEqual(gw.score(0, 0.95)[:3], (-0.5, -1, "WEAK"))                     # closed at the high: a weak expectation of a gap down
        self.assertEqual(gw.score(0, 0.05)[:3], (0.5, 1, "WEAK"))
        self.assertEqual(gw.score(0, 0.5)[:3], (0.0, 0, ""))
        self.assertEqual(gw.score(1, 0.5)[:3], (1.0, 1, "STRONG"))                      # good news on its own is strong
        self.assertEqual(gw.score(1, 0.95)[:3], (0.5, 1, "WEAK"))                       # good news after a stretched close: mixed, weak
        self.assertEqual(gw.score(-1, 0.95)[:3], (-1.5, -1, "STRONG"))                  # bad news and a stretched close agree


def ann(root, rows):
    p = root / "data" / "news_intelligence"
    p.mkdir(parents=True, exist_ok=True)
    (p / "announcements.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    gw._ANN.update(mtime=None, rows=[])
    filing_text._FACTS.update(mtime=None, path=None, data={})


def when(day, hh, mm):
    return datetime.fromisoformat(f"{day}T{hh:02d}:{mm:02d}:00+05:30").isoformat()


class FilingViewTests(unittest.TestCase):
    def test_window_and_latest_view(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ann(root, [{"id": "1", "symbol": "AAA", "desc": "Bagging/Receiving of orders/contracts", "text": "received order worth Rs. 450 crore", "published_at": when("2026-10-22", 17, 0)},
                       {"id": "2", "symbol": "AAA", "desc": "Credit Rating", "text": "downgraded the rating", "published_at": when("2026-10-23", 8, 0)},
                       {"id": "3", "symbol": "BBB", "desc": "Bagging/Receiving of orders/contracts", "text": "order worth Rs. 10 crore", "published_at": when("2026-10-22", 11, 0)},      # during the session: before the window
                       {"id": "4", "symbol": "CCC", "desc": "Bagging/Receiving of orders/contracts", "text": "order worth Rs. 10 crore", "published_at": when("2026-10-23", 9, 30)}])           # after the open: after the window
            start, end = gw._window("2026-10-22", "2026-10-23")
            self.assertEqual(gw.filing_view(root, "AAA", start, end), (-1, "RATING_DOWN"))     # the later filing with a view wins
            self.assertEqual(gw.filing_view(root, "BBB", start, end), (0, ""))
            self.assertEqual(gw.filing_view(root, "CCC", start, end), (0, ""))
            self.assertEqual(gw.filing_view(root, "ZZZ", start, end), (0, ""))


def study_rows(days, syms=70, special=None):
    out = []
    for i, d in enumerate(days):
        for k in range(syms):
            s = f"S{k}"
            sp = (special or {}).get((d, s), {})
            out.append({"day": d, "symbol": s, "pattern": sp.get("pattern", "CHOPPY"), "gap_pct": sp.get("gap_pct", 0.1), "range_pct": 1.5, "move_pct": 0.0, "close_pos": sp.get("close_pos", 0.5),
                        "efficiency": 0.2, "ib_up": 0.0, "ib_dn": 0.0, "orb": 0, "orb_held": "", "hi_hour": 10, "lo_hour": 12, "spark": ""})
    return out


class LedgerTests(unittest.TestCase):
    def test_ledger_scores_with_prior_information_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            days = ["2026-10-21", "2026-10-22", "2026-10-23"]
            special = {("2026-10-21", "S1"): {"close_pos": 0.97}, ("2026-10-22", "S1"): {"gap_pct": -1.2},            # closed at the high on the 21st, gapped down 1.2 % on the 22nd
                       ("2026-10-22", "S2"): {"close_pos": 0.02, "pattern": "LATE_SURGE"}, ("2026-10-23", "S2"): {"gap_pct": 1.5}}
            ss.write_daily(root, study_rows(days, special=special))
            ann(root, [{"id": "9", "symbol": "S3", "desc": "Bagging/Receiving of orders/contracts", "text": "order worth Rs. 450 crore", "published_at": when("2026-10-21", 18, 0)}])
            rows = gw.build_ledger(root)
            by = {(r["day"], r["symbol"]): r for r in rows}
            a = by[("2026-10-22", "S1")]
            self.assertEqual((a["dir"], a["strength"], a["stretch"]), (-1, "WEAK", -0.5))
            self.assertAlmostEqual(a["idio_gap"], -1.3, places=2)                          # -1.2 % against the median stock's +0.1 %
            b = by[("2026-10-23", "S2")]
            self.assertEqual((b["dir"], b["late_surge"]), (1, 1))
            self.assertAlmostEqual(b["idio_gap"], 1.4, places=2)
            c = by[("2026-10-22", "S3")]
            self.assertEqual((c["dir"], c["strength"], c["filing"], c["kind"]), (1, "STRONG", 1, "ORDER_WIN"))     # evening order filing, seen before the open
            self.assertNotIn(("2026-10-21", "S1"), by)                                     # the first day has no previous session
            out = gw.review(root)
            text = out.read_text(encoding="utf-8")
            self.assertIn("| All watched |", text)
            self.assertIn("Filing view good (+1) | 1 |", text)
            self.assertTrue((root / "data" / "gap_watch" / "ledger.csv").exists())

    def test_nothing_without_a_study(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(gw.review(Path(tmp)))


class TagTests(unittest.TestCase):
    def test_tags_for_today(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            days = ["2026-10-21", "2026-10-22"]
            ss.write_daily(root, study_rows(days, special={("2026-10-22", "S1"): {"close_pos": 0.96, "pattern": "LATE_SURGE"}}))
            ss.save_profiles(root, ss.read_daily(root))
            ann(root, [{"id": "7", "symbol": "S1", "desc": "Credit Rating", "text": "downgraded the rating", "published_at": when("2026-10-22", 19, 0)}])
            now = datetime(2026, 10, 23, 10, 0, tzinfo=IST)
            put, call = gw.tags("S1", "BEARISH", now, root), gw.tags("S1", "BULLISH", now, root)
            self.assertEqual((put["gw_dir"], put["gw_strength"], put["gw_with_trade"], put["gw_big_risk"]), (-1, "STRONG", 1, 1))
            self.assertEqual(call["gw_with_trade"], -1)
            self.assertEqual(gw.tags("S2", "BULLISH", now, root)["gw_dir"], 0)
            self.assertEqual(gw.tags("S1", "BULLISH", datetime(2026, 10, 22, 11, 0, tzinfo=IST), root), {})   # the profile's latest day is today: no 'previous session' to watch from
            self.assertEqual(gw.tags("ZZZ", "BULLISH", now, root), {})


if __name__ == "__main__":
    unittest.main()
