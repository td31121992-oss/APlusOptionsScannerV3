from pathlib import Path
import py_compile
for name in ("paper_safety_evidence_agent.py",):
    p=Path(name)
    if not p.exists():
        raise SystemExit("FAIL missing "+name)
    py_compile.compile(str(p),doraise=True)
s=Path("paper_safety_evidence_agent.py").read_text(encoding="utf-8")
checks={
"paper_state":"consecutive_losses" in s and "realized_pnl_today" in s,
"capsules":"trade_evidence_capsules" in s,
"zero_dhan":"dhan" not in s.lower() or "ZERO Dhan" in s,
}
print("="*96)
print("APLUS PAPER SAFETY + EVIDENCE V1.2 VERIFY")
for k,v in checks.items(): print("PASS" if v else "FAIL",k)
print("="*96)
raise SystemExit(0 if all(checks.values()) else 1)
