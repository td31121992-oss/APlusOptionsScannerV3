import unittest
from datetime import datetime, timedelta, timezone

import paper_trade_journal as pj

IST = timezone(timedelta(hours=5, minutes=30))


class Notifier:
    def __init__(self):
        self.calls = []

    def notify_hold_check(self, trade, mins, stock_since, price):
        self.calls.append((round(mins), round(stock_since, 2), price))


def make():
    j = pj.PaperTradeJournal.__new__(pj.PaperTradeJournal)
    j.notifier = Notifier()
    return j


def trade(**kw):
    peak_at = datetime(2026, 10, 16, 11, 0, tzinfo=IST).isoformat()
    t = {"entry_price": 100.0, "highest_option_price": 120.0, "highest_option_price_at": peak_at, "stock_at_high": 1000.0,
         "stock_at_high_for": peak_at, "option_type": "CE"}
    t.update(kw)
    return t


class HoldCheckTests(unittest.TestCase):
    def test_fires_once_when_stock_is_against_after_30_minutes(self):
        j, t = make(), trade()
        now = datetime(2026, 10, 16, 11, 40, tzinfo=IST)
        j._hold_check_alert(t, 994.0, 110.0, now)                      # stock -0.6% since the peak, 40 min later
        self.assertEqual(j.notifier.calls, [(40, -0.6, 110.0)])
        j._hold_check_alert(t, 990.0, 108.0, now + timedelta(minutes=5))
        self.assertEqual(len(j.notifier.calls), 1)                     # once per peak

    def test_rearms_after_a_new_peak(self):
        j, t = make(), trade()
        j._hold_check_alert(t, 994.0, 110.0, datetime(2026, 10, 16, 11, 40, tzinfo=IST))
        new_at = datetime(2026, 10, 16, 12, 0, tzinfo=IST).isoformat()
        t.update(highest_option_price=130.0, highest_option_price_at=new_at, stock_at_high=1010.0, stock_at_high_for=new_at)
        j._hold_check_alert(t, 1004.0, 120.0, datetime(2026, 10, 16, 12, 35, tzinfo=IST))
        self.assertEqual(len(j.notifier.calls), 2)

    def test_no_alert_when_too_early_or_stock_ok_or_small_peak(self):
        j = make()
        now = datetime(2026, 10, 16, 11, 40, tzinfo=IST)
        j._hold_check_alert(trade(), 994.0, 110.0, datetime(2026, 10, 16, 11, 20, tzinfo=IST))      # only 20 minutes
        j._hold_check_alert(trade(), 998.0, 110.0, now)                                              # stock only -0.2%
        j._hold_check_alert(trade(highest_option_price=108.0), 994.0, 104.0, now)                    # peak only +8%
        j._hold_check_alert(trade(), 994.0, 125.0, now)                                              # option above its recorded peak
        self.assertEqual(j.notifier.calls, [])

    def test_puts_use_the_other_direction(self):
        j = make()
        t = trade(option_type="PE")
        j._hold_check_alert(t, 1006.0, 110.0, datetime(2026, 10, 16, 11, 40, tzinfo=IST))           # stock UP 0.6% = against a put
        self.assertEqual(len(j.notifier.calls), 1)
        j2, t2 = make(), trade(option_type="PE")
        j2._hold_check_alert(t2, 994.0, 110.0, datetime(2026, 10, 16, 11, 40, tzinfo=IST))           # stock down = in favour of a put
        self.assertEqual(j2.notifier.calls, [])


if __name__ == "__main__":
    unittest.main()
