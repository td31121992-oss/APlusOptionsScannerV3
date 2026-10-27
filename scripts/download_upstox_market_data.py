"""Read-only Upstox historical candle downloader."""
import argparse, csv, gzip, json, os, time
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import quote
import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "upstox_market_data"
MASTER = "https://assets.upstox.com/market-quote/instruments/exchange/complete.json.gz"
API = "https://api.upstox.com/v3/historical-candle"

def token_from_env():
    token = os.getenv("UPSTOX_ACCESS_TOKEN") or os.getenv("UPSTOX_API_ACCESS_TOKEN")
    if token: return token.strip()
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8-sig").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                if key.strip() in ("UPSTOX_ACCESS_TOKEN", "UPSTOX_API_ACCESS_TOKEN"):
                    return value.strip().strip("'").strip('"')
    raise RuntimeError("Set UPSTOX_ACCESS_TOKEN in local .env or environment. Do not share it.")

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--from-date", default=(date.today()-timedelta(days=29)).isoformat())
    p.add_argument("--to-date", default=date.today().isoformat())
    p.add_argument("--symbols", default="")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--refresh", action="store_true")
    a = p.parse_args()
    start, end = date.fromisoformat(a.from_date), date.fromisoformat(a.to_date)
    if start > end or (end-start).days > 30: p.error("Minute candle range must be within 30 days.")
    OUT.mkdir(parents=True, exist_ok=True)
    sess = requests.Session()
    master_path = OUT / "instrument_master.json"
    if master_path.exists() and not a.refresh:
        instruments = json.loads(master_path.read_text(encoding="utf-8"))
    else:
        r = sess.get(MASTER, timeout=60); r.raise_for_status()
        try: raw = gzip.decompress(r.content)
        except OSError: raw = r.content
        instruments = json.loads(raw.decode("utf-8-sig"))
        master_path.write_text(json.dumps(instruments), encoding="utf-8")
    fno = {str(x.get("underlying_symbol","")).upper() for x in instruments if x.get("segment")=="NSE_FO" and x.get("underlying_type")=="EQUITY" and x.get("instrument_type") in ("FUT","CE","PE")}
    eq = {str(x.get("trading_symbol","")).upper():x for x in instruments if x.get("segment")=="NSE_EQ" and x.get("instrument_type")=="EQ" and str(x.get("trading_symbol","")).upper() in fno and str(x.get("instrument_key","")).startswith("NSE_EQ|")}
    symbols = sorted(eq)
    if a.symbols: symbols = [s.strip().upper() for s in a.symbols.split(",") if s.strip() in eq]
    if a.limit > 0: symbols = symbols[:a.limit]
    if not symbols: raise RuntimeError("No matching NSE F&O equity symbols found.")
    token = token_from_env()
    manifest = {"source":"Upstox Historical Candle API V3","read_only":True,"from_date":str(start),"to_date":str(end),"results":[]}
    for n, symbol in enumerate(symbols, 1):
        for interval in (3, 5):
            path = OUT / f"{symbol}_{interval}m.csv"
            if path.exists() and path.stat().st_size > 20 and not a.refresh:
                manifest["results"].append({"symbol":symbol,"interval":interval,"status":"cached"}); continue
            url = f"{API}/{quote(eq[symbol]['instrument_key'],safe='')}/minutes/{interval}/{end}/{start}"
            try:
                response = sess.get(url, headers={"Accept":"application/json","Authorization":"Bearer "+token}, timeout=30)
                if response.status_code in (401,403): raise RuntimeError("Upstox token unauthorized/expired; refresh it locally.")
                response.raise_for_status()
                data = response.json()
                if data.get("status") != "success": raise RuntimeError("Upstox returned non-success response.")
                candles = data.get("data",{}).get("candles",[])
                tmp = path.with_suffix(".tmp")
                with tmp.open("w",newline="",encoding="utf-8") as f:
                    w = csv.writer(f); w.writerow(["timestamp","open","high","low","close","volume","open_interest"])
                    for c in candles:
                        if len(c)>=6: w.writerow(c[:7] if len(c)>=7 else c[:6]+[""])
                tmp.replace(path)
                manifest["results"].append({"symbol":symbol,"interval":interval,"status":"ok" if candles else "empty","rows":len(candles),"file":path.name})
                print(f"[{n}/{len(symbols)}] {symbol} {interval}m: {len(candles)} rows")
            except Exception as e:
                manifest["results"].append({"symbol":symbol,"interval":interval,"status":"error","error":str(e)[:200]})
                print(f"ERROR {symbol} {interval}m: {e}")
                if "token unauthorized" in str(e): break
            time.sleep(0.25)
        if manifest["results"] and "token unauthorized" in manifest["results"][-1].get("error",""): break
    (OUT/"download_manifest.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")
    errors=sum(x["status"]=="error" for x in manifest["results"])
    print(f"Done. Manifest: {OUT/'download_manifest.json'}; errors={errors}")
    return 1 if errors else 0

if __name__ == "__main__": raise SystemExit(main())
