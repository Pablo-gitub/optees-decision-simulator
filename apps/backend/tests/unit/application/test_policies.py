"""Unit tests for deterministic baseline policies."""

from decimal import Decimal

from simulator.application.policies.cash import AllReferenceCashPolicy
from simulator.application.policies.equal import EqualAllocationPolicy
from simulator.application.policies.reactive import ReactiveObservationPolicy
from simulator.application.policies.static import StaticBaselinePolicy
from simulator.application.ports.policy import PolicyContext
from simulator.domain.lifecycle import ActionType
from simulator.domain.models import (
    BalanceItem,
    CumulativeCostItem,
    ObservationRecord,
    ReferenceValuation,
    VirtualAccountState,
)


def _make_context(
    balances: tuple[BalanceItem, ...],
    observations: tuple[ObservationRecord, ...] = (),
    hyperparameters: dict | None = None,
) -> PolicyContext:
    return PolicyContext(
        policy_id="test_pol",
        policy_version_id="test_ver",
        round_id="rnd_0",
        round_index=0,
        knowledge_cutoff="2026-08-01T00:00:00Z",
        account_state=VirtualAccountState(
            account_state_id="acc_0",
            policy_id="test_pol",
            round_index=0,
            as_of_time="2026-08-01T00:00:00Z",
            balances=balances,
            cumulative_costs=(CumulativeCostItem("TRANSACTION_FEE", Decimal("0.00")),),
            reference_valuation=ReferenceValuation(
                "USD", Decimal("10000.00"), Decimal("0.00"), Decimal("10000.00")
            ),
            parent_state_hash=None,
        ),
        eligible_observations=observations,
        hyperparameters=hyperparameters or {},
    )


def test_static_baseline_policy() -> None:
    pol = StaticBaselinePolicy()
    ctx = _make_context(
        balances=(
            BalanceItem("USD", Decimal("8000.00")),
            BalanceItem("RES_ALPHA", Decimal("20.00")),
        )
    )
    prop = pol.propose_decision(ctx)
    assert len(prop.requested_actions) == 2
    assert all(a.action_type == ActionType.HOLD for a in prop.requested_actions)


def test_cash_policy() -> None:
    pol = AllReferenceCashPolicy(reference_resource_id="USD")
    ctx = _make_context(
        balances=(
            BalanceItem("USD", Decimal("8000.00")),
            BalanceItem("RES_ALPHA", Decimal("20.00")),
        )
    )
    prop = pol.propose_decision(ctx)
    # Requests liquidating RES_ALPHA
    assert any(
        a.resource_id == "RES_ALPHA" and a.action_type == ActionType.TRANSFER
        for a in prop.requested_actions
    )


def test_equal_allocation_policy() -> None:
    pol = EqualAllocationPolicy(target_resources=("RES_ALPHA", "RES_BETA"))
    obs = (
        ObservationRecord(
            observation_id="obs_1",
            snapshot_id="ds_1",
            series_id="RES_ALPHA_PRICE",
            event_time="2026-07-31T23:59:00Z",
            knowledge_time="2026-08-01T00:00:00Z",
            revision=1,
            payload={"price": "100.00"},
        ),
        ObservationRecord(
            observation_id="obs_2",
            snapshot_id="ds_1",
            series_id="RES_BETA_PRICE",
            event_time="2026-07-31T23:59:00Z",
            knowledge_time="2026-08-01T00:00:00Z",
            revision=1,
            payload={"price": "50.00"},
        ),
    )
    ctx = _make_context(
        balances=(BalanceItem("USD", Decimal("10000.00")),),
        observations=obs,
    )
    prop = pol.propose_decision(ctx)
    # 5000 USD each -> 50 units RES_ALPHA, 100 units RES_BETA
    actions_map = {a.resource_id: a.quantity for a in prop.requested_actions}
    assert actions_map["RES_ALPHA"] == Decimal("50.00")
    assert actions_map["RES_BETA"] == Decimal("100.00")


def test_reactive_observation_policy() -> None:
    pol = ReactiveObservationPolicy(target_resource_id="RES_ALPHA")
    obs = (
        ObservationRecord(
            observation_id="obs_1",
            snapshot_id="ds_1",
            series_id="RES_ALPHA_PRICE",
            event_time="2026-07-31T23:59:00Z",
            knowledge_time="2026-08-01T00:00:00Z",
            revision=1,
            payload={"price": "100.00"},
        ),
    )
    # 20% of 10000 USD = 2000 USD / 100 = 20 units
    ctx = _make_context(
        balances=(BalanceItem("USD", Decimal("10000.00")),),
        observations=obs,
        hyperparameters={"allocation_fraction": "0.20"},
    )
    prop = pol.propose_decision(ctx)
    assert len(prop.requested_actions) == 1
    assert prop.requested_actions[0].resource_id == "RES_ALPHA"
    assert prop.requested_actions[0].quantity == Decimal("20.00")
