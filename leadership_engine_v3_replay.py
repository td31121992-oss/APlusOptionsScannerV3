from __future__ import annotations
import csv, json, math
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT=Path(__file__).resolve().parent
LATEST=ROOT/"data"/"reports"/"fno_market_watch_latest.json"
CHART_BASE=ROOT/"data"/"chart_history"
OUTBASE=ROOT/"data"/"rank_leadership_v3"
TARGETS={"BDL","CDSL","GVT&D","POWERINDIA","POWERGRID"}

def f(v,d=0.0):
    try:
        x=float(v); return x if math.isfinite(x) else d
    except Exception:return d

def parse_ts(v):
    try:return datetime.fromisoformat(str(v))
    except Exception:return None

def latest_day():
    try:
        d=json.loads(LATEST.read_text(encoding="utf-8"))
        t=parse_ts(d.get("generated_at"))
        if t:return t.date().isoformat()
    except Exception:pass
    return datetime.now().date().isoformat()

def load_day(day):
    p=CHART_BASE/day/"market_watch_1m.csv"
    if not p.exists(): raise SystemExit(f"Missing {p}")
    by=defaultdict(list)
    with p.open("r",encoding="utf-8-sig",newline="") as h:
        for r in csv.DictReader(h):
            sym=str(r.get("symbol") or "").upper().strip()
            minute=str(r.get("minute") or "").strip()
            if sym and minute:
                by[minute].append({
                    "symbol":sym,"sector":r.get("sector",""),
                    "from_open_pct":f(r.get("from_open_pct")),
                    "range_position_pct":f(r.get("range_position_pct")),
                })
    return dict(by)

def ranks(rows):
    up=sorted(rows,key=lambda r:r["from_open_pct"],reverse=True)
    dn=sorted(rows,key=lambda r:r["from_open_pct"])
    return ({r["symbol"]:i+1 for i,r in enumerate(up)},
            {r["symbol"]:i+1 for i,r in enumerate(dn)})

def main():
    day=latest_day(); by=load_day(day); minutes=sorted(by)
    if len(minutes)<20: raise SystemExit("Need at least 20 minutes of saved history")

    tl=defaultdict(list)
    for minute in minutes:
        rows=by[minute]; ur,dr=ranks(rows)
        for r in rows:
            move=r["from_open_pct"]; direction="UP" if move>=0 else "DOWN"
            rank=ur[r["symbol"]] if direction=="UP" else dr[r["symbol"]]
            tl[r["symbol"]].append({**r,"minute":minute,"direction":direction,"rank":rank})

    all_signals=[]; summaries=[]
    for sym,h in tl.items():
        h.sort(key=lambda x:x["minute"]); states=[]
        for i,x in enumerate(h):
            if i<15:
                states.append({**x,"eligible_history":False}); continue

            p5,p10,p15=h[i-5],h[i-10],h[i-15]
            sign=1 if x["direction"]=="UP" else -1
            rc5=(p5["rank"]-x["rank"]) if p5["direction"]==x["direction"] else 0
            rc10=(p10["rank"]-x["rank"]) if p10["direction"]==x["direction"] else 0
            rc15=(p15["rank"]-x["rank"]) if p15["direction"]==x["direction"] else 0
            mc5=(x["from_open_pct"]-p5["from_open_pct"])*sign
            mc10=(x["from_open_pct"]-p10["from_open_pct"])*sign
            mc15=(x["from_open_pct"]-p15["from_open_pct"])*sign
            recent=h[i-4:i+1]
            persist=sum(1 for z in recent if z["direction"]==x["direction"] and z["rank"]<=20)>=3
            range_ok=x["range_position_pct"]>=70 if x["direction"]=="UP" else x["range_position_pct"]<=30
            rank_accel=(rc5>=5 or rc10>=10)
            price_accel=(mc5>=0.20 or mc10>=0.35)
            fast=(x["rank"]<=20 and rank_accel and price_accel and persist and range_ok)
            strong=(x["rank"]<=10 and price_accel and persist)
            state="FAST_BREAKOUT" if fast else "STRONG_LEADER" if strong else "LEADERSHIP_DEVELOPING" if x["rank"]<=20 and rank_accel else "WATCH"
            score=round(min(max(rc5,0),30)*1.8+min(max(rc10,0),50)*0.8+min(max(mc5,0),1.5)*22+min(max(mc10,0),2.5)*10+max(0,21-x["rank"])*1.1+(8 if persist else 0)+(6 if range_ok else 0),2)
            rec={**x,"eligible_history":True,"rank_change_5m":rc5,"rank_change_10m":rc10,"rank_change_15m":rc15,
                 "move_change_5m_pct":round(mc5,4),"move_change_10m_pct":round(mc10,4),"move_change_15m_pct":round(mc15,4),
                 "persistence_5m":persist,"range_extreme":range_ok,"leadership_state":state,"leadership_score":score,"signal":bool(fast or strong)}
            states.append(rec)
            if rec["signal"]: all_signals.append(rec)

        valid=[z for z in states if z.get("eligible_history")]
        if not valid: continue
        first=next((z for z in valid if z["signal"]),None)
        best=max(valid,key=lambda z:z["leadership_score"]); last=valid[-1]
        summaries.append({"symbol":sym,"first_signal_minute":first["minute"] if first else "",
                          "first_signal_state":first["leadership_state"] if first else "",
                          "first_signal_rank":first["rank"] if first else "",
                          "first_signal_move_pct":round(first["from_open_pct"],4) if first else "",
                          "best_score":best["leadership_score"],"best_minute":best["minute"],
                          "latest_rank":last["rank"],"latest_move_pct":round(last["from_open_pct"],4)})
        if sym in TARGETS:
            d=OUTBASE/day/"targets"; d.mkdir(parents=True,exist_ok=True)
            fields=sorted({k for z in states for k in z})
            with (d/f"{sym.replace('&','AND')}_v3_timeline.csv").open("w",encoding="utf-8-sig",newline="") as fh:
                w=csv.DictWriter(fh,fieldnames=fields,extrasaction="ignore"); w.writeheader(); w.writerows(states)

    idx={sym:{z["minute"]:i for i,z in enumerate(h)} for sym,h in tl.items()}
    ev=[]
    for s in all_signals:
        h=tl[s["symbol"]]; i=idx[s["symbol"]][s["minute"]]; sign=1 if s["direction"]=="UP" else -1; entry=s["from_open_pct"]
        def fw(n):
            j=min(len(h)-1,i+n); return round((h[j]["from_open_pct"]-entry)*sign,4)
        future=h[i:min(len(h),i+61)]
        vals=[(z["from_open_pct"]-entry)*sign for z in future]
        ev.append({"minute":s["minute"],"symbol":s["symbol"],"direction":s["direction"],"state":s["leadership_state"],
                   "rank":s["rank"],"entry_from_open_pct":round(entry,4),"leadership_score":s["leadership_score"],
                   "fwd_5m_pct":fw(5),"fwd_15m_pct":fw(15),"fwd_30m_pct":fw(30),"fwd_60m_pct":fw(60),
                   "mfe_60m_pct":round(max(vals),4),"mae_60m_pct":round(min(vals),4)})

    episodes=[]; last={}
    for r in sorted(ev,key=lambda x:(x["symbol"],x["minute"])):
        i=idx[r["symbol"]][r["minute"]]
        if r["symbol"] not in last or i-last[r["symbol"]]>=15:
            episodes.append(r); last[r["symbol"]]=i

    outdir=OUTBASE/day; outdir.mkdir(parents=True,exist_ok=True)
    def write(path,rows):
        if not rows:return
        with path.open("w",encoding="utf-8-sig",newline="") as fh:
            w=csv.DictWriter(fh,fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    write(outdir/"v3_signal_episodes.csv",episodes); write(outdir/"v3_symbol_summary.csv",summaries)

    def win(k):
        return round(100*sum(1 for r in episodes if r[k]>0)/len(episodes),2) if episodes else 0.0
    metrics={"day":day,"symbols":len(tl),"minutes":len(minutes),"episodes":len(episodes),
             "win_5m_pct":win("fwd_5m_pct"),"win_15m_pct":win("fwd_15m_pct"),
             "win_30m_pct":win("fwd_30m_pct"),"win_60m_pct":win("fwd_60m_pct"),
             "avg_mfe_60m_pct":round(sum(r["mfe_60m_pct"] for r in episodes)/len(episodes),4) if episodes else 0.0,
             "avg_mae_60m_pct":round(sum(r["mae_60m_pct"] for r in episodes)/len(episodes),4) if episodes else 0.0,
             "research_only":True}
    (outdir/"run_manifest.json").write_text(json.dumps(metrics,indent=2),encoding="utf-8")

    print("="*118); print("APLUS LEADERSHIP ENGINE V3 - FULL MARKET REPLAY"); print("="*118)
    for k,v in metrics.items(): print(f"{k:<20}: {v}")
    print("\nTARGETS")
    for sym in sorted(TARGETS):
        s=next((x for x in summaries if x["symbol"]==sym),None); print(sym, s or "NO DATA")
    print("\nTOP 20 EPISODES BY SCORE")
    for r in sorted(episodes,key=lambda x:x["leadership_score"],reverse=True)[:20]:
        print(f"{r['minute']} {r['symbol']:<14} {r['direction']:<4} {r['state']:<20} rank={r['rank']:>3} score={r['leadership_score']:>7.2f} 5m={r['fwd_5m_pct']:>+6.3f}% 15m={r['fwd_15m_pct']:>+6.3f}% 30m={r['fwd_30m_pct']:>+6.3f}% 60m={r['fwd_60m_pct']:>+6.3f}%")
    print("\nResearch only. No scanner/trading files changed."); print("="*118)

if __name__=="__main__": main()
