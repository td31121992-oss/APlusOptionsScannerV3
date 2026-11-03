import unittest

import put_late_review as pl


def sig(day, minute, rule, close, best=20, worst=-5, sf=False, fate=None):
    return {"day": day, "symbol": "X", "minute": minute, "ready": f"{minute // 60:02d}:{minute % 60:02d}",
            "fate": fate or (f"A_PLUS:{rule}" if rule else "TRADED"), "rule": rule, "best": best, "worst": worst, "close": close, "stop_first": sf}


class PutLateTests(unittest.TestCase):
    def test_only_soft_rules_in_the_window_are_released(self):
        rows = [sig("2026-10-07", 650, "late_vwap_extension", 10), sig("2026-10-07", 700, "late_10m_overheat", 5),
                sig("2026-10-07", 790, "late_vwap_extension", 8),            # after 13:00: stays blocked
                sig("2026-10-07", 650, "pivot_to_r1", -9),                   # control
                sig("2026-10-07", 560, "late_vwap_extension", 4)]            # before 10:00: stays blocked
        ev = pl.evaluate(rows)
        self.assertEqual(ev["released"]["n"], 2)
        self.assertEqual(ev["held_other_times"]["n"], 2)
        self.assertEqual(ev["pivot_control"]["n"], 1)
        self.assertEqual(ev["verdict"], "not yet")                           # far too few signals and days

    def test_enough_good_days_support_it(self):
        rows = []
        for d in range(6):
            for k in range(6):
                rows.append(sig(f"2026-10-{10 + d:02d}", 630 + 10 * k, "late_vwap_extension", 6 + k))
        rows += [sig("2026-10-10", 640, "", 7, fate="TRADED")]
        ev = pl.evaluate(rows)
        self.assertEqual(ev["released"]["n"], 36)
        self.assertEqual(ev["verdict"], "supports relaxing")

    def test_one_great_day_is_not_enough(self):
        rows = []
        for d in range(6):
            for k in range(6):
                rows.append(sig(f"2026-10-{10 + d:02d}", 630 + 10 * k, "late_vwap_extension", 30 if d == 0 else -2))
        ev = pl.evaluate(rows)
        self.assertEqual(ev["verdict"], "not yet")
        self.assertTrue(any("removing" in m or "days positive" in m for m in ev["missing"]))

    def test_render(self):
        text = pl.render(pl.evaluate([sig("2026-10-08", 650, "late_vwap_extension", 12)]), ["2026-10-08"])
        self.assertIn("RELEASED", text)
        self.assertIn("Verdict: not yet", text)


if __name__ == "__main__":
    unittest.main()
