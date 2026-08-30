"""Unit tests for MarketKlinePricingAdapter."""

import random
from decimal import Decimal

import pytest

from simulator.domain.models import ObservationRecord
from simulator.infrastructure.adapters.market_pricing import MarketKlinePricingAdapter


def _make_kline_obs(
    obs_id: str,
    series_id: str,
    event_time: str,
    knowledge_time: str,
    open_p: str,
    close_p: str,
    revision: int = 1,
) -> ObservationRecord:
    return ObservationRecord(
        observation_id=obs_id,
        snapshot_id="ds-snap_binance_spot_1d_test",
        series_id=series_id,
        event_time=event_time,
        knowledge_time=knowledge_time,
        revision=revision,
        payload={
            "open": open_p,
            "high": "70000.00",
            "low": "60000.00",
            "close": close_p,
            "volume": "1000.00",
            "quote_volume": "65000000.00",
            "count": 50000,
            "taker_buy_volume": "500.00",
            "taker_buy_quote_volume": "32500000.00",
        },
    )


def test_market_pricing_valuation_mark_latest_eligible_close() -> None:
    adapter = MarketKlinePricingAdapter()

    # Day 1: 2026-08-01 (published 2026-08-03T00:00:00Z)
    obs_day1 = _make_kline_obs(
        obs_id="obs_btc_d1",
        series_id="BTC_USDT_PRICE_1D",
        event_time="2026-08-01T00:00:00Z",
        knowledge_time="2026-08-03T00:00:00Z",
        open_p="60000.00",
        close_p="62000.00",
    )
    # Day 2: 2026-08-02 (published 2026-08-04T00:00:00Z)
    obs_day2 = _make_kline_obs(
        obs_id="obs_btc_d2",
        series_id="BTC_USDT_PRICE_1D",
        event_time="2026-08-02T00:00:00Z",
        knowledge_time="2026-08-04T00:00:00Z",
        open_p="62000.00",
        close_p="65000.00",
    )
    # Day 3 (future bar for execution): 2026-08-05 (published 2026-08-05T00:00:00Z)
    obs_day3 = _make_kline_obs(
        obs_id="obs_btc_d3",
        series_id="BTC_USDT_PRICE_1D",
        event_time="2026-08-05T00:00:00Z",
        knowledge_time="2026-08-05T00:00:00Z",
        open_p="65500.00",
        close_p="68000.00",
    )

    all_obs = (obs_day1, obs_day2, obs_day3)

    # Cutoff at 2026-08-04T00:00:00Z (when Day 2 close is known)
    cutoff = "2026-08-04T00:00:00Z"
    effective_time = "2026-08-05T00:00:00Z"

    res = adapter.resolve_pricing(
        all_observations=all_obs,
        knowledge_cutoff=cutoff,
        effective_time=effective_time,
        valuation_resources=("BTC", "USDT"),
        execution_resources=("BTC",),
        reference_resource_id="USDT",
    )

    assert res.is_valid
    assert len(res.rejection_reasons) == 0

    # USDT is reference resource
    assert res.valuation_marks["USDT"].price == Decimal("1.00")
    assert "USDT" not in res.execution_prices

    # BTC valuation mark is Day 2 close (65000.00), NOT Day 1 close or Day 3 close
    btc_mark = res.valuation_marks["BTC"]
    assert btc_mark.price == Decimal("65000.00")
    assert btc_mark.observation_id == "obs_btc_d2"
    assert btc_mark.event_time == "2026-08-02T00:00:00Z"
    assert btc_mark.staleness_seconds == Decimal("172800")  # 2 days (48 hours)

    # BTC execution price is Day 3 open (65500.00), NOT Day 2 close (65000.00)
    btc_exec = res.execution_prices["BTC"]
    assert btc_exec.price == Decimal("65500.00")
    assert btc_exec.observation_id == "obs_btc_d3"
    assert btc_exec.event_time == "2026-08-05T00:00:00Z"
    assert btc_exec.staleness_seconds == Decimal("0")


def test_market_pricing_revision_handling() -> None:
    adapter = MarketKlinePricingAdapter()

    # Day 1 initial: revision 1
    obs_rev1 = _make_kline_obs(
        obs_id="obs_eth_r1",
        series_id="ETH_USDT_PRICE_1D",
        event_time="2026-08-01T00:00:00Z",
        knowledge_time="2026-08-03T00:00:00Z",
        open_p="3000.00",
        close_p="3100.00",
        revision=1,
    )
    # Day 1 revised: revision 2 published before cutoff
    obs_rev2 = _make_kline_obs(
        obs_id="obs_eth_r2",
        series_id="ETH_USDT_PRICE_1D",
        event_time="2026-08-01T00:00:00Z",
        knowledge_time="2026-08-03T12:00:00Z",
        open_p="3000.00",
        close_p="3150.00",
        revision=2,
    )
    # Future bar
    obs_fut = _make_kline_obs(
        obs_id="obs_eth_fut",
        series_id="ETH_USDT_PRICE_1D",
        event_time="2026-08-04T00:00:00Z",
        knowledge_time="2026-08-04T00:00:00Z",
        open_p="3200.00",
        close_p="3300.00",
        revision=1,
    )

    all_obs = (obs_rev1, obs_rev2, obs_fut)
    cutoff = "2026-08-03T18:00:00Z"
    effective_time = "2026-08-04T00:00:00Z"

    res = adapter.resolve_pricing(
        all_observations=all_obs,
        knowledge_cutoff=cutoff,
        effective_time=effective_time,
        valuation_resources=("ETH", "USDT"),
        execution_resources=("ETH",),
        reference_resource_id="USDT",
    )

    assert res.is_valid
    # Mark selects revision 2 close (3150.00)
    assert res.valuation_marks["ETH"].price == Decimal("3150.00")
    assert res.valuation_marks["ETH"].revision == 2


def test_market_pricing_permutation_invariance() -> None:
    adapter = MarketKlinePricingAdapter()

    obs_list = [
        _make_kline_obs(
            f"obs_sol_{i}",
            "SOL_USDT_PRICE_1D",
            f"2026-08-0{i}T00:00:00Z",
            f"2026-08-0{i + 2}T00:00:00Z",
            f"{150 + i}.00",
            f"{155 + i}.00",
        )
        for i in range(1, 5)
    ]

    cutoff = "2026-08-04T00:00:00Z"
    effective_time = "2026-08-05T00:00:00Z"

    base_res = adapter.resolve_pricing(
        all_observations=tuple(obs_list),
        knowledge_cutoff=cutoff,
        effective_time=effective_time,
        valuation_resources=("SOL", "USDT"),
        execution_resources=("SOL",),
        reference_resource_id="USDT",
    )

    rng = random.Random(42)
    for _ in range(10):
        shuffled = list(obs_list)
        rng.shuffle(shuffled)
        perm_res = adapter.resolve_pricing(
            all_observations=tuple(shuffled),
            knowledge_cutoff=cutoff,
            effective_time=effective_time,
            valuation_resources=("SOL", "USDT"),
            execution_resources=("SOL",),
            reference_resource_id="USDT",
        )
        assert perm_res == base_res


def test_market_pricing_missing_valuation_mark() -> None:
    adapter = MarketKlinePricingAdapter()

    # Only future observation exists
    obs_fut = _make_kline_obs(
        obs_id="obs_bnb_fut",
        series_id="BNB_USDT_PRICE_1D",
        event_time="2026-08-02T00:00:00Z",
        knowledge_time="2026-08-03T00:00:00Z",
        open_p="550.00",
        close_p="560.00",
    )

    res = adapter.resolve_pricing(
        all_observations=(obs_fut,),
        knowledge_cutoff="2026-08-01T00:00:00Z",
        effective_time="2026-08-03T00:00:00Z",
        valuation_resources=("BNB", "USDT"),
        execution_resources=("BNB",),
        reference_resource_id="USDT",
    )

    assert not res.is_valid
    assert len(res.rejection_reasons) == 1
    assert res.rejection_reasons[0].code == "MISSING_VALUATION_MARK"


def test_market_pricing_missing_execution_price() -> None:
    adapter = MarketKlinePricingAdapter()

    # Only past observation exists
    obs_past = _make_kline_obs(
        obs_id="obs_bnb_past",
        series_id="BNB_USDT_PRICE_1D",
        event_time="2026-08-01T00:00:00Z",
        knowledge_time="2026-08-02T00:00:00Z",
        open_p="540.00",
        close_p="550.00",
    )

    res = adapter.resolve_pricing(
        all_observations=(obs_past,),
        knowledge_cutoff="2026-08-02T00:00:00Z",
        effective_time="2026-08-03T00:00:00Z",
        valuation_resources=("BNB", "USDT"),
        execution_resources=("BNB",),
        reference_resource_id="USDT",
    )

    assert not res.is_valid
    assert len(res.rejection_reasons) == 1
    assert res.rejection_reasons[0].code == "MISSING_EXECUTION_PRICE"


def test_market_pricing_does_not_require_execution_price_for_held_only_resource() -> None:
    adapter = MarketKlinePricingAdapter()
    obs_past = _make_kline_obs(
        obs_id="obs_bnb_mark",
        series_id="BNB_USDT_PRICE_1D",
        event_time="2026-08-01T00:00:00Z",
        knowledge_time="2026-08-02T00:00:00Z",
        open_p="540.00",
        close_p="550.00",
    )

    result = adapter.resolve_pricing(
        all_observations=(obs_past,),
        knowledge_cutoff="2026-08-02T00:00:00Z",
        effective_time="2026-08-02T00:00:00Z",
        valuation_resources=("BNB", "USDT"),
        execution_resources=(),
        reference_resource_id="USDT",
    )

    assert result.is_valid
    assert result.valuation_marks["BNB"].price == Decimal("550.00")
    assert result.execution_prices == {}


def test_price_resolution_result_copies_mutable_input_maps() -> None:
    adapter = MarketKlinePricingAdapter()
    result = adapter.resolve_pricing(
        all_observations=(),
        knowledge_cutoff="2026-08-02T00:00:00Z",
        effective_time="2026-08-02T00:00:00Z",
        valuation_resources=("USDT",),
        execution_resources=(),
        reference_resource_id="USDT",
    )

    with pytest.raises(TypeError):
        result.valuation_marks["USDT"] = result.valuation_marks["USDT"]


def test_market_pricing_unsupported_resource() -> None:
    adapter = MarketKlinePricingAdapter()

    res = adapter.resolve_pricing(
        all_observations=(),
        knowledge_cutoff="2026-08-02T00:00:00Z",
        effective_time="2026-08-03T00:00:00Z",
        valuation_resources=("UNKNOWN_TOKEN", "USDT"),
        execution_resources=("UNKNOWN_TOKEN",),
        reference_resource_id="USDT",
    )

    assert not res.is_valid
    assert len(res.rejection_reasons) == 1
    assert res.rejection_reasons[0].code == "UNSUPPORTED_RESOURCE"


def test_market_pricing_malformed_and_non_positive_prices() -> None:
    adapter = MarketKlinePricingAdapter()

    # Observation with zero close price
    obs_zero = _make_kline_obs(
        obs_id="obs_zero",
        series_id="BTC_USDT_PRICE_1D",
        event_time="2026-08-01T00:00:00Z",
        knowledge_time="2026-08-02T00:00:00Z",
        open_p="60000.00",
        close_p="0.00",
    )
    obs_fut = _make_kline_obs(
        obs_id="obs_fut",
        series_id="BTC_USDT_PRICE_1D",
        event_time="2026-08-02T00:00:00Z",
        knowledge_time="2026-08-03T00:00:00Z",
        open_p="-500.00",
        close_p="62000.00",
    )

    res = adapter.resolve_pricing(
        all_observations=(obs_zero, obs_fut),
        knowledge_cutoff="2026-08-02T00:00:00Z",
        effective_time="2026-08-03T00:00:00Z",
        valuation_resources=("BTC", "USDT"),
        execution_resources=("BTC",),
        reference_resource_id="USDT",
    )

    assert not res.is_valid
    codes = {r.code for r in res.rejection_reasons}
    assert "MISSING_VALUATION_MARK" in codes
    assert "MISSING_EXECUTION_PRICE" in codes
