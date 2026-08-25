from __future__ import annotations
import csv,json,math,os,tempfile,time
from dataclasses import asdict,dataclass
from datetime import datetime,time as dtime
from pathlib import Path
from typing import Any,Mapping
from zoneinfo import ZoneInfo
import pandas as pd
from config import AppConfig
from core.dhan_client import DhanClient

IST=ZoneInfo("Asia/Kolkata")
ROOT=Path(__file__).resolve().parent
DATA=ROOT/"data"; REPORTS=DATA/"reports"
MASTER=DATA/"cache"/"api-scrip-master-detailed.csv"
ENTRY_READY=REPORTS/"intraday_entry_ready.csv"
SHADOW=REPORTS/"leadership_v6_shadow_latest.json"
MARKET_WATCH=REPORTS/"fno_market_watch_latest.json"
LATEST_JSON=REPORTS/"stock_futures_paper_latest.json"
LATEST_CSV=REPORTS/"stock_futures_paper.csv"
HISTORY_JSON=REPORTS/"stock_futures_paper_history.json"
HISTORY_CSV=REPORTS/"stock_futures_paper_history.csv"

MAX_OPEN=int(os.getenv("APLUS_FUTURES_PAPER_MAX_OPEN","3"))
MIN_QUALITY=float(os.getenv("APLUS_FUTURES_PAPER_MIN_QUALITY","85"))
MIN_CLEAN=float(os.getenv("APLUS_FUTURES_PAPER_MIN_CLEAN","90"))
MIN_RVOL=float(os.getenv("APLUS_FUTURES_PAPER_MIN_RVOL","1.5"))
FAST_Q=float(os.getenv("APLUS_FUTURES_FAST_CONT_QUALITY","92"))
FAST_C=float(os.getenv("APLUS_FUTURES_FAST_CONT_CLEAN","92"))
FAST_R=float(os.getenv("APLUS_FUTURES_FAST_CONT_RVOL","2.0"))
STOP_PCT=float(os.getenv("APLUS_FUTURES_PAPER_STOP_PCT","0.45"))
TRAIL_ACT=float(os.getenv("APLUS_FUTURES_PAPER_TRAIL_ACTIVATE_PCT","0.35"))
TRAIL_GIVE=float(os.getenv("APLUS_FUTURES_PAPER_TRAIL_GIVEBACK_PCT","0.25"))
TARGET_PCT=float(os.getenv("APLUS_FUTURES_PAPER_TARGET_PCT","1.50"))
EST_MARGIN_PCT=float(os.getenv("APLUS_FUTURES_EST_MARGIN_PCT","25.0"))
MARK_REFRESH=int(os.getenv("APLUS_FUTURES_MARK_REFRESH_SECONDS","180"))
FORCED_EXIT=os.getenv("APLUS_FUTURES_FORCED_EXIT","15:15")

def num(v,d=0.0):
    try:
        if v in (None,""): return d
        x=float(v); return x if math.isfinite(x) else d
    except Exception:return d

def boo(v): return isinstance(v,bool) and v or str(v or "").strip().lower() in {"1","true","yes","y","on"}

def atomic_text(path,text):
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix=path.name+".",suffix=".tmp",dir=str(path.parent))
    try:
        with os.fdopen(fd,"w",encoding="utf-8",newline="") as h:
            h.write(text); h.flush()
            try: os.fsync(h.fileno())
            except OSError: pass
        last=None
        for i in range(7):
            try: os.replace(tmp,path); return
            except PermissionError as e: last=e; time.sleep(.04*(2**i))
        if last: raise last
    finally:
        try:
            if os.path.exists(tmp): os.unlink(tmp)
        except OSError: pass

def read_csv(path):
    if not path.exists(): return []
    try:
        with path.open("r",encoding="utf-8-sig",newline="") as h:return [dict(r) for r in csv.DictReader(h)]
    except Exception:return []

def read_json(path):
    try:return json.loads(path.read_text(encoding="utf-8"))
    except Exception:return {}

def ltp(payload):
    if not isinstance(payload,Mapping):return 0.0
    for k in ("last_price","ltp","LTP","lastPrice","close"):
        x=num(payload.get(k))
        if x>0:return x
    o=payload.get("ohlc")
    return num(o.get("close")) if isinstance(o,Mapping) else 0.0

@dataclass
class Contract:
    symbol:str; security_id:str; trading_symbol:str; expiry:str; lot_size:int
    segment:str="NSE_FNO"

@dataclass
class Trade:
    trade_id:str; trading_date:str; symbol:str; direction:str; side:str
    contract_security_id:str; trading_symbol:str; expiry:str; lot_size:int; quantity:int
    entry_time:str; entry_future_price:float; entry_underlying_price:float
    stop_underlying_price:float; target_underlying_price:float
    signal_quality:float; clean_trend_score:float; relative_volume:float
    vwap_distance_percent:float; leadership_shadow:bool; source_status:str; source_stage:str
    entry_reason:str; notional_value:float; estimated_margin:float; planned_risk_amount:float
    status:str="OPEN"; best_favorable_underlying_pct:float=0.0; worst_adverse_underlying_pct:float=0.0
    last_underlying_price:float=0.0; last_future_price:float=0.0; last_mark_time:str=""
    estimated_unrealized_pnl:float=0.0; exit_time:str=""; exit_future_price:float=0.0
    exit_underlying_price:float=0.0; exit_reason:str=""; gross_pnl:float=0.0
    return_on_estimated_margin_pct:float=0.0; pending_exit_reason:str=""
    def to_dict(self):return asdict(self)

class Resolver:
    def __init__(self): self.by={}
    def load(self):
        if not MASTER.exists(): raise FileNotFoundError(f"Instrument master missing: {MASTER}")
        f=pd.read_csv(MASTER,low_memory=False); cols={str(c).upper():c for c in f.columns}
        def col(*names):
            for n in names:
                if n.upper() in cols:return cols[n.upper()]
            return None
        c_sid=col("SECURITY_ID"); c_under=col("UNDERLYING_SYMBOL","SYMBOL_NAME")
        c_exp=col("SM_EXPIRY_DATE","EXPIRY_DATE"); c_inst=col("INSTRUMENT","INSTRUMENT_TYPE")
        c_disp=col("DISPLAY_NAME","TRADING_SYMBOL","SYMBOL_NAME"); c_lot=col("LOT_SIZE","LOT_UNITS","SEM_LOT_UNITS")
        c_exch=col("EXCH_ID","EXCHANGE")
        if not all([c_sid,c_under,c_exp]): raise RuntimeError("Detailed master missing futures columns")
        today=datetime.now(IST).date(); by={}
        for _,r in f.iterrows():
            inst=str(r.get(c_inst,"") if c_inst else "").upper()
            disp=str(r.get(c_disp,"") if c_disp else "").upper()
            if "FUTSTK" not in (inst+" "+disp): continue
            exch=str(r.get(c_exch,"") if c_exch else "").upper()
            if exch and exch not in {"NSE","N"}: continue
            sym=str(r.get(c_under,"") or "").strip().upper(); sid=str(r.get(c_sid,"") or "").strip()
            ex=str(r.get(c_exp,"") or "").strip()[:10]
            if not sym or not sid or not ex: continue
            try:d=datetime.fromisoformat(ex).date()
            except ValueError:continue
            if d<today:continue
            lot=int(max(1,num(r.get(c_lot),1))) if c_lot else 1
            try:sid=str(int(float(sid)))
            except Exception:pass
            by.setdefault(sym,[]).append(Contract(sym,sid,str(r.get(c_disp,"") or f"{sym} FUT").strip(),d.isoformat(),lot))
        for s in by:by[s].sort(key=lambda x:x.expiry)
        self.by=by
    def nearest(self,symbol):
        if not self.by:self.load()
        x=self.by.get(symbol.upper(),[])
        return x[0] if x else None

class Engine:
    def __init__(self):
        cfg=AppConfig.from_env(); cfg.ensure_runtime_directories()
        self.client=DhanClient(cfg.dhan); self.resolver=Resolver(); self.trades=[]; self.last_mark=0.0
        self.load_state()
    def shadow_map(self):
        o=read_json(SHADOW); rows=o.get("rows",[]) if isinstance(o,dict) else []
        return {str(r.get("symbol") or "").upper():r for r in rows if isinstance(r,dict)}
    def market_map(self):
        o=read_json(MARKET_WATCH); rows=[]
        if isinstance(o,dict):
            for k in ("rows","stocks","market_watch","data"):
                if isinstance(o.get(k),list): rows=o[k]; break
        return {str(r.get("symbol") or "").upper():r for r in rows if isinstance(r,dict)}
    def underlying(self,symbol,market):
        r=market.get(symbol.upper(),{})
        for k in ("ltp","last_price","current","close"):
            x=num(r.get(k))
            if x>0:return x
        for r in read_csv(ENTRY_READY):
            if str(r.get("symbol") or "").upper()==symbol.upper():
                x=num(r.get("ltp"))
                if x>0:return x
        return 0.0
    def qualifies(self,r,shadow):
        sym=str(r.get("symbol") or "").upper(); d=str(r.get("direction") or "").upper()
        if d not in {"BULLISH","BEARISH"}:return False,"NO_DIRECTION",False
        q=num(r.get("trade_quality_score")); c=num(r.get("clean_trend_score")); rv=num(r.get("relative_volume")); vw=num(r.get("vwap_distance_percent"))
        stage=str(r.get("stage") or "").upper(); sh=boo(shadow.get(sym,{}).get("qualified_shadow"))
        vok=vw>0 if d=="BULLISH" else vw<0
        fast=q>=FAST_Q and c>=FAST_C and rv>=FAST_R and vok
        normal=q>=MIN_QUALITY and rv>=MIN_RVOL and vok and (c>=MIN_CLEAN or sh) and ("MOMENTUM" in stage or sh)
        if fast:return True,"FAST_CONTINUATION_RESEARCH",sh
        if normal:return True,"A_PLUS_ENTRY_READY_RESEARCH",sh
        return False,"QUALITY_FILTER",sh
    def already(self,s,d,day):return any(t.symbol==s and t.direction==d and t.trading_date==day for t in self.trades)
    def quote(self,contracts):
        if not contracts:return {}
        try:r=self.client.get_market_quotes({"NSE_FNO":[c.security_id for c in contracts]},mode="quote")
        except Exception as e:
            print(f"FUTURES PAPER quote failed non-fatally: {type(e).__name__}: {e}"); return {}
        seg=r.get("NSE_FNO",{}) if isinstance(r,dict) else {}
        return {str(k):ltp(v) for k,v in seg.items()}
    def candidates(self,now,market):
        if sum(t.status=="OPEN" for t in self.trades)>=MAX_OPEN:return []
        sh=self.shadow_map(); out=[]
        for r in read_csv(ENTRY_READY):
            s=str(r.get("symbol") or "").upper(); d=str(r.get("direction") or "").upper()
            ok,reason,sho=self.qualifies(r,sh)
            if not ok or not s or self.already(s,d,now.date().isoformat()) or self.underlying(s,market)<=0:continue
            c=self.resolver.nearest(s)
            if c:out.append((r,c,reason,sho))
        out.sort(key=lambda x:(num(x[0].get("trade_quality_score")),num(x[0].get("clean_trend_score")),num(x[0].get("relative_volume"))),reverse=True)
        return out[:max(0,MAX_OPEN-sum(t.status=="OPEN" for t in self.trades))]
    def open_new(self,now,market):
        cs=self.candidates(now,market); quotes=self.quote([x[1] for x in cs]); opened=0
        for r,c,reason,sho in cs:
            fp=num(quotes.get(c.security_id)); s=str(r.get("symbol") or "").upper(); d=str(r.get("direction") or "").upper(); up=self.underlying(s,market)
            if fp<=0 or up<=0:continue
            rp=num(r.get("underlying_risk_percent"),STOP_PCT)
            if rp<.1 or rp>2:rp=STOP_PCT
            if d=="BULLISH":stop=up*(1-rp/100);target=up*(1+TARGET_PCT/100);side="LONG_FUT"
            else:stop=up*(1+rp/100);target=up*(1-TARGET_PCT/100);side="SHORT_FUT"
            qty=max(1,c.lot_size); notional=fp*qty; margin=notional*EST_MARGIN_PCT/100
            t=Trade(f"FUTP-{now.strftime('%Y%m%d-%H%M%S')}-{s}-{d[:1]}",now.date().isoformat(),s,d,side,c.security_id,c.trading_symbol,c.expiry,c.lot_size,qty,now.isoformat(),round(fp,4),round(up,4),round(stop,4),round(target,4),num(r.get("trade_quality_score")),num(r.get("clean_trend_score")),num(r.get("relative_volume")),num(r.get("vwap_distance_percent")),sho,str(r.get("paper_trade_status") or ""),str(r.get("stage") or ""),reason,round(notional,2),round(margin,2),round(fp*qty*rp/100,2),last_underlying_price=round(up,4),last_future_price=round(fp,4),last_mark_time=now.isoformat())
            self.trades.append(t);opened+=1
            print(f"FUTURES PAPER ENTRY {s} {side} {c.trading_symbol} entry={fp:.2f} qty={qty} reason={reason}")
        return opened
    def favorable(self,t,u):
        raw=(u-t.entry_underlying_price)/t.entry_underlying_price*100 if t.entry_underlying_price else 0
        return raw if t.direction=="BULLISH" else -raw
    def reason(self,t,now,u):
        f=self.favorable(t,u);t.best_favorable_underlying_pct=max(t.best_favorable_underlying_pct,f);t.worst_adverse_underlying_pct=min(t.worst_adverse_underlying_pct,f)
        if t.direction=="BULLISH" and u<=t.stop_underlying_price:return "UNDERLYING_HARD_STOP"
        if t.direction=="BEARISH" and u>=t.stop_underlying_price:return "UNDERLYING_HARD_STOP"
        if f>=TARGET_PCT:return "UNDERLYING_TARGET"
        if t.best_favorable_underlying_pct>=TRAIL_ACT and f<=t.best_favorable_underlying_pct-TRAIL_GIVE:return "UNDERLYING_PROFIT_TRAIL"
        hh,mm=[int(x) for x in FORCED_EXIT.split(":")]
        if now.time()>=dtime(hh,mm):return "FORCED_INTRADAY_EXIT"
        return ""
    def update_open(self,now,market):
        op=[t for t in self.trades if t.status=="OPEN"]; reasons={}; contracts=[]
        for t in op:
            u=self.underlying(t.symbol,market)
            if u<=0:continue
            t.last_underlying_price=u;rs=t.pending_exit_reason or self.reason(t,now,u)
            if rs:reasons[t.trade_id]=rs;contracts.append(Contract(t.symbol,t.contract_security_id,t.trading_symbol,t.expiry,t.lot_size))
        q=self.quote(contracts) if contracts else {};closed=0
        for t in op:
            rs=reasons.get(t.trade_id)
            if not rs:continue
            fp=num(q.get(t.contract_security_id))
            if fp<=0:t.pending_exit_reason=rs;continue
            sign=1 if t.side=="LONG_FUT" else -1;p=(fp-t.entry_future_price)*t.quantity*sign
            t.exit_time=now.isoformat();t.exit_future_price=round(fp,4);t.exit_underlying_price=round(t.last_underlying_price,4);t.exit_reason=rs;t.gross_pnl=round(p,2);t.return_on_estimated_margin_pct=round(p/t.estimated_margin*100,4) if t.estimated_margin else 0;t.last_future_price=round(fp,4);t.status="CLOSED";t.pending_exit_reason="";closed+=1
            print(f"FUTURES PAPER EXIT {t.symbol} {t.side} exit={fp:.2f} pnl={p:.2f} reason={rs}")
        return closed
    def refresh_marks(self,now):
        if time.monotonic()-self.last_mark<MARK_REFRESH:return
        op=[t for t in self.trades if t.status=="OPEN"]
        q=self.quote([Contract(t.symbol,t.contract_security_id,t.trading_symbol,t.expiry,t.lot_size) for t in op]) if op else {}
        for t in op:
            fp=num(q.get(t.contract_security_id))
            if fp>0:
                sign=1 if t.side=="LONG_FUT" else -1;t.last_future_price=round(fp,4);t.last_mark_time=now.isoformat();t.estimated_unrealized_pnl=round((fp-t.entry_future_price)*t.quantity*sign,2)
        self.last_mark=time.monotonic()
    def load_state(self):
        o=read_json(HISTORY_JSON);rows=o.get("trades",[]) if isinstance(o,dict) else []
        for r in rows:
            try:self.trades.append(Trade(**r))
            except Exception:pass
    def write_csv(self,path,rows):
        if not rows:atomic_text(path,"\ufeff");return
        fields=[];seen=set()
        for r in rows:
            for k in r:
                if k not in seen:seen.add(k);fields.append(k)
        import io
        s=io.StringIO(newline="");w=csv.DictWriter(s,fieldnames=fields,extrasaction="ignore");w.writeheader();w.writerows(rows);atomic_text(path,"\ufeff"+s.getvalue())
    def summary(self,rows):
        c=[r for r in rows if r.get("status")=="CLOSED"];o=[r for r in rows if r.get("status")=="OPEN"];p=sum(num(r.get("gross_pnl")) for r in c);wins=sum(num(r.get("gross_pnl"))>0 for r in c)
        return {"trades":len(rows),"open":len(o),"closed":len(c),"wins":wins,"losses":len(c)-wins,"net_pnl":round(p,2),"estimated_margin_total":round(sum(num(r.get("estimated_margin")) for r in rows),2),"paper_only":True}
    def persist(self,now):
        rows=[t.to_dict() for t in self.trades];today=[r for r in rows if r.get("trading_date")==now.date().isoformat()];s=self.summary(today)
        atomic_text(HISTORY_JSON,json.dumps({"updated_at":now.isoformat(),"trades":rows},indent=2));atomic_text(LATEST_JSON,json.dumps({"updated_at":now.isoformat(),"paper_only":True,"live_futures_orders_allowed":False,"summary":s,"trades":today},indent=2));self.write_csv(HISTORY_CSV,rows);self.write_csv(LATEST_CSV,today)
    def run_once(self,now=None):
        now=(now or datetime.now(IST)).astimezone(IST);market=self.market_map();closed=self.update_open(now,market);self.refresh_marks(now);opened=0
        if dtime(9,15)<=now.time()<dtime(15,10):opened=self.open_new(now,market)
        self.persist(now);today=[t.to_dict() for t in self.trades if t.trading_date==now.date().isoformat()];s=self.summary(today);print(f"FUTURES PAPER cycle {now.strftime('%H:%M:%S')} opened={opened} closed={closed} today={s['trades']} open={s['open']} pnl={s['net_pnl']:.2f}");return s
    def run_loop(self,poll=30):
        print("="*100);print("APlus Stock Futures PAPER Research Engine V1");print("PAPER FUTURES ONLY - NO LIVE FUTURES ORDERS");print("Live stock-options pipeline is untouched.");print("="*100)
        while True:
            try:self.run_once()
            except KeyboardInterrupt:raise
            except Exception as e:print(f"FUTURES PAPER cycle error - continues: {type(e).__name__}: {e}")
            time.sleep(max(10,int(poll)))

if __name__=="__main__":
    Engine().run_loop()
