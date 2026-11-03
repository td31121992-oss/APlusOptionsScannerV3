import json
import tempfile
import unittest
from pathlib import Path

import results_spike as rsp

H = 3600


class FilingTests(unittest.TestCase):
    def test_results_vs_other_filings(self):
        self.assertTrue(rsp.is_results({"desc": "Outcome of Board Meeting", "text": "submitted the financial results for the period ended September 30, 2026."}))
        self.assertFalse(rsp.is_results({"desc": "Press Release", "text": "Total income up 62%: financial results"}))
        self.assertFalse(rsp.is_results({"desc": "Allotment of Securities", "text": "allotment of equity shares"}))
        self.assertFalse(rsp.is_results({"desc": "Analysts/Institutional Investor Meet/Con. Call Updates", "text": "Presentation on results"}))

    def test_only_market_hours_are_kept(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            p = root.joinpath(*rsp.ANN)
            p.parent.mkdir(parents=True)
            rows = [{"symbol": "AAA", "desc": "Outcome of Board Meeting", "text": "financial results", "published_at": "2026-10-26T14:27:42+05:30"},
                    {"symbol": "BBB", "desc": "Outcome of Board Meeting", "text": "financial results", "published_at": "2026-10-26T18:05:00+05:30"},
                    {"symbol": "CCC", "desc": "Outcome of Board Meeting", "text": "financial results", "published_at": "2026-10-25T14:00:00+05:30"}]
            p.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
            self.assertEqual([f["symbol"] for f in rsp.results_filings("2026-10-26", root)], ["AAA"])


class SpikeTests(unittest.TestCase):
    def series(self, moves):
        """30-second samples from 14:10 to 14:50; `moves` = {sample index: price}, flat at 100 before and holding the last price after."""
        out, price = [], 100.0
        for i in range(80):
            price = moves.get(i, price)
            out.append((14 * H + 10 * 60 + i * 30.0, price, 1000.0 * i))
        return out

    def test_up_spike_found_after_the_filing(self):
        t_pub = 14 * H + 27 * 60
        sp = rsp.find_spike(self.series({36: 101.0, 37: 102.6}), t_pub)           # 14:28:00 and 14:28:30
        self.assertEqual(sp["direction"], "BULLISH")
        self.assertGreaterEqual(sp["spike_pct"], 2.0)

    def test_down_spike_and_no_spike(self):
        t_pub = 14 * H + 27 * 60
        self.assertEqual(rsp.find_spike(self.series({36: 99.0, 37: 97.5}), t_pub)["direction"], "BEARISH")
        self.assertNotIn("spike_t", rsp.find_spike(self.series({}), t_pub))
        self.assertEqual(rsp.find_spike([], t_pub), {})

    def test_volume_multiple(self):
        s = [(t * 60.0, 100.0, t * 100.0) for t in range(0, 60)]            # 100 per minute, steady
        self.assertAlmostEqual(rsp.volume_multiple(s, 50 * 60.0), 1.0, places=1)
        s2 = s[:45] + [(t * 60.0, 100.0, 4400 + (t - 44) * 400.0) for t in range(45, 60)]       # volume 4x per minute from minute 45
        self.assertGreater(rsp.volume_multiple(s2, 50 * 60.0), 2.0)


if __name__ == "__main__":
    unittest.main()
