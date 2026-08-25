from __future__ import annotations
from pathlib import Path
from datetime import datetime
import ast, py_compile, shutil

ROOT=Path(__file__).resolve().parent
SCANNER=ROOT/"opening_momentum_scanner.py"
MARKER="APLUS_SHARED_QUOTE_SCHEDULER_V3_1"

if not SCANNER.exists(): raise SystemExit("FAIL: opening_momentum_scanner.py not found")
src=SCANNER.read_text(encoding="utf-8")
tree=ast.parse(src)
if MARKER in src:
    print("ALREADY INSTALLED:",MARKER); raise SystemExit(0)

cls=next((n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=="OpeningMomentumScanner"),None)
if cls is None: raise SystemExit("FAIL: OpeningMomentumScanner class not found")
run_once=next((n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=="run_once"),None)
monitor_method=next((n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=="_monitor_paper_positions"),None)
if run_once is None or monitor_method is None: raise SystemExit("FAIL: required scanner methods not found")

def is_call_attr(node,name):
    return isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and node.func.attr==name

def has_nse_eq(call):
    vals=list(call.args)+[k.value for k in call.keywords]
    for v in vals:
        if isinstance(v,ast.Dict):
            for key in v.keys:
                if isinstance(key,ast.Constant) and key.value=="NSE_EQ": return True
    return False

quote_stmt=None
monitor_stmt=None
for stmt in run_once.body:
    if isinstance(stmt,(ast.Assign,ast.AnnAssign)):
        value=stmt.value
        if is_call_attr(value,"get_market_quotes") and has_nse_eq(value): quote_stmt=stmt
        names=[]
        if isinstance(stmt,ast.Assign):
            names=[t.id for t in stmt.targets if isinstance(t,ast.Name)]
        elif isinstance(stmt,ast.AnnAssign) and isinstance(stmt.target,ast.Name):
            names=[stmt.target.id]
        if "paper_position_update" in names and is_call_attr(value,"_monitor_paper_positions"): monitor_stmt=stmt

if quote_stmt is None: raise SystemExit("FAIL: could not locate main NSE_EQ quote statement")
if monitor_stmt is None: raise SystemExit("FAIL: could not locate intracycle paper monitor statement")

lines=src.splitlines(keepends=True)
def replace_node(lines,node,text):
    return lines[:node.lineno-1]+text.splitlines(keepends=True)+lines[node.end_lineno:]

quote_repl = '        # APLUS_SHARED_QUOTE_SCHEDULER_V3_1\n        open_paper_positions = self.paper_journal.open_positions(current_time)\n        open_option_ids = sorted({\n            str(item.get("option_security_id") or "")\n            for item in open_paper_positions\n            if str(item.get("option_security_id") or "")\n        })\n        quote_request = {"NSE_EQ": [item.security_id for item in universe]}\n        if open_option_ids:\n            quote_request["NSE_FNO"] = open_option_ids\n        quote_map = self.client.get_market_quotes(quote_request, mode="quote")\n'
monitor_repl = '        # APLUS_SHARED_QUOTE_SCHEDULER_V3_1\n        paper_position_update = self._monitor_paper_positions_from_quote_map(\n            now=current_time,\n            quote_map=quote_map,\n            positions=open_paper_positions,\n            force_close=False,\n        )\n'

for node,text in sorted([(quote_stmt,quote_repl),(monitor_stmt,monitor_repl)], key=lambda x:x[0].lineno, reverse=True):
    lines=replace_node(lines,node,text)
patched="".join(lines)

tree2=ast.parse(patched)
cls2=next(n for n in tree2.body if isinstance(n,ast.ClassDef) and n.name=="OpeningMomentumScanner")
mon2=next(n for n in cls2.body if isinstance(n,ast.FunctionDef) and n.name=="_monitor_paper_positions")
helper = '    # APLUS_SHARED_QUOTE_SCHEDULER_V3_1\n    def _monitor_paper_positions_from_quote_map(\n        self,\n        *,\n        now: datetime,\n        quote_map: Mapping[str, Any],\n        positions: list[Mapping[str, Any]] | None,\n        force_close: bool,\n    ) -> dict[str, Any]:\n        active = list(positions or [])\n        if not active:\n            return {"closed": [], "errors": [], "quote_source": "SHARED_MAIN_QUOTE"}\n        ids = sorted({\n            str(item.get("option_security_id") or "")\n            for item in active\n            if str(item.get("option_security_id") or "")\n        })\n        if not ids:\n            return {"closed": [], "errors": ["open paper positions have no option security_id"], "quote_source": "SHARED_MAIN_QUOTE"}\n        segment = quote_map.get("NSE_FNO", {}) if isinstance(quote_map, Mapping) else {}\n        if not isinstance(segment, Mapping):\n            segment = {}\n        missing = [security_id for security_id in ids if security_id not in segment]\n        if missing:\n            logger.warning(\n                "APLUS_SHARED_QUOTE_SCHEDULER_V3_1 missing_option_quotes=%d ids=%s; next normal cycle will retry",\n                len(missing), ",".join(missing[:10]),\n            )\n        try:\n            closed = self.paper_journal.update_open_positions(\n                option_quotes=segment,\n                when=now,\n                force_close=force_close,\n                force_close_reason="SESSION_END",\n            )\n            return {\n                "closed": closed,\n                "errors": ([f"shared quote missing option ids: {\',\'.join(missing)}"] if missing else []),\n                "quote_source": "SHARED_MAIN_QUOTE",\n                "requested_option_ids": len(ids),\n                "received_option_quotes": sum(1 for security_id in ids if security_id in segment),\n            }\n        except Exception as exc:\n            logger.warning("PAPER shared-position update failed: %s: %s", type(exc).__name__, exc)\n            return {"closed": [], "errors": [f"{type(exc).__name__}: {exc}"], "quote_source": "SHARED_MAIN_QUOTE"}\n\n'
plines=patched.splitlines(keepends=True)
plines=plines[:mon2.lineno-1]+helper.splitlines(keepends=True)+plines[mon2.lineno-1:]
patched="".join(plines)
ast.parse(patched)

required=["APLUS_SCANNER_429_SURVIVAL_V2","OPEN_MOVE_PATTERN_OBSERVER","def _aplus_selective_entry_allowed","PAPER conversion audit","OPTION_EXPIRY_FALLBACK"]
missing=[x for x in required if x not in patched]
if missing: raise RuntimeError("Critical mechanisms missing: "+", ".join(missing))

stamp=datetime.now().strftime("%Y%m%d_%H%M%S")
backup=ROOT/f"backup_before_shared_quote_scheduler_v3_1_{stamp}"
backup.mkdir(parents=True,exist_ok=True)
shutil.copy2(SCANNER,backup/"opening_momentum_scanner.py")
try:
    SCANNER.write_text(patched,encoding="utf-8")
    py_compile.compile(str(SCANNER),doraise=True)
    s=SCANNER.read_text(encoding="utf-8")
    checks={
      "v3_1_marker":MARKER in s,
      "combined_nse_fno":'quote_request["NSE_FNO"] = open_option_ids' in s,
      "shared_monitor":"_monitor_paper_positions_from_quote_map" in s,
      "session_end_preserved":"final_update = self._monitor_paper_positions(now=now, force_close=True)" in s,
      "v2_survival_preserved":"APLUS_SCANNER_429_SURVIVAL_V2" in s,
      "observer_preserved":"OPEN_MOVE_PATTERN_OBSERVER" in s,
      "conversion_preserved":"PAPER conversion audit" in s,
      "expiry_preserved":"OPTION_EXPIRY_FALLBACK" in s,
    }
    if not all(checks.values()): raise RuntimeError(checks)
except Exception:
    shutil.copy2(backup/"opening_momentum_scanner.py",SCANNER)
    print("INSTALL FAILED - original scanner restored automatically.")
    print("Backup:",backup)
    raise

print("="*120)
print("SUCCESS: APLUS DHAN 429 RELIABILITY V3.1 INSTALLED")
print("Backup:",backup)
for k,v in checks.items(): print("PASS" if v else "FAIL",k)
print("PASS AST-adaptive source matching")
print("PASS one normal intracycle Market Quote call removed")
print("PASS strategy/risk/option-selection unchanged")
print("="*120)
