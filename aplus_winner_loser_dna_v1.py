from __future__ import annotations

"""
APlus Winner-vs-Loser DNA V1
READ ONLY - ZERO DHAN CALLS - ZERO STRATEGY CHANGES

Goal:
Find which ENTRY-TIME features distinguish historical winners from losers,
without using future information such as exit reason, P&L magnitude, MFE/MAE,
or post-entry underlying movement as predictors.

Important:
- This is research, not a production strategy.
- With only ~15 winners and ~5 trading days, overfitting risk is very high.
- The tool therefore reports both in-sample rules and leave-one-day-out results.
- Premium is analyzed descriptively but is EXCLUDED from the default DNA score.
"""

import csv
import json
import math
import os
from collections import defaultdict
from itertools import combinations, product
from pathlib import Path
from statistics import mean, median
from typing import Any

ROOT = Path(__file__).resolve().parent
REPORTS = ROOT / "data" / "reports"
OUT = REPORTS / "winner_loser_dna_v1"
OUT.mkdir(parents=True, exist_ok=True)

INPUT_CANDIDATES = [
    REPORTS / "full_history_forensic_v2" / "all_trades_stock_vs_option.csv",
    REPORTS / "full_history_forensic" / "all_trades_forensic.csv",
    REPORTS / "paper_trade_history.csv",
    REPORTS / "paper_trades.csv",
]

# Only information available at or before entry belongs here.
NUMERIC_FEATURES = [
    "trade_quality_score",
    "clean_trend_score",
    "trend_alignment_score",
    "movement_capture_score",
    "chase_risk_score",
    "session_rvol",
    "recent_15m_rvol",
    "tape_accel_5m",
    "tape_accel_15m",
    "vwap_distance_pct",
    "recent_move_5m_pct",
    "recent_move_10m_pct",
    "recent_move_15m_pct",
    "recent_move_30m_pct",
    "move_from_0915_open_pct",
]

CATEGORICAL_FEATURES = [
    "direction",
    "option_type",
    "stage",
    "setup_family",
    "selection_tier",
    "pivot_state",
]

# Explicit leakage exclusions. These must never be used in the DNA score/rules.
LEAKAGE_KEYWORDS = (
    "exit",
    "net_pnl",
    "gross_pnl",
    "return_percent",
    "mfe",
    "mae",
    "after_entry",
    "after_exit",
    "underlying_class",
    "root_cause",
    "forensic",
    "status",
)

MIN_RULE_TRADES = int(os.getenv("APLUS_DNA_MIN_RULE_TRADES", "6"))
MIN_RULE_DAYS = int(os.getenv("APLUS_DNA_MIN_RULE_DAYS", "2"))
MAX_RULES = int(os.getenv("APLUS_DNA_MAX_RULES", "5000"))

def num(v: Any, default: float = 0.0) -> float:
    try:
        if v in (None, ""):
            return default
        x = float(v)
        return x if math.isfinite(x) else default
    except Exception:
        return default

def read_csv(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig", newline="") as h:
        return [dict(r) for r in csv.DictReader(h)]

def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields = []
    seen = set()
    for r in rows:
        for k in r:
            if k not in seen:
                seen.add(k)
                fields.append(k)
    with path.open("w", encoding="utf-8-sig", newline="") as h:
        w = csv.DictWriter(h, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

def find_input() -> Path:
    for p in INPUT_CANDIDATES:
        if p.exists():
            return p
    raise SystemExit(
        "FAIL: no forensic trade CSV found. Run Full-History Forensic V2 first."
    )

def parse_hour(entry_time: str) -> float:
    s = str(entry_time or "")
    try:
        hh = int(s[11:13]); mm = int(s[14:16])
        return hh + mm / 60.0
    except Exception:
        return 0.0

def normalize(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for r in rows:
        pnl = num(r.get("net_pnl"))
        if pnl == 0 and not r.get("exit_time"):
            continue
        x = dict(r)
        x["label_win"] = 1 if pnl > 0 else 0
        x["entry_hour_decimal"] = parse_hour(r.get("entry_time"))
        x["abs_vwap_distance_pct"] = abs(num(r.get("vwap_distance_pct")))
        x["directional_vwap_alignment"] = (
            num(r.get("vwap_distance_pct"))
            if str(r.get("direction") or "").upper() == "BULLISH"
            else -num(r.get("vwap_distance_pct"))
        )
        out.append(x)
    return out

def percentile(vals: list[float], q: float) -> float:
    if not vals:
        return 0.0
    s = sorted(vals)
    if len(s) == 1:
        return s[0]
    pos = (len(s)-1) * q
    lo = int(math.floor(pos)); hi = int(math.ceil(pos))
    if lo == hi:
        return s[lo]
    w = pos - lo
    return s[lo]*(1-w) + s[hi]*w

def safe_median(vals):
    return median(vals) if vals else 0.0

def feature_dna(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    wins = [r for r in rows if r["label_win"] == 1]
    losses = [r for r in rows if r["label_win"] == 0]
    feats = list(NUMERIC_FEATURES) + [
        "entry_hour_decimal","abs_vwap_distance_pct","directional_vwap_alignment"
    ]
    dna = []
    for f in feats:
        wv = [num(r.get(f)) for r in wins if r.get(f) not in (None, "")]
        lv = [num(r.get(f)) for r in losses if r.get(f) not in (None, "")]
        if len(wv) < 2 or len(lv) < 5:
            continue
        wm = safe_median(wv); lm = safe_median(lv)
        wall = wv + lv
        span = percentile(wall, .90) - percentile(wall, .10)
        effect = (wm-lm)/span if span else 0.0
        direction = "HIGHER_IS_WINNER_LIKE" if effect > 0 else "LOWER_IS_WINNER_LIKE"
        dna.append({
            "feature": f,
            "winner_n": len(wv),
            "loser_n": len(lv),
            "winner_mean": round(mean(wv), 6),
            "loser_mean": round(mean(lv), 6),
            "winner_median": round(wm, 6),
            "loser_median": round(lm, 6),
            "normalized_median_separation": round(effect, 6),
            "winner_like_direction": direction,
            "abs_separation": round(abs(effect), 6),
        })
    dna.sort(key=lambda r: r["abs_separation"], reverse=True)
    return dna

def categorical_dna(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    overall = sum(r["label_win"] for r in rows) / len(rows) if rows else 0
    out=[]
    for f in CATEGORICAL_FEATURES:
        by=defaultdict(list)
        for r in rows:
            v=str(r.get(f) or "").strip()
            if v:
                by[v].append(r)
        for v, xs in by.items():
            if len(xs) < 3:
                continue
            wr=sum(r["label_win"] for r in xs)/len(xs)
            out.append({
                "feature":f,"value":v,"trades":len(xs),
                "wins":sum(r["label_win"] for r in xs),
                "win_rate_pct":round(wr*100,2),
                "lift_vs_overall":round((wr/overall) if overall else 0,3),
                "net_pnl":round(sum(num(r.get("net_pnl")) for r in xs),2),
            })
    out.sort(key=lambda r:(r["lift_vs_overall"],r["trades"]),reverse=True)
    return out

def make_thresholds(rows, feature, direction):
    vals=[num(r.get(feature)) for r in rows if r.get(feature) not in (None,"")]
    if len(vals)<10:return []
    qs=(.25,.40,.50,.60,.70,.80,.90)
    th=sorted(set(round(percentile(vals,q),6) for q in qs))
    return [(feature,">=",x) for x in th] if direction=="HIGHER_IS_WINNER_LIKE" else [(feature,"<=",x) for x in th]

def match_rule(r, rule):
    f,op,t=rule
    v=num(r.get(f))
    return v>=t if op==">=" else v<=t

def eval_rules(rows, rules):
    xs=[r for r in rows if all(match_rule(r,ru) for ru in rules)]
    if not xs:
        return None
    wins=sum(r["label_win"] for r in xs)
    pnl=sum(num(r.get("net_pnl")) for r in xs)
    days=len(set(str(r.get("trading_date") or "") for r in xs if r.get("trading_date")))
    return {
        "trades":len(xs),"wins":wins,"losses":len(xs)-wins,
        "win_rate_pct":round(wins/len(xs)*100,2),
        "net_pnl":round(pnl,2),
        "expectancy":round(pnl/len(xs),2),
        "days":days,
    }

def rule_text(rules):
    return " AND ".join(f"{f} {op} {t}" for f,op,t in rules)

def candidate_rules(rows, dna):
    # Use strongest entry-time numeric separators only.
    top=[r for r in dna if r["abs_separation"]>0][:8]
    pools=[make_thresholds(rows,r["feature"],r["winner_like_direction"]) for r in top]
    flat=[x for pool in pools for x in pool]
    candidates=[]
    seen=set()
    # Singles, pairs, triples only. Cap total to control overfit explosion.
    for k in (1,2,3):
        for rules in combinations(flat,k):
            feats=[r[0] for r in rules]
            if len(set(feats))<k:
                continue
            key=tuple(sorted(rules))
            if key in seen:
                continue
            seen.add(key)
            ev=eval_rules(rows,rules)
            if not ev or ev["trades"]<MIN_RULE_TRADES or ev["days"]<MIN_RULE_DAYS:
                continue
            rec={"rule":rule_text(rules),**ev}
            # Balanced ranking: precision first, then expectancy, but penalize tiny samples.
            rec["research_score"]=round(
                ev["win_rate_pct"]*1.5 + max(-50,min(50,ev["expectancy"]/100)) + min(20,ev["trades"]),
                3
            )
            candidates.append(rec)
            if len(candidates)>=MAX_RULES:
                break
        if len(candidates)>=MAX_RULES:
            break
    candidates.sort(key=lambda r:(r["win_rate_pct"],r["expectancy"],r["trades"]),reverse=True)
    return candidates

def parse_rule(text):
    out=[]
    for part in text.split(" AND "):
        m=part.rsplit(" ",2)
        if len(m)==3:
            f,op,t=m
            out.append((f,op,float(t)))
    return out

def leave_one_day_out(rows, candidate_recs):
    days=sorted(set(str(r.get("trading_date") or "") for r in rows if r.get("trading_date")))
    results=[]
    # Test top 100 in-sample candidates only, but score strictly on held-out days.
    for rec in candidate_recs[:100]:
        rules=parse_rule(rec["rule"])
        fold_rows=[]
        for d in days:
            test=[r for r in rows if str(r.get("trading_date") or "")==d]
            ev=eval_rules(test,rules)
            if ev and ev["trades"]:
                fold_rows.append((d,ev))
        if not fold_rows:
            continue
        total_trades=sum(ev["trades"] for _,ev in fold_rows)
        total_wins=sum(ev["wins"] for _,ev in fold_rows)
        total_pnl=sum(ev["net_pnl"] for _,ev in fold_rows)
        active_days=sum(1 for _,ev in fold_rows if ev["trades"]>0)
        results.append({
            "rule":rec["rule"],
            "heldout_trades":total_trades,
            "heldout_wins":total_wins,
            "heldout_losses":total_trades-total_wins,
            "heldout_win_rate_pct":round(total_wins/total_trades*100,2) if total_trades else 0,
            "heldout_net_pnl":round(total_pnl,2),
            "heldout_expectancy":round(total_pnl/total_trades,2) if total_trades else 0,
            "active_days":active_days,
            "note":"Leave-one-day-out descriptive check; only 5 days means high uncertainty.",
        })
    results.sort(key=lambda r:(r["heldout_win_rate_pct"],r["heldout_expectancy"],r["heldout_trades"]),reverse=True)
    return results

def dna_score_rows(rows, dna):
    # Entry-time only score. Premium deliberately excluded.
    selected=[r for r in dna if r["abs_separation"]>0][:8]
    out=[]
    for r in rows:
        score=0.0; used=0
        for d in selected:
            f=d["feature"]
            if f not in r or r.get(f) in (None,""):
                continue
            v=num(r.get(f)); wm=num(d["winner_median"]); lm=num(d["loser_median"])
            denom=abs(wm-lm)
            if denom<1e-9:continue
            direction=1 if wm>lm else -1
            contribution=direction*(v-lm)/denom
            contribution=max(-2,min(2,contribution))
            score+=contribution*max(.05,num(d["abs_separation"]))
            used+=1
        x=dict(r)
        x["dna_score"]=round(score/used,6) if used else 0.0
        out.append(x)
    return out

def selectivity_ladder(scored):
    xs=sorted(scored,key=lambda r:num(r.get("dna_score")),reverse=True)
    ns=[5,10,15,20,25,30,40,50,75,100,150,len(xs)]
    out=[]
    seen=set()
    for n in ns:
        n=min(n,len(xs))
        if n<=0 or n in seen:continue
        seen.add(n)
        subset=xs[:n]
        wins=sum(r["label_win"] for r in subset)
        pnl=sum(num(r.get("net_pnl")) for r in subset)
        out.append({
            "top_n":n,"wins":wins,"losses":n-wins,
            "win_rate_pct":round(wins/n*100,2),
            "net_pnl":round(pnl,2),
            "expectancy":round(pnl/n,2),
            "unique_days":len(set(str(r.get("trading_date") or "") for r in subset)),
        })
    return out

def daily(rows):
    by=defaultdict(list)
    for r in rows:by[str(r.get("trading_date") or "UNKNOWN")].append(r)
    out=[]
    for d,xs in sorted(by.items()):
        wins=sum(r["label_win"] for r in xs)
        pnl=sum(num(r.get("net_pnl")) for r in xs)
        out.append({"day":d,"trades":len(xs),"wins":wins,"losses":len(xs)-wins,
                    "win_rate_pct":round(wins/len(xs)*100,2),"net_pnl":round(pnl,2)})
    return out

def make_html(summary,dna,cat,rules,cv,ladder,path):
    def tbl(rows,cols):
        head="".join(f"<th>{c}</th>" for c in cols)
        body="".join("<tr>"+"".join(f"<td>{r.get(c,'')}</td>" for c in cols)+"</tr>" for r in rows)
        return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"
    html=f"""<!doctype html><html><head><meta charset='utf-8'><title>APlus Winner DNA</title>
<style>body{{font-family:Segoe UI,Arial;background:#0b1020;color:#e8eef8;margin:25px}}.warn{{background:#3a2c10;padding:12px;border-radius:10px}}table{{width:100%;border-collapse:collapse;background:#121a2d;margin-bottom:30px}}th,td{{padding:7px;border-bottom:1px solid #29344d;font-size:12px;text-align:left}}th{{color:#8fa1c0}}.cards{{display:grid;grid-template-columns:repeat(5,1fr);gap:10px}}.c{{background:#121a2d;padding:13px;border-radius:12px}}.v{{font-size:22px;font-weight:700}}</style></head><body>
<h1>APlus Winner-vs-Loser DNA V1</h1>
<div class='warn'><b>Research warning:</b> {summary['wins']} winners across {summary['days']} days is a tiny positive sample. Any 90%+ in-sample rule may be overfit. Production promotion requires forward validation.</div>
<div class='cards'>
<div class='c'>Trades<div class='v'>{summary['trades']}</div></div>
<div class='c'>Winners<div class='v'>{summary['wins']}</div></div>
<div class='c'>Losers<div class='v'>{summary['losses']}</div></div>
<div class='c'>Win Rate<div class='v'>{summary['win_rate_pct']}%</div></div>
<div class='c'>Target<div class='v'>204W / 15L</div></div>
</div>
<h2>Numeric Winner DNA</h2>{tbl(dna[:20],['feature','winner_mean','loser_mean','winner_median','loser_median','normalized_median_separation','winner_like_direction'])}
<h2>Categorical Winner DNA</h2>{tbl(cat[:30],['feature','value','trades','wins','win_rate_pct','lift_vs_overall','net_pnl'])}
<h2>Best In-Sample Selective Rules</h2>{tbl(rules[:30],['rule','trades','wins','losses','win_rate_pct','net_pnl','expectancy','days'])}
<h2>Same Rules: Day-Level Check</h2>{tbl(cv[:30],['rule','heldout_trades','heldout_wins','heldout_losses','heldout_win_rate_pct','heldout_net_pnl','heldout_expectancy','active_days'])}
<h2>DNA Score Selectivity Ladder</h2>{tbl(ladder,['top_n','wins','losses','win_rate_pct','net_pnl','expectancy','unique_days'])}
</body></html>"""
    path.write_text(html,encoding="utf-8")

def main():
    source=find_input()
    raw=read_csv(source)
    rows=normalize(raw)
    if not rows:
        raise SystemExit("FAIL: no closed historical trades available.")
    wins=sum(r["label_win"] for r in rows)
    days=len(set(str(r.get("trading_date") or "") for r in rows if r.get("trading_date")))

    dna=feature_dna(rows)
    cat=categorical_dna(rows)
    rules=candidate_rules(rows,dna)
    cv=leave_one_day_out(rows,rules)
    scored=dna_score_rows(rows,dna)
    ladder=selectivity_ladder(scored)

    summary={
        "input_file":str(source),
        "trades":len(rows),"wins":wins,"losses":len(rows)-wins,
        "win_rate_pct":round(wins/len(rows)*100,2),
        "days":days,
        "numeric_features_evaluated":len(dna),
        "categorical_groups_evaluated":len(cat),
        "candidate_rules":len(rules),
        "premium_used_in_dna_score":False,
        "future_information_used_as_predictor":False,
        "read_only":True,"dhan_calls":False,"strategy_changes":False,
        "target_note":"204 winners / 15 losers is a research aspiration, not assumed achievable.",
    }

    write_csv(OUT/"winner_loser_numeric_dna.csv",dna)
    write_csv(OUT/"winner_loser_categorical_dna.csv",cat)
    write_csv(OUT/"selective_rules_in_sample.csv",rules)
    write_csv(OUT/"selective_rules_day_check.csv",cv)
    write_csv(OUT/"trade_dna_scores.csv",scored)
    write_csv(OUT/"selectivity_ladder.csv",ladder)
    write_csv(OUT/"daily_baseline.csv",daily(rows))
    (OUT/"summary.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")
    make_html(summary,dna,cat,rules,cv,ladder,OUT/"winner_loser_dna.html")

    print("="*126)
    print("APLUS WINNER-vs-LOSER DNA V1")
    print("READ ONLY - ZERO DHAN CALLS - ZERO STRATEGY CHANGES - NO FUTURE LEAKAGE")
    print("="*126)
    for k,v in summary.items():print(f"{k:38}: {v}")
    print()
    print("TOP NUMERIC WINNER DNA")
    for x in dna[:12]:
        print(f'{x["feature"]:30} winnerMed={x["winner_median"]:10.4f} loserMed={x["loser_median"]:10.4f} sep={x["normalized_median_separation"]:+.4f} {x["winner_like_direction"]}')
    print()
    print("TOP IN-SAMPLE SELECTIVE RULES")
    for x in rules[:15]:
        print(f'{x["win_rate_pct"]:6.2f}%  trades={x["trades"]:3} wins={x["wins"]:3} losses={x["losses"]:3} exp={x["expectancy"]:9.2f}  {x["rule"]}')
    print()
    print("DAY-LEVEL CHECK OF SAME RULES")
    for x in cv[:15]:
        print(f'{x["heldout_win_rate_pct"]:6.2f}%  trades={x["heldout_trades"]:3} wins={x["heldout_wins"]:3} losses={x["heldout_losses"]:3} exp={x["heldout_expectancy"]:9.2f}  {x["rule"]}')
    print()
    print("DNA SELECTIVITY LADDER")
    for x in ladder:
        print(f'Top {x["top_n"]:3}: wins={x["wins"]:3} losses={x["losses"]:3} win={x["win_rate_pct"]:6.2f}% pnl={x["net_pnl"]:11.2f} exp={x["expectancy"]:9.2f}')
    print()
    print("OPEN:",OUT/"winner_loser_dna.html")
    print("="*126)

if __name__=="__main__":
    main()
