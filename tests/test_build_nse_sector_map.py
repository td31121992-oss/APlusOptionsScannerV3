import csv
import tempfile
import unittest
from pathlib import Path

import build_nse_sector_map as b


def write(folder, name, rows):
    with (folder / name).open("w", encoding="utf-8", newline="") as h:
        w = csv.writer(h)
        w.writerow(["Company Name", "Industry", "Symbol", "Series", "ISIN Code"])
        for sym, industry in rows:
            w.writerow([sym + " Ltd", industry, sym, "EQ", "INE000"])


class BuildTests(unittest.TestCase):
    def test_labels_follow_the_nse_files_and_manual_stocks_are_marked(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            write(folder, "ind_nifty500list.csv", [("HDFCBANK", "Financial Services"), ("SBIN", "Financial Services"), ("BAJFINANCE", "Financial Services"), ("BSE", "Financial Services"),
                                                   ("MARUTI", "Automobile and Auto Components"), ("BEL", "Capital Goods"), ("TCS", "Information Technology"), ("DLF", "Realty")])
            write(folder, "ind_nifty_privatebanklist.csv", [("HDFCBANK", "Financial Services")])
            write(folder, "ind_niftypsubanklist.csv", [("SBIN", "Financial Services")])
            write(folder, "ind_niftycapitalmarkets_list.csv", [("BSE", "Financial Services")])
            write(folder, "ind_niftyindiadefence_list.csv", [("BEL", "Capital Goods")])
            old = b.LISTS
            b.LISTS = folder
            try:
                rows = {r["symbol"]: r for r in b.build(["HDFCBANK", "SBIN", "BAJFINANCE", "BSE", "MARUTI", "BEL", "TCS", "DLF", "UJJIVANSFB", "NOSUCH"], {"MARUTI": "Consumer Durables"})}
            finally:
                b.LISTS = old
        label = {k: v["sector"] for k, v in rows.items()}
        self.assertEqual(label, {"HDFCBANK": "Private Banks", "SBIN": "PSU Banks", "BAJFINANCE": "NBFC & Insurance", "BSE": "Capital Markets", "MARUTI": "Auto", "BEL": "Defence",
                                 "TCS": "IT", "DLF": "Real Estate", "UJJIVANSFB": "Private Banks", "NOSUCH": "UNCLASSIFIED"})
        self.assertEqual(rows["MARUTI"]["old_sector"], "Consumer Durables")
        self.assertTrue(rows["UJJIVANSFB"]["source"].startswith("manual"))
        self.assertEqual(rows["HDFCBANK"]["source"], "NSE Private Banks index list")

    def test_every_label_the_scanner_can_now_produce_that_matters_has_an_index_mapping(self):
        import sector_rrg

        for label in ("Private Banks", "PSU Banks", "NBFC & Insurance", "Capital Markets", "Real Estate", "Auto", "IT"):
            self.assertIn(label, sector_rrg.SECTOR_TO_INDEX)

    def test_the_applied_map_covers_every_stock_the_scanner_trades(self):
        from order_book_recorder import _universe

        with (b.REF / "fno_sector_map.csv").open(encoding="utf-8-sig", newline="") as h:
            labels = {r["symbol"]: r["sector"] for r in csv.DictReader(h)}
        missing = [s for s in _universe() if s not in labels]
        self.assertEqual(missing, [])
        self.assertLessEqual(sum(1 for v in labels.values() if v == "UNCLASSIFIED"), 2)


if __name__ == "__main__":
    unittest.main()
