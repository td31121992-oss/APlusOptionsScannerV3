from __future__ import annotations
import argparse
from stock_futures_paper_engine import Engine
p=argparse.ArgumentParser();p.add_argument("--once",action="store_true");p.add_argument("--interval",type=int,default=30);a=p.parse_args()
e=Engine()
e.run_once() if a.once else e.run_loop(a.interval)
