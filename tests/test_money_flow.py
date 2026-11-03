import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

import money_flow as mf

HEAD = "time,symbol,ltp,volume,imbalance\n"


def line(hhmm, sym, ltp, vol, imb=0.0):
    return f"2026-10-09T{hhmm}:00+05:30,{sym},{ltp},{vol},{imb}\n"


class FlowTests(unittest.TestCase):
    def test_tick_rule_buy_sell_and_flat_keeps_direction(self):
        st = {}
        mf.step(st, "AAA", "09:20", 100.0, 1000, 0.0)
        mf.step(st, "AAA", "09:21", 101.0, 2000, 0.0)        # up-tick: 1000 shares bought at ~100.5
        mf.step(st, "AAA", "09:22", 101.0, 2500, 0.0)        # flat: keeps buying
        mf.step(st, "AAA", "09:23", 100.0, 3000, 0.0)        # down-tick: 500 shares sold
        ev = st["AAA"]["ev"]
        self.assertEqual([(round(b), round(s)) for _t, b, s in ev], [(100500, 0), (50500, 0), (0, 50250)])

    def test_volume_glitch_is_ignored(self):
        st = {}
        mf.step(st, "AAA", "09:20", 100.0, 5000, 0.0)
        mf.step(st, "AAA", "09:21", 101.0, 100, 0.0)          # volume went backwards: no event
        self.assertEqual(st["AAA"]["ev"], [])

    def _root(self, body, sectors="symbol,sector\nAAA,Metals\nBBB,Metals\nCCC,IT\n"):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / "data" / "order_book").mkdir(parents=True)
        (root / "data" / "reference").mkdir(parents=True)
        (root / "data" / "reports").mkdir(parents=True)
        (root / "data" / "order_book" / "2026-10-09.csv").write_text(HEAD + body, encoding="utf-8")
        (root / "data" / "reference" / "fno_sector_map.csv").write_text(sectors, encoding="utf-8")
        (root / "data" / "reports" / "fno_market_watch_latest.json").write_text(json.dumps({"rows": [
            {"symbol": "AAA", "previous_close": 100.0, "sector": "Metals"}, {"symbol": "CCC", "previous_close": 50.0, "sector": "IT"}]}), encoding="utf-8")
        mf._reset("x")
        return root

    def test_sector_aggregation_windows_and_ranking(self):
        body = "".join([line("09:20", "AAA", 100, 0), line("09:21", "BBB", 200, 0), line("09:20", "CCC", 50, 0),
                         line("09:30", "AAA", 101, 100000), line("09:30", "BBB", 199, 10000), line("09:30", "CCC", 49, 200000),
                         line("10:30", "AAA", 102, 200000), line("10:30", "CCC", 48, 300000)])
        root = self._root(body)
        out = mf.payload(0, root, date(2026, 10, 9))
        names = [s["sector"] for s in out["sectors"]]
        self.assertEqual(names[0], "Metals")                  # net buying
        self.assertEqual(names[-1], "IT")                     # net selling
        self.assertGreater(out["sectors"][0]["net_cr"], 0)
        self.assertLess(out["sectors"][-1]["net_cr"], 0)
        last = mf.payload(60, root, date(2026, 10, 9))        # last hour only: since 09:30 so the 09:30 readings fall out
        self.assertEqual(last["as_of"], "10:30")
        self.assertLess(last["market"]["buy_cr"] + last["market"]["sell_cr"], out["market"]["buy_cr"] + out["market"]["sell_cr"])
        aaa = next(s for s in out["stocks"] if s["symbol"] == "AAA")
        self.assertEqual(aaa["chg_pct"], 2.0)

    def test_no_data_message(self):
        mf._reset("y")
        out = mf.payload(0, Path(tempfile.gettempdir(), "no_aplus_flow"), date(2026, 10, 9))
        self.assertFalse(out["ok"])


if __name__ == "__main__":
    unittest.main()
