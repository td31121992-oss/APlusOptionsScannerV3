import pandas as pd
from pathlib import Path

root = Path(r"C:\Users\Aplus\Desktop\APlusOptionsScannerV3")
for day in ["2026-10-22", "2026-10-23"]:
    p = root / "data" / "options_intelligence_upstox" / day / "option_chain_rows.csv.gz"
    df = pd.read_csv(p, compression="gzip", usecols=["captured_at"])
    t = df["captured_at"].dropna().astype(str)
    print(f"\nDAY: {day}")
    print("Raw first 5 timestamps:", t.head(5).tolist())
    print("Raw last 5 timestamps:", t.tail(5).tolist())
    print("Raw sample strings with timezone suffix:")
    print([x for x in t if ("+" in x or x.endswith("Z"))][:5])
