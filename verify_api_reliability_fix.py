from pathlib import Path
ROOT=Path(__file__).resolve().parent
ENV=ROOT/".env"
SCANNER=ROOT/"opening_momentum_scanner.py"

def envmap():
    d={}
    if ENV.exists():
        for line in ENV.read_text(encoding="utf-8",errors="ignore").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k,v=line.split("=",1); d[k.strip()]=v.strip()
    return d

e=envmap()
s=SCANNER.read_text(encoding="utf-8",errors="ignore") if SCANNER.exists() else ""
print("="*86)
print("APlus API Reliability Verification")
print("="*86)
for k in ["HISTORICAL_REQUESTS_PER_SECOND","OPTION_CHAIN_REQUESTS_PER_SECOND","INTRADAY_HISTORICAL_WORKERS","INTRADAY_ACCOUNT_FUND_CACHE_SECONDS","INTRADAY_ACCOUNT_POSITIONS_CACHE_SECONDS"]:
    print(f"{k:<44} = {e.get(k,'<missing>')}")
print("account cache present           =", "self._account_cache" in s)
print("fund cache present              =", "_fund_cache_seconds" in s)
print("positions cache present         =", "_positions_cache_seconds" in s)
print("live orders remain disabled     =", '"live_orders_enabled": False' in s)
print("="*86)
