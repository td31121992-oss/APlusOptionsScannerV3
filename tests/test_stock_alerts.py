from stock_alerts import evaluate_rows, rule_catalog


def test_current_market_watch_rules():
    rows = [{
        "symbol": "RELIANCE",
        "ltp": 2505,
        "day_high": 2505,
        "day_low": 2440,
        "from_open_pct": 1.42,
    }]
    alerts = evaluate_rows(rows)
    ids = {a["rule_id"] for a in alerts}
    assert "day_high" in ids
    assert "strong_up" in ids
    assert all(a["telegram"] is False for a in alerts)


def test_unavailable_long_term_rules_do_not_fabricate():
    rows = [{"symbol": "SBIN", "ltp": 900, "from_open_pct": 0.3}]
    alerts = evaluate_rows(rows)
    assert not any(a["rule_id"] in {"range_5d_bo", "range_52w_bo", "dma_200_bo"} for a in alerts)
    catalog = {x["rule_id"]: x for x in rule_catalog(rows)}
    assert catalog["range_5d_bo"]["available"] is False
    assert catalog["day_high"]["available"] is True
