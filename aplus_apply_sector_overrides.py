from pathlib import Path
import json

ROOT = Path(__file__).resolve().parent
PATH = ROOT / "data" / "reports" / "fno_market_watch_latest.json"
AUTO = ['ASHOKLEY', 'BAJAJ-AUTO', 'BHARATFORG', 'BOSCHLTD', 'EICHERMOT', 'HEROMOTOCO', 'HYUNDAI', 'M&M', 'MARUTI', 'MOTHERSON', 'SONACOMS', 'TIINDIA', 'TMPV', 'TVSMOTOR', 'UNOMINDA']
AUTO_SET = set(AUTO)

def main():
    if not PATH.exists():
        print("SKIP: fno_market_watch_latest.json not found")
        return 0
    obj = json.loads(PATH.read_text(encoding="utf-8"))
    rows = obj.get("rows", []) if isinstance(obj, dict) else []
    changed = 0
    found = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        sym = str(row.get("symbol") or "").strip().upper()
        if sym in AUTO_SET:
            found.append(sym)
            if row.get("sector") != "Auto":
                row["sector"] = "Auto"
                changed += 1
    if isinstance(obj, dict) and "sectors" in obj:
        obj["sectors"] = sorted(set(str(r.get("sector") or "UNCLASSIFIED") for r in rows if isinstance(r, dict)))
    PATH.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    print("AUTO FOUND:", len(set(found)), sorted(set(found)))
    print("ROWS CHANGED:", changed)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
