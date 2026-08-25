from pathlib import Path
import re, json
from collections import Counter, defaultdict

ROOT = Path(__file__).resolve().parent
DAY = "2026-08-20"

patterns = {
    "FUND_LIMIT_FAIL": re.compile(r"Safety fund-limit fetch failed", re.I),
    "OPTION_CHAIN_FAIL": re.compile(r"(option_chain|option chain).*(failure|failed|blank)", re.I),
    "HTTP_429": re.compile(r"429|Too Many Requests", re.I),
    "SAFETY_BLOCKED": re.compile(r"safety_blocked=(\d+)", re.I),
    "PLANS": re.compile(r"plans=(\d+)", re.I),
    "ENTRY_READY": re.compile(r"entry_ready=(\d+)", re.I),
    "PAPER_TODAY": re.compile(r"paper_today=(\d+)", re.I),
}

counts = Counter()
maxvals = defaultdict(int)
files_scanned = []

search_roots = [
    ROOT / "data" / "logs",
    ROOT / "logs",
    ROOT / "data" / "reports",
]

for base in search_roots:
    if not base.exists():
        continue
    for p in base.rglob("*"):
        if not p.is_file() or p.suffix.lower() not in {".log", ".txt", ".csv", ".json"}:
            continue
        try:
            if p.stat().st_size > 50_000_000:
                continue
            text = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        if DAY not in text and p.suffix.lower() in {".log", ".txt"}:
            continue

        matched = False
        for line in text.splitlines():
            if DAY not in line and p.suffix.lower() in {".log", ".txt"}:
                continue

            if patterns["FUND_LIMIT_FAIL"].search(line):
                counts["FUND_LIMIT_FAIL"] += 1; matched = True
            if patterns["OPTION_CHAIN_FAIL"].search(line):
                counts["OPTION_CHAIN_FAIL"] += 1; matched = True
            if patterns["HTTP_429"].search(line):
                counts["HTTP_429"] += 1; matched = True

            m = patterns["SAFETY_BLOCKED"].search(line)
            if m:
                v = int(m.group(1)); counts["CYCLES_WITH_SAFETY_BLOCKS"] += int(v > 0)
                counts["TOTAL_SAFETY_BLOCKED_REPORTED"] += v
                maxvals["MAX_SAFETY_BLOCKED_IN_CYCLE"] = max(maxvals["MAX_SAFETY_BLOCKED_IN_CYCLE"], v)
                matched = True

            for key in ("PLANS", "ENTRY_READY", "PAPER_TODAY"):
                m = patterns[key].search(line)
                if m:
                    v = int(m.group(1))
                    counts[f"CYCLES_WITH_{key}"] += int(v > 0)
                    maxvals[f"MAX_{key}"] = max(maxvals[f"MAX_{key}"], v)
                    matched = True

        if matched:
            files_scanned.append(str(p.relative_to(ROOT)))

print("="*92)
print("APLUS 2026-08-20 ZERO-TRADE ROOT-CAUSE DIAGNOSTIC")
print("="*92)
print("Files with relevant evidence:")
for f in sorted(set(files_scanned)):
    print(" ", f)

print("\nCOUNTS")
for k in [
    "FUND_LIMIT_FAIL",
    "OPTION_CHAIN_FAIL",
    "HTTP_429",
    "CYCLES_WITH_SAFETY_BLOCKS",
    "TOTAL_SAFETY_BLOCKED_REPORTED",
    "CYCLES_WITH_ENTRY_READY",
    "CYCLES_WITH_PLANS",
    "CYCLES_WITH_PAPER_TODAY",
]:
    print(f"{k:<34}: {counts.get(k,0)}")

print("\nMAX VALUES SEEN")
for k in ["MAX_ENTRY_READY","MAX_SAFETY_BLOCKED_IN_CYCLE","MAX_PLANS","MAX_PAPER_TODAY"]:
    print(f"{k:<34}: {maxvals.get(k,0)}")

print("\nCURRENT PAPER TRADES")
p = ROOT / "data" / "reports" / "paper_trades_latest.json"
if p.is_file():
    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
        trades = obj.get("paper_trades") or obj.get("trades") or []
        print("trading_date:", obj.get("trading_date"))
        print("count:", len(trades))
    except Exception as e:
        print("read error:", e)
else:
    print("missing")

print("\nINTERPRETATION")
if counts["CYCLES_WITH_ENTRY_READY"] > 0 and counts["CYCLES_WITH_PLANS"] == 0:
    print("CONFIRMED: scanner produced entry-ready candidates but no option plans.")
if counts["FUND_LIMIT_FAIL"] > 0 or counts["OPTION_CHAIN_FAIL"] > 0 or counts["HTTP_429"] > 0:
    print("CONFIRMED: Dhan/data reliability failures occurred during the same session.")
if counts["TOTAL_SAFETY_BLOCKED_REPORTED"] > 0:
    print("CONFIRMED: safety blocks were reported in scanner cycles.")
if counts["CYCLES_WITH_ENTRY_READY"] > 0 and counts["CYCLES_WITH_PLANS"] == 0 and (
    counts["FUND_LIMIT_FAIL"] > 0 or counts["OPTION_CHAIN_FAIL"] > 0
):
    print("LIKELY ROOT CAUSE: downstream Dhan option-chain/fund-limit failures prevented plan generation.")
    print("Classification: DATA-DEGRADED SESSION, not a clean 'strategy found no trades' session.")
print("="*92)
