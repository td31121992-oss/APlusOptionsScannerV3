from __future__ import annotations
import argparse
from leadership_v6_4_shadow import V64,run_loop
p=argparse.ArgumentParser();p.add_argument("--once",action="store_true");p.add_argument("--interval",type=int,default=30);a=p.parse_args()
if a.once:
    rows=V64().evaluate()
    for r in rows[:20]:
        print(r["symbol"],r["direction"],r["research_lane"],"q=",r["trade_quality_score"],"move=",r["directional_move_pct"])
else:run_loop(a.interval)
