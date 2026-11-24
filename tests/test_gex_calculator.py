from gamma_exposure.gex_calculator import GEXConfig, calculate_snapshot


def _row(side="CE", **overrides):
    row = {
        "captured_at": "2026-11-24T10:00:00+05:30",
        "symbol": "NIFTY",
        "expiry": "2026-12-01",
        "spot": 24000,
        "strike": 24000,
        "side": side,
        "gamma": 0.0005,
        "oi": 1000,
        "oi_change": 100,
        "lot_size": 25,
        "iv": 15,
    }
    row.update(overrides)
    return row


def test_gross_and_scenario_signs_are_separate():
    result = calculate_snapshot([_row("CE"), _row("PE", strike=24100)])
    assert result["status"] == "OK"
    assert result["gross_gex"] > 0
    assert result["call_gex_scenario"] > 0
    assert result["put_gex_scenario"] < 0
    assert result["scenario_net_gex"] == (
        result["call_gex_scenario"] + result["put_gex_scenario"]
    )


def test_oi_change_is_labeled_as_proxy_not_dealer_flow():
    result = calculate_snapshot([_row("CE")])
    assert result["oi_change_gex_proxy"] > 0
    assert "does not identify" in result["flow_note"]


def test_missing_lot_size_is_excluded_not_guessed():
    result = calculate_snapshot([_row(lot_size=None)])
    assert result["status"] == "INSUFFICIENT_DATA"
    assert result["excluded_rows"] == 1


def test_expiry_exposure_is_kept_separate():
    result = calculate_snapshot([
        _row("CE", expiry="2026-12-01"),
        _row("CE", expiry="2026-12-08", strike=24200),
    ])
    assert set(result["expiry_exposure"]) == {"2026-12-01", "2026-12-08"}


def test_invalid_gamma_is_excluded():
    result = calculate_snapshot([_row(gamma=-0.01)])
    assert result["status"] == "INSUFFICIENT_DATA"
