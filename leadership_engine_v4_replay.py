from __future__ import annotations
import csv, json, math
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LATEST = ROOT/"data"/"reports"/"fno_market_watch_latest.json"
CHART_BASE = ROOT/"data"/"chart_history"
OUTBASE = ROOT/"data"/"leadership_engine_v4"

TARGETS = {"BDL","CDSL","GVT&D","POWERINDIA","POWERGRID"}

def f(v, d=0.0):
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

def load_day(day):
    p=CHART_BASE/day/"market_watch_1m.csv"
    if not p.exists():
        raise SystemExit(f"Missing saved history: {p}")
    by=defaultdict(list)
    with p.open("r",encoding="utf-8-sig",newline="") as h:
        for r in csv.DictReader(h):
            sym=str(r.get("symbol") or "").strip().upper()
            minute=str(r.get("minute") or "").strip()
            if not sym or not minute:
                continue
            by[minute].append({
                "symbol":sym,
                "sector":str(r.get("sector") or ""),
                "ltp":f(r.get("ltp")),
                "open_0915":f(r.get("open_0915")),
                "previous_close":f(r.get("previous_close")),
                "from_open_pct":f(r.get("from_open_pct")),
                "from_prev_close_pct":f(r.get("from_prev_close_pct")),
                "day_high":f(r.get("day_high")),
                "day_low":f(r.get("day_low")),
                "range_position_pct":f(r.get("range_position_pct")),
            })
    return dict(by)

def rank_maps(rows):
    up=sorted(rows,key=lambda r:r["from_open_pct"],reverse=True)
    dn=sorted(rows,key=lambda r:r["from_open_pct"])
    return ({r["symbol"]:i+1 for i,r in enumerate(up)},
            {r["symbol"]:i+1 for i,r in enumerate(dn)})

def main():
    day=latest_day()
    by=load_day(day)
    minutes=sorted(by)
    if len(minutes)<25:
        raise SystemExit("Need at least 25 saved market minutes.")

    timeline=defaultdict(list)
    for minute in minutes:
        rows=by[minute]
        ur,dr=rank_maps(rows)
        for r in rows:
            direction="UP" if r["from_open_pct"]>=0 else "DOWN"
            rank=ur[r["symbol"]] if direction=="UP" else dr[r["symbol"]]
            timeline[r["symbol"]].append({**r,"minute":minute,"direction":direction,"rank":rank})

    states_by_symbol={}
    raw_candidates=[]

    for sym,h in timeline.items():
        h.sort(key=lambda z:z["minute"])
        states=[]
        for i,x in enumerate(h):
            rec={**x,"eligible_history":False,"leadership_state":"EARLY_OBSERVATION",
                 "leadership_score":0.0,"fast_candidate":False}
            if i < 15:
                states.append(rec)
                continue

            p5,p10,p15=h[i-5],h[i-10],h[i-15]
            sign=1 if x["direction"]=="UP" else -1

            rc5=(p5["rank"]-x["rank"]) if p5["direction"]==x["direction"] else 0
            rc10=(p10["rank"]-x["rank"]) if p10["direction"]==x["direction"] else 0
            rc15=(p15["rank"]-x["rank"]) if p15["direction"]==x["direction"] else 0

            mc5=(x["from_open_pct"]-p5["from_open_pct"])*sign
            mc10=(x["from_open_pct"]-p10["from_open_pct"])*sign
            mc15=(x["from_open_pct"]-p15["from_open_pct"])*sign

            recent=h[i-4:i+1]
            persistence=sum(1 for z in recent if z["direction"]==x["direction"] and z["rank"]<=20)
            range_ok=x["range_position_pct"]>=70 if x["direction"]=="UP" else x["range_position_pct"]<=30

            # Price structure using only saved 1-minute LTP; no invented VWAP/EMA/volume.
            ltp_now=x["ltp"]
            ltp5=p5["ltp"]
            ltp10=p10["ltp"]
            price_structure = (
                (ltp_now >= ltp5 >= ltp10) if x["direction"]=="UP"
                else (ltp_now <= ltp5 <= ltp10)
            )

            rank_accel=(rc5>=5 or rc10>=10)
            price_accel=(mc5>=0.20 or mc10>=0.35)
            top20=x["rank"]<=20
            top10=x["rank"]<=10
            persist_ok=persistence>=3
            not_extended=abs(x["from_open_pct"])<=3.25

            score=(
                min(max(rc5,0),30)*1.6 +
                min(max(rc10,0),50)*0.7 +
                min(max(mc5,0),1.5)*24 +
                min(max(mc10,0),2.5)*10 +
                max(0,21-x["rank"])*1.0 +
                (10 if persist_ok else 0) +
                (8 if range_ok else 0) +
                (8 if price_structure else 0) +
                (4 if not_extended else -8)
            )
            score=round(score,2)

            fast_candidate=(
                top20 and rank_accel and price_accel and persist_ok and
                range_ok and price_structure and not_extended
            )
            strong_candidate=(
                top10 and price_accel and persist_ok and
                price_structure and not_extended
            )

            state="WATCH"
            if fast_candidate:
                state="FAST_CE_CANDIDATE" if x["direction"]=="UP" else "FAST_PE_CANDIDATE"
            elif strong_candidate:
                state="STRONG_CE_CANDIDATE" if x["direction"]=="UP" else "STRONG_PE_CANDIDATE"
            elif top20 and rank_accel:
                state="LEADERSHIP_DEVELOPING"

            rec={**x,
                "eligible_history":True,
                "rank_change_5m":rc5,"rank_change_10m":rc10,"rank_change_15m":rc15,
                "move_change_5m_pct":round(mc5,4),
                "move_change_10m_pct":round(mc10,4),
                "move_change_15m_pct":round(mc15,4),
                "persistence_count_5m":persistence,
                "range_confirmed":range_ok,
                "price_structure_confirmed":price_structure,
                "not_extended":not_extended,
                "leadership_score":score,
                "leadership_state":state,
                "fast_candidate":bool(fast_candidate or strong_candidate),
            }
            states.append(rec)
            if rec["fast_candidate"]:
                raw_candidates.append(rec)

        states_by_symbol[sym]=states

    idx={sym:{z["minute"]:i for i,z in enumerate(h)} for sym,h in timeline.items()}

    # Collapse repeated alerts into episodes. First qualified signal wins; no waiting for max score.
    episodes=[]
    last_episode={}
    for s in sorted(raw_candidates,key=lambda z:(z["symbol"],z["minute"])):
        sym=s["symbol"]; i=idx[sym][s["minute"]]
        if sym in last_episode and i-last_episode[sym] < 15:
            continue
        last_episode[sym]=i
        h=timeline[sym]
        sign=1 if s["direction"]=="UP" else -1
        entry=s["from_open_pct"]

        def fw(n):
            if i+n >= len(h):
                return None
            return round((h[i+n]["from_open_pct"]-entry)*sign,4)

        remaining=len(h)-1-i
        future=h[i:min(len(h),i+61)]
        vals=[(z["from_open_pct"]-entry)*sign for z in future]

        episodes.append({
            "signal_minute":s["minute"],
            "symbol":sym,
            "side":"CE" if s["direction"]=="UP" else "PE",
            "state":s["leadership_state"],
            "rank":s["rank"],
            "move_at_signal_pct":round(s["from_open_pct"],4),
            "rank_change_5m":s["rank_change_5m"],
            "rank_change_10m":s["rank_change_10m"],
            "move_change_5m_pct":s["move_change_5m_pct"],
            "move_change_10m_pct":s["move_change_10m_pct"],
            "leadership_score":s["leadership_score"],
            "minutes_remaining":remaining,
            "fwd_5m_pct":fw(5),
            "fwd_15m_pct":fw(15),
            "fwd_30m_pct":fw(30),
            "fwd_60m_pct":fw(60),
            "mfe_next_60m_pct":round(max(vals),4) if vals else None,
            "mae_next_60m_pct":round(min(vals),4) if vals else None,
        })

    # Time-to-entry research: leadership candidate itself is the fast decision point.
    # Future V4.1 may enrich this with actual option-chain validation timestamps.
    for e in episodes:
        e["decision_delay_minutes"]=0
        e["option_validation_status"]="NOT_REPLAYED"
        e["paper_trade_action"]="RESEARCH_CANDIDATE_ONLY"

    outdir=OUTBASE/day
    outdir.mkdir(parents=True,exist_ok=True)

    def write_csv(path,rows):
        if not rows:
            return
        with path.open("w",encoding="utf-8-sig",newline="") as fh:
            w=csv.DictWriter(fh,fieldnames=list(rows[0].keys()))
            w.writeheader(); w.writerows(rows)

    write_csv(outdir/"v4_fast_candidates.csv",episodes)

    summaries=[]
    for sym,h in timeline.items():
        es=[e for e in episodes if e["symbol"]==sym]
        last=h[-1]
        first=es[0] if es else None
        summaries.append({
            "symbol":sym,
            "first_fast_signal":first["signal_minute"] if first else "",
            "first_side":first["side"] if first else "",
            "rank_at_first":first["rank"] if first else "",
            "move_at_first_pct":first["move_at_signal_pct"] if first else "",
            "latest_move_pct":round(last["from_open_pct"],4),
            "episodes":len(es),
        })
    write_csv(outdir/"v4_symbol_summary.csv",summaries)

    target_rows=[e for e in episodes if e["symbol"] in TARGETS]
    write_csv(outdir/"v4_target_forensics.csv",target_rows)

    def valid_vals(field):
        return [e[field] for e in episodes if e[field] is not None]
    def win(field):
        a=valid_vals(field)
        return round(100*sum(1 for x in a if x>0)/len(a),2) if a else None

    manifest={
        "day":day,
        "symbols":len(timeline),
        "minutes":len(minutes),
        "fast_candidate_episodes":len(episodes),
        "win_5m_pct":win("fwd_5m_pct"),
        "win_15m_pct":win("fwd_15m_pct"),
        "win_30m_pct":win("fwd_30m_pct"),
        "win_60m_pct":win("fwd_60m_pct"),
        "valid_5m_samples":len(valid_vals("fwd_5m_pct")),
        "valid_15m_samples":len(valid_vals("fwd_15m_pct")),
        "valid_30m_samples":len(valid_vals("fwd_30m_pct")),
        "valid_60m_samples":len(valid_vals("fwd_60m_pct")),
        "avg_mfe_next_60m_pct":round(sum(valid_vals("mfe_next_60m_pct"))/len(valid_vals("mfe_next_60m_pct")),4) if valid_vals("mfe_next_60m_pct") else None,
        "avg_mae_next_60m_pct":round(sum(valid_vals("mae_next_60m_pct"))/len(valid_vals("mae_next_60m_pct")),4) if valid_vals("mae_next_60m_pct") else None,
        "production_changes":False,
        "dhan_calls":False,
        "option_entries_executed":False,
        "note":"V4 fast qualification uses only fields present in saved market_watch_1m.csv. VWAP/EMA/volume/option-chain validation is intentionally not fabricated."
    }
    (outdir/"run_manifest.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")

    print("="*124)
    print("APLUS LEADERSHIP ENGINE V4 - FAST CE/PE QUALIFICATION REPLAY")
    print("READ ONLY - ZERO DHAN CALLS - ZERO PRODUCTION CHANGES")
    print("="*124)
    for k,v in manifest.items():
        if k!="note": print(f"{k:<28}: {v}")
    print("\nTARGET FAST SIGNALS")
    for sym in ["BDL","CDSL","GVT&D","POWERGRID","POWERINDIA"]:
        ss=[e for e in episodes if e["symbol"]==sym]
        if not ss:
            print(f"{sym:<12} NO FAST SIGNAL")
            continue
        e=ss[0]
        print(f"{sym:<12} {e['signal_minute']} {e['side']} rank={e['rank']:>3} move={e['move_at_signal_pct']:+.3f}% "
              f"r5={e['rank_change_5m']:+d} m5={e['move_change_5m_pct']:+.3f}% score={e['leadership_score']:.2f} "
              f"15m={str(e['fwd_15m_pct']):>7} 30m={str(e['fwd_30m_pct']):>7} 60m={str(e['fwd_60m_pct']):>7}")
    print("\nTOP 20 FAST CANDIDATES")
    for e in sorted(episodes,key=lambda z:z["leadership_score"],reverse=True)[:20]:
        print(f"{e['signal_minute']} {e['symbol']:<14} {e['side']} rank={e['rank']:>3} score={e['leadership_score']:>7.2f} "
              f"move={e['move_at_signal_pct']:+.3f}% 5m={str(e['fwd_5m_pct']):>7} 15m={str(e['fwd_15m_pct']):>7} "
              f"30m={str(e['fwd_30m_pct']):>7} 60m={str(e['fwd_60m_pct']):>7}")
    print("\nIMPORTANT: N/A forward horizons are stored as blank/None, never fake 0.000%.")
    print("IMPORTANT: This identifies fast CE/PE candidates; it does NOT execute or simulate option entries.")
    print("="*124)

if __name__=="__main__":
    main()
