import os
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import candle_refresh as cr

IST = timezone(timedelta(hours=5, minutes=30))


def at(h, m, s=5):
    return datetime(2026, 11, 23, h, m, s, tzinfo=IST)


def cand(stage="LOW_RELATIVE_VOLUME", shortlist="WAIT", actionable=False, score=80.0, quality=70.0, capture=60.0):
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
        self.assertEqual(cr.slot_of(at(10, 0)), cr.slot_of(at(10, 4, 25)))          # the 10:00 candle is not completed until 10:04:30 ...
        self.assertNotEqual(cr.slot_of(at(10, 4, 25)), cr.slot_of(at(10, 4, 35)))   # ... so a new slot (and a refetch) starts there
        self.assertEqual(cr.slot_of(at(10, 4, 35)), cr.slot_of(at(10, 9, 25)))

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


class NearEntryTests(unittest.TestCase):
    def test_near_entry_is_actionable_or_entry_ready_or_pullback(self):
        self.assertTrue(cr.near_entry(cand(actionable=True)))
        self.assertTrue(cr.near_entry(cand(stage="CONTINUATION_BEARISH_ENTRY_READY")))
        self.assertTrue(cr.near_entry(cand(stage="HEALTHY_BULLISH_PULLBACK")))
        self.assertTrue(cr.near_entry(cand(stage="BEARISH_TREND_WAIT_FOR_PULLBACK")))
        self.assertFalse(cr.near_entry(cand(stage="EXTENDED_NO_ENTRY")))
        self.assertFalse(cr.near_entry(cand(stage="LOW_RELATIVE_VOLUME")))


class ScannerHookTests(unittest.TestCase):
    """The scanner-side hook with the analysis mocked. Held candles are the ones from the first cycle of the slot; near-entry stocks are always fetched fresh (hot) and a held-candle verdict of
    'near entry' is verified with a fresh fetch (verify); only quiet stocks are compared. Nothing is returned to the caller."""

    def setUp(self):
        import logging
        from unittest import mock

        logging.disable(logging.CRITICAL)
        from tests.test_history_cache import make_scanner

        self.sc, _ = make_scanner()
        self.sc._cr_tracker = cr.Tracker()
        self.q = SimpleNamespace(symbol="TCS")
        self.verdict = lambda candles: cand()
        p = mock.patch.object(self.sc, "_candle_refresh_note")                          # the real one writes into data/candle_refresh_shadow: never from a test
        p.start()
        self.addCleanup(p.stop)
        p2 = mock.patch.object(self.sc, "_analyse_candidate", side_effect=lambda **kw: self.verdict(kw["candles"]))
        p2.start()
        self.addCleanup(p2.stop)

    def tearDown(self):
        import logging

        logging.disable(logging.NOTSET)

    def cycle(self, when, candles, fresh):
        self.sc._cr_tracker.new_cycle(when)
        self.sc._candle_refresh_shadow(self.q, candles, fresh, when)
        return self.sc._cr_tracker.close_cycle(30)

    def test_quiet_stock_is_fetched_once_per_slot_and_compared_in_between(self):
        self.verdict = lambda candles: cand(stage="LOW_RELATIVE_VOLUME", score=80.0 + len(candles) * 0.0)
        c0 = self.cycle(at(10, 0), ["c"] * 5, cand())
        self.assertEqual((c0["slot"], c0["checks"]), (1, 0))
        c1 = self.cycle(at(10, 1), ["c"] * 5, cand())
        self.assertEqual((c1["checks"], c1["same_decision"], c1["fetches_if_enforced"]), (1, 1, 0))      # reused, no fetch
        c5 = self.cycle(at(10, 5), ["c"] * 6, cand())
        self.assertEqual((c5["slot"], c5["checks"]), (1, 0))                                           # new slot: fetched again

    def test_a_stock_that_was_near_entry_is_fetched_fresh_every_cycle(self):
        self.cycle(at(10, 0), ["c"] * 5, cand(stage="HEALTHY_BULLISH_PULLBACK"))                         # near entry now ...
        c1 = self.cycle(at(10, 1), ["c"] * 5, cand(stage="HEALTHY_BULLISH_PULLBACK"))
        self.assertEqual((c1["hot"], c1["fetches_if_enforced"], c1["checks"]), (1, 1, 0))                # ... so fresh on the next cycle, nothing compared
        c2 = self.cycle(at(10, 2), ["c"] * 5, cand(stage="HEALTHY_BULLISH_PULLBACK"))
        self.assertEqual(c2["hot"], 1)
        c3 = self.cycle(at(10, 3), ["c"] * 5, cand(stage="LOW_RELATIVE_VOLUME"))                         # still hot (it was near entry on the previous cycle) ...
        self.assertEqual(c3["hot"], 1)
        c4 = self.cycle(at(10, 4), ["c"] * 5, cand(stage="LOW_RELATIVE_VOLUME"))                         # ... but is quiet now, so it goes back to reusing held candles
        self.assertEqual((c4["hot"], c4["checks"]), (0, 1))

    def test_held_candles_never_decide_an_entry_they_are_verified(self):
        """The 11:42 PNB case: held candles said entry ready, fresh candles said wait. Verified with a fresh fetch, so it is not a difference and the fresh answer decides."""
        self.verdict = lambda candles: cand(stage="CONTINUATION_BEARISH_ENTRY_READY", actionable=True)
        self.cycle(at(10, 0), ["c"] * 5, cand())                                                          # quiet at the slot start
        c1 = self.cycle(at(10, 1), ["c"] * 5, cand(stage="BEARISH_TREND_WAIT_FOR_PULLBACK"))
        self.assertEqual((c1["verify"], c1["fetches_if_enforced"], c1["checks"]), (1, 1, 0))
        self.assertEqual(c1["same_decision"], 0)

    def test_a_quiet_stock_that_turns_near_entry_is_counted_as_late(self):
        self.verdict = lambda candles: cand(stage="EXTENDED_NO_ENTRY")                                    # held candles still say quiet
        self.cycle(at(10, 0), ["c"] * 5, cand())
        c1 = self.cycle(at(10, 1), ["c"] * 6, cand(stage="HEALTHY_BULLISH_PULLBACK"))                     # fresh candles say pullback
        self.assertEqual((c1["checks"], c1["late"], c1["same_decision"]), (1, 1, 0))

    def test_a_failing_analysis_never_raises(self):
        from unittest import mock

        with mock.patch.object(self.sc, "_analyse_candidate", side_effect=RuntimeError("boom")):
            self.cycle(at(10, 0), ["c"], cand())
            self.cycle(at(10, 1), ["c"], cand())                                                          # must not raise
