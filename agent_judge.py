"""The AI trading agent's judge: one TAKE / SKIP decision per candidate (read-only; no trading effect; paper only).

Two judges with the same interface:
    MockJudge     a fixed rule, no network, no cost: for tests and for trying the pipeline
    ClaudeJudge   asks Claude (needs the `anthropic` package and ANTHROPIC_API_KEY in the environment / .env)

A decision is {decision: "TAKE"|"SKIP", p_win: 0..1, reason: str}. The judge never raises into the caller: a failed call returns decision "ERROR" and costs nothing, and the daily spend is capped
(APLUS_AGENT_DAILY_USD_CAP, default 2.0). Model: APLUS_AGENT_MODEL (default claude-sonnet-5-5). The agent sees only the packet from agent_packet.py (facts known at entry) and the base rates of
trades BEFORE the day being judged, so a past day can be judged without hindsight.
"""

from __future__ import annotations

import json
import os
import threading
from typing import Any, Mapping

DEFAULT_MODEL = "claude-sonnet-5-5"
PRICES = {                                                  # USD per million tokens: input, output, cache read, cache write (5 min)
    "claude-sonnet-5-5": (2.0, 10.0, 0.10, 2.5), "claude-sonnet-5": (2.0, 10.0, 0.20, 2.5), "claude-haiku-5-5": (0.10, 0.50, 0.01, 0.125),
    "claude-opus-5-5": (4.0, 20.0, 0.20, 5.0), "claude-opus-5": (5.0, 25.0, 0.50, 6.25),
}
SCHEMA = {"type": "object", "properties": {"decision": {"type": "string", "enum": ["TAKE", "SKIP"]}, "p_win": {"type": "number"}, "reason": {"type": "string"}},
          "required": ["decision", "p_win", "reason"], "additionalProperties": False}
SYSTEM = """You are a skeptical risk reviewer for an intraday F&O option-BUYING paper-trading system on NSE (India). For each candidate trade you receive facts known at the moment of entry, as JSON.
Decide TAKE or SKIP and give the probability that the trade ends with a net profit (p_win, between 0 and 1).

How the system works: it buys a call (CE) or a put (PE) on a stock, with a stop-loss about 18% below the entry price, and a ladder that lets winners run; many trades are held to the close.
What goes wrong most: the option never goes into profit and is stopped out (about 4 in 10 trades), wide option bid-ask spreads (every trade pays the spread twice), entering a move that has already
happened, entering before the market has settled (before 09:45), stocks with a quiet opening, and piling into one side or sector.

{base_rates}

Rules: use only the facts in the packet; do not assume anything about what the price does afterwards; if the facts are thin or contradictory, say so and lean to SKIP; most candidates are
ordinary, so p_win should usually be near the base rate unless the facts clearly separate this trade. Keep the reason to 30 words and name the fields that decided it. Answer with JSON only."""


def base_rates_text(stats: Mapping[str, Any] | None) -> str:
    if not stats or not stats.get("n"):
        return "Base rates: not available."
    return (f"Base rates from {stats['n']} earlier trades: {stats['win_pct']:.0f}% ended with a net profit; the average winner made Rs {stats['avg_win']:,.0f} and the average loser lost "
            f"Rs {abs(stats['avg_loss']):,.0f}; {stats['never_pct']:.0f}% never went into profit.")


class MockJudge:
    """A fixed rule (for tests and a free dry run): skip wide spreads, quiet openings and very early entries."""

    name = "mock"
    model = "mock-rule"

    def decide(self, packet: Mapping[str, Any], stats: Mapping[str, Any] | None = None) -> dict[str, Any]:
        reasons = []
        if (packet.get("spread_percent") or 0) > 1.5:
            reasons.append("spread over 1.5%")
        if (packet.get("opening_volume_x") if packet.get("opening_volume_x") is not None else 1.0) < 0.7:
            reasons.append("quiet opening volume")
        if packet.get("entry_minute", "99:99") < "09:45":
            reasons.append("entered before 09:45")
        skip = bool(reasons)
        return {"decision": "SKIP" if skip else "TAKE", "p_win": 0.25 if skip else 0.4, "reason": "; ".join(reasons) or "no red flag", "usd": 0.0, "stop_reason": "mock"}


class ClaudeJudge:
    """Asks Claude. Thread-safe spend tracking against a daily cap."""

    name = "claude"

    def __init__(self, model: str | None = None, daily_cap_usd: float | None = None, client: Any = None) -> None:
        self.model = model or os.getenv("APLUS_AGENT_MODEL", DEFAULT_MODEL)
        self.cap = float(daily_cap_usd if daily_cap_usd is not None else os.getenv("APLUS_AGENT_DAILY_USD_CAP", "2.0"))
        self.spent = 0.0
        self._lock = threading.Lock()
        self._client = client

    @property
    def client(self):
        if self._client is None:
            import anthropic

            self._client = anthropic.Anthropic()               # reads ANTHROPIC_API_KEY; the SDK retries 429 / 5xx twice by itself
        return self._client

    def cost(self, usage: Any) -> float:
        p_in, p_out, p_read, p_write = PRICES.get(self.model, PRICES["claude-opus-5-5"])           # an unknown model is priced like the dearest one
        get = lambda k: float(getattr(usage, k, 0) or 0)                                             # noqa: E731
        return (get("input_tokens") * p_in + get("output_tokens") * p_out + get("cache_read_input_tokens") * p_read + get("cache_creation_input_tokens") * p_write) / 1e6

    def decide(self, packet: Mapping[str, Any], stats: Mapping[str, Any] | None = None) -> dict[str, Any]:
        with self._lock:
            if self.spent >= self.cap:
                return {"decision": "ERROR", "p_win": None, "reason": f"daily cap of ${self.cap:.2f} reached", "usd": 0.0, "stop_reason": "cap"}
        try:
            resp = self.client.messages.create(
                model=self.model, max_tokens=800,
                system=[{"type": "text", "text": SYSTEM.replace("{base_rates}", base_rates_text(stats)), "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": json.dumps(packet, sort_keys=True)}],
                output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
            )
        except Exception as exc:                                  # noqa: BLE001 - a failed call is recorded, never raised into the caller
            return {"decision": "ERROR", "p_win": None, "reason": f"{type(exc).__name__}: {str(exc)[:120]}", "usd": 0.0, "stop_reason": "error"}
        usd = self.cost(getattr(resp, "usage", None))
        with self._lock:
            self.spent += usd
        if getattr(resp, "stop_reason", None) == "refusal":
            return {"decision": "ERROR", "p_win": None, "reason": "the model declined to answer", "usd": usd, "stop_reason": "refusal"}
        text = next((b.text for b in getattr(resp, "content", []) if getattr(b, "type", "") == "text"), "")
        try:
            out = json.loads(text)
            decision = str(out["decision"]).upper()
            p = float(out["p_win"])
            if decision not in ("TAKE", "SKIP") or not 0.0 <= p <= 1.0:
                raise ValueError("out of range")
            return {"decision": decision, "p_win": round(p, 3), "reason": str(out.get("reason", ""))[:300], "usd": usd, "stop_reason": getattr(resp, "stop_reason", "")}
        except (ValueError, KeyError, TypeError):
            return {"decision": "ERROR", "p_win": None, "reason": f"unreadable answer: {text[:80]}", "usd": usd, "stop_reason": getattr(resp, "stop_reason", "")}


def judge(kind: str) -> Any:
    return MockJudge() if kind == "mock" else ClaudeJudge()
