from __future__ import annotations
import csv, json, math
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LATEST = ROOT/"data"/"reports"/"fno_market_watch_latest.json"
CHART_BASE = ROOT/"data"/"chart_history"
REPORT_DIR = ROOT/"data"/"reports"
OUTBASE = ROOT/"data"/"leadership_engine_v5"

TARGETS = {"BDL","CDSL","GVT&D","POWERINDIA","POWERGRID"}

def f(v, d=0.0):
    try:
        x=float(v)
        return x if math.isfinite(x) else d
    except Exception:
        return d

def parse_ts(v):
    try:
        return datetime.fromisoformat(str(v))
    except Exception:
        return None

def latest_day():
    try:
        d=json.loads(LATEST.read_text(encoding="utf-8"))
        t=parse_ts(d.get("generated_at"))
        if t:
            return t.date().isoformat()
    except Exception:
        pass
    return datetime.now().date().isoformat()

def load_market_history(day):
    p=CHART_BASE/day/"market_watch_1m.csv"
    if not p.exists():
        raise SystemExit(f"Missing {p}")
    by=defaultdict(list)
    with p.open("r",encoding="utf-8-sig",newline="") as h:
        for r in csv.DictReader(h):
            sym=str(r.get("symbol") or "").upper().strip()
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

def load_optional_candidate_reports():
    """Load latest scanner feature rows if available.

    These are not assumed to be historical minute-perfect; they are used only
    as optional feature evidence when the same symbol has fields persisted.
    """
    names=[
        "intraday_movement_candidates.csv",
        "opening_momentum_candidates.csv",
        "intraday_near_misses.csv",
        "intraday_entry_ready.csv",
    ]
    merged={}
    for name in names:
        p=REPORT_DIR/name
        if not p.exists():
            continue
        try:
            with p.open("r",encoding="utf-8-sig",newline="") as h:
                for r in csv.DictReader(h):
                    sym=str(r.get("symbol") or "").upper().strip()
                    if not sym:
                        continue
                    dst=merged.setdefault(sym,{})
                    for k,v in r.items():
                        if v not in ("",None):
                            dst[k]=v
        except Exception:
            pass
    return merged

def rank_maps(rows):
    up=sorted(rows,key=lambda r:r["from_open_pct"],reverse=True)
    dn=sorted(rows,key=lambda r:r["from_open_pct"])
    return (
        {r["symbol"]:i+1 for i,r in enumerate(up)},
        {r["symbol"]:i+1 for i,r in enumerate(dn)},
    )

def main():
    day=latest_day()
    by=load_market_history(day)
    optional=load_optional_candidate_reports()
    minutes=sorted(by)
    if len(minutes)<30:
        raise SystemExit("Need at least 30 saved minutes.")

    timeline=defaultdict(list)
    for minute in minutes:
        rows=by[minute]
        ur,dr=rank_maps(rows)
        for r in rows:
            direction="UP" if r["from_open_pct"]>=0 else "DOWN"
            rank=ur[r["symbol"]] if direction=="UP" else dr[r["symbol"]]
            timeline[r["symbol"]].append({**r,"minute":minute,"direction":direction,"rank":rank})

    candidates=[]
    states_by_symbol={}

    for sym,h in timeline.items():
        h.sort(key=lambda z:z["minute"])
        states=[]
        opt=optional.get(sym,{})
        opt_rvol=f(opt.get("relative_volume"))
        opt_vwap_dist=f(opt.get("vwap_distance_percent"))
        opt_trend=f(opt.get("trend_alignment_score"))
        opt_clean=f(opt.get("clean_trend_score"))
        opt_chase=f(opt.get("chase_risk_score"))
        opt_adx=f(opt.get("adx14_5m"))
        opt_ema9=f(opt.get("ema9_5m"))
        opt_ema20=f(opt.get("ema20_5m"))

        for i,x in enumerate(h):
            rec={**x,"eligible_history":False,"v5_state":"EARLY_OBSERVATION"}
            if i<15:
                states.append(rec)
                continue

            p3,p5,p10,p15=h[i-3],h[i-5],h[i-10],h[i-15]
            sign=1 if x["direction"]=="UP" else -1

            rc5=(p5["rank"]-x["rank"]) if p5["direction"]==x["direction"] else 0
            rc10=(p10["rank"]-x["rank"]) if p10["direction"]==x["direction"] else 0
            rc15=(p15["rank"]-x["rank"]) if p15["direction"]==x["direction"] else 0
            mc3=(x["from_open_pct"]-p3["from_open_pct"])*sign
            mc5=(x["from_open_pct"]-p5["from_open_pct"])*sign
            mc10=(x["from_open_pct"]-p10["from_open_pct"])*sign
            mc15=(x["from_open_pct"]-p15["from_open_pct"])*sign

            recent=h[i-4:i+1]
            persist=sum(1 for z in recent if z["direction"]==x["direction"] and z["rank"]<=20)
            top20=x["rank"]<=20
            top10=x["rank"]<=10
            rank_accel=(rc5>=5 or rc10>=10)
            price_accel=(mc5>=0.20 or mc10>=0.35)
            range_ok=x["range_position_pct"]>=70 if x["direction"]=="UP" else x["range_position_pct"]<=30
            ltp_structure=(x["ltp"]>=p5["ltp"]>=p10["ltp"]) if x["direction"]=="UP" else (x["ltp"]<=p5["ltp"]<=p10["ltp"])
            not_extended=abs(x["from_open_pct"])<=3.00

            # "Immediate failure" proxy: if the most recent 3-minute directional progress
            # is strongly negative, do not fast-confirm even if 5m/10m leadership is high.
            immediate_failure = mc3 <= -0.18
            soft_pause = (-0.18 < mc3 < 0.05)
            healthy_immediate = mc3 >= 0.05

            # Optional real scanner features when present. These are NOT fabricated.
            rvol_ok = (opt_rvol >= 1.10) if opt_rvol > 0 else None
            vwap_ok = ((opt_vwap_dist >= 0) if x["direction"]=="UP" else (opt_vwap_dist <= 0)) if opt_vwap_dist != 0 else None
            trend_ok = (opt_trend >= 55) if opt_trend > 0 else None
            clean_ok = (opt_clean >= 65) if opt_clean > 0 else None
            chase_ok = (opt_chase <= 18) if opt_chase > 0 else None
            adx_ok = (opt_adx >= 22) if opt_adx > 0 else None
            ema_ok = None
            if opt_ema9>0 and opt_ema20>0:
                ema_ok=(opt_ema9>=opt_ema20) if x["direction"]=="UP" else (opt_ema9<=opt_ema20)

            # Core fast detection must remain early.
            raw_fast = top20 and rank_accel and price_accel and persist>=3 and range_ok and ltp_structure and not_extended

            # Technical confirmation: use available real evidence but do not require unavailable fields.
            available_checks=[z for z in (rvol_ok,vwap_ok,trend_ok,clean_ok,chase_ok,adx_ok,ema_ok) if z is not None]
            positive_checks=sum(1 for z in available_checks if z)
            technical_ratio=(positive_checks/len(available_checks)) if available_checks else None

            technical_confirmed = (
                raw_fast and
                not immediate_failure and
                (
                    technical_ratio is None or
                    technical_ratio >= 0.60
                )
            )

            # Strong top-10 continuation path can survive a soft 3m pause.
            strong_top10 = (
                top10 and price_accel and persist>=4 and range_ok and ltp_structure and
                not_extended and not immediate_failure
            )

            score=(
                min(max(rc5,0),30)*1.4 +
                min(max(rc10,0),50)*0.6 +
                min(max(mc5,0),1.5)*22 +
                min(max(mc10,0),2.5)*9 +
                max(0,21-x["rank"])*1.0 +
                (10 if persist>=3 else 0) +
                (8 if range_ok else 0) +
                (8 if ltp_structure else 0) +
                (6 if healthy_immediate else 0) +
                (2 if soft_pause else 0) +
                (-15 if immediate_failure else 0)
            )
            if technical_ratio is not None:
                score += technical_ratio*15
            score=round(score,2)

            state="WATCH"
            if technical_confirmed:
                state="V5_FAST_CONFIRMED_CE" if x["direction"]=="UP" else "V5_FAST_CONFIRMED_PE"
            elif strong_top10:
                state="V5_STRONG_CONTINUATION_CE" if x["direction"]=="UP" else "V5_STRONG_CONTINUATION_PE"
            elif raw_fast:
                state="V5_RAW_FAST_UNCONFIRMED"
            elif top20 and rank_accel:
                state="V5_LEADERSHIP_DEVELOPING"

            rec={**x,
                "eligible_history":True,
                "rank_change_5m":rc5,"rank_change_10m":rc10,"rank_change_15m":rc15,
                "move_change_3m_pct":round(mc3,4),
                "move_change_5m_pct":round(mc5,4),
                "move_change_10m_pct":round(mc10,4),
                "move_change_15m_pct":round(mc15,4),
                "persistence_count_5m":persist,
                "range_confirmed":range_ok,
                "price_structure_confirmed":ltp_structure,
                "immediate_failure":immediate_failure,
                "technical_checks_available":len(available_checks),
                "technical_checks_positive":positive_checks,
                "technical_ratio":round(technical_ratio,3) if technical_ratio is not None else None,
                "leadership_score":score,
                "v5_state":state,
                "confirmed":state.startswith("V5_FAST_CONFIRMED") or state.startswith("V5_STRONG_CONTINUATION"),
            }
            states.append(rec)
            if rec["confirmed"]:
                candidates.append(rec)

        states_by_symbol[sym]=states

    idx={sym:{z["minute"]:i for i,z in enumerate(h)} for sym,h in timeline.items()}

    # First confirmed signal per 15-minute episode.
    episodes=[]
    last={}
    for s in sorted(candidates,key=lambda z:(z["symbol"],z["minute"])):
        sym=s["symbol"]; i=idx[sym][s["minute"]]
        if sym in last and i-last[sym] < 15:
            continue
        last[sym]=i
        h=timeline[sym]
        sign=1 if s["direction"]=="UP" else -1
        entry=s["from_open_pct"]

        def fw(n):
            if i+n>=len(h):
                return None
            return round((h[i+n]["from_open_pct"]-entry)*sign,4)

        future=h[i:min(len(h),i+61)]
        vals=[(z["from_open_pct"]-entry)*sign for z in future]
        episodes.append({
            "signal_minute":s["minute"],
            "symbol":sym,
            "side":"CE" if s["direction"]=="UP" else "PE",
            "state":s["v5_state"],
            "rank":s["rank"],
            "move_at_signal_pct":round(entry,4),
            "rank_change_5m":s["rank_change_5m"],
            "rank_change_10m":s["rank_change_10m"],
            "move_change_3m_pct":s["move_change_3m_pct"],
            "move_change_5m_pct":s["move_change_5m_pct"],
            "technical_checks_available":s["technical_checks_available"],
            "technical_checks_positive":s["technical_checks_positive"],
            "technical_ratio":s["technical_ratio"],
            "leadership_score":s["leadership_score"],
            "fwd_5m_pct":fw(5),
            "fwd_15m_pct":fw(15),
            "fwd_30m_pct":fw(30),
            "fwd_60m_pct":fw(60),
            "mfe_next_60m_pct":round(max(vals),4) if vals else None,
            "mae_next_60m_pct":round(min(vals),4) if vals else None,
        })

    outdir=OUTBASE/day
    outdir.mkdir(parents=True,exist_ok=True)

    def write_csv(path,rows):
        if not rows:
            return
        with path.open("w",encoding="utf-8-sig",newline="") as fh:
            w=csv.DictWriter(fh,fieldnames=list(rows[0].keys()))
            w.writeheader();w.writerows(rows)

    write_csv(outdir/"v5_confirmed_episodes.csv",episodes)

    summaries=[]
    for sym,h in timeline.items():
        es=[e for e in episodes if e["symbol"]==sym]
        first=es[0] if es else None
        summaries.append({
            "symbol":sym,
            "first_confirmed_signal":first["signal_minute"] if first else "",
            "first_side":first["side"] if first else "",
            "rank_at_first":first["rank"] if first else "",
            "move_at_first_pct":first["move_at_signal_pct"] if first else "",
            "latest_move_pct":round(h[-1]["from_open_pct"],4),
            "episodes":len(es),
        })
    write_csv(outdir/"v5_symbol_summary.csv",summaries)
    write_csv(outdir/"v5_target_forensics.csv",[e for e in episodes if e["symbol"] in TARGETS])

    def vals(k):
        return [e[k] for e in episodes if e[k] is not None]
    def win(k):
        a=vals(k)
        return round(100*sum(1 for x in a if x>0)/len(a),2) if a else None

    manifest={
        "day":day,
        "symbols":len(timeline),
        "minutes":len(minutes),
        "confirmed_episodes":len(episodes),
        "win_5m_pct":win("fwd_5m_pct"),
        "win_15m_pct":win("fwd_15m_pct"),
        "win_30m_pct":win("fwd_30m_pct"),
        "win_60m_pct":win("fwd_60m_pct"),
        "valid_5m_samples":len(vals("fwd_5m_pct")),
        "valid_15m_samples":len(vals("fwd_15m_pct")),
        "valid_30m_samples":len(vals("fwd_30m_pct")),
        "valid_60m_samples":len(vals("fwd_60m_pct")),
        "avg_mfe_next_60m_pct":round(sum(vals("mfe_next_60m_pct"))/len(vals("mfe_next_60m_pct")),4) if vals("mfe_next_60m_pct") else None,
        "avg_mae_next_60m_pct":round(sum(vals("mae_next_60m_pct"))/len(vals("mae_next_60m_pct")),4) if vals("mae_next_60m_pct") else None,
        "production_changes":False,
        "dhan_calls":False,
        "option_entries_executed":False,
    }
    (outdir/"run_manifest.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")

    print("="*126)
    print("APLUS LEADERSHIP ENGINE V5 - FAST TECHNICAL CONFIRMATION REPLAY")
    print("READ ONLY - ZERO DHAN CALLS - ZERO PRODUCTION CHANGES")
    print("="*126)
    for k,v in manifest.items():
        print(f"{k:<28}: {v}")

    print("\nTARGET RETENTION")
    for sym in ["BDL","CDSL","GVT&D","POWERGRID","POWERINDIA"]:
        es=[e for e in episodes if e["symbol"]==sym]
        if not es:
            print(f"{sym:<12} NOT CONFIRMED")
            continue
        e=es[0]
        print(f"{sym:<12} {e['signal_minute']} {e['side']} rank={e['rank']:>3} move={e['move_at_signal_pct']:+.3f}% "
              f"m3={e['move_change_3m_pct']:+.3f}% m5={e['move_change_5m_pct']:+.3f}% "
              f"tech={e['technical_checks_positive']}/{e['technical_checks_available']} "
              f"15m={str(e['fwd_15m_pct']):>7} 30m={str(e['fwd_30m_pct']):>7} 60m={str(e['fwd_60m_pct']):>7}")

    print("\nTOP 20 CONFIRMED EPISODES")
    for e in sorted(episodes,key=lambda z:z["leadership_score"],reverse=True)[:20]:
        print(f"{e['signal_minute']} {e['symbol']:<14} {e['side']} {e['state']:<26} "
              f"rank={e['rank']:>3} score={e['leadership_score']:>7.2f} "
              f"5m={str(e['fwd_5m_pct']):>7} 15m={str(e['fwd_15m_pct']):>7} "
              f"30m={str(e['fwd_30m_pct']):>7} 60m={str(e['fwd_60m_pct']):>7}")

    print("\nNOTE: Optional scanner features are used only when actually present in saved reports.")
    print("NOTE: Missing VWAP/EMA/ADX/volume evidence is never invented.")
    print("="*126)

if __name__=="__main__":
    main()
