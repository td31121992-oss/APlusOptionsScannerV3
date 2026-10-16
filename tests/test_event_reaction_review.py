import csv
import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

import event_reaction_review as er


def stock(start, path):
    closes = (list(path) + [path[-1]] * 48)[:48]
    opens = [start] + closes[:-1]
    return {"minute": [555 + 5 * i for i in range(48)], "open": opens, "close": closes,
            "high": [max(o, c) * 1.001 for o, c in zip(opens, closes)], "low": [min(o, c) * 0.999 for o, c in zip(opens, closes)], "volume": [1000.0] * 48}


def setup(root: Path):
    cd = root / "data" / "pattern_log" / "candles"
    cd.mkdir(parents=True)
    (cd / "2026-10-16.json").write_text(json.dumps({"symbols": {"AAA": stock(100, [100]), "BBB": stock(100, [100]), "CCC": stock(100, [100])}}), encoding="utf-8")
    (cd / "2026-10-19.json").write_text(json.dumps({"symbols": {
        "AAA": stock(103, [103.5, 104, 105, 106]),          # gapped up 3% and kept going
        "BBB": stock(96, [95.5, 95, 94, 93]),               # gapped down 4% and kept going
        "CCC": stock(101, [100.5, 100, 100])}}), encoding="utf-8")   # no event
    sd = root / "data" / "safety"
    sd.mkdir(parents=True)
    with (sd / "corporate_events.csv").open("w", encoding="utf-8", newline="") as h:
        w = csv.DictWriter(h, fieldnames=["symbol", "event_date", "event_type", "severity", "as_of", "source", "notes"])
        w.writeheader()
        w.writerow({"symbol": "AAA", "event_date": "2026-10-19", "event_type": "FINANCIAL RESULTS", "severity": "HIGH", "as_of": "2026-10-18", "source": "x", "notes": ""})
        w.writerow({"symbol": "BBB", "event_date": "2026-10-16", "event_type": "FINANCIAL RESULTS", "severity": "HIGH", "as_of": "2026-10-18", "source": "x", "notes": ""})


class EventReactionTests(unittest.TestCase):
    def test_archive_keeps_the_calendar(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            setup(root)
            dst = er.archive(root)
            self.assertEqual(dst.name, "2026-10-18.csv")
            (root / "data" / "safety" / "corporate_events.csv").write_text("symbol,event_date,event_type,severity,as_of,source,notes\n", encoding="utf-8")   # calendar overwritten
            self.assertIn(("AAA", "2026-10-19"), er.load_events(root))                                              # the archive still has it

    def test_reaction_rows_for_event_date_and_day_after(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            setup(root)
            er.archive(root)
            path = er.run("2026-10-19", root, lambda sid, day: [], pd.DataFrame(columns=["SECURITY_ID", "INSTRUMENT", "UNDERLYING_SYMBOL", "SM_EXPIRY_DATE", "STRIKE_PRICE", "OPTION_TYPE"]))
            with path.open(encoding="utf-8") as h:
                rows = {r["symbol"]: r for r in csv.DictReader(h)}
            self.assertEqual(set(rows), {"AAA", "BBB"})                             # CCC has no event; BBB's was on 16 Oct = the previous trading day
            self.assertEqual(rows["AAA"]["offset"], "D")
            self.assertEqual(rows["BBB"]["offset"], "D+1")
            self.assertAlmostEqual(float(rows["BBB"]["gap_pct"]), -4.0, places=1)
            self.assertAlmostEqual(float(rows["AAA"]["gap_pct"]), 3.0, places=1)
            self.assertEqual(rows["AAA"]["continued"], "1")
            self.assertIn("Results / event reaction", (root / "data" / "shadow_rules" / "event_reaction.md").read_text(encoding="utf-8"))

    def test_day_after_is_matched(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            setup(root)
            events = er.load_events(root)
            syms = json.loads((root / "data" / "pattern_log" / "candles" / "2026-10-19.json").read_text(encoding="utf-8"))["symbols"]
            rows = er.reaction_rows("2026-10-19", syms, {"AAA": 100.0, "BBB": 100.0, "CCC": 100.0}, events, "2026-10-16")
            by = {r["symbol"]: r for r in rows}
            self.assertEqual(by["BBB"]["offset"], "D+1")
            self.assertEqual(by["BBB"]["dir"], "BEARISH")
            self.assertEqual(by["BBB"]["continued"], 1)                             # fell further after gapping down

    def test_no_candles_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(er.run("2026-10-19", Path(tmp)))


if __name__ == "__main__":
    unittest.main()
