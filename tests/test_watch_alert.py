import os
import tempfile
import unittest
from unittest import mock
from pathlib import Path

os.environ["TELEGRAM_ENABLED"] = "false"

import telegram_notifier
from tests.test_journal_costs_and_session_end import _journal, _open_trade


class Spy:
    def __init__(self):
        self.calls = []

    def notify_watch(self, trade, level, price):
        self.calls.append((level, price))


class WatchAlertTests(unittest.TestCase):
    def setUp(self):
        import paper_trade_journal
        patch = mock.patch.object(paper_trade_journal.PaperTradeJournal, "WATCH_LEVELS", (10.0, 20.0))       # these tests are about the 10 / 20 behaviour; the wider ladder has its own test
        patch.start()
        self.addCleanup(patch.stop)

    def test_fires_once_per_level(self):
        with tempfile.TemporaryDirectory() as tmp:
            j = _journal(tmp, "2026-10-14", [_open_trade(entry_price=10.0)])
            j.notifier = Spy()
            t = j.trades[0]
            j._watch_alert(t, 10.0, 10.5, 10.4)
            self.assertEqual(j.notifier.calls, [])
            j._watch_alert(t, 10.0, 11.05, 11.0)
            j._watch_alert(t, 10.0, 11.4, 11.3)
            self.assertEqual(j.notifier.calls, [(10.0, 11.0)])
            j._watch_alert(t, 10.0, 12.1, 12.0)
            self.assertEqual([c[0] for c in j.notifier.calls], [10.0, 20.0])

    def test_wider_profit_ladder_fires_each_level_once(self):
        import paper_trade_journal
        with mock.patch.object(paper_trade_journal.PaperTradeJournal, "WATCH_LEVELS", (5.0, 10.0, 20.0, 30.0, 50.0, 100.0)):
            with tempfile.TemporaryDirectory() as tmp:
                j = _journal(tmp, "2026-10-14", [_open_trade(entry_price=10.0)])
                j.notifier = Spy()
                t = j.trades[0]
                j._watch_alert(t, 10.0, 10.4, 10.3)
                self.assertEqual(j.notifier.calls, [])
                j._watch_alert(t, 10.0, 10.6, 10.5)
                j._watch_alert(t, 10.0, 10.6, 10.5)                                  # same peak again: nothing new
                self.assertEqual([c[0] for c in j.notifier.calls], [5.0])
                j._watch_alert(t, 10.0, 12.1, 12.0)                                  # a jump past several levels sends each once
                self.assertEqual([c[0] for c in j.notifier.calls], [5.0, 10.0, 20.0])
                j._watch_alert(t, 10.0, 13.1, 13.0)
                j._watch_alert(t, 10.0, 15.1, 15.0)
                j._watch_alert(t, 10.0, 20.1, 20.0)
                self.assertEqual([c[0] for c in j.notifier.calls], [5.0, 10.0, 20.0, 30.0, 50.0, 100.0])

    def test_message_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            n = telegram_notifier.TelegramPaperTradeNotifier(state_dir=Path(tmp))
            sent = []
            n._send = lambda event, text: sent.append((event, text)) or True
            n.notify_watch({"paper_trade_id": "X1", "symbol": "ABC", "option_type": "CE", "entry_price": 10, "highest_option_price": 11.2,
                            "stock_move_fav_pct": 0.8}, 10.0, 11.1)
            self.assertEqual(sent[0][0], "X1|WATCH10")
            self.assertIn("+10% in your favour", sent[0][1])
            self.assertIn("+0.80%", sent[0][1])


if __name__ == "__main__":
    unittest.main()
