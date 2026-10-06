from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from scanner_authorization_state import scanner_authorization_is_blocked
from validate_market_data_authorization import positive_ltp, validate_and_record

IST = ZoneInfo("Asia/Kolkata")
GOOD = {"data": {"NSE_EQ": {"2885": {"last_price": 1234.5}}}, "status": "success"}


class AuthorizationRevalidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.runtime = self.dir / "scanner_runtime_health.json"
        self.validation = self.dir / "market_data_authorization_validation.json"

    def _fail_at(self, when: datetime) -> None:
        self.runtime.write_text(
            json.dumps({"status": "AUTHORIZATION_FAILED", "updated_at": when.isoformat()}),
            encoding="utf-8",
        )

    def test_positive_ltp_parsing(self) -> None:
        self.assertTrue(positive_ltp(GOOD))
        self.assertFalse(positive_ltp({"data": {"NSE_EQ": {"2885": {"last_price": 0}}}}))
        self.assertFalse(positive_ltp({"data": {}}))
        self.assertFalse(positive_ltp(None))

    def test_successful_probe_unblocks_scanner_after_failure(self) -> None:
        failed = datetime.now(IST) - timedelta(minutes=5)
        self._fail_at(failed)
        self.assertTrue(scanner_authorization_is_blocked(self.runtime, self.validation))
        ok = validate_and_record("tok", "cid", self.validation, fetch=lambda t, c: GOOD)
        self.assertTrue(ok)
        self.assertFalse(scanner_authorization_is_blocked(self.runtime, self.validation))

    def test_failed_or_empty_probe_leaves_latch_blocked_and_writes_nothing(self) -> None:
        self._fail_at(datetime.now(IST) - timedelta(minutes=5))

        def boom(token: str, client_id: str):
            raise RuntimeError("401")

        self.assertFalse(validate_and_record("tok", "cid", self.validation, fetch=boom))
        self.assertFalse(validate_and_record("tok", "cid", self.validation, fetch=lambda t, c: {"data": {}}))
        self.assertFalse(self.validation.exists())
        self.assertTrue(scanner_authorization_is_blocked(self.runtime, self.validation))

    def test_validation_older_than_failure_does_not_unblock(self) -> None:
        old = datetime.now(IST) - timedelta(hours=1)
        validate_and_record("tok", "cid", self.validation, fetch=lambda t, c: GOOD, now=old)
        self._fail_at(datetime.now(IST))
        self.assertTrue(scanner_authorization_is_blocked(self.runtime, self.validation))

    def test_token_never_printed(self) -> None:
        import contextlib
        import io

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            validate_and_record("SECRET-TOKEN-123", "cid", self.validation, fetch=lambda t, c: GOOD)
        self.assertNotIn("SECRET-TOKEN-123", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
