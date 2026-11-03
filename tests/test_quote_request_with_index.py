from __future__ import annotations

import unittest

import market_context
from core.dhan_client import DhanClient


class QuoteRequestWithIndexTests(unittest.TestCase):
    def test_index_segment_batches_alongside_string_ids(self) -> None:
        request = {"NSE_EQ": ["2885", "1333"], "NSE_FNO": ["55555"]}   # scanner passes string ids
        market_context.add_to_request(request)
        batches = DhanClient._instrument_batches(request, max_batch_size=1000)
        self.assertEqual(len(batches), 1)                  # still ONE api call
        self.assertEqual(sorted(batches[0]["IDX_I"]), [13, 21, 25])
        self.assertEqual(sorted(batches[0]["NSE_EQ"]), [1333, 2885])


if __name__ == "__main__":
    unittest.main()
