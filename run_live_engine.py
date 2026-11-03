"""Start the live execution engine (see live_engine.py). OFF unless APLUS_LIVE_MODE is DRY_RUN or LIVE.

    python run_live_engine.py            run until 15:35 (one process a day; it exits by itself)

DRY_RUN needs nothing else. LIVE also needs today's arming file (`python live_ctl.py arm`) and the Dhan credentials the scanner already uses (.env). The engine reads the paper journal, so the scanner
must be running as usual; the engine never starts, stops or changes the scanner.
"""

from __future__ import annotations

import json
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LOCK_PORT = 8791


def make_broker(cfg, root: Path):
    from live_broker import DhanBroker, DryRunBroker

    def journal_quote(sid: str):
        try:
            for t in json.loads(root.joinpath("data", "intraday_movement", "paper_trade_journal.json").read_text(encoding="utf-8")).get("trades") or []:
                if str(t.get("option_security_id")) == str(sid) and str(t.get("status")).upper() == "OPEN":
                    bid, ask = float(t.get("bid") or 0), float(t.get("ask") or 0)
                    return (bid, ask) if bid > 0 and ask > 0 else None
        except (OSError, ValueError):
            pass
        return None

    dhan = None
    try:
        from config import AppConfig
        from core.dhan_client import DhanClient

        dhan = DhanBroker(DhanClient(AppConfig.from_env().dhan))
    except Exception as exc:                                    # noqa: BLE001
        if cfg.mode == "LIVE":
            raise SystemExit(f"cannot start LIVE without a working Dhan client: {type(exc).__name__}: {exc}")
        print(f"dry-run: no Dhan client ({type(exc).__name__}); quotes come from the paper journal")
    if cfg.mode == "LIVE":
        return dhan
    return DryRunBroker(quote_fn=lambda sid: (dhan.quote(sid) if dhan is not None else None) or journal_quote(sid))


def make_notifier(root: Path):
    try:
        import time

        from telegram_notifier import TelegramPaperTradeNotifier

        n = TelegramPaperTradeNotifier(state_dir=root / "data" / "live")
        return (lambda text: n._send(f"live-{time.time()}", text)) if n.configured else None
    except Exception:                                           # noqa: BLE001
        return None


def main() -> int:
    sys.path.insert(0, str(ROOT))
    from live_engine import LiveConfig, LiveEngine

    cfg = LiveConfig.from_env()
    if cfg.mode == "OFF":
        print("APLUS_LIVE_MODE is OFF: nothing to do")
        return 0
    lock = socket.socket()
    try:
        lock.bind(("127.0.0.1", LOCK_PORT))
    except OSError:
        print("another live engine is already running")
        return 1
    engine = LiveEngine(ROOT, make_broker(cfg, ROOT), cfg, notify=make_notifier(ROOT))
    print(f"live engine: mode {cfg.mode}, lots cap {cfg.lots_cap}, daily loss cap {cfg.max_daily_loss:.0f}, armed {engine.armed()}")
    engine.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
