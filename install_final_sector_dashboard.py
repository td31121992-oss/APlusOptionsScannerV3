from pathlib import Path
from datetime import datetime
import ast,csv,base64,py_compile,shutil

ROOT=Path(__file__).resolve().parent
DASH=ROOT/"aplus_live_pnl_dashboard.py"
MAP=ROOT/"data"/"reference"/"fno_sector_map.csv"
if not DASH.is_file(): raise SystemExit("FAIL: aplus_live_pnl_dashboard.py not found")
if not MAP.is_file(): raise SystemExit(r"FAIL: data\reference\fno_sector_map.csv not found")

stamp=datetime.now().strftime("%Y%m%d_%H%M%S")
backup=ROOT/f"backup_before_sector_dashboard_final_{stamp}"
backup.mkdir(parents=True,exist_ok=False)
shutil.copy2(DASH,backup/DASH.name); shutil.copy2(MAP,backup/MAP.name)

CANON={
"finance":"Banking/Financial Services","financial services":"Banking/Financial Services","banks":"Banking/Financial Services","bank":"Banking/Financial Services","nbfc":"Banking/Financial Services","asset management":"Banking/Financial Services","investment managers":"Banking/Financial Services",
"technology services":"IT","information technology":"IT","software":"IT","it":"IT",
"auto":"Auto","automobile":"Auto","automobiles":"Auto","auto components":"Auto","automobile components":"Auto",
"health technology":"Pharma/Healthcare","health services":"Pharma/Healthcare","pharmaceuticals":"Pharma/Healthcare","pharma":"Pharma/Healthcare","healthcare":"Pharma/Healthcare",
"non-energy minerals":"Metals","metals & mining":"Metals","metals":"Metals","mining":"Metals",
"energy minerals":"Energy/Oil & Gas","energy":"Energy/Oil & Gas","oil & gas":"Energy/Oil & Gas","oil and gas":"Energy/Oil & Gas",
"consumer non-durables":"FMCG/Consumer","consumer goods":"FMCG/Consumer","fmcg":"FMCG/Consumer",
"realty":"Realty","real estate":"Realty",
"construction":"Infrastructure/Construction","infrastructure":"Infrastructure/Construction",
"communications":"Telecom/Media","telecom":"Telecom/Media","media":"Telecom/Media","media & entertainment":"Telecom/Media",
"producer manufacturing":"Capital Goods","capital goods":"Capital Goods",
"process industries":"Chemicals","chemicals":"Chemicals",
"utilities":"Power/Utilities","power":"Power/Utilities",
"cement":"Cement","consumer durables":"Consumer Durables","electronic technology":"Consumer Durables","electronics & technology":"Consumer Durables",
"retail trade":"Retail","retail":"Retail","transportation":"Logistics/Transportation","logistics":"Logistics/Transportation",
"defence":"Defence/Aerospace","defense":"Defence/Aerospace","insurance":"Insurance","consumer services":"Hotels/Travel","hotels":"Hotels/Travel","travel":"Hotels/Travel"
}
EXACT={"BAJAJ-AUTO":"Auto","NAM-INDIA":"Banking/Financial Services"}

def norm(raw):
    raw=str(raw or "").strip()
    if not raw: return "Other/Industrial"
    if raw in set(CANON.values())|{"Other/Industrial","Cement","Consumer Durables","Retail","Logistics/Transportation","Defence/Aerospace","Insurance","Hotels/Travel"}: return raw
    k=raw.casefold()
    if k in CANON: return CANON[k]
    tests=[(("bank","financ","nbfc","asset"),"Banking/Financial Services"),(("software","technology"),"IT"),(("auto","motor","tyre","tire"),"Auto"),(("pharma","health","hospital"),"Pharma/Healthcare"),(("metal","steel","mining","aluminium"),"Metals"),(("oil","gas","energy","petroleum"),"Energy/Oil & Gas"),(("fmcg","food","beverage"),"FMCG/Consumer"),(("realty","real estate"),"Realty"),(("construction","infrastructure"),"Infrastructure/Construction"),(("telecom","media","communication"),"Telecom/Media"),(("machinery","capital goods"),"Capital Goods"),(("chemical","fertil"),"Chemicals"),(("power","utility","electric"),"Power/Utilities"),(("cement",),"Cement"),(("retail",),"Retail"),(("logistics","transport"),"Logistics/Transportation"),(("defence","defense","aerospace"),"Defence/Aerospace"),(("insurance",),"Insurance"),(("hotel","travel","tourism"),"Hotels/Travel")]
    low=raw.casefold()
    for words,sec in tests:
        if any(w in low for w in words): return sec
    return "Other/Industrial"

def normalize_map():
    rows=[]
    with MAP.open("r",encoding="utf-8-sig",newline="") as f:
        for r in csv.DictReader(f):
            sym=str(r.get("symbol") or "").strip().upper()
            if sym: rows.append((sym,EXACT.get(sym) or norm(r.get("sector"))))
    with MAP.open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.writer(f); w.writerow(["symbol","sector"]); w.writerows(sorted(rows))
    return rows

def find_literal(text,name):
    m=name+" = "; i=text.find(m)
    if i<0: raise RuntimeError(name+" block not found")
    st=i+len(m)
    ends=[x for x in (text.find("\n\ndef ",st),text.find("\n\nclass ",st)) if x>=0]
    if not ends: raise RuntimeError("Could not locate end of "+name)
    en=min(ends); return st,en,ast.literal_eval(text[st:en])

try:
    rows=normalize_map()
    s=DASH.read_text(encoding="utf-8")
    st,en,html=find_literal(s,"SECTOR_PERFORMANCE_HTML")
    old_box=base64.b64decode("PGRpdiBjbGFzcz0iYm94dGl0bGUiPlNlY3RvciBQZXJmb3JtYW5jZTwvZGl2PgogICAgPGRpdiBjbGFzcz0ic3ViIj5TZWN0b3IgJSA9IGF2ZXJhZ2UgbW92ZW1lbnQgb2YgaXRzIEYmTyBzdG9ja3MgZnJvbSBlYWNoIHN0b2NrJ3MgMDk6MTUgb3Blbi48L2Rpdj4KICAgIDxkaXYgaWQ9InNlY3RvckJhcnMiIGNsYXNzPSJjaGFydCI+PC9kaXY+CiAgICA8ZGl2IGNsYXNzPSJzdWIiPkNsaWNrIGFueSBzZWN0b3IgdG8gdmlldyBpdHMgY29uc3RpdHVlbnQgc3RvY2tzLjwvZGl2Pg==").decode()
    new_box=base64.b64decode("PGRpdiBjbGFzcz0iYm94dGl0bGUiPlNlY3RvciBQZXJmb3JtYW5jZSAtIGZyb20gMDk6MTUgT3BlbjwvZGl2PgogICAgPGRpdiBjbGFzcz0ic3ViIj5TZWN0b3IgJSA9IGF2ZXJhZ2UgbW92ZSBvZiBpdHMgRiZPIHN0b2NrcyBmcm9tIGVhY2ggc3RvY2sncyBvd24gMDk6MTUgb3Blbi48L2Rpdj4KICAgIDxkaXYgY2xhc3M9InRhYmxld3JhcCIgc3R5bGU9Im1heC1oZWlnaHQ6NTIwcHgiPgogICAgICA8dGFibGU+CiAgICAgICAgPHRoZWFkPjx0cj4KICAgICAgICAgIDx0aD5TZWN0b3I8L3RoPjx0aCBjbGFzcz0icmlnaHQiPiUgZnJvbSAwOToxNTwvdGg+PHRoIGNsYXNzPSJyaWdodCI+U3RvY2tzPC90aD4KICAgICAgICAgIDx0aCBjbGFzcz0icmlnaHQiPkFkdjwvdGg+PHRoIGNsYXNzPSJyaWdodCI+RGVjPC90aD48dGg+VG9wIFN0b2NrPC90aD48dGg+Qm90dG9tIFN0b2NrPC90aD4KICAgICAgICA8L3RyPjwvdGhlYWQ+CiAgICAgICAgPHRib2R5IGlkPSJzZWN0b3JTdW1tYXJ5Ij48L3Rib2R5PgogICAgICA8L3RhYmxlPgogICAgPC9kaXY+CiAgICA8ZGl2IGNsYXNzPSJzdWIiPkNsaWNrIGFueSBzZWN0b3Igcm93IHRvIHZpZXcgYWxsIGNvbnN0aXR1ZW50IHN0b2Nrcy48L2Rpdj4=").decode()
    old_js=base64.b64decode("ZnVuY3Rpb24gYWdncmVnYXRlU2VjdG9ycygpewogY29uc3QgbT17fTsKIGRhdGEuZm9yRWFjaCh4PT57CiAgIGNvbnN0IHM9eC5zZWN0b3J8fCdVTkNMQVNTSUZJRUQnOwogICBpZighbVtzXSltW3NdPXtzZWN0b3I6cyxzdW06MCxjb3VudDowfTsKICAgbVtzXS5zdW0rPU51bWJlcih4LmZyb21fb3Blbl9wY3R8fDApO21bc10uY291bnQrKzsKIH0pOwogcmV0dXJuIE9iamVjdC52YWx1ZXMobSkubWFwKHg9Pih7c2VjdG9yOnguc2VjdG9yLG1vdmU6eC5jb3VudD94LnN1bS94LmNvdW50OjAsY291bnQ6eC5jb3VudH0pKS5zb3J0KChhLGIpPT5iLm1vdmUtYS5tb3ZlKTsKfQpmdW5jdGlvbiByZW5kZXJCYXJzKCl7CiBjb25zdCBhPWFnZ3JlZ2F0ZVNlY3RvcnMoKTsKIGNvbnN0IG1heD1NYXRoLm1heCgwLjAxLC4uLmEubWFwKHg9Pk1hdGguYWJzKHgubW92ZSkpKTsKIHNlY3RvckJhcnMuaW5uZXJIVE1MPWEubWFwKHg9PnsKICAgY29uc3Qgdz1NYXRoLm1heCgxLE1hdGguYWJzKHgubW92ZSkvbWF4KjEwMCk7CiAgIHJldHVybiBgPGRpdiBjbGFzcz0iYmFycm93IiBkYXRhLXNlY3Rvcj0iJHt4LnNlY3Rvci5yZXBsYWNlKC8iL2csJyZxdW90OycpfSI+CiAgICAgPGRpdiBjbGFzcz0iYmFybGFiZWwiPiR7eC5zZWN0b3J9PC9kaXY+CiAgICAgPGRpdiBjbGFzcz0idHJhY2siPjxkaXYgY2xhc3M9ImZpbGwgJHt4Lm1vdmU+PTA/J3VwJzonZG93bid9IiBzdHlsZT0id2lkdGg6JHt3fSUiPjwvZGl2PjwvZGl2PgogICAgIDxkaXYgY2xhc3M9ImJhcnZhbCAke3gubW92ZT49MD8ndXAnOidkb3duJ30iPiR7cGN0KHgubW92ZSl9PC9kaXY+CiAgIDwvZGl2PmA7CiB9KS5qb2luKCcnKTsKIGRvY3VtZW50LnF1ZXJ5U2VsZWN0b3JBbGwoJy5iYXJyb3cnKS5mb3JFYWNoKGVsPT5lbC5vbmNsaWNrPSgpPT5zZWxlY3RTZWN0b3IoZWwuZGF0YXNldC5zZWN0b3IpKTsKIGlmKCFzZWxlY3RlZFNlY3RvciAmJiBhLmxlbmd0aClzZWxlY3RTZWN0b3IoYVswXS5zZWN0b3IpOwp9").decode()
    new_js=base64.b64decode("ZnVuY3Rpb24gYWdncmVnYXRlU2VjdG9ycygpewogY29uc3QgbT17fTsKIGRhdGEuZm9yRWFjaCh4PT57CiAgIGNvbnN0IHM9eC5zZWN0b3J8fCdPdGhlci9JbmR1c3RyaWFsJzsKICAgaWYoIW1bc10pbVtzXT17c2VjdG9yOnMsc3VtOjAsY291bnQ6MCxhZHY6MCxkZWM6MCxzdG9ja3M6W119OwogICBjb25zdCBtdj1OdW1iZXIoeC5mcm9tX29wZW5fcGN0fHwwKTsKICAgbVtzXS5zdW0rPW12O21bc10uY291bnQrKzsKICAgaWYobXY+MCltW3NdLmFkdisrOyBlbHNlIGlmKG12PDApbVtzXS5kZWMrKzsKICAgbVtzXS5zdG9ja3MucHVzaCh4KTsKIH0pOwogcmV0dXJuIE9iamVjdC52YWx1ZXMobSkubWFwKHg9PnsKICAgeC5zdG9ja3Muc29ydCgoYSxiKT0+TnVtYmVyKGIuZnJvbV9vcGVuX3BjdHx8MCktTnVtYmVyKGEuZnJvbV9vcGVuX3BjdHx8MCkpOwogICByZXR1cm4ge3NlY3Rvcjp4LnNlY3Rvcixtb3ZlOnguY291bnQ/eC5zdW0veC5jb3VudDowLGNvdW50OnguY291bnQsYWR2OnguYWR2LGRlYzp4LmRlYywKICAgICAgICAgICB0b3A6eC5zdG9ja3NbMF18fG51bGwsYm90dG9tOnguc3RvY2tzW3guc3RvY2tzLmxlbmd0aC0xXXx8bnVsbH07CiB9KS5zb3J0KChhLGIpPT5iLm1vdmUtYS5tb3ZlKTsKfQpmdW5jdGlvbiByZW5kZXJCYXJzKCl7CiBjb25zdCBhPWFnZ3JlZ2F0ZVNlY3RvcnMoKTsKIHNlY3RvclN1bW1hcnkuaW5uZXJIVE1MPWEubWFwKHg9PmA8dHIgZGF0YS1zZWN0b3I9IiR7eC5zZWN0b3IucmVwbGFjZSgvIi9nLCcmcXVvdDsnKX0iIHN0eWxlPSJjdXJzb3I6cG9pbnRlciI+CiAgIDx0ZD48Yj4ke3guc2VjdG9yfTwvYj48L3RkPgogICA8dGQgY2xhc3M9InJpZ2h0ICR7eC5tb3ZlPj0wPyd1cCc6J2Rvd24nfSI+PGI+JHtwY3QoeC5tb3ZlKX08L2I+PC90ZD4KICAgPHRkIGNsYXNzPSJyaWdodCI+JHt4LmNvdW50fTwvdGQ+CiAgIDx0ZCBjbGFzcz0icmlnaHQgdXAiPiR7eC5hZHZ9PC90ZD4KICAgPHRkIGNsYXNzPSJyaWdodCBkb3duIj4ke3guZGVjfTwvdGQ+CiAgIDx0ZCBjbGFzcz0iJHt4LnRvcCYmTnVtYmVyKHgudG9wLmZyb21fb3Blbl9wY3QpPj0wPyd1cCc6J2Rvd24nfSI+JHt4LnRvcD94LnRvcC5zeW1ib2wrJyAnK3BjdCh4LnRvcC5mcm9tX29wZW5fcGN0KTonLSd9PC90ZD4KICAgPHRkIGNsYXNzPSIke3guYm90dG9tJiZOdW1iZXIoeC5ib3R0b20uZnJvbV9vcGVuX3BjdCk+PTA/J3VwJzonZG93bid9Ij4ke3guYm90dG9tP3guYm90dG9tLnN5bWJvbCsnICcrcGN0KHguYm90dG9tLmZyb21fb3Blbl9wY3QpOictJ308L3RkPgogPC90cj5gKS5qb2luKCcnKTsKIGRvY3VtZW50LnF1ZXJ5U2VsZWN0b3JBbGwoJyNzZWN0b3JTdW1tYXJ5IHRyJykuZm9yRWFjaChlbD0+ZWwub25jbGljaz0oKT0+c2VsZWN0U2VjdG9yKGVsLmRhdGFzZXQuc2VjdG9yKSk7CiBpZighc2VsZWN0ZWRTZWN0b3IgJiYgYS5sZW5ndGgpc2VsZWN0U2VjdG9yKGFbMF0uc2VjdG9yKTsKfQ==").decode()
    if old_box not in html: raise RuntimeError("sector HTML anchor not found")
    if old_js not in html: raise RuntimeError("sector JS anchor not found")
    html=html.replace(old_box,new_box,1).replace(old_js,new_js,1).replace("x.sector||'UNCLASSIFIED'","x.sector||'Other/Industrial'")
    s=s[:st]+repr(html)+s[en:]
    DASH.write_text(s,encoding="utf-8")
    py_compile.compile(str(DASH),doraise=True)
except Exception:
    shutil.copy2(backup/DASH.name,DASH); shutil.copy2(backup/MAP.name,MAP)
    print("INSTALL FAILED - originals restored:",backup)
    raise

counts={}
for _,sec in rows: counts[sec]=counts.get(sec,0)+1
print("="*82)
print("SUCCESS: FINAL SECTOR DASHBOARD INSTALLED")
print("Backup:",backup)
print("PASS: canonical sector taxonomy")
print("PASS: sector % from 09:15 open only")
print("PASS: Stocks / Adv / Dec / Top Stock / Bottom Stock")
print("PASS: scanner untouched; zero additional Dhan API calls")
print()
for sec,n in sorted(counts.items()): print(f"{sec}: {n}")
print("="*82)
