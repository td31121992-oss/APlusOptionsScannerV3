from __future__ import annotations

import unittest
from dataclasses import dataclass

from order_block import order_block_state


@dataclass
class C:
    open: float
    high: float
    low: float
    close: float


def flat(n, price=100.0):
    return [C(price, price + 0.3, price - 0.3, price) for _ in range(n)]


class OrderBlockTests(unittest.TestCase):
    def bull_setup(self):
        c = flat(14)
        c.append(C(100.0, 100.1, 99.2, 99.4))             # down candle = the block (low 99.2, high 100.1)
        c.append(C(99.5, 102.5, 99.4, 102.4))             # strong impulse up breaking the recent highs
        return c

    def test_bullish_block_retest_is_tagged_in_zone(self) -> None:
        c = self.bull_setup() + [C(102.4, 102.5, 101.0, 101.5), C(101.5, 101.6, 99.6, 99.8)]
        s = order_block_state(c, "BULLISH")
        self.assertEqual(s["state"], "IN_FRESH_OB")
        self.assertAlmostEqual(s["zone_low"], 99.2)

    def test_price_still_above_the_block_is_not_retested(self) -> None:
        c = self.bull_setup() + [C(102.4, 103.0, 102.0, 102.8)]
        self.assertEqual(order_block_state(c, "BULLISH")["state"], "ABOVE_OB")

    def test_block_broken_by_a_close_below_is_no_longer_fresh(self) -> None:
        c = self.bull_setup() + [C(102.4, 102.5, 98.0, 98.5)]
        self.assertEqual(order_block_state(c, "BULLISH")["state"], "NONE")

    def test_bearish_mirror(self) -> None:
        c = flat(14)
        c.append(C(100.0, 100.8, 99.9, 100.6))            # up candle = block
        c.append(C(100.5, 100.6, 97.6, 97.7))             # strong impulse down breaking the recent lows
        c.append(C(97.7, 99.0, 97.6, 98.9)) if False else None
        c.append(C(97.7, 100.2, 97.6, 100.3))             # retest up into the zone
        self.assertEqual(order_block_state(c, "BEARISH")["state"], "IN_FRESH_OB")

    def test_too_little_data_or_wrong_direction_is_none(self) -> None:
        self.assertEqual(order_block_state(flat(5), "BULLISH")["state"], "NONE")
        self.assertEqual(order_block_state(self.bull_setup(), "BEARISH")["state"], "NONE")


if __name__ == "__main__":
    unittest.main()
