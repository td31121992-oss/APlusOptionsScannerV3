import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ["TELEGRAM_ENABLED"] = "false"

import telegram_notifier
from tests.test_journal_costs_and_session_end import _journal, _open_trade


class Spy:
    def __init__(self):
        self.watch, self.give = [], []

    def notify_watch(self, trade, level, price):
        self.watch.append((level, price, trade.get("alert_stop_price"), trade.get("alert_ladder_price")))

    def notify_giveback(self, trade, level, price):
        self.give.append((level, price, trade.get("alert_stop_price")))


def journal(tmp, **over):
    j = _journal(tmp, "2026-10-14", [_open_trade(entry_price=10.0, option_stop=8.0, option_target1=12.0, option_target2=13.5, option_target3=15.0, **over)])
    j.notifier = Spy()
    return j, j.trades[0]


class StopLevelTests(unittest.TestCase):
    def test_old_rules_and_ladder_stops(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"APLUS_EXIT_LADDER_MODE": "SHADOW"}):
            j, t = journal(tmp)
            self.assertEqual(j._stop_levels(t, 10.0, 10.4), (8.0, 0.0))                     # nothing reached yet: initial stop, no ladder step
            stop, ladder = j._stop_levels(t, 10.0, 12.0)                                    # T1 (12.0) reached on this very check: stop already at entry; ladder +20% locks +13%
            self.assertEqual((stop, round(ladder, 2)), (10.0, 11.3))
            self.assertEqual(round(j._stop_levels(t, 10.0, 13.6)[0], 2), 10.8)              # T2 -> +8%
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"APLUS_EXIT_LADDER_MODE": "ENFORCE"}):
            j, t = journal(tmp)
            self.assertEqual(round(j._stop_levels(t, 10.0, 11.0)[0], 2), 10.3)               # +10% -> locks +3%
            self.assertEqual(round(j._stop_levels(t, 10.0, 10.6)[0], 2), 8.5)                # +5% -> -15% beats the initial stop
            t["manual_stop"] = 11.0
            self.assertEqual(j._stop_levels(t, 10.0, 10.6)[0], 11.0)                          # a manual stop only ever tightens


class GivebackTests(unittest.TestCase):
    def setUp(self):
        import paper_trade_journal
        patch = mock.patch.object(paper_trade_journal.PaperTradeJournal, "WATCH_LEVELS", (10.0, 20.0))       # these tests are about the 10 / 20 behaviour; the wider ladder has its own test
        patch.start()
        self.addCleanup(patch.stop)

    def test_fires_once_per_level_and_carries_the_stop(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"APLUS_EXIT_LADDER_MODE": "ENFORCE"}):
            j, t = journal(tmp)
            j._giveback_alert(t, 10.0, 10.8, 10.2)                                            # never reached +10%: silent
            j._giveback_alert(t, 10.0, 11.2, 11.1)                                            # +12% peak, gave back 8%: silent
            self.assertEqual(j.notifier.give, [])
            j._giveback_alert(t, 10.0, 11.2, 10.7)                                            # 58% of the 1.2 gain gone
            self.assertEqual(len(j.notifier.give), 1)
            level, price, stop = j.notifier.give[0]
            self.assertEqual((level, price, round(stop, 2)), (0.4, 10.7, 10.3))              # stop in force: ladder +10% -> +3%
            j._giveback_alert(t, 10.0, 11.2, 10.65)                                           # same level again: no repeat
            self.assertEqual(len(j.notifier.give), 1)
            j._giveback_alert(t, 10.0, 11.2, 10.35)                                           # 71% gone -> the 70% level
            self.assertEqual([g[0] for g in j.notifier.give], [0.4, 0.7])

    def test_gap_through_both_levels_sends_one_alert_and_exit_cases_stay_quiet(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"APLUS_EXIT_LADDER_MODE": "ENFORCE"}):
            j, t = journal(tmp)
            j._giveback_alert(t, 10.0, 11.2, 10.35)                                           # 71% gone in one jump: one alert, for the higher level
            self.assertEqual([g[0] for g in j.notifier.give], [0.7])
            self.assertTrue(t.get("giveback40_at") and t.get("giveback70_at"))                 # and the lower level is marked so it never fires later
            j2, t2 = journal(tmp)
            j2._giveback_alert(t2, 10.0, 11.2, 10.25)                                         # at or below the +3% stop (10.3): the exit message covers it
            self.assertEqual(j2.notifier.give, [])

    def test_switch_off(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"APLUS_GIVEBACK_ALERT": "off"}):
            j, t = journal(tmp)
            j._giveback_alert(t, 10.0, 11.2, 10.4)
            self.assertEqual(j.notifier.give, [])

    def test_watch_alert_carries_the_stop(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"APLUS_EXIT_LADDER_MODE": "SHADOW"}):
            j, t = journal(tmp)
            j._watch_alert(t, 10.0, 12.1, 12.0)
            self.assertEqual([(w[0], w[1], round(w[2], 2), round(w[3], 2)) for w in j.notifier.watch], [(10.0, 12.0, 10.0, 11.3), (20.0, 12.0, 10.0, 11.3)])

    def test_runs_inside_a_real_price_update(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"APLUS_EXIT_LADDER_MODE": "ENFORCE"}):
            from datetime import datetime
            from zoneinfo import ZoneInfo
            T = lambda s: datetime(2026, 10, 14, 10, 1, s, tzinfo=ZoneInfo("Asia/Kolkata"))
            j, t = journal(tmp, entry_time="2026-10-14T10:00:00+05:30")
            for i, p in enumerate([11.2, 11.0, 10.7, 10.55]):
                j.update_open_positions(option_quotes={"123": {"last_price": p}}, when=T(i))
            self.assertEqual(len(j.notifier.watch), 1)
            self.assertEqual([g[0] for g in j.notifier.give], [0.4])                          # 11.2 -> 10.7 hands back 58%; 10.55 (46%) is the same level


class MessageTests(unittest.TestCase):
    def test_texts(self):
        with tempfile.TemporaryDirectory() as tmp:
            n = telegram_notifier.TelegramPaperTradeNotifier(state_dir=Path(tmp))
            sent = []
            n._send = lambda event, text: sent.append((event, text)) or True
            base = {"paper_trade_id": "X1", "symbol": "BHEL", "option_type": "PE", "entry_price": 13.4, "highest_option_price": 15.65, "stock_move_fav_pct": 0.8,
                    "alert_stop_price": 13.8, "alert_ladder_price": 13.8}
            n.notify_watch(base, 10.0, 15.0)
            self.assertIn("Stop now", sent[0][1])
            self.assertIn("+3.0% vs entry", sent[0][1])
            self.assertIn("Your ladder locks", sent[0][1])
            n.notify_giveback(base, 0.4, 14.4)
            event, text = sent[1]
            self.assertEqual(event, "X1|GIVEBACK40")
            self.assertIn("GIVING BACK", text)
            self.assertIn("handed back 56%", text)
            self.assertIn("The stop is 4.2% below the price", text)
            n.notify_giveback({**base, "alert_stop_price": 0, "alert_ladder_price": 0}, 0.7, 14.4)
            self.assertIn("No profit-protection stop is set yet", sent[2][1])
            n.notify_watch({k: v for k, v in base.items() if not k.startswith("alert_")}, 20.0, 15.0)
            self.assertNotIn("Stop now", sent[3][1])                                          # older records without the fields still work


if __name__ == "__main__":
    unittest.main()
