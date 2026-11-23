import os
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import candle_refresh as cr

IST = timezone(timedelta(hours=5, minutes=30))


def at(h, m, s=5):
    return datetime(2026, 11, 23, h, m, s, tzinfo=IST)


def cand(stage="ENTRY_READY", shortlist="WAIT", actionable=False, score=80.0, quality=70.0, capture=60.0):
    return SimpleNamespace(stage=stage, shortlist=shortlist, actionable=actionable, score=score, trade_quality_score=quality, movement_capture_score=capture)


class ModeTests(unittest.TestCase):
    def tearDown(self):
        os.environ.pop("INTRADAY_CANDLE_REFRESH", None)

    def test_off_by_default_and_enforce_is_not_available(self):
        os.environ.pop("INTRADAY_CANDLE_REFRESH", None)
        self.assertEqual(cr.mode(), "OFF")
        os.environ["INTRADAY_CANDLE_REFRESH"] = "ENFORCE"
        self.assertEqual(cr.mode(), "OFF")
        os.environ["INTRADAY_CANDLE_REFRESH"] = "shadow"
        self.assertEqual(cr.mode(), "SHADOW")


class CompareTests(unittest.TestCase):
    def test_identical(self):
        r = cr.compare(cand(), cand())
        self.assertTrue(r["same_decision"] and r["same_scores"])

    def test_decision_difference(self):
        r = cr.compare(cand(actionable=True), cand(actionable=False))
        self.assertFalse(r["same_decision"])
        self.assertEqual(r["decision_fields"], ["actionable"])

    def test_small_score_drift_is_not_a_decision_change(self):
        r = cr.compare(cand(score=80.0), cand(score=83.0))
        self.assertTrue(r["same_decision"])
        self.assertFalse(r["same_scores"])
        self.assertEqual(r["score_fields"], ["score"])
        self.assertTrue(cr.compare(cand(score=80.0), cand(score=80.04))["same_scores"])


class TrackerTests(unittest.TestCase):
    def test_slot_boundaries(self):
        self.assertEqual(cr.slot_of(at(10, 0)), cr.slot_of(at(10, 4, 59)))
        self.assertNotEqual(cr.slot_of(at(10, 4)), cr.slot_of(at(10, 5)))

    def test_fetch_once_per_slot_then_reuse(self):
        t = cr.Tracker()
        t.new_cycle(at(10, 0))
        self.assertTrue(t.due("TCS", at(10, 0)))               # first time seen: ENFORCE would fetch
        t.remember("TCS", at(10, 0), ["c1"])
        for minute in (1, 2, 3, 4):
            t.new_cycle(at(10, minute))
            self.assertFalse(t.due("TCS", at(10, minute)))      # same slot: reuse
            self.assertEqual(t.held_candles("TCS"), ["c1"])
        t.new_cycle(at(10, 5))
        self.assertTrue(t.due("TCS", at(10, 5)))               # next slot: fetch again

    def test_tallies_and_new_day_reset(self):
        t = cr.Tracker()
        t.new_cycle(at(10, 1))
        t.record({"same_decision": True, "same_scores": False})
        t.record({"same_decision": False, "same_scores": False})
        c = t.close_cycle(30)
        self.assertEqual((c["checks"], c["same_decision"], c["same_scores"], c["fetches_now"]), (2, 1, 0, 30))
        t.new_cycle(at(10, 2))
        t.close_cycle(30)
        self.assertEqual((t.total["checks"], t.total["fetches_now"]), (2, 60))
        t.remember("TCS", at(10, 2), ["x"])
        nxt = at(10, 2) + timedelta(days=1)
        t.new_cycle(nxt)
        self.assertEqual((t.total["checks"], t.total["fetches_now"]), (0, 0))
        self.assertTrue(t.due("TCS", nxt))


if __name__ == "__main__":
    unittest.main()


class ScannerHookTests(unittest.TestCase):
    """The scanner-side hook with the analysis mocked: stale candles are the ones held from the first cycle of the slot, the verdict is compared with the fresh one, nothing is returned to the caller."""

    def setUp(self):
        import logging

        logging.disable(logging.CRITICAL)
        from tests.test_history_cache import make_scanner

        self.sc, _ = make_scanner()
        self.sc._cr_tracker = cr.Tracker()
        self.q = SimpleNamespace(symbol="TCS")

    def tearDown(self):
        import logging

        logging.disable(logging.NOTSET)

    def run_cycle(self, when, candles, fresh):
        self.sc._cr_tracker.new_cycle(when)
        self.sc._candle_refresh_shadow(self.q, candles, fresh, when)
        return self.sc._cr_tracker.close_cycle(30)

    def test_first_cycle_of_a_slot_is_a_fetch_and_later_ones_are_compared(self):
        from unittest import mock

        verdict = lambda quote, candles, now: cand(actionable=len(candles) > 5)             # the analysis only looks at how many candles it was given
        with mock.patch.object(self.sc, "_analyse_candidate", side_effect=lambda **kw: verdict(kw["quote"], kw["candles"], kw["now"])):
            c0 = self.run_cycle(at(10, 0), ["c"] * 5, cand(actionable=False))
            self.assertEqual((c0["fetches_if_enforced"], c0["checks"]), (1, 0))
            c1 = self.run_cycle(at(10, 1), ["c"] * 5, cand(actionable=False))                # same candles, same verdict
            self.assertEqual((c1["checks"], c1["same_decision"]), (1, 1))
            c2 = self.run_cycle(at(10, 2), ["c"] * 6, cand(actionable=True))                 # fresh has one more candle: the held list would have decided differently
            self.assertEqual((c2["checks"], c2["same_decision"]), (1, 0))
            c5 = self.run_cycle(at(10, 5), ["c"] * 6, cand(actionable=True))                 # new slot: fetched again, nothing to compare
            self.assertEqual((c5["fetches_if_enforced"], c5["checks"]), (1, 0))

    def test_a_failing_analysis_never_raises(self):
        from unittest import mock

        with mock.patch.object(self.sc, "_analyse_candidate", side_effect=RuntimeError("boom")):
            self.run_cycle(at(10, 0), ["c"], cand())
            self.run_cycle(at(10, 1), ["c"], cand())                                          # must not raise
