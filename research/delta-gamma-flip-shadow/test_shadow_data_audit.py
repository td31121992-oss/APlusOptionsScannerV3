import json
import tempfile
import unittest
from pathlib import Path

from shadow_data_audit import audit


class ShadowDataAuditTests(unittest.TestCase):
    def test_reconciles_matching_csv_and_json_history(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            reports = root / "data" / "reports"
            reports.mkdir(parents=True)
            rows = [
                {"paper_trade_id": "PT-1", "status": "CLOSED"},
                {"paper_trade_id": "PT-2", "status": "OPEN"},
            ]
            (reports / "paper_trade_history.csv").write_text(
                "paper_trade_id,status\nPT-1,CLOSED\nPT-2,OPEN\n", encoding="utf-8"
            )
            (reports / "paper_trade_history.json").write_text(
                json.dumps({"trade_count": 2, "paper_trades": rows}), encoding="utf-8"
            )
            day = root / "data" / "options_intelligence" / "2026-10-22"
            day.mkdir(parents=True)
            snapshot = {"metadata": {"captured_at": "2026-10-22T09:30:00+05:30", "symbol": "TCS"}, "rows": []}
            (day / "option_chain_snapshots.jsonl").write_text(json.dumps(snapshot) + "\n", encoding="utf-8")
            result = audit(root)
            self.assertEqual(len(result["ledgers"]), 2)
            self.assertTrue(result["history_reconciliation"][0]["ids_match"])
            self.assertTrue(result["history_reconciliation"][0]["count_match"])
            self.assertTrue(result["ledger_integrity_ok"])
            self.assertTrue(result["ready_for_strategy_replay"])

    def test_flags_duplicate_and_blank_ids(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            reports = root / "data" / "reports"
            reports.mkdir(parents=True)
            (reports / "paper_trades.csv").write_text(
                "paper_trade_id,status\nPT-1,CLOSED\nPT-1,OPEN\n,OPEN\n", encoding="utf-8"
            )
            result = audit(root)
            ledger = result["ledgers"][0]
            self.assertEqual(ledger["duplicate_ids"], 1)
            self.assertEqual(ledger["blank_ids"], 1)
            self.assertFalse(result["ledger_integrity_ok"])
            self.assertFalse(result["ready_for_strategy_replay"])

    def test_reads_option_chain_jsonl_coverage(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            day = root / "data" / "options_intelligence" / "2026-10-22"
            day.mkdir(parents=True)
            payload = {"metadata": {"captured_at": "2026-10-22T09:30:00+05:30", "symbol": "TCS"}, "rows": []}
            (day / "option_chain_snapshots.jsonl").write_text(json.dumps(payload) + "\n", encoding="utf-8")
            result = audit(root)
            self.assertEqual(result["snapshot_coverage"]["valid_records"], 1)
            self.assertEqual(result["snapshot_coverage"]["dates"], ["2026-10-22"])
            self.assertEqual(result["snapshot_coverage"]["symbols"], ["TCS"])
            self.assertFalse(result["ready_for_strategy_replay"])

    def test_missing_runtime_data_is_reported_not_invented(self):
        with tempfile.TemporaryDirectory() as temp:
            result = audit(Path(temp))
            self.assertEqual(result["ledgers"], [])
            self.assertEqual(result["snapshot_coverage"]["valid_records"], 0)
            self.assertFalse(result["ledger_integrity_ok"])
            self.assertFalse(result["ready_for_strategy_replay"])


if __name__ == "__main__":
    unittest.main()
