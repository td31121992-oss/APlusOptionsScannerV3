"""Upstox live market feed (websocket, protobuf v3) that looks like the Dhan MarketFeed the recorders already use. DATA ONLY: never touches a trade.

The recorders (tick_recorder.py, option_tick_recorder.py) ask their feed for three things: start(), close_connection() and subscribe_symbols(); they receive
on_message(feed, packet) with packets in the dict shape the dhanhq library produced. This gives them the same three calls and the same packets from Upstox, so
none of their recording, detector or tracker code changes:

    {"type": "Full Data", "exchange_segment": "NSE_EQ", "security_id": "2885", "LTP", "LTQ", "LTT" (HH:MM:SS), "volume", "avg_price", "OI",
     "total_buy_quantity", "total_sell_quantity", "depth": [{"bid_quantity", "bid_price", "ask_quantity", "ask_price"} x5]}
    {"type": "Ticker Data", "exchange_segment": 0, "security_id": 13, "LTP"}        for indices        {"type": "Previous Close", ..., "prev_close"}

Instruments are (segment, security_id, mode) with the segment names core/upstox_client.py uses (NSE_EQ, NSE_FNO, IDX_I) and mode "full" or "ticker". The Dhan
security id is also Upstox's exchange token, so the recorders' id lists work unchanged. If the connection drops the feed reconnects itself (a fresh authorisation each
time, because the websocket address is single-use) and subscribes everything again; it never gives up before close_connection().

Protobuf is decoded by hand (no protobuf library is installed): the wire format is tiny and the field numbers are those of Upstox's MarketDataFeedV3.proto.
"""

from __future__ import annotations

import json
import logging
import os
import struct
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterable, Iterator, Mapping, Sequence

logger = logging.getLogger(__name__)
IST = timezone(timedelta(hours=5, minutes=30))
AUTHORIZE_URL = "https://api.upstox.com/v3/feed/market-data-feed/authorize"
SUBSCRIBE_CHUNK = 100

# ---------------------------------------------------------------------------------------------------------------- protobuf (wire format only)
# message name -> {field number: (name, kind)}; kind is a message name, "rep:<message>", "map:<message>", "string" or "" (a number: the wire type tells int from double)
SCHEMA: dict[str, dict[int, tuple[str, str]]] = {
    "FeedResponse": {1: ("type", ""), 2: ("feeds", "map:Feed"), 3: ("currentTs", ""), 4: ("marketInfo", "MarketInfo")},
    "MarketInfo": {1: ("segmentStatus", "map:")},
    "Feed": {1: ("ltpc", "LTPC"), 2: ("fullFeed", "FullFeed"), 3: ("firstLevelWithGreeks", "FirstLevelWithGreeks"), 4: ("requestMode", "")},
    "FullFeed": {1: ("marketFF", "MarketFullFeed"), 2: ("indexFF", "IndexFullFeed")},
    "MarketFullFeed": {1: ("ltpc", "LTPC"), 2: ("marketLevel", "MarketLevel"), 3: ("optionGreeks", "OptionGreeks"), 4: ("marketOHLC", "MarketOHLC"),
                       5: ("atp", ""), 6: ("vtt", ""), 7: ("oi", ""), 8: ("iv", ""), 9: ("tbq", ""), 10: ("tsq", "")},
    "IndexFullFeed": {1: ("ltpc", "LTPC"), 2: ("marketOHLC", "MarketOHLC")},
    "FirstLevelWithGreeks": {1: ("ltpc", "LTPC"), 2: ("firstDepth", "Quote"), 3: ("optionGreeks", "OptionGreeks"), 4: ("vtt", ""), 5: ("oi", ""), 6: ("iv", "")},
    "LTPC": {1: ("ltp", ""), 2: ("ltt", ""), 3: ("ltq", ""), 4: ("cp", "")},
    "MarketLevel": {1: ("bidAskQuote", "rep:Quote")},
    "Quote": {1: ("bidQ", ""), 2: ("bidP", ""), 3: ("askQ", ""), 4: ("askP", "")},
    "OptionGreeks": {1: ("delta", ""), 2: ("theta", ""), 3: ("gamma", ""), 4: ("vega", ""), 5: ("rho", "")},
    "MarketOHLC": {1: ("ohlc", "rep:OHLC")},
    "OHLC": {1: ("interval", "string"), 2: ("open", ""), 3: ("high", ""), 4: ("low", ""), 5: ("close", ""), 6: ("vol", ""), 7: ("ts", "")},
}


def _varint(buf: bytes, i: int) -> tuple[int, int]:
    shift = result = 0
    while True:
        b = buf[i]
        i += 1
        result |= (b & 0x7F) << shift
        if not b & 0x80:
            return result, i
        shift += 7


def _wire(buf: bytes) -> Iterator[tuple[int, int, Any]]:
    i, n = 0, len(buf)
    while i < n:
        key, i = _varint(buf, i)
        field, wire = key >> 3, key & 7
        if wire == 0:
            value, i = _varint(buf, i)
        elif wire == 1:
            value, i = struct.unpack("<d", buf[i:i + 8])[0], i + 8
        elif wire == 2:
            length, i = _varint(buf, i)
            value, i = buf[i:i + length], i + length
        elif wire == 5:
            value, i = struct.unpack("<f", buf[i:i + 4])[0], i + 4
        else:
            raise ValueError(f"unsupported wire type {wire}")
        yield field, wire, value


def decode(message: str, buf: bytes) -> dict[str, Any]:
    """Decode `buf` as the named message into a dict (repeated fields -> lists, maps -> dicts). Unknown fields are skipped."""
    schema = SCHEMA.get(message, {})
    out: dict[str, Any] = {}
    for field, wire, value in _wire(buf):
        spec = schema.get(field)
        if spec is None:
            continue
        name, kind = spec
        if wire != 2 or kind == "":
            out[name] = value
        elif kind == "string":
            out[name] = value.decode("utf-8", "replace")
        elif kind.startswith("map:"):
            entry_type = kind[4:]
            key = ""
            val: Any = None
            for f2, w2, v2 in _wire(value):
                if f2 == 1 and w2 == 2:
                    key = v2.decode("utf-8", "replace")
                elif f2 == 2:
                    val = decode(entry_type, v2) if (entry_type and w2 == 2) else v2
            out.setdefault(name, {})[key] = val
        elif kind.startswith("rep:"):
            out.setdefault(name, []).append(decode(kind[4:], value))
        else:
            out[name] = decode(kind, value)
    return out


# ---------------------------------------------------------------------------------------------------------------- packets in the Dhan shape
def _f(v: Any) -> float:
    try:
        x = float(v)
        return x if x == x else 0.0
    except (TypeError, ValueError):
        return 0.0


def _hms(ms: Any) -> str:
    value = _f(ms)
    if value <= 0:
        return ""
    if value > 1e11:                                       # epoch milliseconds
        value /= 1000.0
    return datetime.fromtimestamp(value, IST).strftime("%H:%M:%S")


def packets_from_response(resp: Mapping[str, Any], resolve: Callable[[str], tuple[str, str] | None], sent_prev_close: set[str] | None = None) -> list[dict[str, Any]]:
    """Dhan-shaped packets from one decoded FeedResponse. `resolve(instrument_key)` -> (segment, security_id) or None for a key we did not ask for."""
    out: list[dict[str, Any]] = []
    for key, feed in (resp.get("feeds") or {}).items():
        hit = resolve(key)
        if hit is None or not isinstance(feed, Mapping):
            continue
        segment, sid = hit
        full = feed.get("fullFeed") or {}
        mff, iff = full.get("marketFF"), full.get("indexFF")
        first = feed.get("firstLevelWithGreeks")
        ltpc = (mff or iff or first or {}).get("ltpc") or feed.get("ltpc") or {}
        if not ltpc:
            continue
        if segment == "IDX_I":
            idx = int(sid) if str(sid).isdigit() else sid
            out.append({"type": "Ticker Data", "exchange_segment": 0, "security_id": idx, "LTP": _f(ltpc.get("ltp")), "LTT": _hms(ltpc.get("ltt"))})
            if sent_prev_close is not None and key not in sent_prev_close and _f(ltpc.get("cp")) > 0:
                sent_prev_close.add(key)
                out.append({"type": "Previous Close", "exchange_segment": 0, "security_id": idx, "prev_close": _f(ltpc.get("cp"))})
            continue
        packet: dict[str, Any] = {"type": "Full Data" if (mff or first) else "Ticker Data", "exchange_segment": segment, "security_id": str(sid),
                                  "LTP": _f(ltpc.get("ltp")), "LTQ": int(_f(ltpc.get("ltq"))), "LTT": _hms(ltpc.get("ltt")), "prev_close": _f(ltpc.get("cp"))}
        if mff:
            levels = (mff.get("marketLevel") or {}).get("bidAskQuote") or []
            packet.update({"volume": int(_f(mff.get("vtt"))), "avg_price": _f(mff.get("atp")), "OI": int(_f(mff.get("oi"))),
                           "total_buy_quantity": int(_f(mff.get("tbq"))), "total_sell_quantity": int(_f(mff.get("tsq"))),
                           "depth": [{"bid_quantity": int(_f(q.get("bidQ"))), "bid_price": _f(q.get("bidP")), "ask_quantity": int(_f(q.get("askQ"))), "ask_price": _f(q.get("askP"))}
                                     for q in levels[:5]]})
        elif first:
            q = first.get("firstDepth") or {}
            packet.update({"volume": int(_f(first.get("vtt"))), "OI": int(_f(first.get("oi"))),
                           "depth": [{"bid_quantity": int(_f(q.get("bidQ"))), "bid_price": _f(q.get("bidP")), "ask_quantity": int(_f(q.get("askQ"))), "ask_price": _f(q.get("askP"))}]})
        out.append(packet)
    return out


# ---------------------------------------------------------------------------------------------------------------- the feed
class UpstoxMarketFeed:
    """Same surface as dhanhq.MarketFeed for the recorders: start(), close_connection(), subscribe_symbols([(segment, security_id, mode)])."""

    def __init__(self, instruments: Iterable[Sequence[Any]], on_message: Callable[[Any, Any], None], on_error: Callable[[Any, Exception], None] | None = None,
                 client: Any = None, token: str | None = None, connect: Callable[[str], Any] | None = None) -> None:
        if client is None:
            from core.upstox_client import UpstoxClient

            client = UpstoxClient(token=token)
        self.client = client
        self.token = token or client.token
        self.on_message, self.on_error = on_message, on_error
        self._connect = connect
        self._wanted: dict[str, str] = {}                  # instrument key -> mode
        self._lock = threading.Lock()
        self._ws: Any = None
        self._thread: threading.Thread | None = None
        self._closed = threading.Event()
        self._prev_close_sent: set[str] = set()
        self.packets = 0
        self.reconnects = 0
        self.connected = False
        self.last_error = ""
        self.client._build_maps()
        self._add(instruments)

    # ----------------------------------------------------------------------- instruments
    @staticmethod
    def _mode(mode: Any) -> str:
        m = str(mode).strip().lower()
        return "ltpc" if m in {"ticker", "ltpc", "15", "ticker data"} else "full"

    def _add(self, instruments: Iterable[Sequence[Any]]) -> dict[str, str]:
        fresh: dict[str, str] = {}
        for segment, sid, mode in instruments:
            seg = {"0": "IDX_I", "idx": "IDX_I", "idx_i": "IDX_I", "1": "NSE_EQ", "nse": "NSE_EQ", "2": "NSE_FNO", "nse_fno": "NSE_FNO"}.get(str(segment).strip().lower(), str(segment).upper())
            key = self.client.instrument_key(seg, sid)
            if not key:
                self._error(RuntimeError(f"no Upstox instrument for {seg}:{sid}"))
                continue
            with self._lock:
                if self._wanted.get(key) != self._mode(mode):
                    self._wanted[key] = self._mode(mode)
                    fresh[key] = self._mode(mode)
        return fresh

    def _resolve(self, key: str) -> tuple[str, str] | None:
        return self.client._reverse.get(key)

    def _error(self, exc: Exception) -> None:
        self.last_error = f"{type(exc).__name__}: {exc}"
        if self.on_error is not None:
            try:
                self.on_error(self, exc)
            except Exception:                              # noqa: BLE001
                pass

    # ----------------------------------------------------------------------- connection
    def _authorize(self) -> str:
        import requests

        r = requests.get(AUTHORIZE_URL, headers={"Accept": "application/json", "Authorization": f"Bearer {self.token}"}, timeout=15)
        if r.status_code != 200:
            raise RuntimeError(f"Upstox feed authorise HTTP {r.status_code}: {r.text[:120]}")
        data = (r.json().get("data") or {})
        uri = data.get("authorized_redirect_uri") or data.get("authorizedRedirectUri")
        if not uri:
            raise RuntimeError("Upstox feed authorise returned no address")
        return str(uri)

    def _open(self, uri: str) -> Any:
        if self._connect is not None:
            return self._connect(uri)
        from websockets.sync.client import connect

        return connect(uri, open_timeout=15, close_timeout=3, max_size=None, ping_interval=20, ping_timeout=30)

    def _send_sub(self, ws: Any, method: str, keys: Sequence[str], mode: str) -> None:
        for i in range(0, len(keys), SUBSCRIBE_CHUNK):
            payload = {"guid": uuid.uuid4().hex[:20], "method": method, "data": {"mode": mode, "instrumentKeys": list(keys[i:i + SUBSCRIBE_CHUNK])}}
            ws.send(json.dumps(payload).encode("utf-8"))      # Upstox wants the JSON command as a binary frame
            if i + SUBSCRIBE_CHUNK < len(keys):
                time.sleep(0.15)

    def _subscribe_all(self, ws: Any) -> None:
        with self._lock:
            by_mode: dict[str, list[str]] = {}
            for key, mode in self._wanted.items():
                by_mode.setdefault(mode, []).append(key)
        for mode, keys in by_mode.items():
            self._send_sub(ws, "sub", keys, mode)

    def _run(self) -> None:
        backoff = 2.0
        while not self._closed.is_set():
            try:
                ws = self._open(self._authorize())
                self._ws = ws
                self.connected = True
                backoff = 2.0
                self._subscribe_all(ws)
                while not self._closed.is_set():
                    try:
                        raw = ws.recv(timeout=30)
                    except TimeoutError:
                        continue
                    if isinstance(raw, str):                          # text frames carry nothing we need
                        continue
                    self._handle(raw)
            except Exception as exc:                                  # noqa: BLE001 - connection lost or refused: report, wait, reconnect
                if self._closed.is_set():
                    break
                self.connected = False
                self._error(exc)
            finally:
                try:
                    if self._ws is not None:
                        self._ws.close()
                except Exception:                                     # noqa: BLE001
                    pass
                self._ws = None
                self.connected = False
            if self._closed.is_set():
                break
            self.reconnects += 1
            self._closed.wait(backoff)
            backoff = min(backoff * 2.0, 30.0)

    def _handle(self, raw: bytes) -> None:
        try:
            resp = decode("FeedResponse", raw)
            packets = packets_from_response(resp, self._resolve, self._prev_close_sent)
        except Exception as exc:                                      # noqa: BLE001 - one bad frame must not drop the connection
            self._error(exc)
            return
        for packet in packets:
            self.packets += 1
            try:
                self.on_message(self, packet)
            except Exception as exc:                                  # noqa: BLE001
                self._error(exc)

    # ----------------------------------------------------------------------- the three calls the recorders use
    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._closed.clear()
        self._thread = threading.Thread(target=self._run, name="upstox-feed", daemon=True)
        self._thread.start()

    def subscribe_symbols(self, instruments: Iterable[Sequence[Any]]) -> None:
        fresh = self._add(instruments)
        ws = self._ws
        if ws is None or not fresh:
            return                                                    # not connected yet: _subscribe_all sends everything on connect
        by_mode: dict[str, list[str]] = {}
        for key, mode in fresh.items():
            by_mode.setdefault(mode, []).append(key)
        for mode, keys in by_mode.items():
            self._send_sub(ws, "sub", keys, mode)

    def close_connection(self) -> None:
        self._closed.set()
        ws = self._ws
        if ws is not None:
            try:
                ws.close()
            except Exception:                                         # noqa: BLE001
                pass
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=5)


def feed_provider() -> str:
    """UPSTOX when the data provider switch says so (the same APLUS_DATA_PROVIDER the scanner uses), otherwise DHAN. Reads the project's .env first: the recorders
    start as plain scheduled tasks, so nothing else has loaded it yet (without this they silently stayed on Dhan)."""
    try:
        from pathlib import Path

        from dotenv import load_dotenv

        load_dotenv(Path(__file__).resolve().parent / ".env")          # does not override variables already set
    except Exception:                                                 # noqa: BLE001
        pass
    return "UPSTOX" if os.getenv("APLUS_DATA_PROVIDER", "DHAN").strip().upper() == "UPSTOX" else "DHAN"
