from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import news_watch as nw

IST = ZoneInfo("Asia/Kolkata")


def ev(i, title, hours_ago, now, summary=""):
    t = (now - timedelta(hours=hours_ago)).astimezone(ZoneInfo("UTC"))
    return {"event_id": f"e{i}", "title": title, "summary": summary, "source": "Test News", "published_at_raw": t.strftime("%a, %d %b %Y %H:%M:%S GMT")}


def setup(tmp, events):
    d = Path(tmp, "data", "news_intelligence"); d.mkdir(parents=True)
    d.joinpath("events.jsonl").write_text("\n".join(json.dumps(e) for e in events), encoding="utf-8")
    return Path(tmp)


class WatchTests(unittest.TestCase):
    NOW = datetime(2026, 10, 9, 8, 30, tzinfo=IST)

    def test_matches_visa_story_about_it_firms_only(self) -> None:
        r = nw.RULES[0]
        self.assertTrue(nw.match_event({"title": "US suspends Infosys, TCS from PERM programme", "summary": "labour certification halted"}, r))
        self.assertFalse(nw.match_event({"title": "Infosys wins deal", "summary": ""}, r))                 # company but no visa topic
        self.assertFalse(nw.match_event({"title": "New H-1B rules for farm workers", "summary": ""}, r))   # topic but no IT company

    def test_sends_one_alert_per_rule_per_day_with_extra_count(self) -> None:
        sent = []
        with tempfile.TemporaryDirectory() as tmp:
            base = setup(tmp, [ev(1, "US suspends Infosys, Wipro from PERM programme", 2, self.NOW),
                               ev(2, "H-1B and green card curbs hit TCS, HCL", 1, self.NOW),
                               ev(3, "Unrelated market news", 1, self.NOW)])
            r1 = nw.scan(self.NOW, send=lambda m: (sent.append(m) or (True, "ok")), base=base)
            r2 = nw.scan(self.NOW + timedelta(minutes=5), send=lambda m: (sent.append(m) or (True, "ok")), base=base)
        self.assertEqual((r1["matched"], r1["sent"]), (2, 1))
        self.assertEqual(r2["sent"], 0)                                   # not repeated
        self.assertEqual(len(sent), 1)
        self.assertIn("+ 1 more headline", sent[0])
        self.assertIn("TCS", sent[0])

    def test_quiet_hours_queue_until_morning_and_old_news_is_ignored(self) -> None:
        sent = []
        night = datetime(2026, 10, 9, 2, 0, tzinfo=IST)
        with tempfile.TemporaryDirectory() as tmp:
            base = setup(tmp, [ev(1, "US suspends Infosys from PERM programme", 1, night), ev(2, "PERM suspension of TCS", 80, night)])
            r1 = nw.scan(night, send=lambda m: (sent.append(m) or (True, "ok")), base=base)
            self.assertEqual((r1["sent"], r1["queued"], len(sent)), (0, 1, 0))      # night: queued, 80-hour-old item ignored
            r2 = nw.scan(night.replace(hour=7, minute=5), send=lambda m: (sent.append(m) or (True, "ok")), base=base)
        self.assertEqual((r2["sent"], len(sent)), (1, 1))

    def test_missing_file_is_safe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIn("error", nw.scan(self.NOW, base=Path(tmp)))


if __name__ == "__main__":
    unittest.main()
