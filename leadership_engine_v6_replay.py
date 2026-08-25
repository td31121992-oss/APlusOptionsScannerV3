from __future__ import annotations
import csv, json, math
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT=Path(__file__).resolve().parent
LATEST=ROOT/"data"/"reports"/"fno_market_watch_latest.json"
CHART_BASE=ROOT/"data"/"chart_history"
V5_BASE=ROOT/"data"/"leadership_engine_v5"
OUTBASE=ROOT/"data"/"leadership_engine_v6"

TARGETS={"BDL","CDSL","GVT&D","POWERINDIA","POWERGRID"}

def f(v,d=0.0):
    try:
        x=float(v)
        return x if math.isfinite(x) else d
    except Exception:
        return d

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

def load_history(day):
    p=CHART_BASE/day/"market_watch_1m.csv"
    if not p.exists(): raise SystemExit(f"Missing {p}")
    by_sym=defaultdict(list)
    with p.open("r",encoding="utf-8-sig",newline="") as h:
        for r in csv.DictReader(h):
            sym=str(r.get("symbol") or "").upper().strip()
            minute=str(r.get("minute") or "").strip()
            if not sym or not minute: continue
            by_sym[sym].append({
                "minute":minute,
                "ltp":f(r.get("ltp")),
                "from_open_pct":f(r.get("from_open_pct")),
                "range_position_pct":f(r.get("range_position_pct")),
            })
    for sym in by_sym:
        by_sym[sym].sort(key=lambda z:z["minute"])
    return by_sym

def load_v5(day):
    p=V5_BASE/day/"v5_confirmed_episodes.csv"
    if not p.exists():
        raise SystemExit(f"Missing {p}. Run V5 first.")
    with p.open("r",encoding="utf-8-sig",newline="") as h:
        return list(csv.DictReader(h))

def pct(a,b):
    if not b:return 0.0
    return (a-b)/b*100.0

def bucket_5m(rows):
    """Build sampled 5-minute OHLC from persisted 1-minute LTP observations.

    This is NOT exchange OHLC. It is a truthful reconstruction from observed
    1-minute LTP samples only.
    """
    buckets=defaultdict(list)
    for r in rows:
        hh,mm=map(int,r["minute"].split(":")[:2])
        key=f"{hh:02d}:{(mm//5)*5:02d}"
        buckets[key].append(r)
    out=[]
    for key in sorted(buckets):
        a=buckets[key]
        prices=[z["ltp"] for z in a if z["ltp"]>0]
        if not prices: continue
        out.append({
            "bucket":key,
            "open":prices[0],"high":max(prices),"low":min(prices),"close":prices[-1],
            "first_minute":a[0]["minute"],"last_minute":a[-1]["minute"],
        })
    return out

def nearest_bucket_index(candles,minute):
    # signal minute belongs to its 5-minute bucket
    hh,mm=map(int,minute.split(":")[:2])
    key=f"{hh:02d}:{(mm//5)*5:02d}"
    for i,c in enumerate(candles):
        if c["bucket"]==key:return i
    return None

def main():
    day=latest_day()
    hist=load_history(day)
    v5=load_v5(day)
    outdir=OUTBASE/day
    outdir.mkdir(parents=True,exist_ok=True)

    rows=[]
    for e in v5:
        sym=e["symbol"]
        if sym not in hist: continue
        candles=bucket_5m(hist[sym])
        ci=nearest_bucket_index(candles,e["signal_minute"])
        if ci is None or ci<4: continue

        c=candles[ci]
        prev=candles[ci-1]
        p2=candles[ci-2]
        p3=candles[ci-3]
        p4=candles[ci-4]
        side=e["side"]
        bull=side=="CE"

        # Sampled candle geometry
        rng=max(c["high"]-c["low"],1e-9)
        body=abs(c["close"]-c["open"])
        body_ratio=body/rng
        upper_wick=c["high"]-max(c["open"],c["close"])
        lower_wick=min(c["open"],c["close"])-c["low"]
        close_pos=(c["close"]-c["low"])/rng

        directional_close=(c["close"]>c["open"]) if bull else (c["close"]<c["open"])
        close_near_extreme=(close_pos>=0.70) if bull else (close_pos<=0.30)

        # Higher-high / higher-low proxy on sampled candles.
        hhhl = (
            c["high"]>=prev["high"] and c["low"]>=prev["low"]
            if bull else
            c["low"]<=prev["low"] and c["high"]<=prev["high"]
        )

        # Breakout of recent sampled 5m swing.
        prev3_high=max(prev["high"],p2["high"],p3["high"])
        prev3_low=min(prev["low"],p2["low"],p3["low"])
        breakout=(c["close"]>prev3_high) if bull else (c["close"]<prev3_low)

        # Breakout retention: close remains beyond prior 2-candle extreme.
        prev2_high=max(prev["high"],p2["high"])
        prev2_low=min(prev["low"],p2["low"])
        retention=(c["close"]>=prev2_high) if bull else (c["close"]<=prev2_low)

        # Pullback / chase diagnostics.
        recent4=[p4,p3,p2,prev]
        if bull:
            recent_high=max(z["high"] for z in recent4)
            recent_low=min(z["low"] for z in recent4)
            extension_pct=pct(c["close"],recent_low)
            rejection_wick_ratio=upper_wick/rng
        else:
            recent_high=max(z["high"] for z in recent4)
            recent_low=min(z["low"] for z in recent4)
            extension_pct=pct(recent_high,c["close"])
            rejection_wick_ratio=lower_wick/rng

        # Consecutive directional sampled candles before/current signal.
        seq=0
        for z in reversed(candles[max(0,ci-5):ci+1]):
            ok=(z["close"]>z["open"]) if bull else (z["close"]<z["open"])
            if ok: seq+=1
            else: break

        blowoff=(body_ratio>=0.75 and seq>=3 and extension_pct>=1.8)
        heavy_rejection=rejection_wick_ratio>=0.35
        healthy_body=(body_ratio>=0.35 and directional_close and close_near_extreme)

        # Structure confirmation deliberately permissive enough not to delay good leaders.
        structure_points=sum([
            healthy_body,
            hhhl,
            breakout,
            retention,
        ])
        structure_confirmed=(
            structure_points>=2 and
            not heavy_rejection and
            not blowoff
        )

        # "Fast retain" path for strong leaders even if breakout candle is a pause.
        leadership_score=f(e.get("leadership_score"))
        m3=f(e.get("move_change_3m_pct"))
        m5=f(e.get("move_change_5m_pct"))
        rank=int(float(e.get("rank") or 999))
        pause_retain=(
            structure_points>=1 and
            not heavy_rejection and
            not blowoff and
            rank<=10 and
            leadership_score>=90 and
            m3>=0 and m5>=0.15
        )

        v6_confirmed=structure_confirmed or pause_retain

        rows.append({
            **e,
            "sampled_5m_body_ratio":round(body_ratio,4),
            "sampled_close_position":round(close_pos,4),
            "sampled_hhhl_confirmed":hhhl,
            "sampled_breakout_confirmed":breakout,
            "sampled_breakout_retention":retention,
            "sampled_rejection_wick_ratio":round(rejection_wick_ratio,4),
            "sampled_directional_sequence":seq,
            "sampled_extension_pct":round(extension_pct,4),
            "sampled_heavy_rejection":heavy_rejection,
            "sampled_blowoff":blowoff,
            "sampled_structure_points":structure_points,
            "v6_structure_confirmed":v6_confirmed,
            "v6_confirmation_mode":"STRUCTURE" if structure_confirmed else "PAUSE_RETAIN" if pause_retain else "REJECTED",
            "v6_note":"Sampled 5m candles reconstructed from persisted 1m LTP; not exchange OHLC.",
        })

    confirmed=[r for r in rows if r["v6_structure_confirmed"]]

    def write(path,data):
        if not data:return
        with path.open("w",encoding="utf-8-sig",newline="") as fh:
            w=csv.DictWriter(fh,fieldnames=list(data[0].keys()))
            w.writeheader();w.writerows(data)

    write(outdir/"v6_all_v5_candidates_with_structure.csv",rows)
    write(outdir/"v6_structure_confirmed.csv",confirmed)
    write(outdir/"v6_target_forensics.csv",[r for r in rows if r["symbol"] in TARGETS])

    def vals(data,k):
        a=[]
        for r in data:
            v=r.get(k)
            if v in ("",None,"None"):continue
            try:a.append(float(v))
            except Exception:pass
        return a
    def win(data,k):
        a=vals(data,k)
        return round(100*sum(1 for x in a if x>0)/len(a),2) if a else None

    manifest={
        "day":day,
        "v5_candidates":len(rows),
        "v6_confirmed":len(confirmed),
        "retention_pct":round(100*len(confirmed)/len(rows),2) if rows else 0,
        "win_5m_pct":win(confirmed,"fwd_5m_pct"),
        "win_15m_pct":win(confirmed,"fwd_15m_pct"),
        "win_30m_pct":win(confirmed,"fwd_30m_pct"),
        "win_60m_pct":win(confirmed,"fwd_60m_pct"),
        "avg_mfe_60m_pct":round(sum(vals(confirmed,"mfe_next_60m_pct"))/len(vals(confirmed,"mfe_next_60m_pct")),4) if vals(confirmed,"mfe_next_60m_pct") else None,
        "avg_mae_60m_pct":round(sum(vals(confirmed,"mae_next_60m_pct"))/len(vals(confirmed,"mae_next_60m_pct")),4) if vals(confirmed,"mae_next_60m_pct") else None,
        "production_changes":False,
        "dhan_calls":False,
        "true_exchange_ohlc_used":False,
        "sampled_ohlc_from_1m_ltp":True,
    }
    (outdir/"run_manifest.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")

    print("="*128)
    print("APLUS LEADERSHIP ENGINE V6 - EXACT-SIGNAL CHART-STRUCTURE RECONSTRUCTION")
    print("READ ONLY - ZERO DHAN CALLS - ZERO PRODUCTION CHANGES")
    print("="*128)
    for k,v in manifest.items():
        print(f"{k:<30}: {v}")

    print("\nTARGET RETENTION")
    for sym in ["BDL","CDSL","GVT&D","POWERGRID","POWERINDIA"]:
        rr=[r for r in rows if r["symbol"]==sym]
        if not rr:
            print(f"{sym:<12} NO V5 CANDIDATE")
            continue
        r=rr[0]
        print(
            f"{sym:<12} {r['signal_minute']} {r['side']} "
            f"KEEP={str(r['v6_structure_confirmed']):<5} mode={r['v6_confirmation_mode']:<12} "
            f"pts={r['sampled_structure_points']} body={float(r['sampled_5m_body_ratio']):.2f} "
            f"wick={float(r['sampled_rejection_wick_ratio']):.2f} seq={r['sampled_directional_sequence']} "
            f"15m={r['fwd_15m_pct']} 30m={r['fwd_30m_pct']} 60m={r['fwd_60m_pct']}"
        )

    print("\nTOP 20 V6 CONFIRMED BY V5 LEADERSHIP SCORE")
    for r in sorted(confirmed,key=lambda z:f(z.get("leadership_score")),reverse=True)[:20]:
        print(
            f"{r['signal_minute']} {r['symbol']:<14} {r['side']} "
            f"mode={r['v6_confirmation_mode']:<12} pts={r['sampled_structure_points']} "
            f"score={f(r.get('leadership_score')):>7.2f} "
            f"5m={str(r.get('fwd_5m_pct')):>7} 15m={str(r.get('fwd_15m_pct')):>7} "
            f"30m={str(r.get('fwd_30m_pct')):>7} 60m={str(r.get('fwd_60m_pct')):>7}"
        )

    print("\nIMPORTANT:")
    print("- V6 reconstructs sampled 5m OHLC only from saved 1m LTP observations.")
    print("- It does NOT claim exchange-accurate candle OHLC.")
    print("- Volume is not fabricated.")
    print("- No option entries are executed or simulated.")
    print("="*128)

if __name__=="__main__":
    main()
