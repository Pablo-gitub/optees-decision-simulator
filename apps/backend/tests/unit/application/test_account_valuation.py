"""Unit tests for AccountValuationService (DS-02D2C1A)."""

from decimal import Decimal

import pytest

from simulator.application.ports.pricing import PriceEvidence
from simulator.application.services.account_valuation import AccountValuationService
from simulator.domain.errors import TemporalLeakageError
from simulator.domain.models import (
    BalanceItem,
    CumulativeCostItem,
    ReferenceValuation,
    VirtualAccountState,
)


@pytest.fixture
def genesis_account():
    return VirtualAccountState(
        account_state_id="acc-state_genesis_alpha",
        policy_id="pol-def_alpha",
        round_index=0,
        as_of_time="2026-08-01T00:00:00Z",
        balances=(
            BalanceItem("res_usdt", Decimal("10000.00"), Decimal("0.00")),
            BalanceItem("res_btc", Decimal("2.50000000"), Decimal("0.00")),
            BalanceItem("res_eth", Decimal("10.00000000"), Decimal("1.00")),
        ),
        cumulative_costs=(CumulativeCostItem("TRANSACTION_FEE", Decimal("15.50")),),
        reference_valuation=ReferenceValuation(
            reference_resource_id="res_usdt",
            unallocated_cash=Decimal("10000.00"),
            allocated_resources_value=Decimal("170000.00"),
            net_total_value=Decimal("180000.00"),
        ),
        parent_state_hash=None,
    )


def test_revaluation_multiple_assets(genesis_account):
    marks = {
        "res_btc": PriceEvidence(
            resource_id="res_btc",
            price=Decimal("65000.00"),
            observation_id="obs_btc_1",
            event_time="2026-08-02T00:00:00Z",
            knowledge_time="2026-08-02T00:00:00Z",
            revision=1,
            staleness_seconds=Decimal("0.0"),
        ),
        "res_eth": PriceEvidence(
            resource_id="res_eth",
            price=Decimal("3500.00"),
            observation_id="obs_eth_1",
            event_time="2026-08-02T00:00:00Z",
            knowledge_time="2026-08-02T00:00:00Z",
            revision=1,
            staleness_seconds=Decimal("0.0"),
        ),
    }

    revalued = AccountValuationService.revalue_account(
        current_account=genesis_account,
        round_id="rnd_001",
        round_index=1,
        as_of_time="2026-08-02T00:00:00Z",
        valuation_marks=marks,
    )

    # Cash = 10,000.00
    # BTC = 2.5 * 65,000.00 = 162,500.00
    # ETH = 10.0 * 3,500.00 = 35,000.00
    # Allocated = 197,500.00
    # Total = 207,500.00
    assert revalued.reference_valuation.unallocated_cash == Decimal("10000.00")
    assert revalued.reference_valuation.allocated_resources_value == Decimal("197500.00")
    assert revalued.reference_valuation.net_total_value == Decimal("207500.00")

    # Preserves balances, reservations, costs, policy_id
    assert revalued.balances == genesis_account.balances
    assert revalued.balances[2].reserved_quantity == Decimal("1.00")
    assert revalued.cumulative_costs == genesis_account.cumulative_costs
    assert revalued.policy_id == genesis_account.policy_id
    assert revalued.parent_state_hash == genesis_account.compute_hash()
    assert revalued.round_index == 1
    assert revalued.as_of_time == "2026-08-02T00:00:00Z"


def test_reference_only_account():
    cash_only = VirtualAccountState(
        account_state_id="acc-state_cash",
        policy_id="pol-def_cash",
        round_index=0,
        as_of_time="2026-08-01T00:00:00Z",
        balances=(BalanceItem("res_usd", Decimal("5000.00"), Decimal("0.00")),),
        cumulative_costs=(),
        reference_valuation=ReferenceValuation(
            reference_resource_id="res_usd",
            unallocated_cash=Decimal("5000.00"),
            allocated_resources_value=Decimal("0.00"),
            net_total_value=Decimal("5000.00"),
        ),
        parent_state_hash=None,
    )

    revalued = AccountValuationService.revalue_account(
        current_account=cash_only,
        round_id="rnd_001",
        round_index=1,
        as_of_time="2026-08-02T00:00:00Z",
        valuation_marks={},
    )

    assert revalued.reference_valuation.unallocated_cash == Decimal("5000.00")
    assert revalued.reference_valuation.allocated_resources_value == Decimal("0.00")
    assert revalued.reference_valuation.net_total_value == Decimal("5000.00")


def test_missing_mark_for_held_asset(genesis_account):
    # Missing res_eth
    marks = {
        "res_btc": Decimal("65000.00"),
    }
    with pytest.raises(
        ValueError,
        match="Missing required valuation mark for held non-reference resource 'res_eth'",
    ):
        AccountValuationService.revalue_account(
            current_account=genesis_account,
            round_id="rnd_001",
            round_index=1,
            as_of_time="2026-08-02T00:00:00Z",
            valuation_marks=marks,
        )


def test_mark_mismatch(genesis_account):
    marks = {
        "res_btc": PriceEvidence(
            resource_id="res_wrong",
            price=Decimal("65000.00"),
            observation_id="obs_1",
            event_time=None,
            knowledge_time=None,
            revision=None,
            staleness_seconds=Decimal("0.0"),
        ),
        "res_eth": Decimal("3500.00"),
    }
    with pytest.raises(ValueError, match="does not match PriceEvidence resource_id"):
        AccountValuationService.revalue_account(
            current_account=genesis_account,
            round_id="rnd_001",
            round_index=1,
            as_of_time="2026-08-02T00:00:00Z",
            valuation_marks=marks,
        )


def test_future_knowledge_rejected(genesis_account):
    marks = {
        "res_btc": PriceEvidence(
            resource_id="res_btc",
            price=Decimal("65000.00"),
            observation_id="obs_1",
            event_time="2026-08-02T00:00:00Z",
            knowledge_time="2026-08-02T00:00:01Z",  # 1 second in the future!
            revision=1,
            staleness_seconds=Decimal("0.0"),
        ),
        "res_eth": Decimal("3500.00"),
    }
    with pytest.raises(TemporalLeakageError, match="future knowledge_time"):
        AccountValuationService.revalue_account(
            current_account=genesis_account,
            round_id="rnd_001",
            round_index=1,
            as_of_time="2026-08-02T00:00:00Z",
            valuation_marks=marks,
        )


def test_non_positive_or_non_finite_mark(genesis_account):
    with pytest.raises(ValueError):
        AccountValuationService.revalue_account(
            current_account=genesis_account,
            round_id="rnd_001",
            round_index=1,
            as_of_time="2026-08-02T00:00:00Z",
            valuation_marks={"res_btc": Decimal("0.00"), "res_eth": Decimal("3500.00")},
        )

    with pytest.raises(ValueError):
        AccountValuationService.revalue_account(
            current_account=genesis_account,
            round_id="rnd_001",
            round_index=1,
            as_of_time="2026-08-02T00:00:00Z",
            valuation_marks={"res_btc": Decimal("NaN"), "res_eth": Decimal("3500.00")},
        )


def test_deterministic_hash_production(genesis_account):
    marks = {
        "res_btc": Decimal("65000.00"),
        "res_eth": Decimal("3500.00"),
    }
    rev1 = AccountValuationService.revalue_account(
        current_account=genesis_account,
        round_id="rnd_001",
        round_index=1,
        as_of_time="2026-08-02T00:00:00Z",
        valuation_marks=marks,
    )
    rev2 = AccountValuationService.revalue_account(
        current_account=genesis_account,
        round_id="rnd_001",
        round_index=1,
        as_of_time="2026-08-02T00:00:00Z",
        valuation_marks=marks,
    )
    assert rev1.compute_hash() == rev2.compute_hash()
    assert rev1.compute_hash() != genesis_account.compute_hash()
