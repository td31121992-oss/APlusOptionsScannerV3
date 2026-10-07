from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

import options_history as oh
from download_expired_options import write_atomic_gz

T0 = 1788234300          # an IST morning timestamp in Sep 2026


def _payload(side_key: str, stamps: list[int], strike: float = 1280.0) -> dict:
    n = len(stamps)
    blk = {"timestamp": stamps, "open": [10.0] * n, "high": [11.0] * n, "low": [9.0] * n, "close": [10.5] * n,
           "volume": [100] * n, "oi": [5000] * n, "iv": [17.5] * n, "strike": [strike] * n, "spot": [1284.0] * n}
    return {"http": 200, "candles": n, "response": {"data": {side_key: blk, ("pe" if side_key == "ce" else "ce"): None}}}


class LoaderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_concatenates_windows_sorted_and_deduplicated(self) -> None:
        write_atomic_gz(self.root / "TCS" / "2026-09-01" / "1_CE_ATM.json.gz", _payload("ce", [T0, T0 + 300, T0 + 600]))
        write_atomic_gz(self.root / "TCS" / "2026-10-01" / "1_CE_ATM.json.gz", _payload("ce", [T0 + 600, T0 + 86400 * 30]))
        df = oh.load_series("tcs", "CALL", 0, root=self.root)
        self.assertEqual(len(df), 4)                                   # one duplicate timestamp removed
        self.assertTrue(df.index.is_monotonic_increasing)
        self.assertEqual(str(df.index.tz), "UTC+05:30")
        self.assertEqual(list(df.columns), oh.COLUMNS)
        self.assertEqual(df["iv"].iloc[0], 17.5)

    def test_puts_and_offsets_use_their_own_files(self) -> None:
        write_atomic_gz(self.root / "TCS" / "2026-09-01" / "1_PE_ATM-2.json.gz", _payload("pe", [T0], 1250.0))
        self.assertEqual(len(oh.load_series("TCS", "PUT", -2, root=self.root)), 1)
        self.assertEqual(len(oh.load_series("TCS", "CALL", -2, root=self.root)), 0)
        self.assertEqual(len(oh.load_series("TCS", "PUT", 0, root=self.root)), 0)

    def test_date_filter_and_missing_symbol(self) -> None:
        write_atomic_gz(self.root / "TCS" / "2026-09-01" / "1_CE_ATM.json.gz", _payload("ce", [T0, T0 + 86400 * 5]))
        d0 = date.fromtimestamp(T0)
        only_first = oh.load_series("TCS", "CALL", 0, start=d0, end=d0, root=self.root)
        self.assertEqual(len(only_first), 1)
        self.assertTrue(oh.load_series("NOPE", "CALL", 0, root=self.root).empty)

    def test_invalid_side_and_empty_windows(self) -> None:
        with self.assertRaises(ValueError):
            oh.load_series("TCS", "SPREAD", 0, root=self.root)
        write_atomic_gz(self.root / "TCS" / "2022-09-05" / "1_CE_ATM.json.gz", _payload("ce", []))     # recorded-empty window
        self.assertTrue(oh.load_series("TCS", "CALL", 0, root=self.root).empty)

    def test_coverage_counts_windows_with_data(self) -> None:
        write_atomic_gz(self.root / "TCS" / "2026-09-01" / "1_CE_ATM.json.gz", _payload("ce", [T0]))
        write_atomic_gz(self.root / "TCS" / "2022-09-05" / "1_CE_ATM.json.gz", _payload("ce", []))
        cov = oh.coverage(self.root)
        row = cov.iloc[0]
        self.assertEqual((row["symbol"], row["windows_stored"], row["windows_with_data"]), ("TCS", 2, 1))


if __name__ == "__main__":
    unittest.main()
