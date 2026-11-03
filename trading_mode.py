"""Paper / Live mode switch for the dashboard.

The engine is PAPER only. LIVE here means: the broker connection has been checked (read-only) and the mode is
armed for today. NO ORDER ROUTING EXISTS YET - ``order_routing`` always reports NOT_IMPLEMENTED and
``should_route_orders()`` is always False, so arming LIVE cannot place a real order.

Safety rules enforced on every switch to LIVE:
  * APLUS_LIVE_TRADING_ALLOWED=1 must be set by the user on this machine (default: not allowed);
  * the request must come from this PC (loopback), never from the LAN;
  * the caller must type the confirmation word LIVE;
  * a read-only broker check (profile + fund limits) must succeed;
  * the arming is for the current trading day only - on any later day the mode reverts to PAPER;
  * any failure leaves (or puts) the engine in PAPER.
Switching back to PAPER is always allowed. Every change is appended to data/logs/trading_mode_audit.log.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
IST = ZoneInfo("Asia/Kolkata")
STATE_PATH = ROOT / "data" / "dashboard_state" / "trading_mode.json"
AUDIT_PATH = ROOT / "data" / "logs" / "trading_mode_audit.log"
ORDER_ROUTING = "NOT_IMPLEMENTED"


def live_allowed() -> bool:
    return os.getenv("APLUS_LIVE_TRADING_ALLOWED", "").strip() == "1"


def should_route_orders() -> bool:
    """Single gate any future order-routing code must call. Always False until routing is built and reviewed."""
    return False


def _now() -> datetime:
    return datetime.now(IST)


def _read(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _audit(event: str, **fields: Any) -> None:
    try:
        AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with AUDIT_PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"at": _now().isoformat(), "event": event, **fields}, ensure_ascii=False) + "\n")
    except OSError:
        pass


def get_state(now: datetime | None = None, path: Path = STATE_PATH) -> dict[str, Any]:
    now = now or _now()
    state = _read(path)
    mode = state.get("mode") if state.get("mode") in {"PAPER", "LIVE"} else "PAPER"
    if mode == "LIVE" and state.get("armed_date") != now.date().isoformat():
        mode = "PAPER"                                   # live arming expires at the end of the day it was armed
        state = {**state, "mode": "PAPER", "changed_at": now.isoformat(), "reason": "LIVE_ARMING_EXPIRED"}
        _write(path, state)
        _audit("auto_revert_to_paper", reason="LIVE_ARMING_EXPIRED")
    return {"mode": mode, "changed_at": state.get("changed_at", ""), "armed_date": state.get("armed_date", ""),
            "broker": state.get("broker") or {}, "live_allowed": live_allowed(), "order_routing": ORDER_ROUTING,
            "message": state.get("reason", "")}


def broker_check() -> dict[str, Any]:
    """Read-only Dhan check (profile + fund limits). Never returns the token."""
    try:
        import requests
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env")
        from dhan_auth import resolve_access_token

        client_id = os.getenv("DHAN_CLIENT_ID", "").strip()
        token = resolve_access_token(project_root=ROOT, client_id=client_id, env_token=os.getenv("DHAN_ACCESS_TOKEN", "").strip())
        headers = {"access-token": token, "client-id": client_id, "Accept": "application/json"}
        profile = requests.get("https://api.dhan.co/v2/profile", headers=headers, timeout=15)
        if profile.status_code != 200:
            return {"connected": False, "error": f"profile HTTP {profile.status_code}"}
        funds = requests.get("https://api.dhan.co/v2/fundlimit", headers=headers, timeout=15)
        available = None
        if funds.status_code == 200:
            body = funds.json()
            available = body.get("availabelBalance", body.get("availableBalance"))
        masked = client_id[:2] + "*" * max(0, len(client_id) - 4) + client_id[-2:] if len(client_id) > 4 else "****"
        return {"connected": True, "client": masked, "available_balance": available, "checked_at": _now().isoformat()}
    except Exception as exc:                              # noqa: BLE001 - report, never raise into the dashboard
        return {"connected": False, "error": f"{type(exc).__name__}"}


def set_mode(target: str, *, confirm: str = "", remote_addr: str = "", check: Callable[[], dict[str, Any]] | None = None,
             now: datetime | None = None, path: Path = STATE_PATH) -> tuple[bool, dict[str, Any], str]:
    """Returns (ok, state, message)."""
    now = now or _now()
    target = str(target or "").upper()
    if target == "PAPER":
        _write(path, {"mode": "PAPER", "changed_at": now.isoformat(), "reason": "SWITCHED_TO_PAPER"})
        _audit("switch", to="PAPER", remote=remote_addr)
        return True, get_state(now, path), "Paper mode."
    if target != "LIVE":
        return False, get_state(now, path), "Unknown mode."

    def refuse(reason: str, message: str) -> tuple[bool, dict[str, Any], str]:
        _write(path, {"mode": "PAPER", "changed_at": now.isoformat(), "reason": reason})
        _audit("live_refused", reason=reason, remote=remote_addr)
        return False, get_state(now, path), message

    if not live_allowed():
        return refuse("LIVE_NOT_ENABLED", "Live mode is not enabled on this machine. Staying in PAPER.")
    if remote_addr not in {"127.0.0.1", "::1", "::ffff:127.0.0.1"}:
        return refuse("LIVE_ONLY_FROM_THIS_PC", "LIVE can only be armed from this PC, not over the network. Staying in PAPER.")
    if str(confirm or "").strip() != "LIVE":
        return refuse("CONFIRMATION_MISSING", "Type LIVE to confirm. Staying in PAPER.")
    result = (check or broker_check)()
    if not result.get("connected"):
        return refuse("BROKER_NOT_CONNECTED", f"Broker connection failed ({result.get('error', 'unknown')}). Staying in PAPER.")
    _write(path, {"mode": "LIVE", "changed_at": now.isoformat(), "armed_date": now.date().isoformat(), "broker": result,
                  "reason": "LIVE_ARMED_ORDER_ROUTING_NOT_IMPLEMENTED"})
    _audit("live_armed", remote=remote_addr, broker_client=result.get("client"))
    return True, get_state(now, path), "Broker connected. LIVE is armed for today, but order routing is not built yet: no real order will be sent."
