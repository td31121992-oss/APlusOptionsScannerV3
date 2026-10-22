import sys
import types
import unittest
from types import SimpleNamespace
from unittest import mock

import stock_analysis_tab as sat


class FakeClient:
    made = []

    def __init__(self, dhan_cfg):
        self.token = dhan_cfg.token
        FakeClient.made.append(self.token)


class FakeLoader:
    def __init__(self, cfg):
        pass

    def load(self, force_refresh=False):
        return "universe"


def fake_modules(token_box, fail=False):
    class AppConfig:
        @staticmethod
        def from_env():
            if fail:
                raise RuntimeError("token check failed")
            return SimpleNamespace(dhan=SimpleNamespace(token=token_box["t"]))

    return {"config": types.SimpleNamespace(AppConfig=AppConfig), "core.dhan_client": types.SimpleNamespace(DhanClient=FakeClient),
            "core.instrument_loader": types.SimpleNamespace(InstrumentLoader=FakeLoader)}


class OptionChainTokenTests(unittest.TestCase):
    def setUp(self):
        sat._OPTION_CHAIN_CLIENT = sat._OPTION_CHAIN_LOADER = None
        sat._OPTION_CHAIN_BUILT_AT = 0.0
        FakeClient.made = []

    def test_client_is_rebuilt_with_the_new_token_after_the_refresh_interval(self):
        box = {"t": "yesterday"}
        with mock.patch.dict(sys.modules, fake_modules(box)), mock.patch.object(sat.time, "monotonic", side_effect=[1000.0, 1100.0, 1400.0]):
            c1, _ = sat._option_chain_runtime()          # first build at t=1000
            box["t"] = "today"                           # the 08:40 refresh renewed the token
            c2, _ = sat._option_chain_runtime()          # t=1100: inside 300 s, same client (still the old token)
            c3, _ = sat._option_chain_runtime()          # t=1400: older than 300 s, rebuilt with the new token
        self.assertEqual((c1.token, c2.token, c3.token), ("yesterday", "yesterday", "today"))
        self.assertEqual(FakeClient.made, ["yesterday", "today"])

    def test_a_failed_refresh_keeps_the_old_client_and_a_first_failure_still_raises(self):
        box = {"t": "old"}
        with mock.patch.dict(sys.modules, fake_modules(box)), mock.patch.object(sat.time, "monotonic", side_effect=[0.0, 500.0, 501.0]):
            c1, _ = sat._option_chain_runtime()
        with mock.patch.dict(sys.modules, fake_modules(box, fail=True)), mock.patch.object(sat.time, "monotonic", side_effect=[500.0, 501.0]):
            c2, _ = sat._option_chain_runtime()          # stale, refresh fails -> keeps serving with the old client
            c3, _ = sat._option_chain_runtime()          # 30-second back-off still counts: no second attempt storm
        self.assertIs(c2, c1)
        self.assertIs(c3, c1)
        sat._OPTION_CHAIN_CLIENT = sat._OPTION_CHAIN_LOADER = None
        with mock.patch.dict(sys.modules, fake_modules(box, fail=True)):
            with self.assertRaises(RuntimeError):
                sat._option_chain_runtime()


if __name__ == "__main__":
    unittest.main()
