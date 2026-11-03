import unittest

import fill_realism_report as fr


class FillRealismTests(unittest.TestCase):
    def test_summary_uses_only_trades_with_an_exit_quote(self):
        trades = [{"status": "CLOSED", "exit_bid": 8.6, "net_pnl": -1000, "net_pnl_at_bid": -1300, "entry_slip_pct": 1.0, "entry_spread_pct": 2.0, "exit_spread_pct": 4.0, "exit_bid_covers_qty": 0},
                  {"status": "CLOSED", "exit_bid": 12.0, "net_pnl": 500, "net_pnl_at_bid": 450, "entry_slip_pct": 3.0, "entry_spread_pct": 1.0, "exit_spread_pct": 2.0, "exit_bid_covers_qty": 1},
                  {"status": "CLOSED", "net_pnl": 999}, {"status": "OPEN", "exit_bid": 5}]
        s = fr.summarise(trades)
        self.assertEqual((s["closed"], s["with_exit_quote"], s["net_pnl"], s["net_pnl_at_bid"], s["difference"]), (3, 2, -500, -850, -350))
        self.assertEqual((s["avg_entry_slip_pct"], s["avg_exit_spread_pct"], s["bid_too_thin_pct"]), (2.0, 3.0, 50.0))

    def test_no_quotes_yet(self):
        self.assertEqual(fr.summarise([{"status": "CLOSED", "net_pnl": 1}]), {"closed": 1, "with_exit_quote": 0})


if __name__ == "__main__":
    unittest.main()
