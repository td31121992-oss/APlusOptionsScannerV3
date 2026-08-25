from pathlib import Path
import ast
s=Path("opening_momentum_scanner.py").read_text(encoding="utf-8")
g=Path("safety_gate.py").read_text(encoding="utf-8")
ast.parse(s);ast.parse(g)
checks={
"scanner_marker":"APLUS_PAPER_CIRCUIT_BREAKER_WIRING_V1" in s,
"safety_marker":"APLUS_PAPER_CIRCUIT_BREAKER_WIRING_V1" in g,
"root_state":'self.data_dir / "portfolio_state.json"' in g,
"paper_pnl":"paper_native_state" in g,
"breaker":"def _paper_native_circuit_breaker" in s,
"loss_streak":"CONSECUTIVE_LOSS_LIMIT" in s,
"daily_loss":"DAILY_LOSS_LIMIT" in s,
"failsafe":"PAPER_STATE_STALE" in s and "PAPER_STATE_MISSING_OR_INVALID" in s,
"log":"PAPER_SAFETY_BLOCK" in s,
}
print("="*104);print("APLUS PAPER CIRCUIT BREAKER WIRING V1 AUDIT")
for k,v in checks.items():print("PASS" if v else "FAIL",k)
print("="*104)
raise SystemExit(0 if all(checks.values()) else 1)
