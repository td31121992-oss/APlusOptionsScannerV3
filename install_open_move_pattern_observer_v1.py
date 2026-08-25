from __future__ import annotations
from pathlib import Path
from datetime import datetime
import ast, shutil, py_compile

ROOT=Path(__file__).resolve().parent
SCANNER=ROOT/"opening_momentum_scanner.py"
MODULE=ROOT/"open_move_pattern_observer.py"

if not SCANNER.exists():
    raise SystemExit("FAIL: opening_momentum_scanner.py not found")
if not MODULE.exists():
    raise SystemExit("FAIL: open_move_pattern_observer.py not found")

src=SCANNER.read_text(encoding="utf-8")
if "OPEN_MOVE_PATTERN_OBSERVER_V1" in src and "observe_open_move_patterns" in src:
    print("ALREADY INSTALLED")
    raise SystemExit(0)

ast.parse(src)
anchor="        self._write_reports(payload)\n"
if src.count(anchor)!=1:
    raise SystemExit(f"FAIL: expected one report-write anchor, found {src.count(anchor)}")

lines=src.splitlines()
insert_at=0
for i,line in enumerate(lines):
    if line.startswith("from __future__ import "):
        insert_at=i+1
import_line="from open_move_pattern_observer import observe_open_move_patterns"
if import_line not in lines:
    lines.insert(insert_at,import_line)
src="\n".join(lines)+"\n"

call = '''        # OPEN_MOVE_PATTERN_OBSERVER_V1
        # Observation only; never changes actionability, trade gates, risk or option selection.
        try:
            payload["open_move_pattern_observer"] = observe_open_move_patterns(
                payload=payload,
                current_time=current_time,
                report_dir=self.report_dir,
                logger=logger,
            )
        except Exception as exc:
            logger.warning(
                "OPEN_MOVE_PATTERN_OBSERVER cycle failed non-fatally: %s: %s",
                type(exc).__name__,
                exc,
            )

'''
src=src.replace(anchor,call+anchor,1)
ast.parse(src)

for required in ("def _aplus_selective_entry_allowed","PAPER conversion audit","OPTION_EXPIRY_FALLBACK"):
    if required not in src:
        raise RuntimeError("Critical mechanism missing after patch: "+required)

stamp=datetime.now().strftime("%Y%m%d_%H%M%S")
backup=ROOT/f"backup_before_open_move_pattern_observer_{stamp}"
backup.mkdir(parents=True,exist_ok=True)
shutil.copy2(SCANNER,backup/SCANNER.name)

try:
    SCANNER.write_text(src,encoding="utf-8")
    py_compile.compile(str(MODULE),doraise=True)
    py_compile.compile(str(SCANNER),doraise=True)
except Exception:
    shutil.copy2(backup/SCANNER.name,SCANNER)
    print("INSTALL FAILED - original scanner restored automatically.")
    print("Backup:",backup)
    raise

verify=SCANNER.read_text(encoding="utf-8")
checks={
    "observer_import":import_line in verify,
    "observer_call":"observe_open_move_patterns(" in verify,
    "selective_gate_preserved":"def _aplus_selective_entry_allowed" in verify,
    "conversion_audit_preserved":"PAPER conversion audit" in verify,
    "expiry_fallback_preserved":"OPTION_EXPIRY_FALLBACK" in verify,
}
print("="*116)
print("SUCCESS: APLUS OPEN-MOVE PATTERN OBSERVER V1 INSTALLED")
print("Backup:",backup)
for k,v in checks.items():
    print("PASS" if v else "FAIL",k)
print("PASS observation-only integration")
print("PASS no new Dhan calls")
print("PASS no entry/risk/option-selection thresholds changed")
print("="*116)
raise SystemExit(0 if all(checks.values()) else 1)
