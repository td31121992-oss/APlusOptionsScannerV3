import csv
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import news_spike_exception as nse

IST = timezone(timedelta(hours=5, minutes=30))
NOW = datetime(2026, 10, 26, 14, 30, 0, tzinfo=IST)
FEATS = {"recent_move_15m_percent": 5.2, "recent_relative_volume_15m": 9.0, "chase_risk_score": 60.0}


def root_with(rows):
    d = tempfile.mkdtemp()
    p = Path(d) / "data" / "news_intelligence" / "announcements.jsonl"
    p.parent.mkdir(parents=True)
    p.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    nse._ANN.update(mtime=None, path=None, rows=[])
    nse._LAST.clear()
    return Path(d)


RESULTS = {"symbol": "AAA", "desc": "Outcome of Board Meeting", "text": "financial results for the period", "published_at": "2026-10-26T14:27:42+05:30", "severity": "HIGH"}


class CheckTests(unittest.TestCase):
    def test_confirmed_news_spike(self):
        root = root_with([RESULTS])
        hit = nse.check("AAA", "BULLISH", NOW, FEATS, root)
        self.assertEqual((hit["move_15m_pct"], hit["volume_x"]), (5.2, 9.0))
        self.assertAlmostEqual(hit["filing_min_ago"], 2.3, places=1)

    def test_naive_clock_is_treated_as_indian_time(self):
        root = root_with([RESULTS])
        self.assertIsNotNone(nse.check("AAA", "BULLISH", NOW.replace(tzinfo=None), FEATS, root))

    def test_each_condition_is_needed(self):
        root = root_with([RESULTS])
        self.assertIsNone(nse.check("AAA", "BULLISH", NOW, {**FEATS, "recent_move_15m_percent": 1.0}, root))      # no spike
        self.assertIsNone(nse.check("AAA", "BULLISH", NOW, {**FEATS, "recent_relative_volume_15m": 2.0}, root))   # no volume
        self.assertIsNone(nse.check("AAA", "BEARISH", NOW, FEATS, root))                                          # the spike is up, the candidate is a put
        self.assertIsNone(nse.check("BBB", "BULLISH", NOW, FEATS, root))                                           # no filing for that stock
        old = root_with([{**RESULTS, "published_at": "2026-10-26T13:50:00+05:30"}])
        self.assertIsNone(nse.check("AAA", "BULLISH", NOW, FEATS, old))                                            # filing older than 20 minutes
        other = root_with([{**RESULTS, "desc": "Allotment of Securities", "text": "allotment of shares", "severity": "LOW"}])
        self.assertIsNone(nse.check("AAA", "BULLISH", NOW, FEATS, other))                                          # not results, not HIGH


class ObserveTests(unittest.TestCase):
    def test_writes_once_per_five_minutes_and_never_raises(self):
        root = root_with([RESULTS])
        self.assertTrue(nse.observe(root, "AAA", "BULLISH", NOW, 1500.0, FEATS, 7.2, 6.0))
        self.assertFalse(nse.observe(root, "AAA", "BULLISH", NOW + timedelta(seconds=60), 1510.0, FEATS, 7.2, 6.0))
        self.assertTrue(nse.observe(root, "AAA", "BULLISH", NOW + timedelta(seconds=301), 1520.0, FEATS, 7.3, 6.0))
        rows = list(csv.DictReader((root / "data" / "news_spike_exception" / "2026-10-26.csv").open(encoding="utf-8")))
        self.assertEqual(len(rows), 2)
        self.assertEqual((rows[0]["ext_atr"], rows[0]["chase"]), ("7.2", "60.0"))
        self.assertFalse(nse.observe(Path("/nonexistent/path"), "AAA", "BULLISH", NOW, 1.0, None, 1, 1))          # bad inputs: False, no exception


if __name__ == "__main__":
    unittest.main()
