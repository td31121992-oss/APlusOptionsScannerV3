from __future__ import annotations
import csv, json, math, os
from pathlib import Path
from typing import Any, Mapping

_MARKER = "OPEN_MOVE_PATTERN_OBSERVER_V1_1"
_STATE = {"trading_date":"","symbols":{}}

def _n(v: Any, d: float=0.0) -> float:
    try:
        x=float(v)
        return x if math.isfinite(x) else d
    except Exception:
        return d

def _b(v: Any) -> bool:
    if isinstance(v,bool): return v
    return str(v or "").strip().lower() in {"1","true","yes","y","on"}

def _rows(value: Any) -> list[dict[str,Any]]:
    """Normalize scanner payload structures into a list of row mappings.

    Handles:
      list[dict]
      dict[symbol -> dict]
      dict with rows/data/stocks/items/candidates list
      accidental strings/other values safely
    """
    if isinstance(value, list):
        return [dict(x) for x in value if isinstance(x, Mapping)]
    if not isinstance(value, Mapping):
        return []

    # Common wrapped collections.
    for key in ("rows","data","stocks","items","candidates","market_watch"):
        v=value.get(key)
        if isinstance(v,list):
            return [dict(x) for x in v if isinstance(x, Mapping)]

    # Symbol -> row map.
    out=[]
    for k,v in value.items():
        if isinstance(v,Mapping):
            x=dict(v)
            x.setdefault("symbol",k)
            out.append(x)
    return out

def observe_open_move_patterns(*, payload: Mapping[str,Any], current_time, report_dir, logger=None) -> dict[str,Any]:
    day=current_time.date().isoformat()
    if _STATE.get("trading_date") != day:
        _STATE.clear(); _STATE.update({"trading_date":day,"symbols":{}})

    candidate_rows=_rows(payload.get("candidates",[]))
    market_rows=_rows(payload.get("fno_market_watch",[]))

    candidates={str(r.get("symbol") or "").strip().upper():dict(r)
                for r in candidate_rows if str(r.get("symbol") or "").strip()}
    market={str(r.get("symbol") or "").strip().upper():dict(r)
            for r in market_rows if str(r.get("symbol") or "").strip()}

    observations=[]; progressive=[]; reversals=[]; flips=[]
    for symbol in sorted(set(market)|set(candidates)):
        m=market.get(symbol,{}); c=candidates.get(symbol,{})
        move=_n(m.get("from_open_pct",m.get("move_from_open_percent",
             c.get("move_from_0915_open_percent",c.get("move_from_open_percent",0)))))
        ltp=_n(m.get("ltp",c.get("ltp",0)))
        open_0915=_n(m.get("open_0915",m.get("open",c.get("open_0915",c.get("day_open",0)))))
        day_high=_n(m.get("day_high",m.get("high",c.get("day_high",0))))
        day_low=_n(m.get("day_low",m.get("low",c.get("day_low",0))))
        range_pos=_n(m.get("range_position_percent",m.get("range_pos_pct",
                   m.get("range_position",c.get("range_position_percent",50)))),50)
        if 0 <= range_pos <= 1:
            range_pos *= 100.0

        recent5=_n(c.get("recent_move_5m_percent",0))
        recent10=_n(c.get("recent_move_10m_percent",0))
        recent15=_n(c.get("recent_move_15m_percent",0))
        retention=_n(c.get("trend_retention_percent",0))
        quality=_n(c.get("trade_quality_score",c.get("score",0)))
        clean=_n(c.get("clean_trend_score",0))
        align=_n(c.get("trend_alignment_score",0))
        rvol=max(_n(c.get("relative_volume",0)),_n(c.get("recent_relative_volume_15m",0)),
                 _n(c.get("tape_volume_acceleration_5m",0)),_n(c.get("tape_volume_acceleration_15m",0)))
        fresh=any(_b(c.get(k)) for k in ("fresh_15m_high","fresh_15m_low","fresh_30m_high",
            "fresh_30m_low","fresh_day_high","fresh_day_low","opening_range_breakout"))

        s=_STATE["symbols"].setdefault(symbol,{
            "min_move":move,"max_move":move,"prior_direction":"",
            "progressive_first":"","reversal_first":""
        })
        s["min_move"]=min(_n(s.get("min_move"),move),move)
        s["max_move"]=max(_n(s.get("max_move"),move),move)

        direction="BULLISH" if move>=0.20 else ("BEARISH" if move<=-0.20 else "NEUTRAL")
        prior=str(s.get("prior_direction") or "")
        if prior in {"BULLISH","BEARISH"} and direction in {"BULLISH","BEARISH"} and prior!=direction:
            flips.append({"symbol":symbol,"from":prior,"to":direction,
                          "time":current_time.isoformat(),"move_from_open_pct":round(move,4)})
        if direction!="NEUTRAL":
            s["prior_direction"]=direction

        sign=1 if direction=="BULLISH" else -1
        dir_move=move*sign
        dir5=recent5*sign
        dir10=recent10*sign
        dir_range=range_pos if direction=="BULLISH" else 100-range_pos
        adverse=(-_n(s["min_move"])) if direction=="BULLISH" else _n(s["max_move"])
        recovery=(move-_n(s["min_move"])) if direction=="BULLISH" else (_n(s["max_move"])-move)

        idea=(direction!="NEUTRAL" and dir_move>=0.55 and dir5>=0.08 and dir10>=0.18 and dir_range>=68
              and (retention>=68 or dir_range>=82) and (rvol>=1.15 or quality>=90)
              and (fresh or clean>=82 or align>=78))

        kaynes=(direction!="NEUTRAL" and adverse>=0.30 and recovery>=0.75 and dir_move>=0.40
                and dir5>=0.10 and dir10>=0.22 and dir_range>=65
                and (rvol>=1.15 or quality>=90))

        if idea and not s["progressive_first"]:
            s["progressive_first"]=current_time.isoformat()
        if kaynes and not s["reversal_first"]:
            s["reversal_first"]=current_time.isoformat()

        row={
            "timestamp":current_time.isoformat(),"trading_date":day,"symbol":symbol,
            "pattern_direction":direction,"ltp":ltp,"open_0915":open_0915,
            "move_from_open_pct":round(move,4),"day_high":day_high,"day_low":day_low,
            "range_position_pct":round(range_pos,2),
            "min_move_seen_pct":round(_n(s["min_move"]),4),
            "max_move_seen_pct":round(_n(s["max_move"]),4),
            "initial_adverse_pct_for_direction":round(adverse,4),
            "recovery_from_extreme_pct":round(recovery,4),
            "recent_move_5m_pct":round(recent5,4),
            "recent_move_10m_pct":round(recent10,4),
            "recent_move_15m_pct":round(recent15,4),
            "relative_participation":round(rvol,4),
            "trend_retention_pct":round(retention,2),
            "trade_quality_score":round(quality,2),
            "clean_trend_score":round(clean,2),
            "trend_alignment_score":round(align,2),
            "fresh_breakout":fresh,
            "idea_progressive":idea,
            "kaynes_reversal":kaynes,
            "progressive_first_time":s["progressive_first"],
            "reversal_first_time":s["reversal_first"],
            "paper_trade_status":str(c.get("paper_trade_status") or ""),
            "rejection_reason":str(c.get("rejection_reason") or "")
        }
        observations.append(row)
        if idea: progressive.append(row)
        if kaynes: reversals.append(row)

    report_dir=Path(report_dir)
    latest=report_dir/"open_move_patterns_latest.json"
    hist=report_dir.parent/"open_move_pattern_history"/day
    hist.mkdir(parents=True,exist_ok=True)
    csv_path=hist/"open_move_patterns.csv"

    summary={
        "generated_at":current_time.isoformat(),
        "observer":_MARKER,
        "research_only":True,
        "production_changes":False,
        "symbols_observed":len(observations),
        "candidate_rows_received":len(candidate_rows),
        "market_rows_received":len(market_rows),
        "idea_progressive_hits":progressive,
        "kaynes_reversal_hits":reversals,
        "direction_flips":flips,
    }

    tmp=latest.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(summary,indent=2,default=str),encoding="utf-8")
    os.replace(tmp,latest)

    if observations:
        fields=list(observations[0])
        exists=csv_path.exists() and csv_path.stat().st_size>0
        with csv_path.open("a",newline="",encoding="utf-8") as h:
            w=csv.DictWriter(h,fieldnames=fields)
            if not exists:w.writeheader()
            w.writerows(observations)

    if logger:
        logger.info(
            "OPEN_MOVE_PATTERN_OBSERVER_V1_1 symbols=%d progressive=%d reversal=%d flips=%d progressive_symbols=%s reversal_symbols=%s",
            len(observations),len(progressive),len(reversals),len(flips),
            ",".join(x["symbol"] for x in progressive[:10]),
            ",".join(x["symbol"] for x in reversals[:10]),
        )
    return summary
