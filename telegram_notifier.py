from __future__ import annotations
import json, os, tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo
import requests
try:
    import keyring
except ImportError:
    keyring = None

IST=ZoneInfo("Asia/Kolkata")
SERVICE="CAlphaTrader:Telegram"

class TelegramPaperTradeNotifier:
    """Actual APlus PAPER ENTRY/EXIT alerts using existing CAlphaTrader credentials."""
    def __init__(self, *, state_dir: Path):
        self.enabled=os.getenv("TELEGRAM_ENABLED","true").lower() in {"1","true","yes","on"}
        self.timeout=float(os.getenv("TELEGRAM_TIMEOUT_SECONDS","8"))
        self.state_path=Path(state_dir)/"telegram_paper_alerts.json"
        self.sent=set()
        if self.state_path.exists():
            try: self.sent=set(json.loads(self.state_path.read_text(encoding="utf-8")).get("sent",[]))
            except Exception: self.sent=set()

    def _creds(self):
        if not self.enabled or keyring is None: return "",""
        try:
            return (str(keyring.get_password(SERVICE,"bot_token") or "").strip(),
                    str(keyring.get_password(SERVICE,"chat_id") or "").strip())
        except Exception: return "",""

    @property
    def configured(self): return all(self._creds())

    def notify_entry(self,t): return self._send(f"{t.get('paper_trade_id')}|ENTRY",self._entry(t))
    def notify_exit(self,t): return self._send(f"{t.get('paper_trade_id')}|EXIT",self._exit(t))

    def _send(self,event,text):
        if event in self.sent: return False
        token,chat=self._creds()
        if not token or not chat: return False
        try:
            r=requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id":chat,"text":text,"disable_web_page_preview":True},timeout=self.timeout)
            r.raise_for_status()
            if not r.json().get("ok"): return False
            self.sent.add(event); self._save(); return True
        except Exception: return False

    def _save(self):
        self.state_path.parent.mkdir(parents=True,exist_ok=True)
        fd,tmp=tempfile.mkstemp(dir=str(self.state_path.parent),suffix=".tmp")
        try:
            with os.fdopen(fd,"w",encoding="utf-8") as f:
                json.dump({"sent":sorted(self.sent)[-4000:]},f,indent=2)
            os.replace(tmp,self.state_path)
        finally:
            if os.path.exists(tmp):
                try: os.unlink(tmp)
                except OSError: pass

    @staticmethod
    def _num(v):
        try:return float(v or 0)
        except:return 0.0
    @classmethod
    def _money(cls,v): return f"₹{cls._num(v):,.2f}"
    @staticmethod
    def _time(v):
        try:
            d=datetime.fromisoformat(str(v).replace("Z","+00:00"))
            if d.tzinfo is None:d=d.replace(tzinfo=IST)
            return d.astimezone(IST).strftime("%H:%M:%S IST")
        except:return str(v or "-")

    @classmethod
    def _entry(cls,t:Mapping[str,Any]):
        return "\n".join([
          "🔔 APlus PAPER TRADE OPENED","",
          f"{t.get('symbol','')} | BUY {t.get('option_type','')}",
          f"Contract: {cls._num(t.get('strike')):g} {t.get('option_type','')} | Exp {t.get('expiry','')}",
          f"Entry: {cls._money(t.get('entry_price'))} @ {cls._time(t.get('entry_time'))}",
          f"Qty: {int(cls._num(t.get('quantity')))} | Lots: {int(cls._num(t.get('lots')))}",
          f"Capital: {cls._money(t.get('capital_deployed'))}",
          f"Max Risk: {cls._money(t.get('planned_risk_amount'))} ({cls._num(t.get('planned_risk_percent')):.2f}%)",
          f"SL: {cls._money(t.get('option_stop'))}",
          f"T1/T2/T3: {cls._money(t.get('option_target1'))} / {cls._money(t.get('option_target2'))} / {cls._money(t.get('option_target3'))}",
          f"Reason: {t.get('entry_reason') or '-'}",
          f"Trade ID: {t.get('paper_trade_id','-')}"])

    @classmethod
    def _exit(cls,t:Mapping[str,Any]):
        result=str(t.get("result") or "CLOSED").upper()
        icon="✅" if result=="WIN" else ("🔴" if result=="LOSS" else "⚪")
        sec=max(0,int(cls._num(t.get("holding_seconds")))); m,s=divmod(sec,60)
        return "\n".join([
          f"{icon} APlus PAPER TRADE CLOSED — {result}","",
          f"{t.get('symbol','')} | {cls._num(t.get('strike')):g} {t.get('option_type','')}",
          f"Entry: {cls._money(t.get('entry_price'))} @ {cls._time(t.get('entry_time'))}",
          f"Exit: {cls._money(t.get('exit_price'))} @ {cls._time(t.get('exit_time'))}",
          f"Exit Reason: {t.get('exit_reason') or '-'}",
          f"Net P&L: {cls._money(t.get('net_pnl'))}",
          f"Return: {cls._num(t.get('return_percent')):+.2f}%",
          f"MFE: {cls._money(t.get('mfe_amount'))} | MAE: {cls._money(t.get('mae_amount'))}",
          f"Holding: {m}m {s}s",f"Trade ID: {t.get('paper_trade_id','-')}"])
