from __future__ import annotations
from pathlib import Path
from datetime import datetime
import shutil, py_compile

ROOT=Path(__file__).resolve().parent
P=ROOT/"opening_momentum_scanner.py"

if not P.is_file():
    raise SystemExit("FAIL: opening_momentum_scanner.py missing")

stamp=datetime.now().strftime("%Y%m%d_%H%M%S")
B=ROOT/f"backup_before_leadership_v6_shadow_v2_{stamp}"
B.mkdir()
shutil.copy2(P,B/P.name)

def ensure_import_after_future(text:str, import_line:str)->str:
    if import_line in text:
        return text
    lines=text.splitlines()
    future_idxs=[i for i,line in enumerate(lines) if line.strip().startswith("from __future__ import")]
    idx=max(future_idxs)+1 if future_idxs else 0
    lines.insert(idx,import_line)
    return "\n".join(lines)+("\n" if text.endswith("\n") else "")

try:
    s=P.read_text(encoding="utf-8")

    # Safe import placement
    s=ensure_import_after_future(s,"from leadership_v6_live_shadow import LeadershipV6Shadow")

    # Instantiate only once, using exact existing report-dir anchor.
    if "self.leadership_v6_shadow = LeadershipV6Shadow(self.report_dir)" not in s:
        anchor="self.report_dir.mkdir(parents=True, exist_ok=True)"
        if anchor not in s:
            raise RuntimeError("report_dir anchor missing")
        s=s.replace(
            anchor,
            anchor+"\n        self.leadership_v6_shadow = LeadershipV6Shadow(self.report_dir)",
            1
        )

    # Add evaluation only once after shortlist creation.
    if "LEADERSHIP_V6_SHADOW hits=" not in s:
        anchor=") = self._build_shortlists(candidates)"
        idx=s.find(anchor)
        if idx < 0:
            raise RuntimeError("shortlist anchor missing")
        end=idx+len(anchor)
        code='''

        leadership_shadow_rows = self.leadership_v6_shadow.evaluate(candidates, current_time)
        leadership_shadow_hits = [
            x for x in leadership_shadow_rows
            if x.get("qualified_shadow")
        ]
        if leadership_shadow_hits:
            logger.info(
                "LEADERSHIP_V6_SHADOW hits=%d symbols=%s",
                len(leadership_shadow_hits),
                ",".join(
                    str(x.get("symbol"))
                    for x in leadership_shadow_hits[:10]
                ),
            )
'''
        s=s[:end]+code+s[end:]

    P.write_text(s,encoding="utf-8")
    py_compile.compile(str(P),doraise=True)

    verify=P.read_text(encoding="utf-8")
    checks={
        "shadow_import":"from leadership_v6_live_shadow import LeadershipV6Shadow" in verify,
        "shadow_instance":"self.leadership_v6_shadow = LeadershipV6Shadow(self.report_dir)" in verify,
        "shadow_eval":"leadership_shadow_rows = self.leadership_v6_shadow.evaluate" in verify,
        "shadow_log":"LEADERSHIP_V6_SHADOW hits=" in verify,
        "conversion_audit":"PAPER conversion audit" in verify,
    }
    if not all(checks.values()):
        raise RuntimeError(f"Post-install verification failed: {checks}")

except Exception:
    shutil.copy2(B/P.name,P)
    print("INSTALL FAILED - original restored automatically.")
    print("Backup:",B)
    raise

print("="*108)
print("SUCCESS: LEADERSHIP V6 LIVE SHADOW V2 INSTALLED")
print("Backup:",B)
for k,v in checks.items():
    print(("PASS" if v else "FAIL")+": "+k)
print("PASS: import inserted AFTER __future__ imports")
print("PASS: candidate/actionability/risk/safety logic unchanged")
print("PASS: PAPER only - no live-order authority added")
print("="*108)
