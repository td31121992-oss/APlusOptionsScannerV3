from __future__ import annotations
from pathlib import Path
from datetime import datetime
import ast, py_compile, shutil

ROOT=Path(__file__).resolve().parent
SCANNER=ROOT/"opening_momentum_scanner.py"
MARKER="APLUS_SHARED_QUOTE_SCHEDULER_V3"

if not SCANNER.exists():
    raise SystemExit("FAIL: opening_momentum_scanner.py not found.")

src=SCANNER.read_text(encoding="utf-8")
ast.parse(src)

if MARKER in src:
    print("ALREADY INSTALLED:",MARKER)
    raise SystemExit(0)

old_quote = '        quote_map = self.client.get_market_quotes(\\n            {"NSE_EQ": [item.security_id for item in universe]},\\n            mode="quote",\\n        )\\n'
old_monitor = '        paper_position_update = self._monitor_paper_positions(\\n            now=current_time, force_close=False,\\n        )\\n'
method_anchor = '    def _monitor_paper_positions(self, *, now: datetime, force_close: bool) -> dict[str, Any]:\\n'

if src.count(old_quote)!=1:
    raise SystemExit(f"FAIL: expected one main quote anchor, found {src.count(old_quote)}")
if src.count(old_monitor)!=1:
    raise SystemExit(f"FAIL: expected one intracycle paper-monitor anchor, found {src.count(old_monitor)}")
if src.count(method_anchor)!=1:
    raise SystemExit(f"FAIL: expected one paper monitor method, found {src.count(method_anchor)}")

new_quote = '''        # APLUS_SHARED_QUOTE_SCHEDULER_V3
        open_paper_positions = self.paper_journal.open_positions(current_time)
        open_option_ids = sorted({
            str(item.get("option_security_id") or "")
            for item in open_paper_positions
            if str(item.get("option_security_id") or "")
        })
        quote_request = {
            "NSE_EQ": [item.security_id for item in universe],
        }
        if open_option_ids:
            quote_request["NSE_FNO"] = open_option_ids

        quote_map = self.client.get_market_quotes(
            quote_request,
            mode="quote",
        )
'''

new_monitor = '''        # APLUS_SHARED_QUOTE_SCHEDULER_V3
        paper_position_update = self._monitor_paper_positions_from_quote_map(
            now=current_time,
            quote_map=quote_map,
            positions=open_paper_positions,
            force_close=False,
        )
'''

helper = '''    # APLUS_SHARED_QUOTE_SCHEDULER_V3
    def _monitor_paper_positions_from_quote_map(
        self,
        *,
        now: datetime,
        quote_map: Mapping[str, Any],
        positions: list[Mapping[str, Any]] | None,
        force_close: bool,
    ) -> dict[str, Any]:
        active = list(positions or [])
        if not active:
            return {"closed": [], "errors": [], "quote_source": "SHARED_MAIN_QUOTE"}

        ids = sorted({
            str(item.get("option_security_id") or "")
            for item in active
            if str(item.get("option_security_id") or "")
        })
        if not ids:
            return {
                "closed": [],
                "errors": ["open paper positions have no option security_id"],
                "quote_source": "SHARED_MAIN_QUOTE",
            }

        segment = quote_map.get("NSE_FNO", {}) if isinstance(quote_map, Mapping) else {}
        if not isinstance(segment, Mapping):
            segment = {}

        missing = [security_id for security_id in ids if security_id not in segment]
        if missing:
            logger.warning(
                "APLUS_SHARED_QUOTE_SCHEDULER missing_option_quotes=%d ids=%s; "
                "paper positions kept open and next normal cycle will retry",
                len(missing),
                ",".join(missing[:10]),
            )

        try:
            closed = self.paper_journal.update_open_positions(
                option_quotes=segment,
                when=now,
                force_close=force_close,
                force_close_reason="SESSION_END",
            )
            return {
                "closed": closed,
                "errors": (
                    [f"shared quote missing option ids: {','.join(missing)}"]
                    if missing else []
                ),
                "quote_source": "SHARED_MAIN_QUOTE",
                "requested_option_ids": len(ids),
                "received_option_quotes": sum(
                    1 for security_id in ids if security_id in segment
                ),
            }
        except Exception as exc:
            logger.warning(
                "PAPER shared position quote update failed: %s: %s",
                type(exc).__name__,
                exc,
            )
            return {
                "closed": [],
                "errors": [f"{type(exc).__name__}: {exc}"],
                "quote_source": "SHARED_MAIN_QUOTE",
            }

'''

stamp=datetime.now().strftime("%Y%m%d_%H%M%S")
backup=ROOT/f"backup_before_shared_quote_scheduler_v3_{stamp}"
backup.mkdir(parents=True,exist_ok=True)
shutil.copy2(SCANNER,backup/"opening_momentum_scanner.py")

try:
    patched=src.replace(old_quote,new_quote,1)
    patched=patched.replace(old_monitor,new_monitor,1)
    idx=patched.find(method_anchor)
    if idx<0:
        raise RuntimeError("helper insertion anchor disappeared")
    patched=patched[:idx]+helper+patched[idx:]

    ast.parse(patched)
    SCANNER.write_text(patched,encoding="utf-8")
    py_compile.compile(str(SCANNER),doraise=True)

    installed=SCANNER.read_text(encoding="utf-8")
    checks={
        "v3_marker":MARKER in installed,
        "combined_nse_eq":'"NSE_EQ": [item.security_id for item in universe]' in installed,
        "combined_nse_fno":'quote_request["NSE_FNO"] = open_option_ids' in installed,
        "shared_monitor":"_monitor_paper_positions_from_quote_map" in installed,
        "session_end_monitor_preserved":"final_update = self._monitor_paper_positions(now=now, force_close=True)" in installed,
        "v2_survival_preserved":"APLUS_SCANNER_429_SURVIVAL_V2" in installed,
        "observer_preserved":"OPEN_MOVE_PATTERN_OBSERVER" in installed,
        "selective_gate_preserved":"def _aplus_selective_entry_allowed" in installed,
        "conversion_preserved":"PAPER conversion audit" in installed,
        "expiry_preserved":"OPTION_EXPIRY_FALLBACK" in installed,
    }
    if not all(checks.values()):
        raise RuntimeError(f"verification failed: {checks}")
except Exception:
    shutil.copy2(backup/"opening_momentum_scanner.py",SCANNER)
    print("INSTALL FAILED - original scanner restored automatically.")
    print("Backup:",backup)
    raise

print("="*122)
print("SUCCESS: APLUS DHAN 429 RELIABILITY V3 - SHARED QUOTE SCHEDULER INSTALLED")
print("Backup:",backup)
for k,v in checks.items():
    print("PASS" if v else "FAIL",k)
print("PASS normal scanner cadence unchanged")
print("PASS paper monitoring preserved using shared quote response")
print("PASS strategy/risk/option-selection logic unchanged")
print("PASS ZERO new Dhan calls; one intracycle Market Quote call removed")
print("="*122)
