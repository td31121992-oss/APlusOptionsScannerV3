import unittest

import index_strip
import sector_rrg
import trading_mode
from core.upstox_client import INDEX_KEYS


class IndexCoverageTests(unittest.TestCase):
    def test_every_dhan_index_id_in_use_has_an_upstox_key(self):
        ids = {str(i) for i, _ in index_strip.ALL} | {str(i) for i in sector_rrg.INDICES.values()}
        self.assertEqual(sorted(ids - set(INDEX_KEYS)), [])

    def test_live_switch_stays_refused_without_a_broker_when_upstox_only(self):
        from unittest import mock

        with mock.patch.dict("os.environ", {"APLUS_DATA_PROVIDER": "UPSTOX"}, clear=False):
            self.assertFalse(trading_mode.broker_check()["connected"])


if __name__ == "__main__":
    unittest.main()
