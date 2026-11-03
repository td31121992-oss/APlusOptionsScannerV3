import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

for k in list(os.environ):
    if k.startswith("APLUS_EVENT"):
        os.environ.pop(k)

import event_calendar as ec
import event_gate as eg

IST = timezone(timedelta(hours=5, minutes=30))


def at(day, hh=10, mm=0):
    return datetime(2026, 10, day, hh, mm, tzinfo=IST)


def build(root, events=(), actions=(), filings=(), holidays=("2026-10-20",)):
    d = Path(root, "data")
    (d / "event_calendar").mkdir(parents=True)
    (d / "safety").mkdir(parents=True)
    (d / "news_intelligence").mkdir(parents=True)
    rows = ["symbol,event_date,event_type,severity,as_of,source,notes"] + [f"{s},{day},{t},HIGH,2026-10-19,x," for s, day, t in events]
    (d / "event_calendar" / "2026-10-19.csv").write_text("\n".join(rows), encoding="utf-8")
    (d / "safety" / "corporate_events.csv").write_text("symbol,event_date,event_type,severity,as_of,source,notes\n", encoding="utf-8")
    (d / "safety" / "corporate_actions.csv").write_text("symbol,ex_date,record_date,action,subject,as_of\n" + "\n".join(f"{s},{day},{day},{a},x,2026-10-19" for s, day, a in actions), encoding="utf-8")
    (d / "safety" / "nse_holidays.csv").write_text("date,description\n" + "\n".join(f"{h},holiday" for h in holidays), encoding="utf-8")
    (d / "news_intelligence" / "announcements.jsonl").write_text("\n".join(json.dumps({"symbol": s, "desc": "Outcome of Board Meeting", "text": "has submitted the financial results for the period", "published_at": ts}) for s, ts in filings), encoding="utf-8")
    ec._CACHE.update(key=None, data=None)
    return Path(root)


class EventCalendarTests(unittest.TestCase):
    def test_phases_by_trading_days_and_weekend_holiday(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build(tmp, events=[("AAA", "2026-10-21", "FINANCIAL RESULTS"), ("BBB", "2026-10-22", "FINANCIAL RESULTS"), ("CCC", "2026-10-26", "FINANCIAL RESULTS"),
                                      ("DDD", "2026-10-30", "FINANCIAL RESULTS"), ("EEE", "2026-10-19", "FINANCIAL RESULTS")])
            now = at(21)                                                             # Wednesday 21 Oct
            self.assertEqual(ec.tags("AAA", now, root)["ev_phase"], "RESULTS_TODAY")
            self.assertEqual(ec.tags("BBB", now, root)["ev_phase"], "RESULTS_TOMORROW")
            c = ec.tags("CCC", now, root)                                            # Monday 26 Oct: 3 trading days (22, 23, 26)
            self.assertEqual((c["ev_phase"], c["ev_results_days"]), ("RESULTS_NEAR", 3))
            self.assertEqual(ec.tags("DDD", now, root)["ev_phase"], "")             # 7 trading days away
            e = ec.tags("EEE", now, root)                                            # 19 Oct results, two trading days ago (20 Oct is a holiday)
            self.assertEqual((e["ev_phase"], e["ev_since_days"]), ("POST", 1))
            self.assertEqual(ec.tags("ZZZ", now, root)["ev_phase"], "")
            fri = ec.tags("BBB", at(23), root)                                       # Friday: results Thursday 22 are past
            self.assertEqual(fri["ev_phase"], "POST")
            self.assertEqual(ec.tags("CCC", at(23), root)["ev_results_days"], 1)    # next trading day is Monday

    def test_filing_since_the_last_close_means_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build(tmp, events=[("AAA", "2026-10-22", "FINANCIAL RESULTS"), ("BBB", "2026-10-22", "FINANCIAL RESULTS")],
                         filings=[("AAA", "2026-10-21T17:45:00+05:30"), ("BBB", "2026-10-21T10:00:00+05:30")])
            a = ec.tags("AAA", at(22, 10), root)                                     # filed after yesterday's close: repriced
            self.assertEqual((a["ev_reported"], a["ev_phase"]), (1, "REPORTED"))
            b = ec.tags("BBB", at(22, 10), root)                                     # filed before yesterday's close: not "since the last close", the date still says today
            self.assertEqual((b["ev_reported"], b["ev_phase"]), (0, "RESULTS_TODAY"))
            self.assertEqual(ec.tags("AAA", at(22, 9, 0), root)["ev_reported"], 1)
            self.assertEqual(ec.tags("AAA", at(21, 12), root)["ev_reported"], 0)     # not filed yet at midday on the 21st

    def test_ex_dates_and_other_meetings(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build(tmp, events=[("AAA", "2026-10-22", "BUYBACK")], actions=[("BBB", "2026-10-22", "BONUS"), ("CCC", "2026-10-21", "DIVIDEND"), ("DDD", "2026-10-28", "SPLIT")])
            now = at(21)
            self.assertEqual(ec.tags("AAA", now, root)["ev_other"], "BUYBACK")
            b = ec.tags("BBB", now, root)
            self.assertEqual((b["ev_ex_type"], b["ev_ex_days"]), ("BONUS", 1))
            self.assertEqual(ec.tags("CCC", now, root)["ev_ex_days"], 0)
            self.assertNotIn("ev_ex_type", ec.tags("DDD", now, root))               # a week away

    def test_missing_files_never_raise(self):
        with tempfile.TemporaryDirectory() as tmp:
            ec._CACHE.update(key=None, data=None)
            self.assertEqual(ec.tags("AAA", at(21), Path(tmp))["ev_phase"], "")


class EventGateTests(unittest.TestCase):
    def test_mode(self):
        self.assertEqual(eg.mode(), "SHADOW")
        with mock.patch.dict(os.environ, {"APLUS_EVENT_GATE_MODE": "enforce"}):
            self.assertEqual(eg.mode(), "ENFORCE")

    def test_blocks_pre_results_and_bonus_split_only(self):
        for phase, text in (("RESULTS_TODAY", "results today"), ("RESULTS_TOMORROW", "results tomorrow"), ("RESULTS_NEAR", "results in 2 trading days")):
            out = eg.evaluate({"ev_phase": phase, "ev_results_days": 2})
            self.assertEqual(out["evg_ok"], 0)
            self.assertIn(text, out["evg_why"])
        for phase in ("REPORTED", "POST", ""):
            self.assertEqual(eg.evaluate({"ev_phase": phase})["evg_ok"], 1)
        self.assertEqual(eg.evaluate({"ev_ex_type": "DIVIDEND", "ev_ex_days": 0})["evg_ok"], 1)
        split = eg.evaluate({"ev_ex_type": "SPLIT", "ev_ex_days": 1})
        self.assertEqual((split["evg_ok"], split["evg_why"]), (0, "split ex-date tomorrow"))
        self.assertEqual(eg.evaluate({})["evg_ok"], 1)


if __name__ == "__main__":
    unittest.main()
