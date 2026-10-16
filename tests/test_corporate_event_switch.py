import csv
import os
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from safety_gate import GateStatus, SafetyGateConfig, SafetyGateEngine


def engine(tmp: Path) -> SafetyGateEngine:
    with (tmp / "corporate_events.csv").open("w", encoding="utf-8", newline="") as h:
        w = csv.DictWriter(h, fieldnames=["symbol", "event_date", "event_type", "severity", "as_of", "source", "notes"])
        w.writeheader()
        w.writerow({"symbol": "AAA", "event_date": date.today().isoformat(), "event_type": "FINANCIAL RESULTS", "severity": "HIGH", "as_of": date.today().isoformat(),
                    "source": "test", "notes": ""})
    e = SafetyGateEngine.__new__(SafetyGateEngine)
    e.safety_dir = tmp
    e.config = SafetyGateConfig()
    return e


class CorporateEventSwitchTests(unittest.TestCase):
    def test_blocks_by_default(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("APLUS_CORPORATE_EVENT_BLOCK", None)
            c = engine(Path(tmp))._corporate_event_check("AAA", date.today())
            self.assertEqual(c.status, GateStatus.BLOCK)

    def test_switch_off_lets_event_stocks_through(self):
        with tempfile.TemporaryDirectory() as tmp:
            for value in ("0", "off", "FALSE", "no"):
                with mock.patch.dict(os.environ, {"APLUS_CORPORATE_EVENT_BLOCK": value}):
                    c = engine(Path(tmp))._corporate_event_check("AAA", date.today())
                    self.assertEqual(c.status, GateStatus.PASS, value)
                    self.assertIn("switched off", c.message)

    def test_switch_on_values_keep_the_block(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"APLUS_CORPORATE_EVENT_BLOCK": "1"}):
            self.assertEqual(engine(Path(tmp))._corporate_event_check("AAA", date.today()).status, GateStatus.BLOCK)


if __name__ == "__main__":
    unittest.main()
