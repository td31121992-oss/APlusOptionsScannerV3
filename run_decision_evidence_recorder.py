from __future__ import annotations
import argparse
from aplus_decision_evidence_recorder import Recorder
p=argparse.ArgumentParser()
p.add_argument("--once",action="store_true")
p.add_argument("--interval",type=int,default=15)
a=p.parse_args()
r=Recorder()
if a.once:
    print(r.cycle())
else:
    r.run_loop(a.interval)
