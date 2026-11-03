"""Live execution engine: mirrors the paper journal's trades to the broker, with hard safety rails. DEFAULT OFF.

It runs as its OWN process (run_live_engine.py), not inside the scanner, so it cannot slow the scan and a crash in one never takes down the other. Once a second it reads data/intraday_movement/paper_trade_journal.json:

    a new OPEN paper trade today     -> risk checks, then a BUY limit order at (fresh ask + buffer), capped at paper entry price + MAX_SLIP; waits ENTRY_TIMEOUT_S, cancels what did not fill
    a filled entry                    -> a protective SELL STOP_LOSS order at the paper trade's initial option stop (so a crash or lost connection never leaves a position without a stop)
    the paper trade turns CLOSED      -> the protective stop is cancelled, then a SELL limit at (bid - buffer), re-priced lower twice, then MARKET, until flat
    the broker stop fills first       -> the live position is recorded closed at the stop; the later paper exit sends nothing

Modes (APLUS_LIVE_MODE): OFF (default: nothing happens) | DRY_RUN (the whole flow with DryRunBroker: payloads are built and logged, NOTHING is sent) | LIVE (real orders). LIVE additionally needs
data/control/live_armed.json for TODAY, written by `python live_ctl.py arm` after a typed confirmation, so a stray environment variable cannot start real trading on its own.

Rails (all in LiveConfig, env-overridable): LOTS_CAP lots per order, MAX_ORDER_VALUE rupees per order, MAX_DAILY_LOSS rupees (realised + open, gross) after which new entries stop and open positions are flattened,
MAX_SLIP_PCT between the paper entry and the live ask, last entry time, a flatten-everything time, the kill-switch file data/control/LIVE_KILL (create it: no new entries, everything flattened) and a position
reconciliation against the broker every minute (a mismatch halts new entries). No cap on the NUMBER of trades. Every request and response is appended to data/live/orders_<day>.jsonl.

State is persisted to data/live/state.json after every change; on restart the engine looks orders up again (by id, or by correlation id when a request may not have been recorded) instead of re-sending.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time as clock, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from live_broker import Broker, DryRunBroker, OrderRequest, OrderState

ROOT = Path(__file__).resolve().parent
IST = timezone(timedelta(hours=5, minutes=30))
JOURNAL = ("data", "intraday_movement", "paper_trade_journal.json")


def _env_f(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return default


def _env_t(name: str, default: str) -> clock:
    h, m = (os.getenv(name, default) or default).split(":")[:2]
    return clock(int(h), int(m))


@dataclass
class LiveConfig:
    mode: str = "OFF"
    lots_cap: int = 1
    max_order_value: float = 30_000.0
    max_daily_loss: float = 5_000.0
    max_slip_pct: float = 5.0
    entry_buffer_pct: float = 1.0
    exit_buffer_pct: float = 1.0
    entry_timeout_s: float = 15.0
    exit_wait_s: float = 6.0
    sl_limit_gap_pct: float = 3.0
    product: str = "INTRADAY"
    first_entry: clock = clock(9, 16)
    last_entry: clock = clock(15, 15)
    flatten_at: clock = clock(15, 20)
    flatten_on_cap: bool = True
    reconcile_s: float = 60.0
    tick: float = 0.05

    @classmethod
    def from_env(cls) -> "LiveConfig":
        mode = os.getenv("APLUS_LIVE_MODE", "OFF").strip().upper()
        return cls(mode=mode if mode in ("OFF", "DRY_RUN", "LIVE") else "OFF", lots_cap=int(_env_f("APLUS_LIVE_LOTS_CAP", 1)), max_order_value=_env_f("APLUS_LIVE_MAX_ORDER_VALUE", 30_000.0),
                   max_daily_loss=_env_f("APLUS_LIVE_MAX_DAILY_LOSS", 5_000.0), max_slip_pct=_env_f("APLUS_LIVE_MAX_SLIP_PCT", 5.0), entry_buffer_pct=_env_f("APLUS_LIVE_ENTRY_BUFFER_PCT", 1.0),
                   exit_buffer_pct=_env_f("APLUS_LIVE_EXIT_BUFFER_PCT", 1.0), entry_timeout_s=_env_f("APLUS_LIVE_ENTRY_TIMEOUT_S", 15.0), product=os.getenv("APLUS_LIVE_PRODUCT", "INTRADAY").upper(),
                   last_entry=_env_t("APLUS_LIVE_LAST_ENTRY", "15:15"), flatten_at=_env_t("APLUS_LIVE_FLATTEN_AT", "15:20"),
                   flatten_on_cap=os.getenv("APLUS_LIVE_FLATTEN_ON_CAP", "1") not in ("0", "false", "no"))


def tick_round(price: float, tick: float = 0.05, up: bool = True) -> float:
    n = price / tick
    n = -(-n // 1) if up else n // 1
    return round(n * tick, 2)


@dataclass
class Rec:
    paper_id: str
    symbol: str = ""
    security_id: str = ""
    status: str = "NEW"             # NEW SKIPPED ENTRY_SENT OPEN EXIT_SENT CLOSED FAILED
    qty: int = 0
    lot_size: int = 0
    paper_entry: float = 0.0
    stop: float = 0.0
    entry_order: str = ""
    entry_price: float = 0.0
    sl_order: str = ""
    exit_order: str = ""
    exit_price: float = 0.0
    exit_attempt: int = 0
    exit_sent_at: float = 0.0
    entry_sent_at: float = 0.0
    realized: float = 0.0
    reason: str = ""
    history: list[str] = field(default_factory=list)


class LiveEngine:
    def __init__(self, root: Path, broker: Broker, cfg: LiveConfig | None = None, now_fn: Callable[[], datetime] | None = None, notify: Callable[[str], None] | None = None,
                 sleep: Callable[[float], None] = time.sleep, mono: Callable[[], float] = time.monotonic) -> None:
        self.root, self.broker, self.cfg = root, broker, cfg or LiveConfig.from_env()
        self.mono = mono                                    # monotonic clock for the order timeouts (injectable for tests)
        self.now = now_fn or (lambda: datetime.now(IST))
        self.notify_fn, self.sleep = notify, sleep
        self.state_path = root / "data" / "live" / "state.json"
        self.recs: dict[str, Rec] = {}
        self.halted = ""
        self.day = self.now().date().isoformat()
        self._last_reconcile = 0.0
        self._load()

    # ---- persistence / logging -----------------------------------------------------------------------------------------------------------------------------------------------
    def _load(self) -> None:
        try:
            d = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if d.get("day") != self.day:
            return                                          # another day's state is history, not ours
        self.halted = d.get("halted", "")
        self.recs = {k: Rec(**v) for k, v in d.get("recs", {}).items()}

    def _save(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"day": self.day, "mode": self.cfg.mode, "halted": self.halted, "updated": self.now().isoformat(timespec="seconds"),
                                   "recs": {k: asdict(v) for k, v in self.recs.items()}}, indent=1), encoding="utf-8")
        os.replace(tmp, self.state_path)

    def audit(self, kind: str, **kw: Any) -> None:
        p = self.root / "data" / "live" / f"orders_{self.day}.jsonl"
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as h:
            h.write(json.dumps({"t": self.now().isoformat(timespec="milliseconds"), "mode": self.cfg.mode, "kind": kind, **kw}, default=str) + "\n")

    def say(self, text: str) -> None:
        self.audit("alert", text=text)
        if self.notify_fn:
            try:
                self.notify_fn(f"[LIVE {self.cfg.mode}] {text}")
            except Exception:                               # noqa: BLE001 - an alert failure never stops trading logic
                pass

    # ---- gates ---------------------------------------------------------------------------------------------------------------------------------------------------------------
    def armed(self) -> bool:
        if self.cfg.mode == "DRY_RUN":
            return True
        if self.cfg.mode != "LIVE":
            return False
        try:
            return json.loads((self.root / "data" / "control" / "live_armed.json").read_text(encoding="utf-8")).get("date") == self.day
        except (OSError, ValueError):
            return False

    def killed(self) -> bool:
        return (self.root / "data" / "control" / "LIVE_KILL").exists()

    def halt(self, why: str) -> None:
        if not self.halted:
            self.halted = why
            self.say(f"HALTED: {why}")
            self._save()

    # ---- helpers -------------------------------------------------------------------------------------------------------------------------------------------------------------
    def _place(self, rec: Rec, req: OrderRequest) -> OrderState:
        self.audit("request", paper_id=rec.paper_id, **{k: v for k, v in asdict(req).items()})
        try:
            st = self.broker.place(req)
        except Exception as exc:                            # noqa: BLE001
            self.audit("error", paper_id=rec.paper_id, where="place", error=f"{type(exc).__name__}: {exc}")
            st = self.broker.find_by_correlation(req.correlation_id) if hasattr(self.broker, "find_by_correlation") else None   # the request may have gone through
            if st is None:
                return OrderState("", "REJECTED", message=f"{type(exc).__name__}: {exc}")
        self.audit("response", paper_id=rec.paper_id, order_id=st.order_id, status=st.status, filled=st.filled_qty, avg=st.avg_price, message=st.message)
        return st

    def _poll(self, order_id: str) -> OrderState:
        try:
            return self.broker.get(order_id)
        except Exception as exc:                            # noqa: BLE001
            self.audit("error", where="get", order_id=order_id, error=f"{type(exc).__name__}: {exc}")
            return OrderState(order_id, "UNKNOWN")

    def _journal(self) -> list[dict[str, Any]]:
        try:
            return json.loads(self.root.joinpath(*JOURNAL).read_text(encoding="utf-8")).get("trades") or []
        except (OSError, ValueError):
            return []

    def _quote(self, sid: str) -> tuple[float, float] | None:
        try:
            return self.broker.quote(sid)
        except Exception:                                   # noqa: BLE001
            return None

    # ---- entry ---------------------------------------------------------------------------------------------------------------------------------------------------------------
    def _maybe_enter(self, t: dict[str, Any]) -> None:
        pid = str(t.get("paper_trade_id"))
        rec = Rec(paper_id=pid, symbol=str(t.get("trading_symbol") or t.get("symbol") or ""), security_id=str(t.get("option_security_id") or ""), lot_size=int(t.get("lot_size") or 0),
                  paper_entry=float(t.get("entry_price") or t.get("limit_price") or 0), stop=float(t.get("option_stop") or 0))
        self.recs[pid] = rec

        def skip(why: str) -> None:
            rec.status, rec.reason = "SKIPPED", why
            rec.history.append(f"skipped: {why}")
            self.audit("skip", paper_id=pid, reason=why)
            self.say(f"skipped {rec.symbol}: {why}")
            self._save()

        now_t = self.now().time()
        if not self.armed():
            return skip("not armed")
        if self.halted:
            return skip(f"halted ({self.halted})")
        if self.killed():
            return skip("kill switch")
        if not (self.cfg.first_entry <= now_t <= self.cfg.last_entry):
            return skip("outside the entry window")
        if not rec.security_id or rec.lot_size <= 0 or rec.paper_entry <= 0:
            return skip("incomplete paper trade (security id / lot size / price)")
        lots = max(1, min(int(t.get("lots") or 1), self.cfg.lots_cap))
        rec.qty = lots * rec.lot_size
        q = self._quote(rec.security_id)
        if not q:
            return skip("no live quote")
        bid, ask = q
        if ask > rec.paper_entry * (1 + self.cfg.max_slip_pct / 100.0):
            return skip(f"ask {ask} is more than {self.cfg.max_slip_pct}% above the paper entry {rec.paper_entry}")
        limit = tick_round(min(ask * (1 + self.cfg.entry_buffer_pct / 100.0), rec.paper_entry * (1 + self.cfg.max_slip_pct / 100.0)))
        if limit * rec.qty > self.cfg.max_order_value:
            return skip(f"order value {limit * rec.qty:.0f} above the cap {self.cfg.max_order_value:.0f}")
        if self.cfg.mode == "LIVE":
            try:
                avail = float(self.broker.funds().get("availabelBalance", self.broker.funds().get("availableBalance", 0)) or 0)
            except Exception:                               # noqa: BLE001
                avail = 0.0
            if avail < limit * rec.qty:
                return skip(f"funds {avail:.0f} below the order value {limit * rec.qty:.0f}")
        st = self._place(rec, OrderRequest(f"{pid}-E", "BUY", rec.security_id, rec.qty, "LIMIT", price=limit, product=self.cfg.product, symbol=rec.symbol))
        rec.entry_order, rec.entry_sent_at = st.order_id, self.mono()
        if st.status in ("REJECTED", "CANCELLED", "EXPIRED") and not st.filled_qty:
            rec.status, rec.reason = "FAILED", f"entry {st.status}: {st.message}"
            self.say(f"ENTRY FAILED {rec.symbol}: {rec.reason}")
        else:
            rec.status = "ENTRY_SENT"
            rec.history.append(f"entry sent {rec.qty} @ {limit}")
            self.say(f"entry sent: BUY {rec.symbol} {rec.qty} @ {limit} (paper {rec.paper_entry})")
        self._save()
        self._advance_entry(rec, st)

    def _advance_entry(self, rec: Rec, st: OrderState | None = None) -> None:
        st = st or self._poll(rec.entry_order)
        timed_out = self.mono() - rec.entry_sent_at >= self.cfg.entry_timeout_s
        if st.status == "TRADED" or (st.status == "PART_TRADED" and timed_out) or (timed_out and st.filled_qty):
            if not st.final:                               # a partial fill at the timeout: take back the rest and keep what filled
                try:
                    self.broker.cancel(rec.entry_order)
                except Exception:                           # noqa: BLE001
                    pass
                st = self._poll(rec.entry_order)
            rec.qty, rec.entry_price = st.filled_qty or rec.qty, st.avg_price or rec.paper_entry
            rec.status = "OPEN"
            rec.history.append(f"entry filled {rec.qty} @ {rec.entry_price}")
            self.say(f"ENTRY FILLED {rec.symbol} {rec.qty} @ {rec.entry_price}")
            self._place_stop(rec)
            self._save()
        elif st.status in ("REJECTED", "CANCELLED", "EXPIRED"):
            rec.status, rec.reason = "FAILED", f"entry {st.status}: {st.message}"
            self.say(f"ENTRY {st.status} {rec.symbol}")
            self._save()
        elif timed_out:                                    # nothing filled in time: take the order back
            try:
                self.broker.cancel(rec.entry_order)
            except Exception:                               # noqa: BLE001
                pass
            st = self._poll(rec.entry_order)
            if st.filled_qty:
                return self._advance_entry(rec, st)
            rec.status, rec.reason = "FAILED", "entry not filled in time, cancelled"
            self.say(f"entry not filled, cancelled: {rec.symbol}")
            self._save()

    def _place_stop(self, rec: Rec) -> None:
        if rec.stop <= 0 or rec.stop >= rec.entry_price:
            rec.stop = round(rec.entry_price * 0.80, 2)     # no usable paper stop: the system's standard 20 % initial stop
        trig = tick_round(rec.stop, up=True)
        price = tick_round(trig * (1 - self.cfg.sl_limit_gap_pct / 100.0), up=False)
        st = self._place(rec, OrderRequest(f"{rec.paper_id}-S", "SELL", rec.security_id, rec.qty, "STOP_LOSS", price=price, trigger_price=trig, product=self.cfg.product, symbol=rec.symbol))
        rec.sl_order = st.order_id
        if st.status == "REJECTED":
            self.halt(f"protective stop rejected for {rec.symbol}: {st.message}")
            self._exit(rec, "stop rejected: flatten")      # never hold an unprotected position

    # ---- exit ----------------------------------------------------------------------------------------------------------------------------------------------------------------
    def _exit(self, rec: Rec, reason: str) -> None:
        if rec.status != "OPEN":
            return
        if rec.sl_order:
            st = self._poll(rec.sl_order)
            if st.status == "TRADED":                      # the broker stop got there first
                rec.status, rec.exit_price, rec.reason = "CLOSED", st.avg_price, "broker stop filled"
                rec.realized = (rec.exit_price - rec.entry_price) * rec.qty
                self.say(f"STOP FILLED {rec.symbol} @ {rec.exit_price} (P&L {rec.realized:+.0f})")
                self._save()
                return
            if not st.final:
                try:
                    self.broker.cancel(rec.sl_order)
                except Exception:                           # noqa: BLE001
                    self.audit("error", where="cancel stop", order_id=rec.sl_order)
                st = self._poll(rec.sl_order)
                if st.status == "TRADED":
                    return self._exit(rec, reason)
        rec.reason = reason
        rec.status, rec.exit_attempt = "EXIT_SENT", 0
        self._send_exit(rec)

    def _send_exit(self, rec: Rec) -> None:
        q = self._quote(rec.security_id)
        bid = q[0] if q else 0.0
        steps = [self.cfg.exit_buffer_pct, self.cfg.exit_buffer_pct * 3.0, None]          # limit, lower limit, then market
        buf = steps[min(rec.exit_attempt, 2)]
        if buf is None or bid <= 0:
            req = OrderRequest(f"{rec.paper_id}-X{rec.exit_attempt}", "SELL", rec.security_id, rec.qty, "MARKET", product=self.cfg.product, symbol=rec.symbol)
        else:
            req = OrderRequest(f"{rec.paper_id}-X{rec.exit_attempt}", "SELL", rec.security_id, rec.qty, "LIMIT", price=max(0.05, tick_round(bid * (1 - buf / 100.0), up=False)), product=self.cfg.product, symbol=rec.symbol)
        st = self._place(rec, req)
        rec.exit_order, rec.exit_sent_at = st.order_id, self.mono()
        rec.history.append(f"exit attempt {rec.exit_attempt}: {req.order_type} {req.price or ''}")
        self._save()
        self._advance_exit(rec, st)

    def _advance_exit(self, rec: Rec, st: OrderState | None = None) -> None:
        st = st or self._poll(rec.exit_order)
        if st.status == "TRADED":
            rec.status, rec.exit_price = "CLOSED", st.avg_price
            rec.realized = (rec.exit_price - rec.entry_price) * rec.qty
            self.say(f"EXIT {rec.symbol} {rec.qty} @ {rec.exit_price} ({rec.reason}); P&L {rec.realized:+.0f}")
            self._save()
        elif st.status in ("REJECTED", "CANCELLED", "EXPIRED") or self.mono() - rec.exit_sent_at >= self.cfg.exit_wait_s:
            if not st.final:
                try:
                    self.broker.cancel(rec.exit_order)
                except Exception:                           # noqa: BLE001
                    pass
                st = self._poll(rec.exit_order)
                if st.status == "TRADED":
                    return self._advance_exit(rec, st)
            rec.exit_attempt += 1
            if rec.exit_attempt > 3:
                self.halt(f"could not exit {rec.symbol} after 4 attempts: FLATTEN BY HAND")
                return
            self._send_exit(rec)

    # ---- P&L / reconcile -----------------------------------------------------------------------------------------------------------------------------------------------------
    def pnl(self) -> tuple[float, float]:
        realised = sum(r.realized for r in self.recs.values() if r.status == "CLOSED")
        open_pnl = 0.0
        for r in self.recs.values():
            if r.status in ("OPEN", "EXIT_SENT"):
                q = self._quote(r.security_id)
                if q:
                    open_pnl += (q[0] - r.entry_price) * r.qty
        return realised, open_pnl

    def reconcile(self) -> None:
        try:
            held = self.broker.positions()
        except Exception as exc:                            # noqa: BLE001
            self.audit("error", where="positions", error=f"{type(exc).__name__}: {exc}")
            return
        mine: dict[str, int] = {}
        for r in self.recs.values():
            if r.status in ("OPEN", "EXIT_SENT"):
                mine[r.security_id] = mine.get(r.security_id, 0) + r.qty
        for sid in set(held) | set(mine):
            if held.get(sid, 0) != mine.get(sid, 0):
                self.halt(f"position mismatch on {sid}: broker {held.get(sid, 0)}, engine {mine.get(sid, 0)}")

    # ---- main step -----------------------------------------------------------------------------------------------------------------------------------------------------------
    def flatten_all(self, why: str) -> None:
        for r in self.recs.values():
            if r.status == "OPEN":
                self._exit(r, why)

    def step(self) -> None:
        if self.cfg.mode == "OFF":
            return
        now_t = self.now().time()
        if self.killed() and not self.halted.startswith("KILL"):
            self.halt("KILL switch file present")
            self.flatten_all("kill switch")
        trades = {str(t.get("paper_trade_id")): t for t in self._journal() if str(t.get("entry_time") or "").startswith(self.day)}
        for pid, t in trades.items():
            if pid not in self.recs and str(t.get("status") or "").upper() == "OPEN":
                self._maybe_enter(t)
        for rec in list(self.recs.values()):
            t = trades.get(rec.paper_id, {})
            if rec.status == "ENTRY_SENT":
                self._advance_entry(rec)
            if rec.status == "OPEN":
                if rec.sl_order and self._poll(rec.sl_order).status == "TRADED":
                    self._exit(rec, "broker stop")
                elif str(t.get("status") or "").upper() == "CLOSED":
                    self._exit(rec, f"paper exit: {t.get('exit_reason') or 'closed'}")
                elif now_t >= self.cfg.flatten_at:
                    self._exit(rec, "end-of-day flatten")
            if rec.status == "EXIT_SENT":
                self._advance_exit(rec)
        realised, open_pnl = self.pnl()
        if realised + open_pnl <= -self.cfg.max_daily_loss and not self.halted:
            self.halt(f"daily loss cap hit ({realised + open_pnl:+.0f} vs -{self.cfg.max_daily_loss:.0f})")
            if self.cfg.flatten_on_cap:
                self.flatten_all("daily loss cap")
        if self.mono() - self._last_reconcile >= self.cfg.reconcile_s:
            self._last_reconcile = self.mono()
            self.reconcile()

    def run(self, until: clock = clock(15, 35)) -> None:                   # pragma: no cover - the loop is exercised through step()
        self.say("engine started")
        while self.now().time() < until:
            try:
                self.step()
            except Exception as exc:                        # noqa: BLE001 - never die in the loop; report and keep protecting positions
                self.audit("error", where="step", error=f"{type(exc).__name__}: {exc}")
            self.sleep(1.0)
        self.say("engine stopped for the day")

    def status(self) -> dict[str, Any]:
        realised, open_pnl = self.pnl()
        return {"mode": self.cfg.mode, "armed": self.armed(), "halted": self.halted, "killed": self.killed(), "realised": round(realised, 2), "open_pnl": round(open_pnl, 2),
                "cap": self.cfg.max_daily_loss, "recs": {k: asdict(v) for k, v in self.recs.items()}}
