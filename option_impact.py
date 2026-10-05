"""Read-only option premium impact analytics for Stock Analysis / mover diagnostics."""
from __future__ import annotations
from datetime import date, datetime, time as dtime

def _f(v, default=0.0):
    try:
        x=float(v)
        return x if x==x and abs(x)!=float("inf") else default
    except (TypeError,ValueError,OverflowError):
        return default

def _pick(rows, side, key):
    values=[r for r in rows if r.get("side")==side]
    return max(values, key=lambda r:_f(r.get(key))) if values else None

def _minute_history(client, security_id, day):
    if not client or not security_id:
        return {}
    try:
        d=date.fromisoformat(str(day))
        candles=client.get_intraday_candles(
            security_id=int(security_id), segment="NSE_FNO", instrument="OPTSTK",
            interval=1, from_datetime=datetime.combine(d,dtime(9,15)),
            to_datetime=datetime.combine(d,dtime(15,30)), oi=True)
        ts=candles.get("timestamp",[]) or []
        highs=candles.get("high",[]) or []
        lows=candles.get("low",[]) or []
        opens=candles.get("open",[]) or []
        closes=candles.get("close",[]) or []
        size=min(len(ts),len(highs),len(lows),len(closes))
        if not size: return {}
        hi=max(range(size),key=lambda i:_f(highs[i]))
        lo=min(range(size),key=lambda i:_f(lows[i]))
        def tm(i):
            try:
                x=float(ts[i])
                return datetime.fromtimestamp(x).strftime("%H:%M:%S") if x>10**9 else str(ts[i])
            except Exception: return str(ts[i])
        return {"day_high":_f(highs[hi]),"high_time":tm(hi),
                "day_low":_f(lows[lo]),"low_time":tm(lo),
                "intraday_open":_f(opens[0]) if opens else 0.0,
                "intraday_close":_f(closes[-1])}
    except Exception:
        return {}

def build_option_impact(symbol: str, day: str, chain_loader):
    symbol=str(symbol or "").strip().upper()
    if not symbol: return {"ok":False,"error":"Symbol is required","read_only":True}
    try: chain=chain_loader(symbol)
    except Exception as exc:
        return {"ok":False,"error":f"{type(exc).__name__}: {exc}","read_only":True}
    if not isinstance(chain,dict) or not chain.get("ok"):
        return {"ok":False,"error":str((chain or {}).get("error") or "Option chain unavailable"),"read_only":True}

    rows=[]
    for item in chain.get("rows",[]):
        for side in ("ce","pe"):
            leg=item.get(side)
            if not isinstance(leg,dict) or _f(leg.get("ltp"))<=0: continue
            prev=_f(leg.get("previous_close"))
            ltp=_f(leg.get("ltp"))
            change=((ltp-prev)/prev*100.0) if prev>0 else 0.0
            rows.append({"strike":_f(item.get("strike")),"side":side.upper(),
                "security_id":leg.get("security_id"),"ltp":round(ltp,2),
                "previous_close":round(prev,2),"premium_change_pct":round(change,2),
                "volume":int(_f(leg.get("volume"))),"oi":int(_f(leg.get("oi"))),
                "oi_change":int(_f(leg.get("oi_change"))),
                "oi_change_pct":round(_f(leg.get("oi_change_pct")),2),
                "iv":round(_f(leg.get("iv")),2),
                "day_high":round(ltp,2),"high_time":"",
                "day_low":round(ltp,2),"low_time":""})

    spot=_f(chain.get("spot"))
    top_pe=_pick(rows,"PE","premium_change_pct")
    top_ce=_pick(rows,"CE","premium_change_pct")

    # Enrich only the strongest movers and nearby strikes. This keeps the
    # read-only historical calls bounded while still giving exact timestamps.
    targets=[]
    for r in sorted(rows,key=lambda x:abs(x["strike"]-spot))[:6]:
        targets.append((r["side"],r["strike"]))
    for r in sorted(rows,key=lambda x:_f(x.get("premium_change_pct")),reverse=True)[:4]:
        targets.append((r["side"],r["strike"]))
    targets=set(targets)

    client=None
    try:
        from config import AppConfig
        from core.dhan_client import DhanClient
        client=DhanClient(AppConfig.from_env().dhan)
    except Exception:
        pass

    cache={}
    for r in rows:
        key=(r["side"],r["strike"])
        if key not in targets or not r.get("security_id"):
            continue
        hist=_minute_history(client,r["security_id"],str(day or date.today()))
        if hist:
            r["day_high"]=round(_f(hist.get("day_high",r["ltp"])),2)
            r["high_time"]=str(hist.get("high_time") or "")
            r["day_low"]=round(_f(hist.get("day_low",r["ltp"])),2)
            r["low_time"]=str(hist.get("low_time") or "")
            cache[key]=True

    # For the UI keep ATM-near strikes plus the strongest premium movers.
    visible=sorted(rows,key=lambda r:(0 if abs(r["strike"]-spot)<=500 else 1,
                                      -_f(r.get("premium_change_pct"))))[:24]
    return {"ok":True,"symbol":symbol,"expiry":chain.get("expiry"),"spot":spot,
            "top_pe":top_pe,"top_ce":top_ce,"rows":visible,
            "historical_enriched_count":len(cache),
            "read_only":True,"trading_engine_untouched":True,
            "timestamped_intraday":any(r.get("high_time") or r.get("low_time") for r in visible)}
