import math
import unittest

import chop
import trade_review as tr


def trend(n=30, step=0.4):
    out, c = [], 100.0
    for i in range(n):
        o = c
        c = c + step
        out.append({"o": o, "h": c + 0.05, "l": o - 0.05, "c": c, "v": 1000})
    return out


def sideways(n=30, amp=0.5):
    out, c = [], 100.0
    for i in range(n):
        o = c
        c = 100.0 + amp * (1 if i % 2 else -1)
        out.append({"o": o, "h": max(o, c) + 0.1, "l": min(o, c) - 0.1, "c": c, "v": 1000})
    return out


class ChopTests(unittest.TestCase):
    def test_straight_line_is_trending(self):
        m = chop.measures(trend())
        self.assertEqual(m["chop_state"], "TRENDING")
        self.assertGreater(m["chop_er12"], 0.9)
        self.assertLess(m["chop_ci14"], 45)
        self.assertLessEqual(m["chop_vwap_x60"], 1)

    def test_zigzag_is_choppy(self):
        m = chop.measures(sideways())
        self.assertEqual(m["chop_state"], "CHOPPY")
        self.assertGreaterEqual(m["chop_vwap_x60"], 3)
        self.assertLess(m["chop_er12"], 0.2)

    def test_short_history_uses_a_shorter_window_and_very_short_gives_nothing(self):
        m = chop.measures(trend(10))
        self.assertEqual(m["chop_len"], 9)
        self.assertEqual(chop.measures(trend(5)), {})

    def test_objects_work_too_and_badge_text(self):
        class C:
            def __init__(self, d):
                self.open, self.high, self.low, self.close, self.volume = d["o"], d["h"], d["l"], d["c"], d["v"]
        m = chop.measures([C(x) for x in trend()])
        self.assertEqual(m["chop_state"], "TRENDING")
        self.assertIn("Trending", chop.badge_text(m))

    def test_review_groups(self):
        rows = [{"chop_state": "CHOPPY", "net": -300}, {"chop_state": "TRENDING", "net": 800}, {"chop_state": "CHOPPY", "net": 100}]
        text = "\n".join(tr.verdict_section(rows))
        self.assertIn("Entered while choppy | 2 | 1 | -200", text)
        self.assertIn("Entered while the stock was trending | 1 | 1 | +800", text)


if __name__ == "__main__":
    unittest.main()
