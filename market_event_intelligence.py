from __future__ import annotations
import hashlib,json,os,re,time,urllib.request,xml.etree.ElementTree as ET
from datetime import datetime,timedelta,timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
try:import keyring
except ImportError:keyring=None
from news_intelligence import write_jsonl,load_events
ROOT=Path(__file__).resolve().parent
CALENDAR_PATH=ROOT/"data"/"news_intelligence"/"market_event_calendar.json";STATE_PATH=ROOT/"data"/"news_intelligence"/"market_event_telegram_state.json";LOG_PATH=ROOT/"data"/"logs"/"market_event_intelligence.log"
SEBI_RSS="https://www.sebi.gov.in/sebirss.xml";TG_SERVICE="CAlphaTrader:Telegram"
def log(s):LOG_PATH.parent.mkdir(parents=True,exist_ok=True);LOG_PATH.open("a",encoding="utf-8").write(f"{datetime.now(timezone.utc).isoformat()} {s}\n")
def utc(v):
    try:d=v if isinstance(v,datetime) else datetime.fromisoformat(str(v).replace("Z","+00:00"))
    except ValueError:return None
    return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)
def eid(k):return "CAL-"+hashlib.sha256(k.encode()).hexdigest()[:24]
def seed_events():
    rows=[
    ("2026-10-07T10:00:00+05:30","RBI MPC October 2026 policy decision","RBI_MPC","VERY HIGH",["NIFTY","BANKNIFTY"],"Monitor the actual repo-rate decision, policy stance, inflation and liquidity guidance."),
    ("2026-10-08T18:30:00+05:30","TCS Q2 FY27 results","EARNINGS","HIGH",["TCS","NIFTYIT"],"September-quarter results; earnings, guidance, deal wins and margins."),
    ("2026-10-12T18:30:00+05:30","HCLTech Q2 FY27 results","EARNINGS","HIGH",["HCLTECH","NIFTYIT"],"September-quarter results; guidance, margins and deal momentum."),
    ("2026-10-14T18:30:00+05:30","Tata Technologies Q2 FY27 results","EARNINGS","HIGH",["TATATECH","NIFTYIT"],"September-quarter results and management commentary."),
    ("2026-10-15T18:30:00+05:30","Wipro Q2 FY27 results","EARNINGS","HIGH",["WIPRO","NIFTYIT"],"September-quarter results; guidance, bookings, margins and demand."),
    ("2026-10-15T18:30:00+05:30","Tech Mahindra Q2 FY27 results","EARNINGS","HIGH",["TECHM","NIFTYIT"],"September-quarter results; margins, deal wins and demand."),
    ("2026-10-19T18:00:00+05:30","LTTS Q2 FY27 results","EARNINGS","HIGH",["LTTS","NIFTYIT"],"September-quarter results and engineering-services demand."),
    ("2026-10-23T18:30:00+05:30","Infosys Q2 FY27 results","EARNINGS","HIGH",["INFY","NIFTYIT"],"September-quarter results; guidance, AI monetisation, margins and demand."),
    ("2026-10-23T18:30:00+05:30","Coforge Q2 FY27 results","EARNINGS","HIGH",["COFORGE","NIFTYIT"],"September-quarter results; integration, order intake and margins."),
    ("2026-12-03T10:00:00+05:30","RBI MPC December 2026 policy decision","RBI_MPC","VERY HIGH",["NIFTY","BANKNIFTY"],"Scheduled RBI policy decision window."),
    ("2027-02-04T10:00:00+05:30","RBI MPC February 2027 policy decision","RBI_MPC","VERY HIGH",["NIFTY","BANKNIFTY"],"Scheduled RBI policy decision window.")]
    return [{"event_id":eid(d+t),"published_at":d,"event_time":d,"source":"APlus Market Event Calendar","source_type":"official_schedule_or_company_schedule","category":c,"impact":i,"symbols":s,"title":t,"summary":sm,"direction":"NEUTRAL","confidence":0.95,"read_only":True,"trading_engine_untouched":True} for d,t,c,i,s,sm in rows]
def seed_calendar():
    CALENDAR_PATH.parent.mkdir(parents=True,exist_ok=True);CALENDAR_PATH.write_text(json.dumps(seed_events(),indent=2,ensure_ascii=False),encoding="utf-8")
def load_calendar():
    try:x=json.loads(CALENDAR_PATH.read_text(encoding="utf-8"));return x if isinstance(x,list) else []
    except Exception:return []
def upcoming(now=None,hours=48):
    now=now or datetime.now(timezone.utc);out=[]
    for e in load_calendar():
        t=utc(e.get("event_time"))
        if t and timedelta(0)<=t-now<=timedelta(hours=hours):out.append((t,e))
    return sorted(out,key=lambda x:x[0])
def credentials():
    if keyring:
        try:
            a=keyring.get_password(TG_SERVICE,"bot_token") or "";b=keyring.get_password(TG_SERVICE,"chat_id") or ""
            if a and b:return a.strip(),b.strip()
        except Exception:pass
    return os.getenv("TELEGRAM_BOT_TOKEN","").strip(),os.getenv("TELEGRAM_CHAT_ID","").strip()
def send(msg):
    token,chat=credentials()
    if not token or not chat:log("Telegram credentials missing; skipped");return False
    import urllib.parse
    try:
        data=urllib.parse.urlencode({"chat_id":chat,"text":msg,"disable_web_page_preview":"true"}).encode()
        with urllib.request.urlopen(urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage",data=data,method="POST"),timeout=15) as r:return bool(json.loads(r.read().decode()).get("ok"))
    except Exception as e:log(f"Telegram send failed: {type(e).__name__}: {e}");return False
def ingest_sebi():
    try:
        root=ET.fromstring(urllib.request.urlopen(urllib.request.Request(SEBI_RSS,headers={"User-Agent":"APlusOptionsScannerV3-NewsAlerts/1.0"}),timeout=15).read());out=[]
        for item in root.findall(".//item"):
            def txt(tag):
                el=item.find(tag);return re.sub(r"\s+"," ","".join(el.itertext()).strip()) if el is not None else ""
            title,link,pub,summary=txt("title"),txt("link"),txt("pubDate"),txt("description")
            if not title or not link:continue
            try:published=parsedate_to_datetime(pub).astimezone(timezone.utc).isoformat() if pub else datetime.now(timezone.utc).isoformat()
            except Exception:published=datetime.now(timezone.utc).isoformat()
            out.append({"event_id":"SEBI-"+hashlib.sha256(link.encode()).hexdigest()[:24],"published_at":published,"fetched_at":datetime.now(timezone.utc).isoformat(),"source":"SEBI RSS","source_type":"official_sebi_rss","category":"SEBI_REGULATORY","impact":"HIGH","title":title,"summary":summary[:1200],"url":link,"direction":"NEUTRAL","confidence":0.95,"read_only":True,"trading_engine_untouched":True})
        return out
    except Exception as e:log(f"SEBI RSS fetch failed: {type(e).__name__}: {e}");return []
def process_once():
    if not CALENDAR_PATH.exists():seed_calendar()
    existing={str(e.get("event_id")) for e in load_events()}
    additions=[e for e in seed_events()+ingest_sebi() if e.get("event_id") not in existing]
    if additions:write_jsonl(additions)
    try:state=json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:state={}
    sent=state.setdefault("sent",{});now=datetime.now(timezone.utc);count=0
    for t,e in upcoming(now,48):
        mins=int((t-now).total_seconds()/60);window="24h" if mins>120 else "1h";key=f"{e['event_id']}:{window}"
        if key not in sent and ((window=="24h" and mins<=1440) or (window=="1h" and mins<=60)):
            msg=f"📅 APlus Market Event — {e['impact']}\nEvent: {e['title']}\nWhen: {e['event_time']}\nAffected: {', '.join(e.get('symbols',[]))}\nWindow: ~{mins} minutes\n\n{e.get('summary','')}\nRead-only event alert • No trade/order action taken"
            if send(msg):sent[key]=now.isoformat();count+=1
    for e in load_events()[-500:]:
        x=str(e.get("event_id") or "");blob=(str(e.get("title") or "")+" "+str(e.get("summary") or "")).lower()
        if not x or x in sent:continue
        if e.get("source_type")=="official_sebi_rss" or any(k in blob for k in ("rbi","repo rate","position limit","margin","derivatives","f&o","expiry","settlement","trading rule","circuit")):
            msg=f"🚨 APlus Market News — {e.get('impact','HIGH')}\n{e.get('title','')}\n{e.get('summary','')[:900]}\n{e.get('url','')}\nRead-only news alert • No trade/order action taken"
            if send(msg):sent[x]=now.isoformat();count+=1
    STATE_PATH.parent.mkdir(parents=True,exist_ok=True);STATE_PATH.write_text(json.dumps({"sent":dict(list(sent.items())[-5000:])},indent=2),encoding="utf-8");log(f"cycle complete; sent={count}; upcoming={len(upcoming(now,48))}");return count
def main():
    once=os.getenv("APLUS_MARKET_EVENT_ONCE","").lower() in ("1","true","yes");interval=max(60,int(os.getenv("APLUS_MARKET_EVENT_INTERVAL","60")));log("worker started")
    while True:
        try:process_once()
        except Exception as e:log(f"cycle failed: {type(e).__name__}: {e}")
        if once:return 0
        time.sleep(interval)
if __name__=="__main__":raise SystemExit(main())
