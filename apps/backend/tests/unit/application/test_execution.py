"""Unit tests for decision execution, validation, cost calculation, and transitions."""

from decimal import Decimal

from simulator.application.services.execution import ExecutionService
from simulator.domain.lifecycle import ActionType, DecisionStatus
from simulator.domain.models import (
    AccountBalanceSpec,
    BalanceItem,
    CalendarSpec,
    CostModelSpec,
    CumulativeCostItem,
    DatasetSnapshotRef,
    DecisionRationale,
    DesiredAllocation,
    EpisodeDefinition,
    EpisodeRulesSpec,
    FailurePolicySpec,
    InitialAccountSpec,
    ObservationRecord,
    PolicyVersionRef,
    ProposedDecision,
    ReferenceValuation,
    RequestedAction,
    VirtualAccountState,
)


def _make_test_episode_def() -> EpisodeDefinition:
    return EpisodeDefinition(
        episode_id="ep-def_exec_test",
        title="Execution Test",
        description="Execution Test",
        created_at="2026-08-01T00:00:00Z",
        dataset_snapshot=DatasetSnapshotRef(
            snapshot_id="ds_1",
            source_uri="file:///test.jsonl",
            checksum_sha256="sha256:0000000000000000000000000000000000000000000000000000000000000000",
            retrieval_time="2026-08-01T00:00:00Z",
            calendar_frequency="1d",
        ),
        calendar=CalendarSpec(
            round_cutoffs=("2026-08-01T00:00:00Z", "2026-08-02T00:00:00Z"),
            interval_duration="1d",
            evaluation_delay="1d",
        ),
        policy_versions=(
            PolicyVersionRef(
                policy_id="pol-def_test",
                policy_version_id="pol-ver_test_v1",
                policy_version="1.0.0",
                policy_hash="sha256:1111111111111111111111111111111111111111111111111111111111111111",
                config_hash="sha256:2222222222222222222222222222222222222222222222222222222222222222",
            ),
        ),
        initial_accounts=(
            InitialAccountSpec(
                policy_id="pol-def_test",
                balances=(AccountBalanceSpec(resource_id="USD", quantity=Decimal("10000.00")),),
            ),
        ),
        reference_resource_id="USD",
        rules=EpisodeRulesSpec(
            allow_short_positions=False,
            allow_borrowing=False,
            cost_model=CostModelSpec(
                linear_transaction_fee_rate=Decimal("0.001"),
                fixed_transaction_fee=Decimal("1.00"),
                holding_cost_rate=Decimal("0.0"),
            ),
            failure_policy=FailurePolicySpec(),
        ),
    )


def _make_test_account() -> VirtualAccountState:
    return VirtualAccountState(
        account_state_id="acc-state_init",
        policy_id="pol-def_test",
        round_index=0,
        as_of_time="2026-08-01T00:00:00Z",
        balances=(
            BalanceItem(resource_id="USD", quantity=Decimal("10000.00")),
            BalanceItem(resource_id="RES_ALPHA", quantity=Decimal("0.00")),
        ),
        cumulative_costs=(CumulativeCostItem(cost_type="TRANSACTION_FEE", amount=Decimal("0.00")),),
        reference_valuation=ReferenceValuation(
            reference_resource_id="USD",
            unallocated_cash=Decimal("10000.00"),
            allocated_resources_value=Decimal("0.00"),
            net_total_value=Decimal("10000.00"),
        ),
        parent_state_hash=None,
    )


def test_execution_accepted_proposal() -> None:
    ep_def = _make_test_episode_def()
    account = _make_test_account()
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

    # Allocate 20 units of RES_ALPHA at 100 USD = 2000 USD
    # Fee: 0.001 * 2000 = 2.00 USD + fixed 1.00 USD = 3.00 USD
    # Total deduction from USD: 2003.00 USD -> remaining USD: 7997.00 USD
    proposal = ProposedDecision(
        decision_id="dec_prop_1",
        round_id="rnd_0",
        policy_id="pol-def_test",
        policy_version_id="pol-ver_test_v1",
        knowledge_cutoff="2026-08-01T00:00:00Z",
        generated_at="2026-08-01T00:00:01Z",
        desired_allocations=(DesiredAllocation("RES_ALPHA", Decimal("20.00")),),
        requested_actions=(RequestedAction(ActionType.ALLOCATE, "RES_ALPHA", Decimal("20.00")),),
        rationale=DecisionRationale(method="test"),
    )

    outcome, transition, next_account = ExecutionService.evaluate_and_apply_decision(
        episode_def=ep_def,
        current_account=account,
        proposal=proposal,
        eligible_observations=obs,
        round_id="rnd_0",
        round_index=1,
        effective_time="2026-08-01T00:00:00Z",
    )

    assert outcome.status == DecisionStatus.ACCEPTED
    assert outcome.applied_transition_id is not None
    assert transition is not None
    assert transition.total_cost_reference_unit == Decimal("3.00")

    # Balances
    balances_map = {b.resource_id: b.quantity for b in next_account.balances}
    assert balances_map["USD"] == Decimal("7997.00")
    assert balances_map["RES_ALPHA"] == Decimal("20.00")
    assert next_account.reference_valuation.net_total_value == Decimal("9997.00")
    assert next_account.parent_state_hash == account.compute_hash()


def test_execution_rejected_insufficient_funds() -> None:
    ep_def = _make_test_episode_def()
    account = _make_test_account()
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

    # Request allocating 150 units at 100 USD = 15000 USD (only 10000 USD available)
    proposal = ProposedDecision(
        decision_id="dec_prop_reject",
        round_id="rnd_0",
        policy_id="pol-def_test",
        policy_version_id="pol-ver_test_v1",
        knowledge_cutoff="2026-08-01T00:00:00Z",
        generated_at="2026-08-01T00:00:01Z",
        desired_allocations=(DesiredAllocation("RES_ALPHA", Decimal("150.00")),),
        requested_actions=(RequestedAction(ActionType.ALLOCATE, "RES_ALPHA", Decimal("150.00")),),
        rationale=DecisionRationale(method="test"),
    )

    outcome, transition, next_account = ExecutionService.evaluate_and_apply_decision(
        episode_def=ep_def,
        current_account=account,
        proposal=proposal,
        eligible_observations=obs,
        round_id="rnd_0",
        round_index=1,
        effective_time="2026-08-01T00:00:00Z",
    )

    assert outcome.status == DecisionStatus.REJECTED
    assert outcome.applied_transition_id is None
    assert transition is None
    assert len(outcome.rejection_reasons) > 0
    assert outcome.rejection_reasons[0].code == "INSUFFICIENT_UNALLOCATED_RESOURCE"

    # Account balances remain untouched
    balances_map = {b.resource_id: b.quantity for b in next_account.balances}
    assert balances_map["USD"] == Decimal("10000.00")


def test_execution_cross_policy_rejection() -> None:
    ep_def = _make_test_episode_def()
    account = _make_test_account()
    obs = ()

    # Proposal with external source_policy_id
    proposal = ProposedDecision(
        decision_id="dec_prop_cross",
        round_id="rnd_0",
        policy_id="pol-def_test",
        policy_version_id="pol-ver_test_v1",
        knowledge_cutoff="2026-08-01T00:00:00Z",
        generated_at="2026-08-01T00:00:01Z",
        desired_allocations=(),
        requested_actions=(
            RequestedAction(
                action_type=ActionType.TRANSFER,
                resource_id="USD",
                quantity=Decimal("100.00"),
                parameters={"source_policy_id": "pol-def_other"},
            ),
        ),
        rationale=DecisionRationale(method="test"),
    )

    outcome, transition, next_account = ExecutionService.evaluate_and_apply_decision(
        episode_def=ep_def,
        current_account=account,
        proposal=proposal,
        eligible_observations=obs,
        round_id="rnd_0",
        round_index=1,
        effective_time="2026-08-01T00:00:00Z",
    )

    assert outcome.status == DecisionStatus.REJECTED
    assert any(r.code == "CROSS_POLICY_ACCOUNT_CONTAMINATION" for r in outcome.rejection_reasons)
