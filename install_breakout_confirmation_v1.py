from __future__ import annotations
from pathlib import Path
from datetime import datetime
import ast, shutil, py_compile

ROOT=Path(__file__).resolve().parent
ENGINE=ROOT/"intraday_movement_engine.py"
MARKER="APLUS_BREAKOUT_CONFIRMATION_V1"

if not ENGINE.exists():
    raise SystemExit("FAIL: intraday_movement_engine.py not found")

src=ENGINE.read_text(encoding="utf-8")
tree=ast.parse(src)

if MARKER in src:
    print("ALREADY INSTALLED:",MARKER)
    raise SystemExit(0)

cls=next((n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=="IntradayMovementEngine"),None)
if cls is None:
    raise SystemExit("FAIL: IntradayMovementEngine class not found")

def method(name):
    return next((n for n in cls.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name==name),None)

br=method("_breaks_recent")
cont=method("_continuation_breakout")
if br is None or cont is None:
    raise SystemExit("FAIL: required breakout methods not found")

def node_start(n):
    ds=[d.lineno for d in getattr(n,"decorator_list",[]) if hasattr(d,"lineno")]
    return min(ds+[n.lineno])-1

lines=src.splitlines(keepends=True)
repls=[(br,'    # APLUS_BREAKOUT_CONFIRMATION_V1\n    @staticmethod\n    def _breakout_clearance(level: float, candles: Sequence[Any]) -> float:\n        rows=list(candles)\n        ranges=sorted(\n            max(0.0, float(c.high)-float(c.low))\n            for c in rows\n            if float(c.high)>0 and float(c.low)>0\n        )\n        if ranges:\n            n=len(ranges)\n            median_range=ranges[n//2] if n%2 else (ranges[n//2-1]+ranges[n//2])/2.0\n        else:\n            median_range=0.0\n        return max(abs(float(level))*0.0008, median_range*0.10)\n\n    @staticmethod\n    def _breaks_recent(\n        price: float,\n        completed: Sequence[Any],\n        bars: int,\n        *,\n        bullish: bool,\n    ) -> bool:\n        # Confirmed breakout: prior-window level + completed-candle close + live hold.\n        rows=list(completed)\n        if len(rows) < max(3, bars+1):\n            return False\n\n        reference=list(rows[-(bars+1):-1])\n        confirm=rows[-1]\n        if len(reference) < bars:\n            return False\n\n        level=(\n            max(float(c.high) for c in reference)\n            if bullish\n            else min(float(c.low) for c in reference)\n        )\n        clearance=IntradayMovementEngine._breakout_clearance(level, reference)\n        confirm_close=float(confirm.close)\n\n        if bullish:\n            close_confirmed=confirm_close >= level + clearance\n            live_holding=float(price) >= level + clearance*0.25\n        else:\n            close_confirmed=confirm_close <= level - clearance\n            live_holding=float(price) <= level - clearance*0.25\n\n        return bool(close_confirmed and live_holding)\n'),(cont,'    # APLUS_BREAKOUT_CONFIRMATION_V1\n    @staticmethod\n    def _continuation_breakout(\n        *,\n        direction: str,\n        price: float,\n        recent5: float,\n        completed: Sequence[Any],\n        previous_state: str,\n        healthy_pullback: bool,\n    ) -> bool:\n        rows=list(completed)\n        if len(rows) < 4:\n            return False\n\n        bullish=direction=="BULLISH"\n        resumes=recent5>0 if bullish else recent5<0\n        prior_pullback=(\n            healthy_pullback\n            or "PULLBACK" in previous_state\n            or "WAIT_FOR_PULLBACK" in previous_state\n        )\n        if not prior_pullback or not resumes:\n            return False\n\n        reference=list(rows[-3:-1])\n        confirm=rows[-1]\n        level=(\n            max(float(c.high) for c in reference)\n            if bullish\n            else min(float(c.low) for c in reference)\n        )\n        clearance=IntradayMovementEngine._breakout_clearance(level, reference)\n        confirm_close=float(confirm.close)\n\n        if bullish:\n            return (\n                confirm_close >= level + clearance\n                and float(price) >= level + clearance*0.25\n            )\n        return (\n            confirm_close <= level - clearance\n            and float(price) <= level - clearance*0.25\n        )\n')]
for n,replacement in sorted(repls,key=lambda x:node_start(x[0]),reverse=True):
    st=node_start(n); en=n.end_lineno
    lines=lines[:st]+replacement.splitlines(keepends=True)+lines[en:]

patched="".join(lines)
ast.parse(patched)

newtree=ast.parse(patched)
newcls=next(n for n in newtree.body if isinstance(n,ast.ClassDef) and n.name=="IntradayMovementEngine")
targets=[n for n in newcls.body if isinstance(n,ast.FunctionDef) and n.name in {"_breaks_recent","_continuation_breakout"}]
segment="\n".join(ast.get_source_segment(patched,n) or "" for n in targets)
if 'price >= max(float(c.high) for c in window)' in segment or 'price <= min(float(c.low) for c in window)' in segment:
    raise RuntimeError("bare-touch fresh breakout still present")
if 'price >= max(float(c.high) for c in reference)' in segment or 'price <= min(float(c.low) for c in reference)' in segment:
    raise RuntimeError("bare-touch continuation breakout still present")

stamp=datetime.now().strftime("%Y%m%d_%H%M%S")
backup=ROOT/f"backup_before_breakout_confirmation_v1_{stamp}"
backup.mkdir(parents=True,exist_ok=True)
shutil.copy2(ENGINE,backup/"intraday_movement_engine.py")

try:
    ENGINE.write_text(patched,encoding="utf-8")
    py_compile.compile(str(ENGINE),doraise=True)
except Exception:
    shutil.copy2(backup/"intraday_movement_engine.py",ENGINE)
    print("INSTALL FAILED - original engine restored automatically")
    print("Backup:",backup)
    raise

print("="*122)
print("SUCCESS: APLUS BREAKOUT CONFIRMATION V1 INSTALLED")
print("Backup:",backup)
print("PASS fresh 15m/30m breakout no longer fires on live-price touch")
print("PASS continuation breakout no longer fires on live-price touch")
print("PASS latest completed candle must CLOSE beyond level + clearance")
print("PASS live price must still HOLD beyond the broken level")
print("PASS clearance = max(0.08% of level, 10% median reference candle range)")
print("PASS other movement/risk/option logic untouched")
print("="*122)
