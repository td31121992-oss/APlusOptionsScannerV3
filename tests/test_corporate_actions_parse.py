import unittest
from datetime import date

import update_safety_data as u


class ParseActionsTests(unittest.TestCase):
    def test_parse_and_classify(self):
        rows = u.parse_actions([
            {"symbol": "ABC", "exDate": "23-Oct-2026", "recDate": "23-Oct-2026", "subject": "Interim Dividend - Rs 7 Per Share"},
            {"symbol": "xyz", "exDate": "24-OCT-2026", "recDate": "-", "subject": "Bonus 1:1"},
            {"symbol": "DEF", "exDate": "26-Oct-2026", "recDate": "26-Oct-2026", "subject": "Face Value Split (Sub-Division) - From Rs 10/- To Rs 2/-"},
            {"symbol": "", "exDate": "26-Oct-2026", "subject": "x"},
            {"symbol": "BAD", "exDate": "not a date", "subject": "Dividend"},
        ], date(2026, 10, 23))
        self.assertEqual([(r[0], r[1], r[3]) for r in rows], [("ABC", "2026-10-23", "DIVIDEND"), ("XYZ", "2026-10-24", "BONUS"), ("DEF", "2026-10-26", "SPLIT")])
        self.assertEqual(rows[1][2], "")                                              # no usable record date
        self.assertEqual(u.parse_actions(None, date(2026, 10, 23)), [])


if __name__ == "__main__":
    unittest.main()
