import unittest
from types import SimpleNamespace

import v2_shadow


def cand(sym, direction="BULLISH", vwap=0.4):
    return SimpleNamespace(symbol=sym, direction=direction, vwap_distance_percent=vwap)


def blk(sym, reasons, d5, direction="BULLISH"):
    return {"symbol": sym, "direction": direction, "reasons": reasons, "directional_5m_pct": d5}


class PullbackTests(unittest.TestCase):
    def test_small_dip_above_vwap_passes(self):
        out = v2_shadow.pullback_pass(
            [cand("TCS")], [blk("TCS", ["CURRENT_5M_REVERSING(-0.41%)", "NO_FRESH_CONTINUATION(votes=1/2,5m=-0.41)"], -0.41)])
        self.assertEqual([c.symbol for c in out], ["TCS"])

    def test_other_reasons_or_deep_dip_or_wrong_vwap_fail(self):
        blocked = [
            blk("RANK", ["NOT_IN_DYNAMIC_TOP5_DIRECTION", "CURRENT_5M_REVERSING(-0.1%)"], -0.1),      # also fails rank
            blk("DEEP", ["CURRENT_5M_REVERSING(-0.9%)"], -0.9),                                       # dip too big
            blk("LOWVWAP", ["CURRENT_5M_REVERSING(-0.2%)"], -0.2),                                    # below VWAP
            blk("PART", ["CURRENT_5M_REVERSING(-0.2%)", "PARTICIPATION_TOO_LOW(0.5x<1.2x)"], -0.2),   # other rule
        ]
        cs = [cand("RANK"), cand("DEEP"), cand("LOWVWAP", vwap=-0.2), cand("PART"), cand("NOTBLOCKED")]
        self.assertEqual(v2_shadow.pullback_pass(cs, blocked), [])

    def test_put_uses_inverse_vwap_side(self):
        blocked = [blk("PUT", ["CURRENT_5M_REVERSING(-0.2%)"], -0.2, "BEARISH")]
        self.assertEqual(len(v2_shadow.pullback_pass([cand("PUT", "BEARISH", vwap=-0.3)], blocked)), 1)
        self.assertEqual(v2_shadow.pullback_pass([cand("PUT", "BEARISH", vwap=0.3)], blocked), [])


if __name__ == "__main__":
    unittest.main()
