import unittest

import smc_levels as smc
import trade_review as tr


def bar(o, h, l, c, t=0):
    return {"o": o, "h": h, "l": l, "c": c, "t": t}


def uptrend_with_block():
    quiet = [bar(100.2, 100.45, 99.95, 100.2 + (0.05 if i % 2 else -0.05)) for i in range(12)]
    rows = quiet + [bar(100, 100.4, 99.8, 100.2), bar(100.2, 100.5, 100.0, 100.3), bar(100.3, 100.6, 100.1, 100.4), bar(100.4, 100.5, 100.2, 100.3),
            bar(100.3, 100.4, 100.1, 100.2),
            bar(100.2, 100.3, 99.9, 100.0),                      # last down candle = the order block (99.9-100.3)
            bar(100.0, 102.2, 99.95, 102.0),                     # strong impulse breaking the range
            bar(102.0, 102.6, 101.8, 102.4), bar(102.4, 103.0, 102.2, 102.9), bar(102.9, 103.2, 102.5, 103.0),
            bar(103.0, 103.1, 102.6, 102.7), bar(102.7, 103.0, 102.5, 102.9), bar(102.9, 103.4, 102.8, 103.3), bar(103.3, 103.5, 103.0, 103.2)]
    return rows


class SmcTests(unittest.TestCase):
    def test_bullish_order_block_found_and_drawn(self):
        zs = smc.zones(uptrend_with_block())
        ob = [z for z in zs if z["kind"] == "orderblock"]
        self.assertTrue(ob and ob[0]["side"] == "bull")
        self.assertLess(ob[0]["low"], ob[0]["high"])
        names = [m["name"] for m in smc.marks(uptrend_with_block())]
        self.assertTrue(any("Bull OB top" in n for n in names))

    def test_equal_lows_become_a_liquidity_pool_below_price(self):
        rows = []
        px = 100.0
        for i in range(30):                                    # a zigzag whose swing lows repeat at about 99.00
            if i % 6 == 0:
                rows.append(bar(px, px + 0.1, 99.0 + (0.03 if i % 12 else 0.0), 99.2))
            elif i % 6 in (1, 2):
                rows.append(bar(99.2, 99.8, 99.15, 99.7))
            else:
                rows.append(bar(99.7, 100.4, 99.6, 100.2))
        liq = smc.liquidity_levels(rows)
        self.assertTrue(liq["below"])
        self.assertTrue(all(lv["price"] < rows[-1]["c"] for lv in liq["below"]))
        self.assertTrue(all(lv["touches"] >= 2 for lv in liq["below"]))

    def test_too_little_data_gives_nothing(self):
        self.assertEqual(smc.zones([bar(1, 1, 1, 1)] * 5), [])
        self.assertEqual(smc.entry_tags([bar(1, 1, 1, 1)] * 5, "BULLISH"), {})

    def test_entry_tags_state_and_distance(self):
        t = smc.entry_tags(uptrend_with_block(), "BULLISH", 103.2)
        self.assertIn(t["smc_ob_state"], ("ABOVE_OB", "IN_FRESH_OB", "NONE"))
        self.assertIn("smc_liq_pools", t)

    def test_review_groups_by_order_block_state(self):
        rows = [{"smc_ob_state": "IN_FRESH_OB", "net": 500}, {"smc_ob_state": "NONE", "net": -300}, {"smc_ob_state": "ABOVE_OB", "net": 100}]
        text = "\n".join(tr.verdict_section(rows))
        self.assertIn("Entered inside a fresh order block | 1 | 1 | +500", text)
        self.assertIn("Entered with no fresh order block | 1 | 0 | -300", text)


if __name__ == "__main__":
    unittest.main()
