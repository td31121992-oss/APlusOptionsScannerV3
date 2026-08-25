from pathlib import Path
from datetime import datetime
import shutil,py_compile
ROOT=Path(__file__).resolve().parent;P=ROOT/"opening_momentum_scanner.py"
if not P.exists():raise SystemExit("opening_momentum_scanner.py missing")
B=ROOT/("backup_before_leadership_v6_shadow_"+datetime.now().strftime("%Y%m%d_%H%M%S"));B.mkdir();shutil.copy2(P,B/P.name)
s=P.read_text(encoding="utf-8")
try:
    imp="from leadership_v6_live_shadow import LeadershipV6Shadow"
    if imp not in s:s=imp+"\n"+s
    if "self.leadership_v6_shadow = LeadershipV6Shadow" not in s:
        a="self.report_dir.mkdir(parents=True, exist_ok=True)"
        if a not in s:raise RuntimeError("report_dir anchor missing")
        s=s.replace(a,a+"\n        self.leadership_v6_shadow = LeadershipV6Shadow(self.report_dir)",1)
    if "LEADERSHIP_V6_SHADOW hits=" not in s:
        a=") = self._build_shortlists(candidates)"
        i=s.find(a)
        if i<0:raise RuntimeError("shortlist anchor missing")
        e=i+len(a)
        code="""
        leadership_shadow_rows = self.leadership_v6_shadow.evaluate(candidates, current_time)
        leadership_shadow_hits = [x for x in leadership_shadow_rows if x.get("qualified_shadow")]
        if leadership_shadow_hits:
            logger.info(
                "LEADERSHIP_V6_SHADOW hits=%d symbols=%s",
                len(leadership_shadow_hits),
                ",".join(str(x.get("symbol")) for x in leadership_shadow_hits[:10]),
            )
"""
        s=s[:e]+code+s[e:]
    P.write_text(s,encoding="utf-8");py_compile.compile(str(P),doraise=True)
except Exception:
    shutil.copy2(B/P.name,P);print("INSTALL FAILED - restored",B);raise
print("SUCCESS: LEADERSHIP V6 LIVE SHADOW INSTALLED")
print("Backup:",B)
print("NO candidate/actionability/risk/safety behavior changed")
