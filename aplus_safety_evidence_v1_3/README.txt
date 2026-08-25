V1.3 fixes the evidence-capsule gap seen after V1.2.

Root cause addressed:
paper_trades_latest can contain trades without trade_id/paper_trade_id. V1.2
silently skipped those trades. V1.3 creates a deterministic synthetic ID from
symbol, direction, entry time, option security ID, strike and expiry.

It also writes data/reports/paper_safety_evidence_status.json so coverage is
visible every cycle.

This does not change scanner or trading logic and adds zero Dhan calls.
