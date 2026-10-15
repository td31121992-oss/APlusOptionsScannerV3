import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

import futures_flow as ff
import trade_journal as tj

MASTER = """INSTRUMENT,UNDERLYING_SYMBOL,SECURITY_ID,SM_EXPIRY_DATE
FUTSTK,TCS,49013,2026-10-27
FUTSTK,TCS,862626,2026-11-24
FUTSTK,RELIANCE,100,2026-10-27
FUTSTK,OLD,5,2026-10-14
OPTSTK,TCS,777,2026-10-27
"""
T0 = datetime(2026, 10, 15, 10, 0)


def qm(fut, oi, sid="49013"):
    return {"NSE_FNO": {sid: {"last_price": fut, "oi": oi}}}


class FuturesFlowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.master = Path(self.tmp.name) / "master.csv"
        self.master.write_text(MASTER, encoding="utf-8")

    def flow(self):
        f = ff.FuturesFlow(self.tmp.name, master_csv=self.master)
        f.request_ids(date(2026, 10, 15))
        return f

    def test_picks_nearest_future_not_about_to_expire(self):
        ids = ff.load_future_ids(self.master, date(2026, 10, 15))
        self.assertEqual(ids["TCS"], "49013")
        self.assertNotIn("OLD", ids)                                     # already expired
        self.assertEqual(ff.load_future_ids(self.master, date(2026, 10, 26))["TCS"], "862626")   # day before expiry rolls to next month

    def test_request_ids_can_be_limited_to_the_scanner_universe(self):
        f = ff.FuturesFlow(self.tmp.name, master_csv=self.master)
        self.assertEqual(f.request_ids(date(2026, 10, 15), ["TCS"]), ["49013"])
        g = ff.FuturesFlow(self.tmp.name, master_csv=self.master)
        self.assertEqual(sorted(g.request_ids(date(2026, 10, 15))), ["100", "49013"])

    def test_long_buildup_confirms_a_call(self):
        f = self.flow()
        f.update(qm(2300.0, 1_000_000), {"TCS": 2290.0}, T0)
        f.update(qm(2310.0, 1_020_000), {"TCS": 2300.0}, T0 + timedelta(minutes=31))
        t = f.tags_for("TCS", "BULLISH")
        self.assertEqual(t["fut_flow"], "LONG_BUILDUP")
        self.assertTrue(t["fut_confirms"])
        self.assertAlmostEqual(t["fut_oi_chg_30m_pct"], 2.0, places=1)
        self.assertAlmostEqual(t["fut_price_chg_30m_pct"], 0.43, places=1)
        self.assertFalse(f.tags_for("TCS", "BEARISH")["fut_confirms"])

    def test_short_covering_and_short_buildup(self):
        f = self.flow()
        f.update(qm(2300.0, 1_000_000), {"TCS": 2290.0}, T0)
        f.update(qm(2312.0, 980_000), {"TCS": 2302.0}, T0 + timedelta(minutes=31))        # price up, OI down
        self.assertEqual(f.tags_for("TCS", "BULLISH")["fut_flow"], "SHORT_COVERING")
        self.assertFalse(f.tags_for("TCS", "BULLISH")["fut_confirms"])
        f.update(qm(2290.0, 1_030_000), {"TCS": 2280.0}, T0 + timedelta(minutes=62))      # price down, OI up vs ~30 min ago
        t = f.tags_for("TCS", "BEARISH")
        self.assertEqual(t["fut_flow"], "SHORT_BUILDUP")
        self.assertTrue(t["fut_confirms"])

    def test_tiny_moves_are_neutral_and_premium_tracked(self):
        f = self.flow()
        f.update(qm(2300.0, 1_000_000), {"TCS": 2290.0}, T0)
        f.update(qm(2300.5, 1_000_500), {"TCS": 2290.0}, T0 + timedelta(minutes=31))
        t = f.tags_for("TCS", "BULLISH")
        self.assertEqual(t["fut_flow"], "NEUTRAL")
        self.assertAlmostEqual(t["fut_premium_pct"], 0.44, places=1)
        self.assertIn("fut_premium_chg_pct", t)

    def test_yesterdays_oi_persists_across_days(self):
        f = self.flow()
        f.update(qm(2300.0, 1_000_000), {"TCS": 2290.0}, T0)
        f._saved_at = 0.0
        f.update(qm(2300.0, 1_050_000), {"TCS": 2290.0}, T0 + timedelta(minutes=10))     # saved as the day's last reading
        g = ff.FuturesFlow(self.tmp.name, master_csv=self.master)
        g.request_ids(date(2026, 10, 16))
        g.update(qm(2310.0, 1_071_000), {"TCS": 2300.0}, datetime(2026, 10, 16, 9, 20))
        t = g.tags_for("TCS", "BULLISH")
        self.assertAlmostEqual(t["fut_oi_chg_day_pct"], 2.0, places=1)

    def test_missing_data_returns_empty_and_never_raises(self):
        f = self.flow()
        self.assertEqual(f.tags_for("TCS", "BULLISH"), {})
        f.update({}, {}, T0)
        self.assertEqual(f.tags_for("ZZZ", "BULLISH"), {})

    def test_journal_text(self):
        t = {"fut_premium_pct": 0.31, "fut_premium_chg_pct": -0.12, "fut_oi_chg_day_pct": 3.4, "fut_oi_chg_30m_pct": 1.8,
             "fut_price_chg_30m_pct": 0.55, "fut_flow": "LONG_BUILDUP", "fut_confirms": True}
        s = tj._futures_text(t)
        self.assertIn("LONG BUILDUP", s)
        self.assertIn("CONFIRMS", s)
        self.assertEqual(tj._futures_text({}), "")


if __name__ == "__main__":
    unittest.main()
