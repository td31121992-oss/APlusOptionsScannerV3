from __future__ import annotations
import csv, json, itertools, math
from pathlib import Path
from datetime import datetime

ROOT=Path(__file__).resolve().parent
LATEST=ROOT/"data"/"reports"/"fno_market_watch_latest.json"
V6BASE=ROOT/"data"/"leadership_engine_v6"
OUTBASE=ROOT/"data"/"leadership_engine_v6_1"
TARGETS={"BDL","CDSL","GVT&D","POWERINDIA","POWERGRID"}

def f(v,d=None):
    try:
        x=float(v)
        return x if math.isfinite(x) else d
    except Exception:
        return d

def b(v):
    if isinstance(v,bool): return v
    return str(v).strip().lower() in {"1","true","yes","y"}

def latest_day():
    try:
        x=json.loads(LATEST.read_text(encoding="utf-8"))
        t=datetime.fromisoformat(str(x.get("generated_at")))
        return t.date().isoformat()
    except Exception:
        return datetime.now().date().isoformat()

def read_csv(p):
    with p.open("r",encoding="utf-8-sig",newline="") as h:
        return list(csv.DictReader(h))

def win(rows,field):
    vals=[f(r.get(field)) for r in rows]
    vals=[x for x in vals if x is not None]
    if not vals:return None
    return round(100*sum(1 for x in vals if x>0)/len(vals),2)

def avg(rows,field):
    vals=[f(r.get(field)) for r in rows]
    vals=[x for x in vals if x is not None]
    if not vals:return None
    return round(sum(vals)/len(vals),4)

def target_retention(rows):
    syms={r["symbol"] for r in rows}
    return sum(1 for s in TARGETS if s in syms)

def main():
    day=latest_day()
    src=V6BASE/day/"v6_structure_confirmed.csv"
    if not src.exists():
        raise SystemExit(f"Missing {src}. Run V6 first.")
    rows=read_csv(src)

    # Normalize fields used in matrix.
    for r in rows:
        r["_body"]=f(r.get("sampled_5m_body_ratio"),0.0)
        r["_wick"]=f(r.get("sampled_rejection_wick_ratio"),1.0)
        r["_pts"]=int(f(r.get("sampled_structure_points"),0) or 0)
        r["_seq"]=int(f(r.get("sampled_directional_sequence"),0) or 0)
        r["_ext"]=f(r.get("sampled_extension_pct"),0.0)
        r["_rank"]=int(f(r.get("rank"),999) or 999)
        r["_m3"]=f(r.get("move_change_3m_pct"),0.0)
        r["_m5"]=f(r.get("move_change_5m_pct"),0.0)
        r["_score"]=f(r.get("leadership_score"),0.0)
        r["_mode"]=str(r.get("v6_confirmation_mode") or "")
        r["_side"]=str(r.get("side") or "")
        r["_target"]=r.get("symbol") in TARGETS

    configs=[]
    body_opts=[0.0,0.35,0.50,0.65]
    wick_opts=[1.0,0.30,0.20,0.12]
    pts_opts=[1,2,3,4]
    rank_opts=[20,15,10]
    m3_opts=[-9.0,0.0,0.10,0.20]
    m5_opts=[0.0,0.15,0.25,0.40]
    mode_opts=["ANY","STRUCTURE_ONLY"]

    for body,wick,pts,rank,m3,m5,mode in itertools.product(
        body_opts,wick_opts,pts_opts,rank_opts,m3_opts,m5_opts,mode_opts
    ):
        kept=[]
        for r in rows:
            if r["_body"]<body: continue
            if r["_wick"]>wick: continue
            if r["_pts"]<pts: continue
            if r["_rank"]>rank: continue
            if r["_m3"]<m3: continue
            if r["_m5"]<m5: continue
            if mode=="STRUCTURE_ONLY" and r["_mode"]!="STRUCTURE": continue
            kept.append(r)

        if len(kept)<12: continue

        tr=target_retention(kept)
        w15=win(kept,"fwd_15m_pct")
        w30=win(kept,"fwd_30m_pct")
        w60=win(kept,"fwd_60m_pct")
        mfe=avg(kept,"mfe_next_60m_pct")
        mae=avg(kept,"mae_next_60m_pct")

        # Rank configs with heavy weight on retaining all 5 targets.
        score=(
            tr*100 +
            (w15 or 0)*1.4 +
            (w30 or 0)*1.2 +
            (w60 or 0)*0.7 +
            min(len(kept),80)*0.15 +
            ((mfe or 0) - abs(mae or 0))*20
        )

        configs.append({
            "body_min":body,"wick_max":wick,"points_min":pts,"rank_max":rank,
            "m3_min":m3,"m5_min":m5,"mode":mode,
            "kept":len(kept),"targets_retained":tr,
            "win_5m_pct":win(kept,"fwd_5m_pct"),
            "win_15m_pct":w15,"win_30m_pct":w30,"win_60m_pct":w60,
            "avg_mfe_60m_pct":mfe,"avg_mae_60m_pct":mae,
            "matrix_score":round(score,3),
        })

    configs.sort(key=lambda x:(x["targets_retained"],x["matrix_score"]),reverse=True)

    # Best all-5-target configuration, then best overall fallback.
    best5=next((c for c in configs if c["targets_retained"]==5),None)
    best=best5 or (configs[0] if configs else None)
    if not best:
        raise SystemExit("No matrix configuration produced enough samples.")

    def applies(r,c):
        return (
            r["_body"]>=c["body_min"] and
            r["_wick"]<=c["wick_max"] and
            r["_pts"]>=c["points_min"] and
            r["_rank"]<=c["rank_max"] and
            r["_m3"]>=c["m3_min"] and
            r["_m5"]>=c["m5_min"] and
            (c["mode"]=="ANY" or r["_mode"]=="STRUCTURE")
        )

    selected=[r for r in rows if applies(r,best)]
    rejected=[r for r in rows if not applies(r,best)]

    outdir=OUTBASE/day
    outdir.mkdir(parents=True,exist_ok=True)

    def clean(r):
        return {k:v for k,v in r.items() if not k.startswith("_")}

    def write(path,data):
        if not data:return
        data=[clean(r) for r in data]
        with path.open("w",encoding="utf-8-sig",newline="") as fh:
            w=csv.DictWriter(fh,fieldnames=list(data[0].keys()))
            w.writeheader();w.writerows(data)

    with (outdir/"v6_1_threshold_matrix.csv").open("w",encoding="utf-8-sig",newline="") as fh:
        w=csv.DictWriter(fh,fieldnames=list(configs[0].keys()))
        w.writeheader();w.writerows(configs)

    write(outdir/"v6_1_best_selected.csv",selected)
    write(outdir/"v6_1_best_rejected.csv",rejected)

    summary={
        "day":day,
        "v6_input":len(rows),
        "best_config":best,
        "selected":len(selected),
        "rejected":len(rejected),
        "targets_retained":target_retention(selected),
        "selected_win_5m_pct":win(selected,"fwd_5m_pct"),
        "selected_win_15m_pct":win(selected,"fwd_15m_pct"),
        "selected_win_30m_pct":win(selected,"fwd_30m_pct"),
        "selected_win_60m_pct":win(selected,"fwd_60m_pct"),
        "selected_avg_mfe_60m_pct":avg(selected,"mfe_next_60m_pct"),
        "selected_avg_mae_60m_pct":avg(selected,"mae_next_60m_pct"),
        "production_changes":False,
        "dhan_calls":False,
    }
    (outdir/"run_manifest.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")

    print("="*132)
    print("APLUS LEADERSHIP ENGINE V6.1 - THRESHOLD MATRIX / FALSE-POSITIVE FORENSIC")
    print("READ ONLY - ZERO DHAN CALLS - ZERO PRODUCTION CHANGES")
    print("="*132)
    print("V6 INPUT:",len(rows))
    print()
    print("BEST CONFIG RETAINING ALL 5 TARGETS" if best["targets_retained"]==5 else "BEST AVAILABLE CONFIG")
    for k,v in best.items():
        print(f"{k:<24}: {v}")

    print("\nSELECTED TARGETS")
    for sym in ["BDL","CDSL","GVT&D","POWERGRID","POWERINDIA"]:
        rr=[r for r in selected if r["symbol"]==sym]
        if not rr:
            print(f"{sym:<12} REJECTED")
            continue
        r=rr[0]
        print(
            f"{sym:<12} {r['signal_minute']} {r['side']} "
            f"rank={r['rank']} body={r['sampled_5m_body_ratio']} "
            f"wick={r['sampled_rejection_wick_ratio']} pts={r['sampled_structure_points']} "
            f"m3={r.get('move_change_3m_pct')} m5={r.get('move_change_5m_pct')} "
            f"15m={r.get('fwd_15m_pct')} 30m={r.get('fwd_30m_pct')} 60m={r.get('fwd_60m_pct')}"
        )

    print("\nTOP 15 MATRIX CONFIGS")
    for c in configs[:15]:
        print(
            f"targets={c['targets_retained']} kept={c['kept']:>3} "
            f"15m={str(c['win_15m_pct']):>6} 30m={str(c['win_30m_pct']):>6} 60m={str(c['win_60m_pct']):>6} "
            f"body>={c['body_min']:.2f} wick<={c['wick_max']:.2f} pts>={c['points_min']} "
            f"rank<={c['rank_max']} m3>={c['m3_min']:.2f} m5>={c['m5_min']:.2f} mode={c['mode']}"
        )

    print("\nFALSE-POSITIVE CHECK - SELECTED LOSERS BY 30M")
    bad=[r for r in selected if (f(r.get("fwd_30m_pct")) is not None and f(r.get("fwd_30m_pct"))<=0)]
    for r in sorted(bad,key=lambda z:f(z.get("fwd_30m_pct"),0))[:20]:
        print(
            f"{r['signal_minute']} {r['symbol']:<14} {r['side']} 30m={r.get('fwd_30m_pct')} "
            f"body={r['sampled_5m_body_ratio']} wick={r['sampled_rejection_wick_ratio']} "
            f"pts={r['sampled_structure_points']} rank={r['rank']} "
            f"m3={r.get('move_change_3m_pct')} m5={r.get('move_change_5m_pct')}"
        )

    print("\nFiles:")
    print(" ",outdir/"v6_1_threshold_matrix.csv")
    print(" ",outdir/"v6_1_best_selected.csv")
    print(" ",outdir/"v6_1_best_rejected.csv")
    print(" ",outdir/"run_manifest.json")
    print("="*132)

if __name__=="__main__":
    main()
