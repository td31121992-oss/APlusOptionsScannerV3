import unittest

import mf_tags as mt


def payload(sectors, stocks):
    return {"ok": True, "sectors": sectors, "stocks": stocks}


DAY = payload(
    [{"sector": "Hotels/Travel", "stocks": 2, "flow_pct": 17.6, "net_cr": 287.7}, {"sector": "Pharma", "stocks": 16, "flow_pct": 4.5, "net_cr": 148.0},
     {"sector": "Metals", "stocks": 15, "flow_pct": -3.0, "net_cr": -50.0}, {"sector": "Lone", "stocks": 1, "flow_pct": 40.0, "net_cr": 1.0}],
    [{"symbol": "INDHOTEL", "sector": "Hotels/Travel", "flow_pct": 17.8}, {"symbol": "JUBLFOOD", "sector": "Hotels/Travel", "flow_pct": 11.5},
     {"symbol": "TATASTEEL", "sector": "Metals", "flow_pct": -4.0}, {"symbol": "HINDZINC", "sector": "Metals", "flow_pct": -1.0}])
W15 = payload([{"sector": "Hotels/Travel", "stocks": 2, "flow_pct": -7.0}, {"sector": "Metals", "stocks": 15, "flow_pct": -5.0}],
              [{"symbol": "INDHOTEL", "sector": "Hotels/Travel", "flow_pct": -8.0}, {"symbol": "TATASTEEL", "sector": "Metals", "flow_pct": -6.0}])


class MfTagTests(unittest.TestCase):
    def test_call_in_the_top_flow_sector(self):
        t = mt.tags_from_payloads(DAY, W15, "INDHOTEL", "BULLISH")
        self.assertEqual((t["mf_sector"], t["mf_sec_flow_dir"], t["mf_sec_rank"], t["mf_sec_n"]), ("Hotels/Travel", 17.6, 1, 3))      # the one-stock sector is not ranked
        self.assertEqual((t["mf_stock_flow_dir"], t["mf_stock_rank_in_sector"]), (17.8, 1))
        self.assertEqual((t["mf_sec_flow15_dir"], t["mf_stock_flow15_dir"]), (-7.0, -8.0))
        self.assertFalse(t["mf_aligned"])                              # day flow is with us but the last 15 minutes turned against

    def test_put_reads_the_flow_the_other_way(self):
        t = mt.tags_from_payloads(DAY, W15, "TATASTEEL", "BEARISH")
        self.assertEqual((t["mf_sec_flow_dir"], t["mf_sec_rank"], t["mf_stock_rank_in_sector"]), (3.0, 1, 1))                        # Metals is the biggest seller; TATASTEEL leads it
        self.assertTrue(t["mf_aligned"])                               # 3.0% with us and the last 15 minutes also selling
        self.assertEqual(mt.tags_from_payloads(DAY, W15, "INDHOTEL", "BEARISH")["mf_sec_flow_dir"], -17.6)

    def test_without_the_15_minute_payload_and_bad_input(self):
        t = mt.tags_from_payloads(DAY, None, "INDHOTEL", "BULLISH")
        self.assertNotIn("mf_sec_flow15_dir", t)
        self.assertTrue(t["mf_aligned"])
        self.assertEqual(mt.tags_from_payloads(DAY, W15, "NOPE", "BULLISH"), {})
        self.assertEqual(mt.tags_from_payloads({"ok": False}, None, "INDHOTEL", "BULLISH"), {})
        self.assertEqual(mt.tags_from_payloads(None, None, "INDHOTEL", "BULLISH"), {})


if __name__ == "__main__":
    unittest.main()
