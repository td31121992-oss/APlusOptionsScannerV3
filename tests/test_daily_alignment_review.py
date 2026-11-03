import tempfile
import unittest
from pathlib import Path

import daily_alignment_review as dar


def rising(n=60, start=100.0, step=1.0):
    rows = []
    for i in range(n):
        d = f"2026-{8 + (i // 30):02d}-{(i % 30) + 1:02d}"
        c = start + step * i
        rows.append((d, c - 0.3, c + 0.5, c - 0.6, c, 1000.0))
    return rows


class DailyAlignmentTests(unittest.TestCase):
    def test_score_signs(self):
        up = rising(60, 100, 1.0)
        down = rising(60, 200, -1.0)
        self.assertGreater(dar.daily_score(up, "2026-10-01"), 0.6)
        self.assertLess(dar.daily_score(down, "2026-10-01"), -0.6)
        self.assertIsNone(dar.daily_score(up[:10], "2026-10-01"))                # too little history
        self.assertIsNone(dar.daily_score(up, "2026-08-02"))                     # nothing before that day to use

    def test_rows_are_signed_by_direction(self):
        hist = {"UP": rising(60, 100, 1.0)}
        sigs = {"2026-10-05": [{"symbol": "UP", "dir": "BULLISH", "fate": "TRADED", "ready": "09:30", "close": 5, "best": 20},
                               {"symbol": "UP", "dir": "BEARISH", "fate": "V2_BLOCKED", "ready": "09:31", "close": -5, "best": 2},
                               {"symbol": "NOHIST", "dir": "BULLISH", "fate": "TRADED", "ready": "09:30", "close": 1}]}
        rows = dar.build_rows(sigs, hist)
        self.assertEqual(len(rows), 2)
        self.assertGreater(rows[0]["daily_signed"], 0.5)
        self.assertLess(rows[1]["daily_signed"], -0.5)

    def test_report(self):
        rows = [{"day": f"2026-10-0{1 + i % 5}", "symbol": "A", "dir": "BULLISH", "ready": "09:30", "fate": "TRADED", "close": 4.0 if i % 2 else -2.0, "best": 20,
                 "daily_signed": 0.95 if i % 3 == 0 else 0.1, "blocked": i % 2} for i in range(30)]
        with tempfile.TemporaryDirectory() as tmp:
            path = dar.write_report(rows, Path(tmp))
            text = path.read_text(encoding="utf-8")
            self.assertIn("fully aligned", text)
            self.assertIn("Override test", text)


if __name__ == "__main__":
    unittest.main()
