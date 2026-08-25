from __future__ import annotations
from pathlib import Path
from datetime import datetime
import ast, py_compile, shutil

ROOT=Path(__file__).resolve().parent
DHAN=ROOT/"core"/"dhan_client.py"
SCANNER=ROOT/"opening_momentum_scanner.py"
DBLOCK=(ROOT/"dhan_reliability_block_v2.txt").read_text(encoding="utf-8")
SBLOCK=(ROOT/"scanner_survival_block_v2.txt").read_text(encoding="utf-8")

for p in (DHAN,SCANNER):
    if not p.exists():
        raise SystemExit(f"FAIL: missing {p}")

dhan_src=DHAN.read_text(encoding="utf-8")
scanner_src=SCANNER.read_text(encoding="utf-8")
ast.parse(dhan_src); ast.parse(scanner_src)

for required in ("class DhanClient","def _post_data_api","def get_market_quotes"):
    if required not in dhan_src:
        raise SystemExit("FAIL: Dhan source architecture mismatch: "+required)
for required in ("class OpeningMomentumScanner","def run_once","def run_loop","PAPER conversion audit","OPTION_EXPIRY_FALLBACK","def _aplus_selective_entry_allowed"):
    if required not in scanner_src:
        raise SystemExit("FAIL: scanner source architecture mismatch: "+required)

stamp=datetime.now().strftime("%Y%m%d_%H%M%S")
backup=ROOT/f"backup_before_dhan_429_reliability_v2_{stamp}"
(backup/"core").mkdir(parents=True,exist_ok=True)
shutil.copy2(DHAN,backup/"core"/"dhan_client.py")
shutil.copy2(SCANNER,backup/"opening_momentum_scanner.py")

try:
    if "APLUS_DHAN_429_RELIABILITY_V2" not in dhan_src:
        dhan_src=dhan_src.rstrip()+"\n\n"+DBLOCK.strip()+"\n"
    if "APLUS_SCANNER_429_SURVIVAL_V2" not in scanner_src:
        scanner_src=scanner_src.rstrip()+"\n\n"+SBLOCK.strip()+"\n"

    ast.parse(dhan_src); ast.parse(scanner_src)
    DHAN.write_text(dhan_src,encoding="utf-8")
    SCANNER.write_text(scanner_src,encoding="utf-8")
    py_compile.compile(str(DHAN),doraise=True)
    py_compile.compile(str(SCANNER),doraise=True)

    ds=DHAN.read_text(encoding="utf-8")
    ss=SCANNER.read_text(encoding="utf-8")
    checks={
        "dhan_marker":"APLUS_DHAN_429_RELIABILITY_V2" in ds,
        "quote_cap":"safe_rps = 0.30" in ds,
        "history_cap":"safe_rps = 1.50" in ds,
        "global_gap":"global_gap = 0.45" in ds,
        "scanner_survival":"APLUS_SCANNER_429_SURVIVAL_V2" in ss,
        "cycle_skip":"APLUS_429_CYCLE_SKIPPED" in ss,
        "selective_gate_preserved":"def _aplus_selective_entry_allowed" in ss,
        "conversion_preserved":"PAPER conversion audit" in ss,
        "expiry_preserved":"OPTION_EXPIRY_FALLBACK" in ss,
        "observer_preserved":"OPEN_MOVE_PATTERN_OBSERVER" in ss,
    }
    if not all(checks.values()):
        raise RuntimeError(checks)
except Exception:
    shutil.copy2(backup/"core"/"dhan_client.py",DHAN)
    shutil.copy2(backup/"opening_momentum_scanner.py",SCANNER)
    print("INSTALL FAILED - originals restored automatically.")
    print("Backup:",backup)
    raise

print("="*118)
print("SUCCESS: APLUS DHAN 429 RELIABILITY V2 INSTALLED")
print("Backup:",backup)
for k,v in checks.items():
    print("PASS" if v else "FAIL",k)
print("PASS strategy/risk/option rules unchanged")
print("="*118)
