import csv
import tempfile
import unittest
from pathlib import Path

from core import upstox_master as um

EXPIRY_MS = 1795458599000          # 2026-11-23 23:59:59 IST


def _master(extra_options: int = 0):
    rows = [
        {"segment": "NSE_EQ", "instrument_type": "EQ", "instrument_key": "NSE_EQ|INE002A01018", "exchange_token": "2885", "trading_symbol": "RELIANCE",
         "name": "Reliance Industries Ltd", "short_name": "Reliance", "tick_size": 10.0, "isin": "INE002A01018"},
        {"segment": "NSE_FO", "instrument_type": "CE", "exchange_token": "125951", "underlying_symbol": "RELIANCE", "underlying_key": "NSE_EQ|INE002A01018",
         "underlying_type": "EQUITY", "expiry": EXPIRY_MS, "lot_size": 500, "strike_price": 720.0, "tick_size": 5.0},
        {"segment": "NSE_FO", "instrument_type": "PE", "exchange_token": "125952", "underlying_symbol": "RELIANCE", "underlying_key": "NSE_EQ|INE002A01018",
         "underlying_type": "EQUITY", "expiry": EXPIRY_MS, "lot_size": 500, "strike_price": 172.5, "tick_size": 5.0},
        {"segment": "NSE_FO", "instrument_type": "FUT", "exchange_token": "61697", "underlying_symbol": "RELIANCE", "underlying_key": "NSE_EQ|INE002A01018",
         "underlying_type": "EQUITY", "expiry": EXPIRY_MS, "lot_size": 500, "tick_size": 10.0},
    ]
    return rows


class UpstoxMasterTests(unittest.TestCase):
    def test_rows_use_the_nse_exchange_token_as_the_security_id_and_the_dhan_layout(self):
        rows = {(r["INSTRUMENT"], r["SECURITY_ID"]): r for r in um.rows_from_upstox(_master())}
        eq = rows[("EQUITY", "2885")]
        self.assertEqual((eq["SEGMENT"], eq["INSTRUMENT_TYPE"], eq["SERIES"], eq["UNDERLYING_SYMBOL"]), ("E", "ES", "EQ", "RELIANCE"))
        ce = rows[("OPTSTK", "125951")]
        self.assertEqual((ce["UNDERLYING_SECURITY_ID"], ce["SM_EXPIRY_DATE"], ce["OPTION_TYPE"], ce["LOT_SIZE"], ce["STRIKE_PRICE"], ce["TICK_SIZE"]),
                         ("2885", "2026-11-23", "CE", 500.0, 720.0, 5.0))
        self.assertEqual(ce["SYMBOL_NAME"], "RELIANCE-Nov2026-720-CE")
        self.assertEqual(ce["DISPLAY_NAME"], "RELIANCE 23 NOV 720 CALL")
        self.assertEqual(rows[("OPTSTK", "125952")]["DISPLAY_NAME"], "RELIANCE 23 NOV 172.50 PUT")
        fut = rows[("FUTSTK", "61697")]
        self.assertEqual((fut["DISPLAY_NAME"], fut["OPTION_TYPE"], fut["SM_EXPIRY_DATE"]), ("RELIANCE NOV FUT", "XX", "2026-11-23"))

    def test_a_thin_master_never_overwrites_the_cached_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "master.csv"
            path.write_text("keep", encoding="utf-8")
            with self.assertRaises(RuntimeError):
                um.write_master_csv(_master(), path)
            self.assertEqual(path.read_text(encoding="utf-8"), "keep")

    def test_written_file_has_every_column_the_instrument_loader_requires(self):
        from core.instrument_loader import REQUIRED_COLUMNS

        big = _master()
        for i in range(10100):
            big.append({"segment": "NSE_FO", "instrument_type": "CE", "exchange_token": str(200000 + i), "underlying_symbol": "RELIANCE",
                        "underlying_key": "NSE_EQ|INE002A01018", "underlying_type": "EQUITY", "expiry": EXPIRY_MS, "lot_size": 500, "strike_price": 100.0 + i,
                        "tick_size": 5.0})
        for i in range(1100):
            big.append({"segment": "NSE_EQ", "instrument_type": "EQ", "instrument_key": f"NSE_EQ|X{i}", "exchange_token": str(900000 + i), "trading_symbol": f"X{i}",
                        "name": f"X{i}", "tick_size": 5.0})
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "master.csv"
            um.write_master_csv(big, path)
            with path.open(encoding="utf-8", newline="") as handle:
                header = next(csv.reader(handle))
        self.assertEqual([c for c in REQUIRED_COLUMNS if c not in header], [])


if __name__ == "__main__":
    unittest.main()
