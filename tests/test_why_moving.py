from __future__ import annotations

import unittest

import why_moving as wm

ROWS = [{"symbol": s, "sector": sec, "ltp": 100.0, "from_prev_close_pct": c, "from_open_pct": c, "gap_pct": 0.1, "range_position_pct": 50}
        for s, sec, c in (("AAA", "Power", -5.0), ("BBB", "Power", -4.5), ("CCC", "Power", -4.8), ("DDD", "Banks", -0.5),
                          ("EEE", "Banks", -0.2), ("FFF", "IT", 0.3), ("GGG", "IT", 0.4))]
PROFILES = {"AAA": {"owner": "Adani family", "name": "Aaa Ltd"}, "BBB": {"owner": "Adani family", "name": "Bbb"}, "CCC": {"owner": "Adani family", "name": "Ccc"}}


class WhyTests(unittest.TestCase):
    def test_group_and_sector_move_is_called_out(self) -> None:
        d = wm.analyse("AAA", ROWS, PROFILES, {}, [], [], [])
        kinds = [x["kind"] for x in d["drivers"]]
        self.assertIn("group", kinds)
        self.assertIn("Mostly a group or sector move", d["summary"])
        self.assertIn("not confirmed causes", d["summary"])

    def test_stock_specific_with_news_and_levels_and_volume_surge(self) -> None:
        rows = [dict(r) for r in ROWS]
        rows[5]["from_prev_close_pct"] = 6.0                       # FFF rises alone
        ann = [{"severity": "HIGH", "desc": "Acquisition", "text": "FFF acquires X", "published_at": "2026-10-08T09:44:00+05:30"}]
        book = [{"time": f"2026-10-08T10:{i:02d}:00+05:30", "ltp": 100 + i, "volume": 1000 * i + (50000 if i >= 15 else 0),
                 "avg_price": 99.0, "imbalance": 0.4, "symbol": "FFF"} for i in range(25)]
        d = wm.analyse("FFF", rows, {}, {"FFF": {"pdh": 101.5, "hi_52w": 0, "lo_52w": 0}}, book, ann, [])
        titles = " | ".join(x["title"] for x in d["drivers"])
        self.assertIn("NSE announcement (HIGH)", titles)
        self.assertIn("Volume surge", titles)
        self.assertIn("First trade above the previous day's high", titles)
        self.assertIn("Order book leaning to buyers", titles)
        self.assertEqual(d["drivers"][0]["strength"], 3)

    def test_unknown_symbol_and_group_mapping(self) -> None:
        self.assertFalse(wm.analyse("ZZZ", ROWS, {}, {}, [], [], [])["ok"])
        self.assertEqual(wm.group_of("Adani family (Gautam Adani)"), "Adani")
        self.assertEqual(wm.group_of("Government of India"), "Government of India")
        self.assertEqual(wm.group_of("Widely held"), "")


if __name__ == "__main__":
    unittest.main()
