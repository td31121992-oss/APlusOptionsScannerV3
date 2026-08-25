from __future__ import annotations
import argparse, json, math, sys
from pathlib import Path
import pandas as pd
from candle_chart_patterns import add_candle_patterns, add_chart_structure

REQUIRED={"symbol","timestamp","open","high","low","close","volume"}

ALIASES={
 "datetime":"timestamp","date":"timestamp","time":"timestamp",
 "ticker":"symbol","tradingsymbol":"symbol",
 "vol":"volume"
}

def normalize(df):
    df=df.copy()
    df.columns=[str(c).strip().lower().replace(" ","_") for c in df.columns]
    for a,b in ALIASES.items():
        if a in df.columns and b not in df.columns: df=df.rename(columns={a:b})
    missing=REQUIRED-set(df.columns)
    if missing: raise ValueError("missing columns: "+",".join(sorted(missing)))
    df["symbol"]=df["symbol"].astype(str).str.upper().str.strip()
    df["timestamp"]=pd.to_datetime(df["timestamp"],errors="coerce")
    for c in ("open","high","low","close","volume"):
        df[c]=pd.to_numeric(df[c],errors="coerce")
    df=df.dropna(subset=list(REQUIRED))
    df=df[(df["open"]>0)&(df["high"]>0)&(df["low"]>0)&(df["close"]>0)]
    return df.sort_values(["symbol","timestamp"]).drop_duplicates(["symbol","timestamp"])

def read_all(folder):
    frames=[]
    for p in sorted(Path(folder).rglob("*")):
        if p.suffix.lower() not in (".csv",".parquet",".pq"): continue
        try:
            d=pd.read_csv(p) if p.suffix.lower()==".csv" else pd.read_parquet(p)
            d=normalize(d); d["_source"]=str(p); frames.append(d)
            print("LOADED",p,len(d))
        except Exception as e:
            print("SKIP",p.name,type(e).__name__,e)
    if not frames: raise SystemExit("No usable historical OHLCV files found.")
    return pd.concat(frames,ignore_index=True).sort_values(["symbol","timestamp"])

def project_auto(root):
    root=Path(root)
    candidates=[
      root/"data"/"historical",
      root/"data"/"history",
      root/"data"/"candles",
      root/"data"/"research",
      root/"data"
    ]
    for c in candidates:
        if c.exists():
            try:
                d=read_all(c)
                if len(d): return d,c
            except SystemExit: pass
    raise SystemExit("No historical candle dataset auto-discovered. Use --input <folder>.")

def enrich_one(g):
    g=g.sort_values("timestamp").copy()
    g=add_candle_patterns(g); g=add_chart_structure(g)
    day=g["timestamp"].dt.date
    g["open_0915"]=g.groupby(day)["open"].transform("first")
    g["from_open_pct"]=(g["close"]/g["open_0915"]-1)*100
    avgvol=g["volume"].rolling(20,min_periods=5).mean()
    g["relative_volume"]=(g["volume"]/avgvol.replace(0,float("nan"))).fillna(0)
    first3_hi=g.groupby(day)["high"].transform(lambda s: s.iloc[:3].max() if len(s)>=1 else float("nan"))
    first3_lo=g.groupby(day)["low"].transform(lambda s: s.iloc[:3].min() if len(s)>=1 else float("nan"))
    g["opening_range_high"]=first3_hi; g["opening_range_low"]=first3_lo
    g["or_breakout"]=g["close"]>g["opening_range_high"]
    g["or_breakdown"]=g["close"]<g["opening_range_low"]
    return g

def strategy_signals(g):
    x=g.copy()
    bull_candle=x["bullish_engulfing"]|x["bullish_rejection"]|x["marubozu"]|x["expansion_candle"]
    bear_candle=x["bearish_engulfing"]|x["bearish_rejection"]|x["marubozu"]|x["expansion_candle"]
    bull_score=(
      (x["from_open_pct"]>=0.40).astype(int)*20+
      (x["close"]>x["vwap"]).astype(int)*15+
      x["hh_hl"].astype(int)*15+
      (x["relative_volume"]>=1.5).astype(int)*15+
      x["or_breakout"].astype(int)*15+
      bull_candle.astype(int)*10+
      x["bullish_trend"].astype(int)*10
    )
    bear_score=(
      (x["from_open_pct"]<=-0.40).astype(int)*20+
      (x["close"]<x["vwap"]).astype(int)*15+
      x["lh_ll"].astype(int)*15+
      (x["relative_volume"]>=1.5).astype(int)*15+
      x["or_breakdown"].astype(int)*15+
      bear_candle.astype(int)*10+
      x["bearish_trend"].astype(int)*10
    )
    x["bull_score"]=bull_score;x["bear_score"]=bear_score
    x["signal"]="NONE"
    x.loc[(bull_score>=60)&(bull_score>bear_score),"signal"]="BUY_CE"
    x.loc[(bear_score>=60)&(bear_score>bull_score),"signal"]="BUY_PE"
    return x

def forward_outcomes(g,horizons=(1,3,6,12)):
    x=g.copy()
    for h in horizons:
        fut=x["close"].shift(-h)
        raw=(fut/x["close"]-1)*100
        x[f"fwd_{h}_bars_pct"]=raw.where(x["signal"]=="BUY_CE",-raw.where(x["signal"]=="BUY_PE"))
    return x

def main():
    ap=argparse.ArgumentParser(description="READ-ONLY APlus candle/chart research backtest")
    ap.add_argument("--input",help="folder containing historical CSV/Parquet OHLCV")
    ap.add_argument("--project-root",default=".")
    ap.add_argument("--output",default="data/backtest_research")
    ap.add_argument("--min-score",type=int,default=60)
    args=ap.parse_args()

    root=Path(args.project_root).resolve()
    out=(root/args.output).resolve()
    # Guard: output must be inside project root.
    if root not in out.parents and out!=root:
        raise SystemExit("Safety guard: output must be inside project root.")
    out.mkdir(parents=True,exist_ok=True)

    if args.input:
        data=read_all(Path(args.input))
        source=Path(args.input)
    else:
        data,source=project_auto(root)

    print("SOURCE",source)
    groups=[]
    for sym,g in data.groupby("symbol",sort=False):
        e=enrich_one(g)
        s=strategy_signals(e)
        s.loc[(s["signal"]!="NONE")&(s[["bull_score","bear_score"]].max(axis=1)<args.min_score),"signal"]="NONE"
        groups.append(forward_outcomes(s))
    allx=pd.concat(groups,ignore_index=True)
    sig=allx[allx["signal"]!="NONE"].copy()

    cols=["symbol","timestamp","signal","open","high","low","close","volume","open_0915","from_open_pct",
          "vwap","relative_volume","bull_score","bear_score","bullish_engulfing","bearish_engulfing",
          "hammer","shooting_star","inside_bar","outside_bar","nr4","nr7","expansion_candle",
          "hh_hl","lh_ll","range_breakout","range_breakdown","or_breakout","or_breakdown",
          "fwd_1_bars_pct","fwd_3_bars_pct","fwd_6_bars_pct","fwd_12_bars_pct"]
    sig[cols].to_csv(out/"signals.csv",index=False)

    summary=[]
    for side,g in sig.groupby("signal"):
        row={"signal":side,"signals":len(g)}
        for h in (1,3,6,12):
            c=f"fwd_{h}_bars_pct"; vals=g[c].dropna()
            row[f"avg_{h}bar_pct"]=round(vals.mean(),3) if len(vals) else 0
            row[f"winrate_{h}bar_pct"]=round((vals>0).mean()*100,2) if len(vals) else 0
        summary.append(row)
    pd.DataFrame(summary).to_csv(out/"summary.csv",index=False)

    pattern_cols=["bullish_engulfing","bearish_engulfing","hammer","shooting_star","inside_bar","outside_bar",
                  "nr4","nr7","expansion_candle","hh_hl","lh_ll","range_breakout","range_breakdown"]
    pats=[]
    for p in pattern_cols:
        z=sig[sig[p]==True]
        if not len(z): continue
        vals=z["fwd_3_bars_pct"].dropna()
        pats.append({"pattern":p,"signals":len(z),"avg_3bar_pct":round(vals.mean(),3) if len(vals) else 0,
                     "winrate_3bar_pct":round((vals>0).mean()*100,2) if len(vals) else 0})
    pd.DataFrame(pats).sort_values(["winrate_3bar_pct","signals"],ascending=False).to_csv(out/"pattern_stats.csv",index=False)

    report={
      "mode":"READ_ONLY_RESEARCH",
      "production_files_modified":False,
      "source":str(source),
      "rows":int(len(allx)),
      "symbols":int(allx["symbol"].nunique()),
      "signals":int(len(sig)),
      "note":"Underlying-direction research. This does not claim exact option P&L unless exact historical option candles are supplied by a separate option replay."
    }
    (out/"run_manifest.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    print("="*80)
    print("APLUS CANDLE + CHART STRATEGY BACKTEST COMPLETE")
    print(json.dumps(report,indent=2))
    print("Output:",out)
    print("="*80)

if __name__=="__main__":
    main()
