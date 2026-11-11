import unittest

import review_check as rc

FACTS = {"calendar": {"is_trading_day": True}, "trades": {"closed": 28, "net": 17826}, "scanner": {"failed_cycles": 0, "auth_problems": 0}, "pipeline": {"not_current": []},
         "experiments": [{"id": "V01", "status": "COLLECTING"}, {"id": "G01", "status": "COLLECTING"}]}
GOOD = """# Evening review 2026-11-11

**Verdict: AMBER** - ran fine.

## The day in numbers
28 trades, net +Rs 17,826.

## What went right and wrong
RVNL.

## Experiments
V01 collecting. G01 collecting.

## Issues found
none

## Open items
none

## Telegram summary
AMBER
28 trades, net +Rs 17,826
"""


class EveningTests(unittest.TestCase):
    def test_a_good_review_passes(self):
        self.assertEqual(rc.check(GOOD, FACTS, "evening"), [])

    def test_missing_sections_numbers_and_experiments_are_found(self):
        bad = GOOD.replace("## Issues found\nnone\n\n", "").replace("17,826", "18,000").replace("G01 collecting.", "")
        text = " | ".join(rc.check(bad, FACTS, "evening"))
        self.assertIn("missing section: ## Issues found", text)
        self.assertIn("net (Rs 17,826) is not in the review", text)
        self.assertIn("experiment G01 is not listed", text)

    def test_claiming_ready_without_it_in_the_facts_and_missing_verdict(self):
        text = " | ".join(rc.check(GOOD.replace("**Verdict: AMBER**", "Verdict amber") + "\nV01: READY: meets the pass mark", FACTS, "evening"))
        self.assertIn("no verdict line", text)
        self.assertIn("says an experiment is READY but none is in the facts", text)

    def test_ready_experiment_needs_a_request_to_decide_and_summary_must_be_short(self):
        facts = {**FACTS, "experiments": [{"id": "V01", "status": "READY: meets the pass mark"}, {"id": "G01", "status": "COLLECTING"}]}
        self.assertIn("does not ask the user to decide", " | ".join(rc.check(GOOD, facts, "evening")))
        long_summary = GOOD + "\n" + "\n".join(f"line {i}" for i in range(12))
        self.assertIn("too long", " | ".join(rc.check(long_summary, FACTS, "evening")))

    def test_market_closed_day_only_needs_to_say_so(self):
        closed = {"calendar": {"is_trading_day": False}}
        self.assertEqual(rc.check("# Evening review\n\nThe market is closed today (holiday).\n", closed, "evening"), [])
        self.assertTrue(rc.check("# Evening review\n\nAll good.\n", closed, "evening"))


class MorningTests(unittest.TestCase):
    TEXT = "# Morning check 2026-11-12\n\n**READY**\n\n## Checks\nok\n\n## Last session\nok\n\n## Open items\nnone\n\n## Telegram summary\nMorning check: READY\n"

    def test_ready_must_fit_the_preflight_and_scanner_health(self):
        facts = {"calendar": {"is_trading_day": True}, "preflight": {"passed": True}, "system": {"scanner_health": {"status": "HEALTHY"}}, "pipeline": {"not_current": []}}
        self.assertEqual(rc.check(self.TEXT, facts, "morning"), [])
        failed = {**facts, "preflight": {"passed": False}, "system": {"scanner_health": {"status": "AUTHORIZATION_FAILED"}}}
        text = " | ".join(rc.check(self.TEXT, failed, "morning"))
        self.assertIn("pre-flight failed", text)
        self.assertIn("AUTHORIZATION_FAILED", text)


if __name__ == "__main__":
    unittest.main()
