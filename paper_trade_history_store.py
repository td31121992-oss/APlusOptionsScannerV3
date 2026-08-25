from __future__ import annotations
import csv, json, os, tempfile, time
from pathlib import Path
from typing import Any, Iterable, Mapping

HISTORY_CSV="paper_trade_history.csv"
HISTORY_JSON="paper_trade_history.json"

def _key(t):
    tid=str(t.get("paper_trade_id") or t.get("trade_id") or "").strip()
    if tid:return tid
    return "|".join([str(t.get("entry_time") or t.get("generated_at") or ""),str(t.get("symbol") or ""),str(t.get("direction") or ""),str(t.get("option_type") or t.get("side") or ""),str(t.get("strike") or "")])

def _atomic_text(path:Path,text:str):
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix=path.name+".",suffix=".tmp",dir=str(path.parent))
    try:
        with os.fdopen(fd,"w",encoding="utf-8",newline="") as h:
            h.write(text);h.flush()
            try:os.fsync(h.fileno())
            except OSError:pass
        last=None
        for i in range(7):
            try:os.replace(tmp,path);return
            except PermissionError as e:last=e;time.sleep(0.04*(2**i))
        if last:raise last
    finally:
        try:
            if os.path.exists(tmp):os.unlink(tmp)
        except OSError:pass

def load_history(report_dir:Path):
    report_dir=Path(report_dir)
    p=report_dir/HISTORY_JSON
    if p.exists():
        try:
            obj=json.loads(p.read_text(encoding="utf-8"))
            rows=obj.get("paper_trades") if isinstance(obj,dict) else obj
            if isinstance(rows,list):return [dict(x) for x in rows if isinstance(x,Mapping)]
        except Exception:pass
    p=report_dir/HISTORY_CSV
    if p.exists():
        try:
            with p.open("r",encoding="utf-8-sig",newline="") as h:return [dict(x) for x in csv.DictReader(h)]
        except Exception:pass
    return []

def sync_history(report_dir:Path,trades:Iterable[Mapping[str,Any]]):
    try:
        report_dir=Path(report_dir)
        merged={_key(x):dict(x) for x in load_history(report_dir) if _key(x)}
        added=updated=0
        for raw in trades:
            if not isinstance(raw,Mapping):continue
            row=dict(raw);k=_key(row)
            if not k:continue
            if k in merged:merged[k].update(row);updated+=1
            else:merged[k]=row;added+=1
        rows=sorted(merged.values(),key=lambda x:str(x.get("entry_time") or x.get("generated_at") or ""))
        _atomic_text(report_dir/HISTORY_JSON,json.dumps({"paper_trades":rows,"trade_count":len(rows)},ensure_ascii=False,indent=2,default=str))
        fields=[];seen=set()
        for r in rows:
            for k in r:
                if k not in seen:seen.add(k);fields.append(k)
        import io
        sio=io.StringIO(newline="")
        if fields:
            w=csv.DictWriter(sio,fieldnames=fields,extrasaction="ignore");w.writeheader()
            for r in rows:
                clean={}
                for k in fields:
                    v=r.get(k,"")
                    if isinstance(v,(list,tuple,dict)):v=json.dumps(v,ensure_ascii=False,default=str)
                    clean[k]=v
                w.writerow(clean)
        _atomic_text(report_dir/HISTORY_CSV,"\ufeff"+sio.getvalue())
        return {"ok":True,"added":added,"updated":updated,"total":len(rows)}
    except Exception as exc:
        print(f"Paper trade history sync failed but scanner will continue: {type(exc).__name__}: {exc}")
        return {"ok":False,"error":f"{type(exc).__name__}: {exc}"}
