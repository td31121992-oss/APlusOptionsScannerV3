from __future__ import annotations

import csv
import json
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import announcement_feed as af
import safety_gate as sg

IST = ZoneInfo("Asia/Kolkata")


def ist(d: int, h: int, m: int = 0) -> datetime:
    return datetime(2026, 10, d, h, m, tzinfo=IST)


def row(symbol="TCS", desc="Outcome of Board Meeting", an_dt="07-Oct-2026 11:00:00", text="results", seq="1"):
    return {"symbol": symbol, "desc": desc, "an_dt": an_dt, "attchmntText": text, "sm_name": symbol + " Ltd", "seq_id": seq, "attchmntFile": "http://x/y.pdf"}


class ClassifyTests(unittest.TestCase):
    def test_grades(self) -> None:
        self.assertEqual(af.classify("Outcome of Board Meeting"), "HIGH")
        self.assertEqual(af.classify("Acquisition"), "HIGH")
        self.assertEqual(af.classify("Action(s) initiated or orders passed"), "HIGH")
        self.assertEqual(af.classify("Credit Rating"), "MEDIUM")
        self.assertEqual(af.classify("Spurt in Volume"), "MEDIUM")
        self.assertEqual(af.classify("Awarding of Order(s)/Contract(s)"), "HIGH")
        self.assertEqual(af.classify("Record Date"), "MEDIUM")          # routine, must not block trading
        self.assertEqual(af.classify("ESOP/ESOS/ESPS"), "LOW")          # routine allotments are noise
        self.assertEqual(af.classify("Copy of Newspaper Publication"), "LOW")
        self.assertEqual(af.classify("Certificate under SEBI (Depositories and Participants) Regulations, 2018"), "LOW")

    def test_resignation_depends_on_role(self) -> None:
        self.assertEqual(af.classify("Resignation", "Resignation of the Chief Financial Officer"), "HIGH")
        self.assertEqual(af.classify("Resignation", "Resignation of an independent director"), "MEDIUM")


class ParseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.hol = Path(self.tmp.name, "h.csv")
        self.hol.write_text("date,description\n2026-10-09,Test holiday\n", encoding="utf-8")

    def test_only_fno_symbols_and_session_date(self) -> None:
        rows = [row("TCS", an_dt="07-Oct-2026 11:00:00"), row("NOTFNO"), row("INFY", an_dt="07-Oct-2026 18:30:00", seq="2")]
        out = af.parse_announcements(rows, {"TCS", "INFY"}, self.hol)
        self.assertEqual([a["symbol"] for a in out], ["TCS", "INFY"])
        self.assertEqual(out[0]["session_date"], "2026-10-07")        # before the close -> same day
        self.assertEqual(out[1]["session_date"], "2026-10-08")        # after the close -> next session

    def test_after_close_before_holiday_rolls_past_it(self) -> None:
        pub = ist(8, 18, 0)   # Thursday evening; Friday 9 Oct is a listed holiday; weekend follows
        self.assertEqual(af.effective_session_date(pub, self.hol), date(2026, 10, 12))

    def test_bad_rows_are_skipped_and_ids_are_stable(self) -> None:
        a = af.parse_announcements([row(), {"symbol": "TCS", "desc": "x", "an_dt": "garbage"}], {"TCS"}, self.hol)
        b = af.parse_announcements([row()], {"TCS"}, self.hol)
        self.assertEqual(len(a), 1)
        self.assertEqual(a[0]["id"], b[0]["id"])


def _anns(*specs):
    return [dict(id=f"id{i}", symbol=s, desc=d, text="t", severity=sev, published_at=ist(7, 10).isoformat(),
                 session_date="2026-10-07") for i, (s, d, sev) in enumerate(specs)]


class ProcessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.sent: list[str] = []
        self.sender = lambda msg: (self.sent.append(msg) or (True, ""))

    def test_first_run_is_silent_baseline(self) -> None:
        state = af.load_state(Path("nonexistent-state.json"))
        r = af.process(_anns(("TCS", "Acquisition", "HIGH")), state, ist(7, 10), self.sender)
        self.assertTrue(r["baseline"])
        self.assertEqual(self.sent, [])
        self.assertTrue(state["baselined"])

    def test_new_high_alerts_once_and_low_never(self) -> None:
        state = {"baselined": True, "seen": [], "pending": [], "sent_today": {"date": "", "count": 0}, "last_digest": ""}
        batch = _anns(("TCS", "Acquisition", "HIGH"), ("INFY", "Credit Rating", "MEDIUM"), ("WIPRO", "Newspaper", "LOW"))
        r1 = af.process(batch, state, ist(7, 10), self.sender)
        self.assertEqual((r1["sent"], len(self.sent)), (1, 1))
        self.assertIn("TCS", self.sent[0])
        r2 = af.process(batch, state, ist(7, 10, 5), self.sender)       # same items again -> nothing new
        self.assertEqual((r2["sent"], len(self.sent)), (0, 1))

    def test_quiet_hours_queue_then_single_morning_digest(self) -> None:
        state = {"baselined": True, "seen": [], "pending": [], "sent_today": {"date": "", "count": 0}, "last_digest": ""}
        batch = _anns(("TCS", "Acquisition", "HIGH"), ("INFY", "Buyback", "HIGH"))
        af.process(batch, state, ist(7, 2), self.sender)                  # 02:00 quiet
        self.assertEqual(self.sent, [])
        self.assertEqual(len(state["pending"]), 2)
        r = af.process(batch, state, ist(7, 7, 5), self.sender)           # after 07:00
        self.assertTrue(r["digest"])
        self.assertEqual(len(self.sent), 1)
        self.assertIn("digest", self.sent[0])
        self.assertEqual(state["pending"], [])

    def test_daily_cap_overflows_into_digest(self) -> None:
        state = {"baselined": True, "seen": [], "pending": [], "sent_today": {"date": "2026-10-07", "count": af.MAX_ALERTS_PER_DAY}, "last_digest": ""}
        af.process(_anns(("TCS", "Acquisition", "HIGH")), state, ist(7, 10), self.sender)
        self.assertEqual(self.sent[:1] and "digest" in self.sent[0], True)  # went to the digest, not a single alert

    def test_failed_send_is_kept_pending(self) -> None:
        state = {"baselined": True, "seen": [], "pending": [], "sent_today": {"date": "", "count": 0}, "last_digest": "x"}
        af.process(_anns(("TCS", "Acquisition", "HIGH")), state, ist(7, 10), lambda m: (False, "down"))
        self.assertEqual(len(state["pending"]), 1)


class GateIntegrationTests(unittest.TestCase):
    def test_high_announcement_blocks_symbol_and_medium_warns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            items = [
                dict(symbol="TCS", session_date="2026-10-07", desc="Acquisition", severity="HIGH", text="deal"),
                dict(symbol="INFY", session_date="2026-10-07", desc="Credit Rating", severity="MEDIUM", text="rating"),
                dict(symbol="WIPRO", session_date="2026-10-07", desc="Press", severity="LOW", text="pr"),
            ]
            n = af.write_gate_csv(items, date(2026, 10, 7), Path(tmp, "safety", "announcement_events.csv"))
            self.assertEqual(n, 2)                                           # LOW is not published
            engine = sg.SafetyGateEngine(sg.SafetyGateConfig(), data_dir=tmp)
            today = date(2026, 10, 7)
            value = lambda c: getattr(c.status, "value", c.status)
            self.assertEqual(value(engine._corporate_event_check("TCS", today)), "BLOCK")
            self.assertEqual(value(engine._corporate_event_check("INFY", today)), "WARN")
            self.assertEqual(value(engine._corporate_event_check("WIPRO", today)), "PASS")


class StoreTests(unittest.TestCase):
    def test_recent_from_store_filters_by_age_and_severity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "a.jsonl")
            items = [
                dict(id="1", symbol="A", desc="x", severity="HIGH", published_at=ist(7, 9).isoformat()),
                dict(id="2", symbol="B", desc="x", severity="LOW", published_at=ist(7, 9).isoformat()),
                dict(id="3", symbol="C", desc="x", severity="HIGH", published_at=ist(1, 9).isoformat()),   # too old
            ]
            af.append_store(items, path)
            got = af.recent_from_store(10, 24, ist(7, 12), path)
            self.assertEqual([g["symbol"] for g in got], ["A"])


if __name__ == "__main__":
    unittest.main()
