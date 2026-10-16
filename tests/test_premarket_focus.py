import csv
import json
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

import premarket_focus as pf


def bulk(root, now):
    return {"AAA": {"direction": "BULLISH", "confidence": "HIGH", "type": "RESULTS", "age_h": 3.0, "event_risk": True, "score": 6.0},
            "BBB": {"direction": "BEARISH", "confidence": "MEDIUM", "type": "RATING", "age_h": 10.0, "event_risk": False, "score": -2.0},
            "CCC": {"direction": "NEUTRAL", "confidence": "LOW", "type": "", "age_h": 1.0, "event_risk": True, "score": 0.0},
            "DDD": {"direction": "BULLISH", "confidence": "LOW", "type": "EVENT", "age_h": 2.0, "event_risk": False, "score": 1.6},
            "EEE": {"direction": "MIXED", "confidence": "LOW", "type": "RESULTS", "age_h": 5.0, "event_risk": True, "score": 0.0}}


def items(symbol, root, now):
    return {"items": [{"title": f"{symbol} headline", "dir": 1}]}


def setup(root: Path):
    sd = root / "data" / "safety"
    sd.mkdir(parents=True)
    with (sd / "corporate_events.csv").open("w", encoding="utf-8", newline="") as h:
        w = csv.DictWriter(h, fieldnames=["symbol", "event_date", "event_type", "severity", "as_of", "source", "notes"])
        w.writeheader()
        w.writerow({"symbol": "AAA", "event_date": "2026-10-19", "event_type": "FINANCIAL RESULTS", "severity": "HIGH", "as_of": "x", "source": "x", "notes": ""})
        w.writerow({"symbol": "ZZZ", "event_date": "2026-10-19", "event_type": "FINANCIAL RESULTS", "severity": "HIGH", "as_of": "x", "source": "x", "notes": ""})
        w.writerow({"symbol": "YYY", "event_date": "2026-10-16", "event_type": "FINANCIAL RESULTS", "severity": "HIGH", "as_of": "x", "source": "x", "notes": ""})


class FocusTests(unittest.TestCase):
    def test_build_ranks_and_filters(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            setup(root)
            p = pf.build("2026-10-19", root, bulk_fn=bulk, items_fn=items)
            syms = [f["symbol"] for f in p["focus"]]
            self.assertEqual(syms, ["AAA", "BBB"])                          # neutral, low-confidence and mixed are not on the list
            self.assertEqual(p["focus"][0]["rank"], 1)
            self.assertTrue(p["focus"][0]["results_today"])
            self.assertEqual(p["focus"][0]["headline"], "AAA headline")
            self.assertEqual(p["mixed"][0]["symbol"], "EEE")
            self.assertEqual(p["results_today"], ["AAA", "ZZZ"])
            self.assertIn("YYY", p["results_prev_evening"])                  # results on the previous trading day (Friday 16 Oct)

    def test_telegram_text_and_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            setup(root)
            p = pf.build("2026-10-19", root, bulk_fn=bulk, items_fn=items)
            text = pf.telegram_text(p)
            self.assertIn("PRE-MARKET FOCUS", text)
            self.assertIn("1. AAA", text)
            self.assertIn("[RESULTS TODAY]", text)
            self.assertIn("Trade only if", text)
            self.assertLessEqual(len(text), 3900)
            self.assertIn("/api/premarket-focus", pf.FOCUS_HTML)

    def test_save_payload_and_entry_tags(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            setup(root)
            p = pf.build(date.today().isoformat(), root, bulk_fn=bulk, items_fn=items)
            pf.save(p, root)
            self.assertTrue((root / "data" / "news_focus" / "latest.json").exists())
            self.assertEqual(pf.payload(root)["focus"][0]["symbol"], "AAA")
            self.assertEqual(pf.entry_tags("AAA", "BULLISH", root), {"nf_rank": 1, "nf_dir": "BULLISH", "nf_aligned": True})
            self.assertFalse(pf.entry_tags("AAA", "BEARISH", root)["nf_aligned"])
            self.assertEqual(pf.entry_tags("QQQ", "BULLISH", root), {"nf_rank": 0})
            self.assertEqual(pf.entry_tags("AAA", "BULLISH", Path(tmp) / "nothing"), {})

    def test_empty_day(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data" / "safety").mkdir(parents=True)
            p = pf.build("2026-10-19", root, bulk_fn=lambda r, n: {}, items_fn=items)
            self.assertIn("No stock has a clear", pf.telegram_text(p))


if __name__ == "__main__":
    unittest.main()
