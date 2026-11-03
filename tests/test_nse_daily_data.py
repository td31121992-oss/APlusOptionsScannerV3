import csv
import gzip
import io
import tempfile
import unittest
import zipfile
from datetime import date, datetime
from pathlib import Path

import nse_daily_data as nd
import nse_tags as nt
import preopen_recorder as po

SEC = """SYMBOL, SERIES, DATE1, PREV_CLOSE, OPEN_PRICE, HIGH_PRICE, LOW_PRICE, LAST_PRICE, CLOSE_PRICE, AVG_PRICE, TTL_TRD_QNTY, TURNOVER_LACS, NO_OF_TRADES, DELIV_QTY, DELIV_PER
RELIANCE, EQ, 22-Oct-2026, 1209.00, 1206.20, 1208.00, 1184.50, 1184.50, 1184.50, 1192.53, 14957042, 178367.52, 213072, 5009411, 33.49
RELIANCE, BE, 22-Oct-2026, 1.0, 1, 1, 1, 1, 1, 1, 10, 1, 1, 5, 50.0
TINY, EQ, 22-Oct-2026, 10, 10, 10, 10, 10, 10, 10, 100, 1, 1, 50, 50.00
"""
FO_HEAD = "TradDt,BizDt,Sgmt,Src,FinInstrmTp,FinInstrmId,ISIN,TckrSymb,SctySrs,XpryDt,FininstrmActlXpryDt,StrkPric,OptnTp,FinInstrmNm,OpnPric,HghPric,LwPric,ClsPric,LastPric,PrvsClsgPric,UndrlygPric,SttlmPric,OpnIntrst,ChngInOpnIntrst,TtlTradgVol,TtlTrfVal,TtlNbOfTxsExctd,SsnId,NewBrdLotQty,Rmks,Rsvd1,Rsvd2,Rsvd3,Rsvd4"


def fo_row(tp, sym, exp, strike, opt, close, oi, chg, vol, lot=100):
    return f"2026-10-22,2026-10-22,FO,NSE,{tp},1,,{sym},,{exp},{exp},{strike},{opt},X,0,0,0,{close},{close},{close},0,{close},{oi},{chg},{vol},1000,5,F1,{lot},,,,,"


def fo_zip():
    rows = [FO_HEAD,
            fo_row("STF", "RELIANCE", "2026-10-27", "0.00", "", 1190.9, 90945000, -26260000, 100),
            fo_row("STF", "RELIANCE", "2026-11-24", "0.00", "", 1195.0, 1000, 10, 5),
            fo_row("STO", "RELIANCE", "2026-10-27", "1200.00", "CE", 20.0, 5000, 100, 10, lot=500),
            fo_row("STO", "RELIANCE", "2026-11-24", "1200.00", "CE", 30.0, 3000, 50, 4, lot=500),
            fo_row("STO", "RELIANCE", "2026-10-27", "1200.00", "PE", 25.0, 4000, 0, 8, lot=500),
            fo_row("IDO", "NIFTY", "2026-10-27", "22500.00", "PE", 100.0, 10, 0, 1, lot=75),
            fo_row("STO", "NOTOURS", "2026-10-27", "100.00", "CE", 5.0, 1, 0, 1)]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("BhavCopy.csv", "\n".join(rows))
    return buf.getvalue()


class ParseTests(unittest.TestCase):
    def test_delivery_filters_series_and_universe(self):
        rows = nd.parse_delivery(SEC, ["RELIANCE"])
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["symbol"], rows[0]["deliv_per"], rows[0]["deliv_qty"], rows[0]["turnover_cr"]), ("RELIANCE", 33.49, 5009411, 1783.68))

    def test_fo_parse_and_summary(self):
        fo = nd.parse_fo(fo_zip(), ["RELIANCE"])
        self.assertEqual({(r["type"], r["symbol"]) for r in fo}, {("STF", "RELIANCE"), ("STO", "RELIANCE"), ("IDO", "NIFTY")})        # not-our stock dropped, index kept
        s = nd.summarise("2026-10-22", nd.parse_delivery(SEC, ["RELIANCE"]), fo)
        self.assertEqual([x["symbol"] for x in s], ["RELIANCE"])                                                                   # index rows are not part of the stock summary
        r = s[0]
        self.assertEqual((r["fut_expiry"], r["fut_oi"], r["fut_oi_chg"]), ("2026-10-27", 90945000, -26260000))                    # the NEAR-month future
        self.assertEqual((r["call_oi"], r["put_oi"], r["call_vol"], r["put_vol"]), (8000, 4000, 14, 8))
        self.assertAlmostEqual(r["call_prem_cr"], (10 * 500 * 20.0 + 4 * 500 * 30.0) / 1e7, places=4)                              # contracts x lot x close
        self.assertEqual(r["deliv_per"], 33.49)

    def test_deals_parse(self):
        text = "Date,Symbol,Security Name,Client Name,Buy/Sell,Quantity Traded,Trade Price / Wght. Avg. Price,Remarks\n22-OCT-2026,ABC,ABC Ltd,Some Fund,BUY,1000000,50.00,-\n"
        r = nd.parse_deals(text)[0]
        self.assertEqual((r["day"], r["symbol"], r["side"], r["qty"], r["value_cr"]), ("2026-10-22", "ABC", "BUY", 1000000, 5.0))

    def test_weekdays_back_skips_weekends(self):
        d = nd.weekdays_back(date(2026, 10, 19), 3)                                                                                # Mon 19 Oct
        self.assertEqual([x.isoformat() for x in d], ["2026-10-19", "2026-10-16", "2026-10-15"])


class FakeFetcher:
    def __init__(self, files):
        self.files = files
        self.calls = []

    def get(self, url):
        self.calls.append(url)
        for k, v in self.files.items():
            if k in url:
                return v
        return None


class StoreTests(unittest.TestCase):
    def test_process_day_stores_and_skips_existing_and_holidays(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            f = FakeFetcher({"sec_bhavdata_full_22102026": SEC.encode(), "20261022_F_0000": fo_zip()})
            self.assertEqual(nd.process_day(f, date(2026, 10, 22), ["RELIANCE"], root), "stored")
            self.assertEqual(nd.process_day(f, date(2026, 10, 22), ["RELIANCE"], root), "exists")
            self.assertEqual(nd.process_day(f, date(2026, 10, 21), ["RELIANCE"], root), "no file")                                 # a holiday: neither file exists
            self.assertEqual(len(f.calls), 4)                                                                                      # 2 for the stored day, none when it exists, 2 for the holiday
            out = nd.build_stock_daily(root)
            with out.open(encoding="utf-8") as h:
                self.assertEqual(len(list(csv.DictReader(h))), 1)
            with gzip.open(root / "data/nse_daily/fo/2026-10-22.csv.gz", "rt", encoding="utf-8") as h:
                self.assertEqual(len(list(csv.DictReader(h))), 6)                                                                  # 2 futures + 3 options of RELIANCE + the NIFTY option


def write_daily(root, rows):
    nd._write_csv(root / "data" / "nse_daily" / "stock_daily.csv", nd.SUMMARY_FIELDS, rows)
    nt._DAILY.update(mtime=None, path=None)


def drow(day, deliv=40.0, qty=1000000, call_oi=1000, put_oi=1000, fut_oi=1000, chg=0, close=100.0, prev=100.0, call_prem=10.0, put_prem=10.0):
    return {"day": day, "symbol": "AAA", "close": close, "prev_close": prev, "ttl_qty": qty, "turnover_cr": 1, "trades": 1, "deliv_qty": 1, "deliv_per": deliv, "fut_oi": fut_oi,
            "fut_oi_chg": chg, "fut_close": close, "fut_settle": close, "call_oi": call_oi, "put_oi": put_oi, "call_vol": 1, "put_vol": 1, "call_prem_cr": call_prem, "put_prem_cr": put_prem}


class TagTests(unittest.TestCase):
    def test_daily_tags_use_only_earlier_days_and_ratios(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            days = [f"2026-10-{d:02d}" for d in range(1, 13)]
            rows = [drow(d) for d in days[:-1]] + [drow("2026-10-12", deliv=80.0, qty=3000000, call_oi=1000, put_oi=2000, fut_oi=1100, chg=100, close=102.0, prev=100.0, call_prem=30.0, put_prem=10.0)]
            rows.append(drow("2026-10-13", deliv=1.0))                                                                              # a later day must not leak into today's tags
            write_daily(root, rows)
            t = nt.daily_tags("AAA", "2026-10-13", root)
            self.assertEqual((t["nd_deliv_pct"], t["nd_deliv_x"], t["nd_vol_x"], t["nd_pcr_oi"], t["nd_pcr_oi_x"]), (80.0, 2.0, 3.0, 2.0, 2.0))
            self.assertEqual((t["nd_fut_label"], t["nd_prem_x"], t["nd_prem_call_share"], t["nd_days"]), ("LONG_BUILDUP", 2.0, 0.75, 11))
            self.assertAlmostEqual(t["nd_fut_oi_chg_pct"], 10.0)
            self.assertEqual(nt.daily_tags("ZZZ", "2026-10-13", root), {})
            self.assertEqual(nt.daily_tags("AAA", "2026-10-01", root), {})                                                          # nothing before the first day

    def test_deal_tags_sign_and_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            nd._write_csv(root / "data/nse_daily/deals/2026-10-22_bulk.csv", ["day", "symbol", "client", "side", "qty", "price", "value_cr"],
                          [{"day": "2026-10-22", "symbol": "AAA", "client": "X", "side": "BUY", "qty": 1, "price": 1, "value_cr": 5.0}, {"day": "2026-10-22", "symbol": "AAA", "client": "Y", "side": "SELL", "qty": 1, "price": 1, "value_cr": 2.0}])
            nd._write_csv(root / "data/nse_daily/deals/2026-10-10_bulk.csv", ["day", "symbol", "client", "side", "qty", "price", "value_cr"],
                          [{"day": "2026-10-10", "symbol": "AAA", "client": "X", "side": "BUY", "qty": 1, "price": 1, "value_cr": 99.0}])        # outside the 5-day window
            self.assertEqual(nt.deal_tags("AAA", 1.0, "2026-10-23", root), {"nd_deal_dir_cr": 3.0, "nd_deal_n": 2})
            self.assertEqual(nt.deal_tags("AAA", -1.0, "2026-10-23", root)["nd_deal_dir_cr"], -3.0)                                   # a put: buying deals are against it
            self.assertEqual(nt.deal_tags("BBB", 1.0, "2026-10-23", root), {})

    def test_preopen_parse_tags_and_final_snapshot(self):
        payload = {"timestamp": "23-Oct-2026 09:09:05", "data": [{"metadata": {"symbol": "AAA", "iep": 102.0, "pChange": 2.0, "previousClose": 100.0, "finalQuantity": 500000, "totalTurnover": 51000000},
                                                                  "detail": {"preOpenMarket": {"IEP": 102.0, "finalQuantity": 500000, "totalBuyQuantity": 300, "totalSellQuantity": 100, "atoBuyQty": 5, "atoSellQty": 0,
                                                                                               "preopen": [{"price": 101}, {"price": 102}]}}}]}
        when, rows = po.parse(payload)
        self.assertEqual((when, rows[0]["gap_pct"], rows[0]["imbalance"], rows[0]["turnover_cr"], rows[0]["levels"]), ("2026-10-23T09:09:05", 2.0, 0.5, 5.1, 2))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            po.write_final(root, "2026-10-23", rows)
            write_daily(root, [drow(f"2026-10-{d:02d}", qty=1000000) for d in range(1, 12)])
            nt._PRE.update(path=None, mtime=None)
            t = nt.preopen_tags("AAA", 1.0, "2026-10-23", root)
            self.assertEqual((t["po_gap_dir_pct"], t["po_imb_dir"], t["po_qty_pct_adv"], t["po_turnover_cr"]), (2.0, 0.5, 50.0, 5.1))
            self.assertEqual(nt.preopen_tags("AAA", -1.0, "2026-10-23", root)["po_gap_dir_pct"], -2.0)                                # a gap up is against a put
            self.assertEqual(nt.preopen_tags("AAA", 1.0, "2026-10-24", root), {})

    def test_tags_never_raise_and_are_empty_without_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(nt.tags("AAA", "BULLISH", datetime(2026, 10, 23, 10, 0), Path(tmp)), {})


if __name__ == "__main__":
    unittest.main()
