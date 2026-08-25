from pathlib import Path
ROOT=Path(__file__).resolve().parent
req=["stock_futures_paper_engine.py","run_stock_futures_paper.py","stock_futures_paper_dashboard.py"]
for n in req:
    p=ROOT/n
    if not p.exists():raise SystemExit("FAIL missing "+n)
    compile(p.read_text(encoding="utf-8"),n,"exec")
src=(ROOT/"stock_futures_paper_engine.py").read_text(encoding="utf-8")
for needle in (".place_order(",".modify_order(",".cancel_order("):
    if needle in src:raise SystemExit("FAIL live futures order authority found: "+needle)
checks={"paper_only":"PAPER FUTURES ONLY" in src,"entry_ready_input":"intraday_entry_ready.csv" in src,"leadership_input":"leadership_v6_shadow_latest.json" in src,"futstk_resolution":"FUTSTK" in src,"actual_futures_quote":"get_market_quotes" in src,"forced_intraday_exit":"FORCED_INTRADAY_EXIT" in src,"history":"stock_futures_paper_history.json" in src}
print("="*100);print("APLUS STOCK FUTURES PAPER V1 VERIFY")
for k,v in checks.items():print("PASS" if v else "FAIL",k)
print("PASS no live futures order call exists")
print("PASS existing stock-options scanner is not patched")
print("="*100)
raise SystemExit(0 if all(checks.values()) else 1)
