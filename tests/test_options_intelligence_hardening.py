from __future__ import annotations

import unittest
import sys
import types
from datetime import datetime, time
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo


class _TestAppConfig:
    @classmethod
    def from_env(cls):
        raise AssertionError("Unit tests must not load runtime configuration")


class _TestDhanConfig:
    pass


_test_config = types.ModuleType("config")
_test_config.AppConfig = _TestAppConfig
_test_config.DhanConfig = _TestDhanConfig
_test_dhan_client = types.ModuleType("core.dhan_client")
_test_dhan_client.DhanClient = type("DhanClient", (), {})
_test_instrument_loader = types.ModuleType("core.instrument_loader")
_test_instrument_loader.InstrumentLoader = type("InstrumentLoader", (), {})

# config.py constructs CONFIG at import time and authenticates against Dhan.
# Replace only that module dependency while importing these pure helper paths;
# production configuration and authentication remain unchanged.
_DHAN_AUTH_PRELOADED = "dhan_auth" in sys.modules  # other tests in a full run may already have imported it
with patch.dict(
    sys.modules,
    {
        "config": _test_config,
        "core.dhan_client": _test_dhan_client,
        "core.instrument_loader": _test_instrument_loader,
    },
):
    from options_intelligence_data_layer import _safe_error, classify_failure, resolve_symbols
    from options_intelligence_runtime import (
        _cycle_status,
        _seconds_until,
        _should_reconnect_after_failed_cycle,
    )


class _Loader:
    def get_universe(self):
        return [SimpleNamespace(symbol=f"S{i}") for i in range(1, 41)]


class OptionsIntelligenceHardeningTests(unittest.TestCase):
    def test_import_uses_mocked_config_without_dhan_or_credential_access(self) -> None:
        self.assertIs(_TestAppConfig, _test_config.AppConfig)
        self.assertIsNot(sys.modules.get("config"), _test_config)
        # Importing the options-intelligence modules must not itself pull in dhan_auth.
        self.assertTrue(_DHAN_AUTH_PRELOADED or "dhan_auth" not in sys.modules)

    def test_explicit_and_default_symbol_lists_obey_configured_cap(self) -> None:
        loader = _Loader()
        explicit = resolve_symbols(loader, ",".join(f"S{i}" for i in range(1, 36)), 100)
        default = resolve_symbols(loader, "", 30)
        self.assertEqual(len(explicit), 30)
        self.assertEqual(len(default), 30)
        self.assertEqual(explicit[0], "S1")
        self.assertEqual(default[-1], "S30")

    def test_failure_classification_and_credential_redaction(self) -> None:
        self.assertEqual(classify_failure("HTTP 429 rate limit"), "RATE_LIMITED")
        self.assertEqual(classify_failure("HTTP 401 unauthorized"), "AUTHORIZATION")
        self.assertEqual(classify_failure("request timed out"), "TIMEOUT")
        self.assertEqual(classify_failure("Dhan returned blank response"), "EMPTY_RESPONSE")
        safe = _safe_error(RuntimeError("access_token=do-not-print socket timeout"))
        self.assertNotIn("do-not-print", safe)
        self.assertIn("[REDACTED]", safe)
        safe_header = _safe_error(RuntimeError("Authorization: Bearer do-not-print-this"))
        self.assertNotIn("do-not-print-this", safe_header)
        safe_id = _safe_error(RuntimeError("client_id=do-not-print-id"))
        self.assertNotIn("do-not-print-id", safe_id)

    def test_next_session_time_handles_month_end_and_weekends(self) -> None:
        ist = ZoneInfo("Asia/Kolkata")
        month_end = datetime(2026, 9, 30, 16, 0, tzinfo=ist)
        until = _seconds_until(month_end, time(9, 15))
        self.assertEqual(datetime.fromtimestamp(month_end.timestamp() + until, ist),
                         datetime(2026, 10, 1, 9, 15, tzinfo=ist))
        friday = datetime(2026, 10, 2, 16, 0, tzinfo=ist)
        until = _seconds_until(friday, time(9, 15))
        self.assertEqual(datetime.fromtimestamp(friday.timestamp() + until, ist),
                         datetime(2026, 10, 5, 9, 15, tzinfo=ist))

    def test_cycle_state_and_transient_reconnect_threshold(self) -> None:
        self.assertEqual(_cycle_status(30, 0), "HEALTHY")
        self.assertEqual(_cycle_status(25, 5), "DEGRADED")
        self.assertEqual(_cycle_status(0, 30), "FAILED")
        errors = [{"failure_type": "NETWORK"}]
        self.assertFalse(_should_reconnect_after_failed_cycle(1, errors))
        self.assertTrue(_should_reconnect_after_failed_cycle(2, errors))
        self.assertFalse(_should_reconnect_after_failed_cycle(2, [{"failure_type": "AUTHORIZATION"}]))


if __name__ == "__main__":
    unittest.main()
