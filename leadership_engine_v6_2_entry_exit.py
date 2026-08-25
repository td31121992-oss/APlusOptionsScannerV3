from __future__ import annotations
import csv, json, math
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT=Path(__file__).resolve().parent
LATEST=ROOT/"data"/"reports"/"fno_market_watch_latest.json"
CHART_BASE=ROOT/"data"/"chart_history"
V61_BASE=ROOT/"data"/"leadership_engine_v6_1"
OUTBASE=ROOT/"data"/"leadership_engine_v6_2"

def f(v,d=None):
    try:
        x=float(v)
        return x if math.isfinite(x) else d
    except Exception:
        return d

def latest_day():
    try:
        x=json.loads(LATEST.read_text(encoding="utf-8"))
        t=datetime.fromisoformat(str(x.get("generated_at")))
        return t.date().isoformat()
    except Exception:
        return datetime.now().date().isoformat()

def load_hist(day):
    p=CHART_BASE/day/"market_watch_1m.csv"
    if not p.exists(): raise SystemExit(f"Missing {p}")
    by=defaultdict(list)
    with p.open("r",encoding="utf-8-sig",newline="") as h:
        for r in csv.DictReader(h):
            sym=str(r.get("symbol") or "").upper().strip()
            minute=str(r.get("minute") or "").strip()
            if not sym or not minute: continue
            by[sym].append({
                "minute":minute,
                "from_open_pct":f(r.get("from_open_pct"),0.0),
                "ltp":f(r.get("ltp"),0.0),
            })
    for sym in by:
        by[sym].sort(key=lambda z:z["minute"])
    return by

def read_csv(p):
    with p.open("r",encoding="utf-8-sig",newline="") as h:
        return list(csv.DictReader(h))

def main():
    day=latest_day()
    selected_path=V61_BASE/day/"v6_1_best_selected.csv"
    if not selected_path.exists():
        raise SystemExit(f"Missing {selected_path}. Run V6.1 first.")
    selected=read_csv(selected_path)
    hist=load_hist(day)

    rows=[]
    for e in selected:
        sym=e["symbol"]
        if sym not in hist: continue
        h=hist[sym]
        idx={z["minute"]:i for i,z in enumerate(h)}
        i=idx.get(e["signal_minute"])
        if i is None: continue
        side=e["side"]
        sign=1 if side=="CE" else -1
        entry=h[i]["from_open_pct"]

        future=h[i:min(len(h),i+61)]
        path=[]
        for j,z in enumerate(future):
            move=(z["from_open_pct"]-entry)*sign
            path.append((j,z["minute"],move))

        mfe=max(path,key=lambda x:x[2]) if path else (0,e["signal_minute"],0.0)
        mae=min(path,key=lambda x:x[2]) if path else (0,e["signal_minute"],0.0)

        # MAE before MFE tells whether the setup immediately went wrong before producing profit.
        pre_mfe=path[:mfe[0]+1] if path else []
        mae_before_mfe=min((x[2] for x in pre_mfe),default=0.0)

        # First useful profit thresholds.
        def first_hit(th):
            for j,minute,move in path:
                if move>=th:return (j,minute,round(move,4))
            return None

        hit_020=first_hit(0.20)
        hit_030=first_hit(0.30)
        hit_050=first_hit(0.50)

        # First retracement after MFE by fixed fractions of achieved favorable move.
        def retrace(frac):
            if mfe[2] <= 0:return None
            trigger=mfe[2]*(1-frac)
            for j,minute,move in path[mfe[0]:]:
                if move<=trigger:
                    return (j,minute,round(move,4))
            return None

        retr20=retrace(0.20)
        retr35=retrace(0.35)
        retr50=retrace(0.50)

        # Simple profit-protect research exits.
        # Activate trail only after +0.25pp favorable move.
        trail_exit=None
        peak=-1e9
        active=False
        for j,minute,move in path:
            peak=max(peak,move)
            if peak>=0.25: active=True
            if active and move<=peak-0.18:
                trail_exit=(j,minute,round(move,4),round(peak,4))
                break

        # Structure stall proxy: after signal, 3 consecutive minutes without new favorable high
        # and at least 0.12pp retrace from best.
        stall_exit=None
        peak=-1e9
        no_new=0
        for j,minute,move in path:
            if move>peak+1e-9:
                peak=move; no_new=0
            else:
                no_new+=1
            if j>=3 and no_new>=3 and peak>=0.15 and move<=peak-0.12:
                stall_exit=(j,minute,round(move,4),round(peak,4))
                break

        # Hard adverse stop research at -0.25pp.
        hard_stop=None
        for j,minute,move in path:
            if move<=-0.25:
                hard_stop=(j,minute,round(move,4))
                break

        # Choose earliest exit among profit trail / stall / hard stop.
        exits=[]
        if trail_exit: exits.append(("PROFIT_TRAIL",trail_exit[0],trail_exit[1],trail_exit[2],trail_exit[3]))
        if stall_exit: exits.append(("STRUCTURE_STALL",stall_exit[0],stall_exit[1],stall_exit[2],stall_exit[3]))
        if hard_stop: exits.append(("HARD_STOP",hard_stop[0],hard_stop[1],hard_stop[2],None))
        if exits:
            chosen=min(exits,key=lambda x:x[1])
        else:
            # If no exit inside 60m, realize 60m/last available move.
            last=path[-1]
            chosen=("TIME_HORIZON",last[0],last[1],round(last[2],4),round(mfe[2],4))

        # Classification.
        if mfe[2] >= 0.30:
            if chosen[3] > 0:
                cls="GOOD_ENTRY_EXITABLE_PROFIT"
            else:
                cls="GOOD_ENTRY_PROFIT_NOT_PROTECTED"
        elif mfe[2] >= 0.15:
            cls="MARGINAL_ENTRY_SMALL_OPPORTUNITY"
        else:
            cls="BAD_ENTRY_IMMEDIATE_FAILURE"

        rows.append({
            "symbol":sym,
            "signal_minute":e["signal_minute"],
            "side":side,
            "rank":e.get("rank",""),
            "move_at_signal_pct":e.get("move_at_signal_pct",""),
            "mfe_60m_pct":round(mfe[2],4),
            "mfe_minute":mfe[1],
            "minutes_to_mfe":mfe[0],
            "mae_60m_pct":round(mae[2],4),
            "mae_before_mfe_pct":round(mae_before_mfe,4),
            "hit_020_minute":hit_020[1] if hit_020 else "",
            "hit_030_minute":hit_030[1] if hit_030 else "",
            "hit_050_minute":hit_050[1] if hit_050 else "",
            "retr20_minute":retr20[1] if retr20 else "",
            "retr35_minute":retr35[1] if retr35 else "",
            "retr50_minute":retr50[1] if retr50 else "",
            "research_exit_reason":chosen[0],
            "research_exit_minute":chosen[2],
            "research_realized_pct":chosen[3],
            "peak_before_exit_pct":chosen[4],
            "classification":cls,
            "v6_1_30m_pct":e.get("fwd_30m_pct",""),
            "v6_1_60m_pct":e.get("fwd_60m_pct",""),
        })

    outdir=OUTBASE/day
    outdir.mkdir(parents=True,exist_ok=True)
    outcsv=outdir/"v6_2_entry_exit_forensic.csv"
    if rows:
        with outcsv.open("w",encoding="utf-8-sig",newline="") as fh:
            w=csv.DictWriter(fh,fieldnames=list(rows[0].keys()))
            w.writeheader();w.writerows(rows)

    classes=defaultdict(int)
    exits=defaultdict(int)
    for r in rows:
        classes[r["classification"]]+=1
        exits[r["research_exit_reason"]]+=1

    realized=[f(r["research_realized_pct"]) for r in rows]
    realized=[x for x in realized if x is not None]
    manifest={
        "day":day,
        "setups":len(rows),
        "classification_counts":dict(classes),
        "exit_reason_counts":dict(exits),
        "positive_research_exit_pct":round(100*sum(1 for x in realized if x>0)/len(realized),2) if realized else None,
        "avg_research_realized_pct":round(sum(realized)/len(realized),4) if realized else None,
        "avg_mfe_pct":round(sum(r["mfe_60m_pct"] for r in rows)/len(rows),4) if rows else None,
        "avg_mae_pct":round(sum(r["mae_60m_pct"] for r in rows)/len(rows),4) if rows else None,
        "production_changes":False,
        "dhan_calls":False,
        "option_premium_simulated":False,
    }
    (outdir/"run_manifest.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")

    print("="*128)
    print("APLUS LEADERSHIP ENGINE V6.2 - ENTRY vs EXIT FORENSIC")
    print("READ ONLY - ZERO DHAN CALLS - ZERO PRODUCTION CHANGES")
    print("="*128)
    for k,v in manifest.items():
        print(f"{k:<30}: {v}")

    print("\nALL 15 SETUPS")
    for r in rows:
        print(
            f"{r['signal_minute']} {r['symbol']:<14} {r['side']} "
            f"MFE={r['mfe_60m_pct']:+.3f}%@{r['mfe_minute']} "
            f"MAE={r['mae_60m_pct']:+.3f}% preMFE={r['mae_before_mfe_pct']:+.3f}% "
            f"EXIT={r['research_exit_reason']:<16} {r['research_realized_pct']:+.3f}% "
            f"{r['classification']}"
        )

    print("\nAPPARENT 30M LOSERS - ENTRY/EXIT DIAGNOSIS")
    losers=[r for r in rows if f(r.get("v6_1_30m_pct"),0)<=0]
    for r in losers:
        print(
            f"{r['symbol']:<14} sig={r['signal_minute']} 30m={r['v6_1_30m_pct']} "
            f"MFE={r['mfe_60m_pct']:+.3f}% at {r['mfe_minute']} "
            f"preMFE_MAE={r['mae_before_mfe_pct']:+.3f}% "
            f"research_exit={r['research_exit_reason']} {r['research_realized_pct']:+.3f}% "
            f"=> {r['classification']}"
        )

    print("\nNOTE: percentages are underlying directional percentage-point moves, not option-premium returns.")
    print("NOTE: exit rules are research heuristics only; no trade/order logic changed.")
    print("Files:")
    print(" ",outcsv)
    print(" ",outdir/"run_manifest.json")
    print("="*128)

if __name__=="__main__":
    main()
