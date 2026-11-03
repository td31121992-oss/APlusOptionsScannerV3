import unittest

import gate_whatif as gw


def row(**kw):
    base = {"direction": "BULLISH", "pivot_state": "S1_TO_PIVOT", "setup_family": "HEALTHY_PULLBACK", "fresh_15m": 0, "fresh_30m": 0, "fresh_day": 0, "opening_range_breakout": 0,
            "recent_5m_pct": 0.3, "recent_10m_pct": 0.5, "recent_15m_pct": 0.6, "move_from_0915_pct": 1.0, "day_change_pct": 0.5, "vwap_dist_pct": 0.5, "chase_risk": 10, "rsi_5m": 60,
            "rel_volume": 1.5, "rel_volume_15m": 1.2, "tape_acc_5m": 1.0, "tape_acc_15m": 1.0, "trade_quality": 80, "trend_alignment": 75, "clean_trend": 80}
    base.update(kw)
    return base


class ChainTests(unittest.TestCase):
    def test_clean_candidate_passes(self):
        self.assertEqual(gw.evaluate(row()), "PASSED")

    def test_late_10m_then_falls_through_to_vwap(self):
        r = row(recent_10m_pct=1.76, vwap_dist_pct=1.58)
        self.assertEqual(gw.evaluate(r), "LATE_10M_OVERHEAT")
        self.assertEqual(gw.evaluate(r, frozenset({"LATE_10M_OVERHEAT"})), "LATE_VWAP_EXTENSION")      # COFORGE 09:32
        self.assertEqual(gw.evaluate(r, frozenset({"LATE_10M_OVERHEAT", "LATE_VWAP_EXTENSION"})), "PASSED")

    def test_pivot_comes_first_and_bearish_signs(self):
        self.assertEqual(gw.evaluate(row(pivot_state="PIVOT_TO_R1", recent_10m_pct=2.0)), "PIVOT_TO_R1")
        put = row(direction="BEARISH", recent_10m_pct=-1.2, recent_5m_pct=-0.5, recent_15m_pct=-1.0, vwap_dist_pct=-1.0, move_from_0915_pct=-1.0, day_change_pct=-0.5)
        self.assertEqual(gw.evaluate(put), "LATE_10M_OVERHEAT")

    def test_recorded_status_mapping(self):
        self.assertEqual(gw.recorded({"status": "A_PLUS_WAIT_PIVOT_TO_R1"}), "PIVOT_TO_R1")
        self.assertEqual(gw.recorded({"status": "PASSED_ALL_GATES"}), "PASSED")
        self.assertEqual(gw.recorded({"status": "V2_STOCK_SELECTION_BLOCKED"}), "OTHER")


if __name__ == "__main__":
    unittest.main()
