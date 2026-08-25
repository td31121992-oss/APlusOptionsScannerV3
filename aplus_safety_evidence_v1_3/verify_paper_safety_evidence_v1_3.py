from pathlib import Path
import json, py_compile, re
py_compile.compile("paper_safety_evidence_agent.py",doraise=True)
s=Path("paper_safety_evidence_agent.py").read_text(encoding="utf-8")
checks={
"synthetic_ids":"stable_trade_id" in s and "SYN_" in s,
"capsules":"trade_evidence_capsules" in s,
"status":"paper_safety_evidence_status.json" in s,
"paper_state":"consecutive_losses" in s and "realized_pnl_today" in s,
}
print("="*100)
print("APLUS PAPER SAFETY + EVIDENCE V1.3 VERIFY")
for k,v in checks.items():print("PASS" if v else "FAIL",k)
print("="*100)
raise SystemExit(0 if all(checks.values()) else 1)
