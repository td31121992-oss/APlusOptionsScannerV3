import os
import tempfile
import unittest
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
