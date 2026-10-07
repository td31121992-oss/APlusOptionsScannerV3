from __future__ import annotations

import unittest
from datetime import date

import daily_movers_telegram as dm


class MoversTests(unittest.TestCase):
    ROWS = [{"symbol": s, "ltp": p, "previous_close": q} for s, p, q in (
        ("AAA", 110, 100), ("BBB", 95, 100), ("CCC", 103, 100), ("DDD", 90, 100), ("EEE", 101, 100),
        ("FFF", 99, 100), ("GGG", 120, 100), ("HHH", 80, 100), ("III", 100, 100), ("JJJ", 0, 100), ("KKK", 50, 0))]

    def test_ranking_drops_bad_rows_and_zero_changes(self) -> None:
        g, l = dm.compute_movers(self.ROWS)
        self.assertEqual([x["symbol"] for x in g], ["GGG", "AAA", "CCC", "EEE"])        # only positive, best first
        self.assertEqual([x["symbol"] for x in l], ["HHH", "DDD", "BBB", "FFF"])        # only negative, worst first
        self.assertAlmostEqual(g[0]["pct"], 20.0)

    def test_message_format(self) -> None:
        g, l = dm.compute_movers(self.ROWS)
        text = dm.format_message(date(2026, 10, 8), g, l, 9)
        self.assertIn("08 Oct 2026", text)
        self.assertIn("1. GGG  ₹120.00  (+20.00%)", text)
        self.assertIn("1. HHH  ₹80.00  (-20.00%)", text)
        self.assertIn("TOP 5 GAINERS", text)
        self.assertIn("TOP 5 LOSERS", text)
        self.assertTrue(text.rstrip().endswith("Darpan Bobhate (F&O Trader with 7 years of experience)"))

    def test_empty_sides_do_not_crash(self) -> None:
        text = dm.format_message(date(2026, 10, 8), [], [], 0)
        self.assertEqual(text.count("(none)"), 2)


class CardTests(unittest.TestCase):
    def test_picture_card_is_written_as_a_portrait_png(self) -> None:
        import tempfile
        from pathlib import Path

        from PIL import Image

        g, l = dm.compute_movers(MoversTests.ROWS)
        with tempfile.TemporaryDirectory() as tmp:
            path = dm.render_card(date(2026, 10, 8), g, l, Path(tmp, "card.png"))
            with Image.open(path) as img:
                self.assertEqual(img.size, (1080, 1920))


if __name__ == "__main__":
    unittest.main()
