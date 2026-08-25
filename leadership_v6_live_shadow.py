from __future__ import annotations
import csv,json
from collections import defaultdict,deque
from datetime import timedelta
from pathlib import Path

class LeadershipV6Shadow:
    """All-day rank/acceleration observer. It NEVER changes actionability."""
    def __init__(self,report_dir:Path):
        self.report_dir=Path(report_dir);self.report_dir.mkdir(parents=True,exist_ok=True)
        self.hist=defaultdict(lambda:deque(maxlen=45))
    @staticmethod
    def dmove(c):
        m=float(getattr(c,"move_from_0915_open_percent",0) or 0)
        return m if str(getattr(c,"direction",""))=="BULLISH" else -m
    def evaluate(self,candidates,now):
        bulls=sorted([c for c in candidates if str(getattr(c,"direction",""))=="BULLISH"],key=self.dmove,reverse=True)
        bears=sorted([c for c in candidates if str(getattr(c,"direction",""))=="BEARISH"],key=self.dmove,reverse=True)
        ranks={}
        for arr in (bulls,bears):
            for i,c in enumerate(arr):ranks[str(getattr(c,"symbol",""))]=i+1
        rows=[]
        for c in candidates:
            sym=str(getattr(c,"symbol",""));direction=str(getattr(c,"direction",""));rank=ranks.get(sym,999);move=self.dmove(c);q=self.hist[sym];q.append({"t":now,"rank":rank,"move":move})
            def past(minutes):
                target=now-timedelta(minutes=minutes);a=[x for x in q if x["t"]<=target];return a[-1] if a else None
            p3,p5=past(3),past(5);m3=move-p3["move"] if p3 else 0.0;m5=move-p5["move"] if p5 else 0.0;r5=p5["rank"]-rank if p5 else 0
            edge=float(getattr(c,"range_position_percent",50) or 50);edge=edge if direction=="BULLISH" else 100-edge
            breakout=bool(getattr(c,"fresh_15m_high",False) or getattr(c,"fresh_30m_high",False) or getattr(c,"fresh_day_high",False)) if direction=="BULLISH" else bool(getattr(c,"fresh_15m_low",False) or getattr(c,"fresh_30m_low",False) or getattr(c,"fresh_day_low",False))
            struct=float(getattr(c,"aligned_structure_ratio",0) or 0)>=.60
            vwap=float(getattr(c,"vwap_distance_percent",0) or 0);vwap_ok=vwap>0 if direction=="BULLISH" else vwap<0
            e9=float(getattr(c,"ema9_5m",0) or 0);e20=float(getattr(c,"ema20_5m",0) or 0);ema_ok=e9>=e20 if direction=="BULLISH" else e9<=e20
            pts=sum([edge>=70,breakout,struct,vwap_ok and ema_ok])
            qualified=rank<=10 and m3>=.20 and m5>=.25 and pts>=3
            rows.append({"timestamp":now.isoformat(),"symbol":sym,"direction":direction,"rank":rank,"directional_move_pct":round(move,4),"rank_change_5m":r5,"move_change_3m_pct":round(m3,4),"move_change_5m_pct":round(m5,4),"structure_points_proxy":pts,"qualified_shadow":qualified,"trade_quality_score":getattr(c,"trade_quality_score",0),"trend_alignment_score":getattr(c,"trend_alignment_score",0),"clean_trend_score":getattr(c,"clean_trend_score",0),"relative_volume":getattr(c,"relative_volume",0)})
        (self.report_dir/"leadership_v6_shadow_latest.json").write_text(json.dumps({"generated_at":now.isoformat(),"rows":rows},indent=2,default=str),encoding="utf-8")
        if rows:
            with (self.report_dir/"leadership_v6_shadow_latest.csv").open("w",encoding="utf-8-sig",newline="") as h:
                w=csv.DictWriter(h,fieldnames=list(rows[0].keys()));w.writeheader();w.writerows(rows)
        return rows
