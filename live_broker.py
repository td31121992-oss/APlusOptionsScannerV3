"""Broker layer for live trading: one small interface, a Dhan implementation, and a dry-run implementation that sends nothing.

    OrderRequest / OrderState      what the engine asks for and what the broker reports back (status TRADED / PART_TRADED / PENDING / TRANSIT / CANCELLED / REJECTED / EXPIRED / UNKNOWN)
    DhanBroker(client)             Dhan v2 REST (POST/GET/DELETE /orders, GET /positions, /fundlimit, market quote). Built on core.dhan_client.DhanClient, which already holds the session, headers and retry logic.
    DryRunBroker(quote_fn)         the same interface with no network: orders are logged and filled in memory at their limit price, stop orders wait until trigger() is called. This is what DRY_RUN mode and
                                   the tests use. It never touches the broker.

IMPORTANT: the Dhan response field names below follow Dhan's v2 documentation (orderId, orderStatus, tradedQuantity, averageTradedPrice, netQty, securityId ...) but have NOT been exercised against the
live API by this code. `python live_ctl.py check` makes read-only calls (funds, positions, today's orders, one quote) and prints the raw responses so the shapes can be confirmed before any order is sent.
"""

from __future__ import annotations

import itertools
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Protocol

logger = logging.getLogger(__name__)

SEGMENT = "NSE_FNO"
FINAL = {"TRADED", "CANCELLED", "REJECTED", "EXPIRED"}


@dataclass
class OrderRequest:
    correlation_id: str
    side: str                       # BUY / SELL
    security_id: str
    quantity: int
    order_type: str                 # LIMIT / MARKET / STOP_LOSS
    price: float = 0.0
    trigger_price: float = 0.0
    product: str = "INTRADAY"
    symbol: str = ""


@dataclass
class OrderState:
    order_id: str = ""
    status: str = "UNKNOWN"
    filled_qty: int = 0
    avg_price: float = 0.0
    message: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def final(self) -> bool:
        return self.status in FINAL


class Broker(Protocol):
    name: str

    def place(self, req: OrderRequest) -> OrderState: ...
    def get(self, order_id: str) -> OrderState: ...
    def find_by_correlation(self, correlation_id: str) -> OrderState | None: ...
    def cancel(self, order_id: str) -> OrderState: ...
    def positions(self) -> dict[str, int]: ...
    def funds(self) -> dict[str, Any]: ...
    def quote(self, security_id: str) -> tuple[float, float] | None: ...


def _f(v: Any) -> float:
    try:
        x = float(v)
        return x if x == x else 0.0
    except (TypeError, ValueError):
        return 0.0


def parse_order(d: Mapping[str, Any]) -> OrderState:
    """An OrderState from a Dhan order record (placement response or order-book row)."""
    status = str(d.get("orderStatus") or d.get("status") or "UNKNOWN").upper()
    if status == "PARTIALLY_FILLED":
        status = "PART_TRADED"
    return OrderState(order_id=str(d.get("orderId") or d.get("order_id") or ""), status=status, filled_qty=int(_f(d.get("tradedQuantity") or d.get("filledQty"))),
                      avg_price=_f(d.get("averageTradedPrice") or d.get("avgPrice")), message=str(d.get("omsErrorDescription") or d.get("remarks") or d.get("message") or ""), raw=dict(d))


class DhanBroker:
    name = "dhan"

    def __init__(self, client: Any) -> None:
        self.client = client
        self.cfg = client.config

    def payload(self, req: OrderRequest) -> dict[str, Any]:
        p: dict[str, Any] = {"dhanClientId": self.cfg.client_id, "correlationId": req.correlation_id[:25], "transactionType": req.side, "exchangeSegment": SEGMENT,
                             "productType": req.product, "orderType": req.order_type, "validity": "DAY", "securityId": str(req.security_id), "quantity": int(req.quantity),
                             "price": round(req.price, 2) if req.order_type in ("LIMIT", "STOP_LOSS") else 0, "triggerPrice": round(req.trigger_price, 2) if req.order_type == "STOP_LOSS" else 0,
                             "afterMarketOrder": False}
        return p

    def place(self, req: OrderRequest) -> OrderState:
        body = self.client.place_order(self.payload(req))
        st = parse_order(body if isinstance(body, Mapping) else {})
        if not st.order_id:
            st.status, st.message = "REJECTED", f"no orderId in response: {body!r}"[:300]
        return st

    def _get_json(self, path: str, method: str = "get") -> Any:
        url = f"{self.cfg.api_base_url.rstrip('/')}/{path.lstrip('/')}"
        r = getattr(self.client._session, method)(url, timeout=(self.cfg.connect_timeout_seconds, self.cfg.read_timeout_seconds), verify=self.cfg.verify_tls)
        r.raise_for_status()
        return r.json() if r.text.strip() else {}

    def get(self, order_id: str) -> OrderState:
        d = self._get_json(f"orders/{order_id}")
        if isinstance(d, list):
            d = d[0] if d else {}
        return parse_order(d)

    def find_by_correlation(self, correlation_id: str) -> OrderState | None:
        rows = self._get_json("orders")
        for d in rows if isinstance(rows, list) else []:
            if str(d.get("correlationId") or "") == correlation_id[:25]:
                return parse_order(d)
        return None

    def cancel(self, order_id: str) -> OrderState:
        d = self._get_json(f"orders/{order_id}", method="delete")
        st = parse_order(d if isinstance(d, Mapping) else {})
        st.order_id = st.order_id or order_id
        return st

    def positions(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for p in self.client.get_positions():
            if str(p.get("exchangeSegment") or SEGMENT) == SEGMENT:
                out[str(p.get("securityId"))] = out.get(str(p.get("securityId")), 0) + int(_f(p.get("netQty")))
        return {k: v for k, v in out.items() if v}

    def funds(self) -> dict[str, Any]:
        return self.client.get_fund_limits()

    def quote(self, security_id: str) -> tuple[float, float] | None:
        """(best bid, best ask) from Dhan's market quote, or None when the response has no usable depth."""
        q = self.client.get_quote(str(security_id), SEGMENT)
        d = q
        for key in ("data", SEGMENT, str(security_id)):
            if isinstance(d, Mapping) and key in d:
                d = d[key]
        if not isinstance(d, Mapping):
            return None
        depth = d.get("depth") or {}
        try:
            bid, ask = float(depth["buy"][0]["price"]), float(depth["sell"][0]["price"])
        except (KeyError, IndexError, TypeError, ValueError):
            bid, ask = _f(d.get("best_bid_price") or d.get("bestBid")), _f(d.get("best_ask_price") or d.get("bestAsk"))
        return (bid, ask) if bid > 0 and ask > 0 else None


class DryRunBroker:
    """Same interface, nothing sent. LIMIT orders fill at once at their price (or at the quote when marketable-looking), STOP_LOSS orders stay PENDING until trigger(order_id) is called."""

    name = "dry-run"

    def __init__(self, quote_fn: Callable[[str], tuple[float, float] | None] | None = None) -> None:
        self.quote_fn = quote_fn or (lambda sid: None)
        self.orders: dict[str, OrderState] = {}
        self.requests: dict[str, OrderRequest] = {}
        self.by_corr: dict[str, str] = {}
        self._ids = itertools.count(1)
        self.net: dict[str, int] = {}
        self.sent: list[OrderRequest] = []              # everything "sent", for logs and tests

    def place(self, req: OrderRequest) -> OrderState:
        oid = f"DRY{next(self._ids):06d}"
        self.sent.append(req)
        self.requests[oid] = req
        self.by_corr[req.correlation_id] = oid
        if req.order_type == "STOP_LOSS":
            st = OrderState(oid, "PENDING", 0, 0.0, "dry-run stop waiting")
        else:
            px = req.price
            if req.order_type == "MARKET" or px <= 0:
                q = self.quote_fn(req.security_id)
                px = (q[1] if req.side == "BUY" else q[0]) if q else req.price
            st = OrderState(oid, "TRADED", req.quantity, px, "dry-run fill")
            self.net[req.security_id] = self.net.get(req.security_id, 0) + (req.quantity if req.side == "BUY" else -req.quantity)
        self.orders[oid] = st
        return st

    def get(self, order_id: str) -> OrderState:
        return self.orders.get(order_id, OrderState(order_id, "UNKNOWN"))

    def find_by_correlation(self, correlation_id: str) -> OrderState | None:
        oid = self.by_corr.get(correlation_id)
        return self.orders.get(oid) if oid else None

    def cancel(self, order_id: str) -> OrderState:
        st = self.orders.get(order_id)
        if st is None:
            return OrderState(order_id, "UNKNOWN")
        if not st.final:
            st.status = "CANCELLED"
        return st

    def trigger(self, order_id: str, price: float) -> OrderState:
        """Test / simulation hook: the stop order's trigger was hit and it filled at `price`."""
        st, req = self.orders[order_id], self.requests[order_id]
        st.status, st.filled_qty, st.avg_price = "TRADED", req.quantity, price
        self.net[req.security_id] = self.net.get(req.security_id, 0) - req.quantity
        return st

    def positions(self) -> dict[str, int]:
        return {k: v for k, v in self.net.items() if v}

    def funds(self) -> dict[str, Any]:
        return {"availabelBalance": 10_000_000.0, "dry_run": True}

    def quote(self, security_id: str) -> tuple[float, float] | None:
        return self.quote_fn(security_id)
