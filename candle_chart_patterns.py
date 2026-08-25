from __future__ import annotations
import math
import pandas as pd

def _safe_div(a,b):
    return a/b if b not in (0,0.0) else 0.0

def add_candle_patterns(df: pd.DataFrame) -> pd.DataFrame:
    x=df.copy()
    body=(x["close"]-x["open"]).abs()
    rng=(x["high"]-x["low"]).replace(0,float("nan"))
    upper=x["high"]-x[["open","close"]].max(axis=1)
    lower=x[["open","close"]].min(axis=1)-x["low"]
    x["body_ratio"]=(body/rng).fillna(0)
    x["bullish"]=x["close"]>x["open"]
    x["bearish"]=x["close"]<x["open"]
    x["doji"]=x["body_ratio"]<=0.10
    x["marubozu"]=x["body_ratio"]>=0.82
    x["hammer"]=(lower>=body*2.0)&(upper<=body*0.8)&(x["body_ratio"]<=0.50)
    x["shooting_star"]=(upper>=body*2.0)&(lower<=body*0.8)&(x["body_ratio"]<=0.50)
    po=x["open"].shift(1); pc=x["close"].shift(1)
    x["bullish_engulfing"]=(pc<po)&(x["close"]>x["open"])&(x["open"]<=pc)&(x["close"]>=po)
    x["bearish_engulfing"]=(pc>po)&(x["close"]<x["open"])&(x["open"]>=pc)&(x["close"]<=po)
    ph=x["high"].shift(1); pl=x["low"].shift(1)
    x["inside_bar"]=(x["high"]<ph)&(x["low"]>pl)
    x["outside_bar"]=(x["high"]>ph)&(x["low"]<pl)
    tr=(x["high"]-x["low"]).abs()
    x["nr4"]=tr<=tr.rolling(4,min_periods=4).min()
    x["nr7"]=tr<=tr.rolling(7,min_periods=7).min()
    avg_body=body.rolling(20,min_periods=5).mean()
    x["expansion_candle"]=(body>=avg_body*1.8)&(x["body_ratio"]>=0.65)
    x["bullish_rejection"]=x["hammer"] & (x["close"]>=x["open"])
    x["bearish_rejection"]=x["shooting_star"] & (x["close"]<=x["open"])
    return x

def add_chart_structure(df: pd.DataFrame) -> pd.DataFrame:
    x=df.copy()
    x["ema9"]=x["close"].ewm(span=9,adjust=False).mean()
    x["ema20"]=x["close"].ewm(span=20,adjust=False).mean()
    x["ema50"]=x["close"].ewm(span=50,adjust=False).mean()
    pv=(x["close"]*x["volume"]).cumsum()
    vv=x["volume"].cumsum().replace(0,float("nan"))
    x["vwap"]=(pv/vv).fillna(x["close"])
    prev_close=x["close"].shift(1)
    tr=pd.concat([(x["high"]-x["low"]).abs(),(x["high"]-prev_close).abs(),(x["low"]-prev_close).abs()],axis=1).max(axis=1)
    x["atr14"]=tr.rolling(14,min_periods=3).mean()
    x["hh"]=x["high"]>x["high"].shift(1)
    x["hl"]=x["low"]>=x["low"].shift(1)
    x["lh"]=x["high"]<=x["high"].shift(1)
    x["ll"]=x["low"]<x["low"].shift(1)
    x["hh_hl"]=(x["hh"]&x["hl"]).rolling(3,min_periods=3).sum()>=2
    x["lh_ll"]=(x["lh"]&x["ll"]).rolling(3,min_periods=3).sum()>=2
    roll_hi=x["high"].rolling(6,min_periods=6).max().shift(1)
    roll_lo=x["low"].rolling(6,min_periods=6).min().shift(1)
    x["range_breakout"]=x["close"]>roll_hi
    x["range_breakdown"]=x["close"]<roll_lo
    width=(roll_hi-roll_lo)
    atr=x["atr14"].replace(0,float("nan"))
    x["compression"]=(width/atr<=3.0).fillna(False)
    x["bullish_trend"]= (x["close"]>x["vwap"])&(x["ema9"]>x["ema20"])&(x["ema20"]>=x["ema50"])
    x["bearish_trend"]= (x["close"]<x["vwap"])&(x["ema9"]<x["ema20"])&(x["ema20"]<=x["ema50"])
    return x
