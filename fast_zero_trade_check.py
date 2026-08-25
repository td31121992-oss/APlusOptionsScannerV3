from pathlib import Path
from collections import Counter
import re

ROOT = Path(__file__).resolve().parent
DAY = "2026-08-20"

# Only likely scanner logs; do not scan reports/data recursively.
candidates = []
for base in (ROOT / "data" / "logs", ROOT / "logs"):
    if base.exists():
        for p in base.glob("*.log"):
            candidates.append(p)

terms = (
    "entry_ready=",
    "plans=",
    "paper_today=",
    "safety_blocked=",
    "fund-limit",
    "option_chain",
    "option chain",
    "429",
)

counts = Counter()
matching_lines = []
files_used = []

for p in candidates:
    try:
        text = p.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        continue
    local = []
    for line in text.splitlines():
        if DAY not in line:
            continue
        low = line.lower()
        if any(t.lower() in low for t in terms):
            local.append(line)
            if "fund-limit" in low:
                counts["fund_limit_fail"] += 1
            if "option_chain" in low or "option chain" in low:
                if "fail" in low or "blank" in low or "429" in low:
                    counts["option_chain_fail"] += 1
            if "429" in low:
                counts["http_429"] += 1

            m = re.search(r"entry_ready=(\d+)", line)
            if m:
                v = int(m.group(1))
                counts["cycles"] += 1
                counts["entry_ready_total"] += v
                counts["entry_ready_max"] = max(counts["entry_ready_max"], v)

            m = re.search(r"plans=(\d+)", line)
            if m:
                v = int(m.group(1))
                counts["plans_total"] += v
                counts["plans_max"] = max(counts["plans_max"], v)

            m = re.search(r"paper_today=(\d+)", line)
            if m:
                counts["paper_today_max"] = max(counts["paper_today_max"], int(m.group(1)))

            m = re.search(r"safety_blocked=(\d+)", line)
            if m:
                v = int(m.group(1))
                counts["safety_blocked_total"] += v
                counts["safety_blocked_max"] = max(counts["safety_blocked_max"], v)

    if local:
        files_used.append(p)
        matching_lines.extend(local)

print("=" * 92)
print("APLUS FAST ZERO-TRADE CHECK - 2026-08-20")
print("=" * 92)
print("Logs checked:", len(candidates))
print("Logs with matches:", len(files_used))
for p in files_used:
    print(" ", p.relative_to(ROOT))

print("\nSUMMARY")
print("scanner cycles seen       :", counts["cycles"])
print("max entry_ready           :", counts["entry_ready_max"])
print("max plans                 :", counts["plans_max"])
print("max paper_today           :", counts["paper_today_max"])
print("total safety_blocked      :", counts["safety_blocked_total"])
print("max safety_blocked/cycle  :", counts["safety_blocked_max"])
print("fund-limit failures       :", counts["fund_limit_fail"])
print("option-chain failures     :", counts["option_chain_fail"])
print("HTTP 429 lines            :", counts["http_429"])

print("\nLAST 30 RELEVANT LINES")
for line in matching_lines[-30:]:
    print(line)

print("\nVERDICT")
if counts["entry_ready_max"] > 0 and counts["plans_max"] == 0:
    print("CONFIRMED: entry-ready candidates existed, but no option plans were generated.")
if counts["fund_limit_fail"] or counts["option_chain_fail"] or counts["http_429"]:
    print("CONFIRMED: Dhan/data failures occurred during the session.")
if counts["entry_ready_max"] > 0 and counts["plans_max"] == 0 and (
    counts["fund_limit_fail"] or counts["option_chain_fail"] or counts["http_429"]
):
    print("SESSION CLASSIFICATION: DATA-DEGRADED / EXECUTION-DATA BLOCKED")
    print("Do NOT classify this as a clean strategy 'no-trade' day.")
elif counts["cycles"] == 0:
    print("No matching scanner-cycle log was found in data\\logs or logs.")
    print("If scanner console output was not logged, paste the scanner CMD output instead.")
print("=" * 92)
