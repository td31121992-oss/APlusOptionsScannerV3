import unittest
from datetime import datetime
from types import SimpleNamespace

import mover_rank
from paper_trade_journal import PaperTradeJournal


def quotes(moves):
    return {s: (100.0 * (1 + m / 100.0), 100.0) for s, m in moves.items()}


class RankTests(unittest.TestCase):
    def test_gainer_and_loser_ranks(self):
        r = mover_rank.ranks_from_quotes(quotes({"A": 3.0, "B": 1.0, "C": -1.0, "D": -4.0}))
        self.assertEqual((r["A"]["gain"], r["A"]["loss"]), (1, 4))
        self.assertEqual((r["D"]["gain"], r["D"]["loss"]), (4, 1))
        self.assertEqual(r["C"]["n"], 4)
        self.assertEqual(mover_rank.ranks_from_quotes({"X": (0, 100.0)}), {})

    def test_put_rank_path_entry_best_and_close(self):
        fake = SimpleNamespace(trades=[{"symbol": "D", "direction": "BEARISH", "status": "OPEN"}])
        t = fake.trades[0]
        when = lambda m: datetime(2026, 10, 21, 10, m)
        # 3rd biggest loser at entry, then 1st, then 2nd when the trade closes
        for minute, loss_rank in ((1, 3), (2, 3), (5, 1), (9, 2)):
            ranks = {"D": {"gain": 10 - loss_rank, "loss": loss_rank, "from_open": -2.0, "n": 9}}
            if minute == 9:
                t["status"] = "CLOSED"
            PaperTradeJournal.record_stock_rank(fake, ranks, when(minute), extra=[t] if minute == 9 else [])
        self.assertEqual((t["rank_side"], t["rank_entry"], t["rank_best"], t["rank_worst"], t["rank_close"], t["rank_now"]), ("LOSERS", 3, 1, 3, 2, 2))
        self.assertEqual([p[1] for p in t["rank_path"]], [3, 1, 2])                 # only changes are kept
        ranks = {"D": {"gain": 1, "loss": 9, "n": 9}}
        PaperTradeJournal.record_stock_rank(fake, ranks, when(20), extra=[t])        # a later look must not move the close rank
        self.assertEqual(t["rank_close"], 2)

    def test_call_uses_the_gainer_rank_and_unknown_symbols_are_skipped(self):
        fake = SimpleNamespace(trades=[{"symbol": "A", "direction": "BULLISH", "status": "OPEN"}, {"symbol": "ZZZ", "direction": "BULLISH", "status": "OPEN"}])
        n = PaperTradeJournal.record_stock_rank(fake, mover_rank.ranks_from_quotes(quotes({"A": 3.0, "B": 1.0})), datetime(2026, 10, 21, 10, 0))
        self.assertEqual((n, fake.trades[0]["rank_side"], fake.trades[0]["rank_entry"]), (1, "GAINERS", 1))
        self.assertNotIn("rank_entry", fake.trades[1])


if __name__ == "__main__":
    unittest.main()
