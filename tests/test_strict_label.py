import unittest

import strict_label as sl


def bars(prices, start=560):
    """prices = list of (high, low, close) per minute starting at `start`; open = previous close."""
    out, prev = [], None
    for i, (h, l, c) in enumerate(prices):
        out.append((start + i, prev if prev is not None else c, h, l, c))
        prev = c
    return out


class LabelTests(unittest.TestCase):
    def test_target_before_stop(self):
        b = bars([(100, 100, 100), (101, 99, 100), (112, 100, 111), (111, 70, 80)])       # +10% (110.1 after 1% slip) hit at minute 562, stop later
        r = sl.label(b, 560, 0, slip=0.0)
        self.assertEqual((r["hit10_first"], r["stop_first"], r["min_to_hit10"]), (1, 0, 2))
        self.assertEqual(r["hit10_30"], 1)

    def test_stop_before_target_and_same_minute_counts_as_stop(self):
        b = bars([(100, 100, 100), (101, 79, 85), (130, 85, 120)])
        self.assertEqual(sl.label(b, 560, 0, slip=0.0)["stop_first"], 1)
        b2 = bars([(100, 100, 100), (115, 79, 100)])                                      # touches both in one minute: conservative stop
        r = sl.label(b2, 560, 0, slip=0.0)
        self.assertEqual((r["hit10_first"], r["stop_first"]), (0, 1))

    def test_delay_moves_the_entry_and_no_data_gives_none(self):
        b = bars([(100, 100, 100), (100, 100, 100), (150, 100, 150), (150, 140, 145)])
        late = sl.label(b, 560, 2, slip=0.0)                                              # entered at the 150 candle: no +10% afterwards
        self.assertEqual((late["entry"], late["hit10_first"]), (150.0, 0))
        self.assertIsNone(sl.label(b, 500, 1))                                            # nothing at or before the entry minute
        self.assertIsNone(sl.label(b, 563, 5))                                            # nothing after the entry candle

    def test_pick_contract_is_itm_for_the_side(self):
        cts = [{"key": f"k{k}", "strike": float(k), "type": t, "expiry": "e"} for k in (95, 100, 105) for t in ("CE", "PE")]
        self.assertEqual(sl.pick_contract(cts, True, 100.4)["strike"], 100.0)             # wants 99.9
        self.assertEqual(sl.pick_contract(cts, False, 100.0)["type"], "PE")
        self.assertIsNone(sl.pick_contract([], True, 100.0))


if __name__ == "__main__":
    unittest.main()
