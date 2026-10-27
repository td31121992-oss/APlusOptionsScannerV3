import unittest
from scripts.download_upstox_market_data import ROOT, OUT

class UpstoxDownloaderTests(unittest.TestCase):
    def test_output_is_inside_project_data_directory(self):
        self.assertEqual(OUT.parent, ROOT / "data")
        self.assertEqual(OUT.name, "upstox_market_data")

if __name__ == "__main__":
    unittest.main()
