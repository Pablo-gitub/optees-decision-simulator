"""Unit and contract tests for DeferredAdmissionService (DS-02D2B1).

Verifies all frozen admission semantics:
1. Positive buy and signed sell produce expected immutable pending links, account hash,
   target-bar rule, evidence and deterministic IDs.
2. Unaffordable buy and sale exceeding holdings are admitted without pricing.
3. HOLD without/with active pending has accepted outcome, no transition, no new pending;
   original pending preserved by identity when present.
4. Policy contamination, wrong pinned version, round, cutoff and generated_at are rejected;
   equivalent UTC spellings are tested.
5. Empty/multiple actions, desired allocations, unsupported ADJUST/parameters, zero trades,
   nonzero HOLD, unknown resource and direct cash trade are rejected.
6. Boolean/float/non-finite and wrong-sign ALLOCATE inputs cannot escape as valid pending records;
   signed TRANSFER remains accepted.
7. Transition count limit 0/1 and unset is tested, including HOLD.
8. New decision while pending is rejected; identical retry reuses the pending;
   same-ID changed quantity/resource/version/target/predecessor cannot be admitted.
9. Invalid caller context fails explicitly, including foreign-policy pending.
10. Every path preserves input account bytes/hash/balances/costs; nested configuration mutation
    cannot change an already emitted record or result.
11. Output schema validation against authoritative draft 2020-12 schemas.
12. Canonical hash determinism and repeated execution tests.
"""

from __future__ import annotations

import copy
import importlib.util
import json
from decimal import Decimal
from pathlib import Path

import pytest

from simulator.application.services.deferred_admission import (
    REJECTION_CROSS_POLICY_ACCOUNT_CONTAMINATION,
    REJECTION_DECISION_ID_CONFLICT,
    REJECTION_INVALID_ACTION_SYNTAX,
    REJECTION_INVALID_DECISION_CONTEXT,
    REJECTION_POLICY_HAS_PENDING_SETTLEMENT,
    REJECTION_POLICY_VERSION_MISMATCH,
    REJECTION_TRANSITION_LIMIT_EXCEEDED,
    REJECTION_UNSUPPORTED_DESIRED_ALLOCATIONS,
    REJECTION_UNSUPPORTED_RESOURCE,
    DeferredAdmissionResult,
    DeferredAdmissionService,
)
from simulator.domain.lifecycle import ActionType, DecisionStatus, PendingStatus
from simulator.domain.models import (
    AccountBalanceSpec,
    BalanceItem,
    CalendarSpec,
    ConstraintsSpec,
    CostModelSpec,
    CumulativeCostItem,
    DatasetSnapshotRef,
    DecisionOutcome,
    DecisionRationale,
    DesiredAllocation,
    EpisodeDefinition,
    EpisodeRulesSpec,
    FailurePolicySpec,
    InitialAccountSpec,
    PendingTransitionRecord,
    PolicyVersionRef,
    ProposedDecision,
    ReferenceValuation,
    RequestedAction,
    TargetBarRule,
    VirtualAccountState,
)

REPO_ROOT = Path(__file__).resolve().parents[5]
SCHEMAS_DIR = REPO_ROOT / "docs" / "contracts" / "schemas"

validator_path = REPO_ROOT / "tools" / "validate_contracts.py"
spec = importlib.util.spec_from_file_location("validate_contracts", str(validator_path))
validate_contracts = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
spec.loader.exec_module(validate_contracts)  # type: ignore[union-attr]
validate_data = validate_contracts.validate_data


def _load_schema(filename: str) -> dict:
    with open(SCHEMAS_DIR / filename, "r", encoding="utf-8") as f:
        return json.load(f)


PENDING_SCHEMA = _load_schema("pending_transition.v1.json")
DECISION_OUTCOME_SCHEMA = _load_schema("decision_outcome.v1.json")


def _make_episode_def(
    policy_id: str = "pol-def_alpha",
    policy_version_id: str = "pol-ver_alpha_v1",
    reference_resource_id: str = "USD",
    max_transition_count_per_round: int | None = None,
) -> EpisodeDefinition:
    return EpisodeDefinition(
        episode_id="ep_admission_test",
        title="Admission Test Episode",
        description="Episode for admission testing",
        created_at="2026-01-01T00:00:00Z",
        dataset_snapshot=DatasetSnapshotRef(
            snapshot_id="dss_admission_test",
            source_uri="file:///test/snapshot",
            checksum_sha256="sha256:" + "0" * 64,
            retrieval_time="2026-01-01T00:00:00Z",
            calendar_frequency="1d",
        ),
        calendar=CalendarSpec(
            round_cutoffs=("2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z"),
            interval_duration="1d",
            evaluation_delay="1d",
        ),
        policy_versions=(
            PolicyVersionRef(
                policy_id=policy_id,
                policy_version_id=policy_version_id,
                policy_version="1.0.0",
                policy_hash="sha256:" + "1" * 64,
                config_hash="sha256:" + "2" * 64,
            ),
        ),
        initial_accounts=(
            InitialAccountSpec(
                policy_id=policy_id,
                balances=(
                    AccountBalanceSpec(
                        resource_id=reference_resource_id, quantity=Decimal("100000.00")
                    ),
                ),
            ),
        ),
        reference_resource_id=reference_resource_id,
        rules=EpisodeRulesSpec(
            allow_short_positions=False,
            allow_borrowing=False,
            cost_model=CostModelSpec(
                linear_transaction_fee_rate=Decimal("0.001"),
                fixed_transaction_fee=Decimal("1.00"),
                holding_cost_rate=Decimal("0.0"),
            ),
            failure_policy=FailurePolicySpec(),
            constraints=ConstraintsSpec(
                max_transition_count_per_round=max_transition_count_per_round
            ),
        ),
    )


def _make_account_state(
    policy_id: str = "pol-def_alpha",
    as_of_time: str = "2026-01-01T00:00:00Z",
    usd_qty: Decimal = Decimal("100000.00"),
    btc_qty: Decimal = Decimal("0.00"),
) -> VirtualAccountState:
    return VirtualAccountState(
        account_state_id=f"acc-state_rnd_001_{policy_id}",
        policy_id=policy_id,
        round_index=1,
        as_of_time=as_of_time,
        balances=(
            BalanceItem(resource_id="USD", quantity=usd_qty),
            BalanceItem(resource_id="BTC", quantity=btc_qty),
        ),
        cumulative_costs=(CumulativeCostItem(cost_type="TRANSACTION_FEE", amount=Decimal("0.00")),),
        reference_valuation=ReferenceValuation(
            reference_resource_id="USD",
            unallocated_cash=usd_qty,
            allocated_resources_value=Decimal("0.00"),
            net_total_value=usd_qty,
        ),
        parent_state_hash=None,
    )


def _make_proposal(
    decision_id: str = "dec-prop_001",
    round_id: str = "rnd_001",
    policy_id: str = "pol-def_alpha",
    policy_version_id: str = "pol-ver_alpha_v1",
    knowledge_cutoff: str = "2026-01-01T00:00:00Z",
    generated_at: str = "2026-01-01T00:00:00Z",
    requested_actions: tuple[RequestedAction, ...] | None = None,
    desired_allocations: tuple[DesiredAllocation, ...] = (),
) -> ProposedDecision:
    if requested_actions is None:
        requested_actions = (
            RequestedAction(
                action_type=ActionType.ALLOCATE,
                resource_id="BTC",
                quantity=Decimal("1.50000000"),
            ),
        )
    return ProposedDecision(
        decision_id=decision_id,
        round_id=round_id,
        policy_id=policy_id,
        policy_version_id=policy_version_id,
        knowledge_cutoff=knowledge_cutoff,
        generated_at=generated_at,
        desired_allocations=desired_allocations,
        requested_actions=requested_actions,
        rationale=DecisionRationale(method="test_admission"),
    )


RESOURCE_MAP = {"BTC": "BTC_USDT_KLINE_1D", "ETH": "ETH_USDT_KLINE_1D"}


# ==============================================================================
# 1. Buy & Sell Admission: links, hashes, rules, evidence, deterministic IDs
# ==============================================================================


def test_positive_allocate_buy_is_admitted():
    ep = _make_episode_def()
    account = _make_account_state()
    prop = _make_proposal(
        requested_actions=(
            RequestedAction(
                action_type=ActionType.ALLOCATE,
                resource_id="BTC",
                quantity=Decimal("2.5"),
            ),
        )
    )

    result = DeferredAdmissionService.admit_decision(
        episode_def=ep,
        current_account=account,
        proposal=prop,
        authoritative_round_id="rnd_001",
        authoritative_cutoff="2026-01-01T00:00:00Z",
        resource_to_series_map=RESOURCE_MAP,
    )

    assert result.is_newly_admitted is True
    assert result.is_reused_pending is False
    assert result.decision_outcome is None
    assert result.pending_transition is not None

    pending = result.pending_transition
    assert pending.decision_id == prop.decision_id
    assert pending.round_id == "rnd_001"
    assert pending.policy_id == prop.policy_id
    assert pending.policy_version_id == prop.policy_version_id
    assert pending.knowledge_cutoff == "2026-01-01T00:00:00Z"
    assert pending.admitted_at == "2026-01-01T00:00:00Z"
    assert pending.predecessor_account_hash == account.compute_hash()
    assert pending.requested_action == prop.requested_actions[0]
    assert pending.target_bar_rule == TargetBarRule(
        series_id="BTC_USDT_KLINE_1D",
        selection_rule="FIRST_OPEN_GE_CUTOFF",
        expected_open_time=None,
    )
    assert pending.status == PendingStatus.ADMITTED_PENDING
    assert pending.admission_evidence == {"proposal_hash": prop.compute_hash()}

    # Validate output schema
    errs = validate_data(pending.to_dict(), PENDING_SCHEMA)
    assert errs == []


def test_signed_transfer_sell_is_admitted():
    ep = _make_episode_def()
    account = _make_account_state()
    prop = _make_proposal(
        requested_actions=(
            RequestedAction(
                action_type=ActionType.TRANSFER,
                resource_id="BTC",
                quantity=Decimal("-1.25000000"),
            ),
        )
    )

    result = DeferredAdmissionService.admit_decision(
        episode_def=ep,
        current_account=account,
        proposal=prop,
        authoritative_round_id="rnd_001",
        authoritative_cutoff="2026-01-01T00:00:00Z",
        resource_to_series_map=RESOURCE_MAP,
    )

    assert result.is_newly_admitted is True
    assert result.pending_transition is not None
    assert result.pending_transition.requested_action.quantity == Decimal("-1.25000000")

    errs = validate_data(result.pending_transition.to_dict(), PENDING_SCHEMA)
    assert errs == []


def test_signed_transfer_buy_is_admitted():
    ep = _make_episode_def()
    account = _make_account_state()
    prop = _make_proposal(
        requested_actions=(
            RequestedAction(
                action_type=ActionType.TRANSFER,
                resource_id="ETH",
                quantity=Decimal("10.00"),
            ),
        )
    )

    result = DeferredAdmissionService.admit_decision(
        episode_def=ep,
        current_account=account,
        proposal=prop,
        authoritative_round_id="rnd_001",
        authoritative_cutoff="2026-01-01T00:00:00Z",
        resource_to_series_map=RESOURCE_MAP,
    )

    assert result.is_newly_admitted is True
    assert result.pending_transition is not None
    assert result.pending_transition.target_bar_rule.series_id == "ETH_USDT_KLINE_1D"


# ==============================================================================
# 2. No financial checks / pricing during admission
# ==============================================================================


def test_unaffordable_buy_and_sale_exceeding_holdings_are_both_admitted():
    ep = _make_episode_def()
    # Account has 10 USD and 0 BTC
    account = _make_account_state(usd_qty=Decimal("10.00"), btc_qty=Decimal("0.00"))

    # Buy 1,000,000 BTC with only 10 USD cash
    huge_buy = _make_proposal(
        decision_id="dec-prop_huge_buy",
        requested_actions=(
            RequestedAction(
                action_type=ActionType.ALLOCATE,
                resource_id="BTC",
                quantity=Decimal("1000000.00"),
            ),
        ),
    )
    buy_result = DeferredAdmissionService.admit_decision(
        episode_def=ep,
        current_account=account,
        proposal=huge_buy,
        authoritative_round_id="rnd_001",
        authoritative_cutoff="2026-01-01T00:00:00Z",
        resource_to_series_map=RESOURCE_MAP,
    )
    assert buy_result.is_newly_admitted is True

    # Sell 500 BTC when holdings are 0
    oversized_sale = _make_proposal(
        decision_id="dec-prop_oversized_sale",
        requested_actions=(
            RequestedAction(
                action_type=ActionType.TRANSFER,
                resource_id="BTC",
                quantity=Decimal("-500.00"),
            ),
        ),
    )
    sale_result = DeferredAdmissionService.admit_decision(
        episode_def=ep,
        current_account=account,
        proposal=oversized_sale,
        authoritative_round_id="rnd_001",
        authoritative_cutoff="2026-01-01T00:00:00Z",
        resource_to_series_map=RESOURCE_MAP,
    )
    assert sale_result.is_newly_admitted is True


# ==============================================================================
# 3. HOLD semantics without and with active pending
# ==============================================================================


def test_hold_without_pending_returns_accepted_outcome():
    ep = _make_episode_def()
    account = _make_account_state()
    hold_prop = _make_proposal(
        requested_actions=(
            RequestedAction(
                action_type=ActionType.HOLD,
                resource_id="USD",
                quantity=Decimal("0.00"),
            ),
        )
    )

    result = DeferredAdmissionService.admit_decision(
        episode_def=ep,
        current_account=account,
        proposal=hold_prop,
        authoritative_round_id="rnd_001",
        authoritative_cutoff="2026-01-01T00:00:00Z",
        resource_to_series_map=RESOURCE_MAP,
        current_pending=None,
    )

    assert result.is_newly_admitted is False
    assert result.is_reused_pending is False
    assert result.pending_transition is None
    assert result.decision_outcome is not None

    outcome = result.decision_outcome
    assert outcome.status == DecisionStatus.ACCEPTED
    assert outcome.rejection_reasons == ()
    assert outcome.evaluated_at == "2026-01-01T00:00:00Z"
    assert outcome.applied_transition_id is None
    assert outcome.round_id == "rnd_001"
    assert outcome.policy_id == hold_prop.policy_id
    assert outcome.decision_id == hold_prop.decision_id

    errs = validate_data(outcome.to_dict(), DECISION_OUTCOME_SCHEMA)
    assert errs == []


def test_hold_with_active_pending_preserves_original_pending_by_identity():
    ep = _make_episode_def()
    account = _make_account_state()

    # Active pending for this policy
    active_pending = PendingTransitionRecord(
        pending_transition_id="pnd_existing_001",
        decision_id="dec-prop_prev",
        round_id="rnd_000",
        policy_id="pol-def_alpha",
        policy_version_id="pol-ver_alpha_v1",
        knowledge_cutoff="2025-12-31T00:00:00Z",
        admitted_at="2025-12-31T00:00:00Z",
        predecessor_account_hash="sha256:" + "a" * 64,
        requested_action=RequestedAction(
            action_type=ActionType.ALLOCATE,
            resource_id="BTC",
            quantity=Decimal("1.0"),
        ),
        target_bar_rule=TargetBarRule(
            series_id="BTC_USDT_KLINE_1D",
            selection_rule="FIRST_OPEN_GE_CUTOFF",
        ),
        admission_evidence={"proposal_hash": "sha256:" + "b" * 64},
        status=PendingStatus.ADMITTED_PENDING,
    )

    hold_prop = _make_proposal(
        decision_id="dec-prop_hold_001",
        requested_actions=(
            RequestedAction(
                action_type=ActionType.HOLD,
                resource_id="BTC",
                quantity=Decimal("0.00"),
            ),
        ),
    )

    result = DeferredAdmissionService.admit_decision(
        episode_def=ep,
        current_account=account,
        proposal=hold_prop,
        authoritative_round_id="rnd_001",
        authoritative_cutoff="2026-01-01T00:00:00Z",
        resource_to_series_map=RESOURCE_MAP,
        current_pending=active_pending,
    )

    assert result.is_newly_admitted is False
    assert result.is_reused_pending is False
    assert result.decision_outcome is not None
    assert result.decision_outcome.status == DecisionStatus.ACCEPTED
    assert result.pending_transition is active_pending  # Preserved by identity!


# ==============================================================================
# 4. Policy contamination & context rejection
# ==============================================================================


def test_cross_policy_proposal_is_rejected():
    ep = _make_episode_def()
    account = _make_account_state(policy_id="pol-def_alpha")
    prop = _make_proposal(policy_id="pol-def_beta")

    result = DeferredAdmissionService.admit_decision(
        episode_def=ep,
        current_account=account,
        proposal=prop,
        authoritative_round_id="rnd_001",
        authoritative_cutoff="2026-01-01T00:00:00Z",
        resource_to_series_map=RESOURCE_MAP,
    )

    assert result.decision_outcome is not None
    assert result.decision_outcome.status == DecisionStatus.REJECTED
    codes = [r.code for r in result.decision_outcome.rejection_reasons]
    assert REJECTION_CROSS_POLICY_ACCOUNT_CONTAMINATION in codes


def test_cross_policy_action_parameter_is_rejected():
    ep = _make_episode_def()
    account = _make_account_state(policy_id="pol-def_alpha")
    prop = _make_proposal(
        requested_actions=(
            RequestedAction(
                action_type=ActionType.ALLOCATE,
                resource_id="BTC",
                quantity=Decimal("1.0"),
                parameters={"source_policy_id": "pol-def_external"},
            ),
        )
    )

    result = DeferredAdmissionService.admit_decision(
        episode_def=ep,
        current_account=account,
        proposal=prop,
        authoritative_round_id="rnd_001",
        authoritative_cutoff="2026-01-01T00:00:00Z",
        resource_to_series_map=RESOURCE_MAP,
    )

    assert result.decision_outcome is not None
    assert result.decision_outcome.status == DecisionStatus.REJECTED
    codes = [r.code for r in result.decision_outcome.rejection_reasons]
    assert REJECTION_CROSS_POLICY_ACCOUNT_CONTAMINATION in codes


def test_valid_source_policy_id_parameter_is_admitted():
    ep = _make_episode_def()
    account = _make_account_state(policy_id="pol-def_alpha")
    prop = _make_proposal(
        requested_actions=(
            RequestedAction(
                action_type=ActionType.ALLOCATE,
                resource_id="BTC",
                quantity=Decimal("1.0"),
                parameters={"source_policy_id": "pol-def_alpha"},
            ),
        )
    )

    result = DeferredAdmissionService.admit_decision(
        episode_def=ep,
        current_account=account,
        proposal=prop,
        authoritative_round_id="rnd_001",
        authoritative_cutoff="2026-01-01T00:00:00Z",
        resource_to_series_map=RESOURCE_MAP,
    )

    assert result.is_newly_admitted is True


def test_policy_version_mismatch_is_rejected():
    ep = _make_episode_def(policy_id="pol-def_alpha", policy_version_id="pol-ver_alpha_v1")
    account = _make_account_state(policy_id="pol-def_alpha")
    prop = _make_proposal(policy_version_id="pol-ver_alpha_v2_unpinned")

    result = DeferredAdmissionService.admit_decision(
        episode_def=ep,
        current_account=account,
        proposal=prop,
        authoritative_round_id="rnd_001",
        authoritative_cutoff="2026-01-01T00:00:00Z",
        resource_to_series_map=RESOURCE_MAP,
    )

    assert result.decision_outcome is not None
    assert result.decision_outcome.status == DecisionStatus.REJECTED
    codes = [r.code for r in result.decision_outcome.rejection_reasons]
    assert REJECTION_POLICY_VERSION_MISMATCH in codes


def test_round_and_cutoff_mismatches_are_rejected():
    ep = _make_episode_def()
    account = _make_account_state()
    prop = _make_proposal(
        round_id="rnd_999",
        knowledge_cutoff="2026-01-02T00:00:00Z",
        generated_at="2026-01-03T00:00:00Z",
    )

    result = DeferredAdmissionService.admit_decision(
        episode_def=ep,
        current_account=account,
        proposal=prop,
        authoritative_round_id="rnd_001",
        authoritative_cutoff="2026-01-01T00:00:00Z",
        resource_to_series_map=RESOURCE_MAP,
    )

    assert result.decision_outcome is not None
    assert result.decision_outcome.status == DecisionStatus.REJECTED
    codes = [r.code for r in result.decision_outcome.rejection_reasons]
    assert REJECTION_INVALID_DECISION_CONTEXT in codes
    fields = [r.violating_field for r in result.decision_outcome.rejection_reasons]
    assert "round_id" in fields
    assert "knowledge_cutoff" in fields
    assert "generated_at" in fields


def test_equivalent_utc_timestamp_spellings_are_accepted():
    ep = _make_episode_def()
    account = _make_account_state()
    # Authoritative cutoff is "2026-01-01T00:00:00Z"
    # Proposal uses equivalent instant "2026-01-01T00:00:00.000000Z"
    prop = _make_proposal(
        knowledge_cutoff="2026-01-01T00:00:00.000000Z",
        generated_at="2026-01-01T00:00:00.000Z",
    )

    result = DeferredAdmissionService.admit_decision(
        episode_def=ep,
        current_account=account,
        proposal=prop,
        authoritative_round_id="rnd_001",
        authoritative_cutoff="2026-01-01T00:00:00Z",
        resource_to_series_map=RESOURCE_MAP,
    )

    assert result.is_newly_admitted is True
    # Newly generated pending uses authoritative cutoff spelling
    assert result.pending_transition is not None
    assert result.pending_transition.knowledge_cutoff == "2026-01-01T00:00:00Z"
    assert result.pending_transition.admitted_at == "2026-01-01T00:00:00Z"


# ==============================================================================
# 5. Invalid action syntax, unsupported channels & resources
# ==============================================================================


def test_desired_allocations_are_rejected():
    ep = _make_episode_def()
    account = _make_account_state()
    prop = _make_proposal(
        desired_allocations=(DesiredAllocation(resource_id="BTC", target_quantity=Decimal("0.5")),)
    )

    result = DeferredAdmissionService.admit_decision(
        episode_def=ep,
        current_account=account,
        proposal=prop,
        authoritative_round_id="rnd_001",
        authoritative_cutoff="2026-01-01T00:00:00Z",
        resource_to_series_map=RESOURCE_MAP,
    )

    assert result.decision_outcome is not None
    codes = [r.code for r in result.decision_outcome.rejection_reasons]
    assert REJECTION_UNSUPPORTED_DESIRED_ALLOCATIONS in codes


def test_empty_and_multiple_actions_are_rejected():
    ep = _make_episode_def()
    account = _make_account_state()

    empty_prop = _make_proposal(requested_actions=())
    res_empty = DeferredAdmissionService.admit_decision(
        episode_def=ep,
        current_account=account,
        proposal=empty_prop,
        authoritative_round_id="rnd_001",
        authoritative_cutoff="2026-01-01T00:00:00Z",
        resource_to_series_map=RESOURCE_MAP,
    )
    assert res_empty.decision_outcome is not None
    assert REJECTION_INVALID_ACTION_SYNTAX in [
        r.code for r in res_empty.decision_outcome.rejection_reasons
    ]

    multi_prop = _make_proposal(
        requested_actions=(
            RequestedAction(
                action_type=ActionType.ALLOCATE, resource_id="BTC", quantity=Decimal("1.0")
            ),
            RequestedAction(
                action_type=ActionType.ALLOCATE, resource_id="ETH", quantity=Decimal("2.0")
            ),
        )
    )
    res_multi = DeferredAdmissionService.admit_decision(
        episode_def=ep,
        current_account=account,
        proposal=multi_prop,
        authoritative_round_id="rnd_001",
        authoritative_cutoff="2026-01-01T00:00:00Z",
        resource_to_series_map=RESOURCE_MAP,
    )
    assert res_multi.decision_outcome is not None
    assert REJECTION_INVALID_ACTION_SYNTAX in [
        r.code for r in res_multi.decision_outcome.rejection_reasons
    ]


def test_adjust_action_type_is_explicitly_rejected():
    ep = _make_episode_def()
    account = _make_account_state()
    prop = _make_proposal(
        requested_actions=(
            RequestedAction(
                action_type=ActionType.ADJUST,
                resource_id="BTC",
                quantity=Decimal("1.0"),
            ),
        )
    )

    result = DeferredAdmissionService.admit_decision(
        episode_def=ep,
        current_account=account,
        proposal=prop,
        authoritative_round_id="rnd_001",
        authoritative_cutoff="2026-01-01T00:00:00Z",
        resource_to_series_map=RESOURCE_MAP,
    )

    assert result.decision_outcome is not None
    codes = [r.code for r in result.decision_outcome.rejection_reasons]
    assert REJECTION_INVALID_ACTION_SYNTAX in codes


def test_unsupported_parameters_are_rejected():
    ep = _make_episode_def()
    account = _make_account_state()
    prop = _make_proposal(
        requested_actions=(
            RequestedAction(
                action_type=ActionType.ALLOCATE,
                resource_id="BTC",
                quantity=Decimal("1.0"),
                parameters={"order_type": "LIMIT", "limit_price": "50000"},
            ),
        )
    )

    result = DeferredAdmissionService.admit_decision(
        episode_def=ep,
        current_account=account,
        proposal=prop,
        authoritative_round_id="rnd_001",
        authoritative_cutoff="2026-01-01T00:00:00Z",
        resource_to_series_map=RESOURCE_MAP,
    )

    assert result.decision_outcome is not None
    codes = [r.code for r in result.decision_outcome.rejection_reasons]
    assert REJECTION_INVALID_ACTION_SYNTAX in codes


def test_zero_trades_and_nonzero_hold_are_rejected():
    ep = _make_episode_def()
    account = _make_account_state()

    for action_type in (ActionType.ALLOCATE, ActionType.TRANSFER):
        prop_zero = _make_proposal(
            requested_actions=(
                RequestedAction(
                    action_type=action_type,
                    resource_id="BTC",
                    quantity=Decimal("0.00"),
                ),
            )
        )
        res = DeferredAdmissionService.admit_decision(
            episode_def=ep,
            current_account=account,
            proposal=prop_zero,
            authoritative_round_id="rnd_001",
            authoritative_cutoff="2026-01-01T00:00:00Z",
            resource_to_series_map=RESOURCE_MAP,
        )
        assert res.decision_outcome is not None
        assert REJECTION_INVALID_ACTION_SYNTAX in [
            r.code for r in res.decision_outcome.rejection_reasons
        ]

    # Nonzero HOLD
    prop_nonzero_hold = _make_proposal(
        requested_actions=(
            RequestedAction(
                action_type=ActionType.HOLD,
                resource_id="BTC",
                quantity=Decimal("1.00"),
            ),
        )
    )
    res_hold = DeferredAdmissionService.admit_decision(
        episode_def=ep,
        current_account=account,
        proposal=prop_nonzero_hold,
        authoritative_round_id="rnd_001",
        authoritative_cutoff="2026-01-01T00:00:00Z",
        resource_to_series_map=RESOURCE_MAP,
    )
    assert res_hold.decision_outcome is not None
    assert REJECTION_INVALID_ACTION_SYNTAX in [
        r.code for r in res_hold.decision_outcome.rejection_reasons
    ]


def test_direct_cash_trade_and_unsupported_resources_are_rejected():
    ep = _make_episode_def(reference_resource_id="USD")
    account = _make_account_state()

    # Direct cash trade
    prop_cash = _make_proposal(
        requested_actions=(
            RequestedAction(
                action_type=ActionType.ALLOCATE,
                resource_id="USD",
                quantity=Decimal("100.00"),
            ),
        )
    )
    res_cash = DeferredAdmissionService.admit_decision(
        episode_def=ep,
        current_account=account,
        proposal=prop_cash,
        authoritative_round_id="rnd_001",
        authoritative_cutoff="2026-01-01T00:00:00Z",
        resource_to_series_map=RESOURCE_MAP,
    )
    assert res_cash.decision_outcome is not None
    assert REJECTION_UNSUPPORTED_RESOURCE in [
        r.code for r in res_cash.decision_outcome.rejection_reasons
    ]

    # Unknown resource
    prop_unknown = _make_proposal(
        requested_actions=(
            RequestedAction(
                action_type=ActionType.ALLOCATE,
                resource_id="SOL",
                quantity=Decimal("10.00"),
            ),
        )
    )
    res_unknown = DeferredAdmissionService.admit_decision(
        episode_def=ep,
        current_account=account,
        proposal=prop_unknown,
        authoritative_round_id="rnd_001",
        authoritative_cutoff="2026-01-01T00:00:00Z",
        resource_to_series_map=RESOURCE_MAP,
    )
    assert res_unknown.decision_outcome is not None
    assert REJECTION_UNSUPPORTED_RESOURCE in [
        r.code for r in res_unknown.decision_outcome.rejection_reasons
    ]

    # Unknown resource on HOLD is also rejected
    prop_hold_unknown = _make_proposal(
        requested_actions=(
            RequestedAction(
                action_type=ActionType.HOLD,
                resource_id="SOL",
                quantity=Decimal("0.00"),
            ),
        )
    )
    res_hold_unknown = DeferredAdmissionService.admit_decision(
        episode_def=ep,
        current_account=account,
        proposal=prop_hold_unknown,
        authoritative_round_id="rnd_001",
        authoritative_cutoff="2026-01-01T00:00:00Z",
        resource_to_series_map=RESOURCE_MAP,
    )
    assert res_hold_unknown.decision_outcome is not None
    assert REJECTION_UNSUPPORTED_RESOURCE in [
        r.code for r in res_hold_unknown.decision_outcome.rejection_reasons
    ]


# ==============================================================================
# 6. Type checks: boolean, float, non-finite, wrong-sign ALLOCATE
# ==============================================================================


@pytest.mark.parametrize(
    "bad_qty",
    [
        True,
        False,
        1.5,
        float("nan"),
        float("inf"),
        Decimal("NaN"),
        Decimal("Infinity"),
        Decimal("-0.5"),  # Wrong sign for ALLOCATE
    ],
)
def test_invalid_quantities_cannot_escape_as_valid_pending(bad_qty):
    ep = _make_episode_def()
    account = _make_account_state()
    # Construct RequestedAction directly with bad_qty
    action = RequestedAction(
        action_type=ActionType.ALLOCATE,
        resource_id="BTC",
        quantity=bad_qty,  # type: ignore[arg-type]
    )
    prop = _make_proposal(requested_actions=(action,))

    result = DeferredAdmissionService.admit_decision(
        episode_def=ep,
        current_account=account,
        proposal=prop,
        authoritative_round_id="rnd_001",
        authoritative_cutoff="2026-01-01T00:00:00Z",
        resource_to_series_map=RESOURCE_MAP,
    )

    assert result.decision_outcome is not None
    assert result.decision_outcome.status == DecisionStatus.REJECTED
    assert result.pending_transition is None
    codes = [r.code for r in result.decision_outcome.rejection_reasons]
    assert REJECTION_INVALID_ACTION_SYNTAX in codes


# ==============================================================================
# 7. Transition count limits: 0, 1, and unset
# ==============================================================================


def test_transition_count_limit_zero_rejects_trades_and_hold():
    ep = _make_episode_def(max_transition_count_per_round=0)
    account = _make_account_state()

    trade_prop = _make_proposal()
    res_trade = DeferredAdmissionService.admit_decision(
        episode_def=ep,
        current_account=account,
        proposal=trade_prop,
        authoritative_round_id="rnd_001",
        authoritative_cutoff="2026-01-01T00:00:00Z",
        resource_to_series_map=RESOURCE_MAP,
    )
    assert res_trade.decision_outcome is not None
    assert REJECTION_TRANSITION_LIMIT_EXCEEDED in [
        r.code for r in res_trade.decision_outcome.rejection_reasons
    ]

    hold_prop = _make_proposal(
        requested_actions=(
            RequestedAction(
                action_type=ActionType.HOLD,
                resource_id="USD",
                quantity=Decimal("0.00"),
            ),
        )
    )
    res_hold = DeferredAdmissionService.admit_decision(
        episode_def=ep,
        current_account=account,
        proposal=hold_prop,
        authoritative_round_id="rnd_001",
        authoritative_cutoff="2026-01-01T00:00:00Z",
        resource_to_series_map=RESOURCE_MAP,
    )
    assert res_hold.decision_outcome is not None
    assert REJECTION_TRANSITION_LIMIT_EXCEEDED in [
        r.code for r in res_hold.decision_outcome.rejection_reasons
    ]


def test_transition_count_limit_one_and_unset_both_allow_single_action():
    for limit in (1, None):
        ep = _make_episode_def(max_transition_count_per_round=limit)
        account = _make_account_state()
        prop = _make_proposal()
        res = DeferredAdmissionService.admit_decision(
            episode_def=ep,
            current_account=account,
            proposal=prop,
            authoritative_round_id="rnd_001",
            authoritative_cutoff="2026-01-01T00:00:00Z",
            resource_to_series_map=RESOURCE_MAP,
        )
        assert res.is_newly_admitted is True


# ==============================================================================
# 8. Pending retry and conflict handling
# ==============================================================================


def test_different_decision_with_active_pending_is_rejected():
    ep = _make_episode_def()
    account = _make_account_state()

    # Active pending
    first_prop = _make_proposal(decision_id="dec-prop_001")
    first_res = DeferredAdmissionService.admit_decision(
        episode_def=ep,
        current_account=account,
        proposal=first_prop,
        authoritative_round_id="rnd_001",
        authoritative_cutoff="2026-01-01T00:00:00Z",
        resource_to_series_map=RESOURCE_MAP,
    )
    active_pending = first_res.pending_transition
    assert active_pending is not None

    # Second decision with different decision_id while pending is active
    second_prop = _make_proposal(decision_id="dec-prop_002")
    second_res = DeferredAdmissionService.admit_decision(
        episode_def=ep,
        current_account=account,
        proposal=second_prop,
        authoritative_round_id="rnd_001",
        authoritative_cutoff="2026-01-01T00:00:00Z",
        resource_to_series_map=RESOURCE_MAP,
        current_pending=active_pending,
    )

    assert second_res.is_newly_admitted is False
    assert second_res.is_reused_pending is False
    assert second_res.pending_transition is active_pending  # Preserved unchanged
    assert second_res.decision_outcome is not None
    assert second_res.decision_outcome.status == DecisionStatus.REJECTED
    codes = [r.code for r in second_res.decision_outcome.rejection_reasons]
    assert REJECTION_POLICY_HAS_PENDING_SETTLEMENT in codes


def test_exact_retry_reuses_active_pending():
    ep = _make_episode_def()
    account = _make_account_state()
    prop = _make_proposal(decision_id="dec-prop_001")

    # Initial admission
    initial_res = DeferredAdmissionService.admit_decision(
        episode_def=ep,
        current_account=account,
        proposal=prop,
        authoritative_round_id="rnd_001",
        authoritative_cutoff="2026-01-01T00:00:00Z",
        resource_to_series_map=RESOURCE_MAP,
    )
    pending = initial_res.pending_transition
    assert pending is not None

    # Identical retry
    retry_res = DeferredAdmissionService.admit_decision(
        episode_def=ep,
        current_account=account,
        proposal=prop,
        authoritative_round_id="rnd_001",
        authoritative_cutoff="2026-01-01T00:00:00Z",
        resource_to_series_map=RESOURCE_MAP,
        current_pending=pending,
    )

    assert retry_res.is_reused_pending is True
    assert retry_res.is_newly_admitted is False
    assert retry_res.decision_outcome is None
    assert retry_res.pending_transition is pending


@pytest.mark.parametrize(
    "drift_kwarg",
    [
        {
            "requested_actions": (
                RequestedAction(
                    action_type=ActionType.ALLOCATE,
                    resource_id="BTC",
                    quantity=Decimal("9.99"),  # Drifted quantity
                ),
            )
        },
        {
            "requested_actions": (
                RequestedAction(
                    action_type=ActionType.ALLOCATE,
                    resource_id="ETH",  # Drifted resource
                    quantity=Decimal("1.50000000"),
                ),
            )
        },
    ],
)
def test_same_id_drifted_proposal_returns_conflict(drift_kwarg):
    ep = _make_episode_def()
    account = _make_account_state()
    base_prop = _make_proposal(decision_id="dec-prop_001")

    initial_res = DeferredAdmissionService.admit_decision(
        episode_def=ep,
        current_account=account,
        proposal=base_prop,
        authoritative_round_id="rnd_001",
        authoritative_cutoff="2026-01-01T00:00:00Z",
        resource_to_series_map=RESOURCE_MAP,
    )
    pending = initial_res.pending_transition
    assert pending is not None

    drifted_prop = _make_proposal(decision_id="dec-prop_001", **drift_kwarg)
    drifted_res = DeferredAdmissionService.admit_decision(
        episode_def=ep,
        current_account=account,
        proposal=drifted_prop,
        authoritative_round_id="rnd_001",
        authoritative_cutoff="2026-01-01T00:00:00Z",
        resource_to_series_map=RESOURCE_MAP,
        current_pending=pending,
    )

    assert drifted_res.is_reused_pending is False
    assert drifted_res.is_newly_admitted is False
    assert drifted_res.pending_transition is pending  # Preserved!
    assert drifted_res.decision_outcome is not None
    assert drifted_res.decision_outcome.status == DecisionStatus.REJECTED
    codes = [r.code for r in drifted_res.decision_outcome.rejection_reasons]
    assert REJECTION_DECISION_ID_CONFLICT in codes


def test_retry_with_drifted_predecessor_account_returns_conflict():
    ep = _make_episode_def()
    account1 = _make_account_state(usd_qty=Decimal("100000.00"))
    prop = _make_proposal(decision_id="dec-prop_001")

    initial_res = DeferredAdmissionService.admit_decision(
        episode_def=ep,
        current_account=account1,
        proposal=prop,
        authoritative_round_id="rnd_001",
        authoritative_cutoff="2026-01-01T00:00:00Z",
        resource_to_series_map=RESOURCE_MAP,
    )
    pending = initial_res.pending_transition
    assert pending is not None

    # Now caller provides a drifted account state
    account2 = _make_account_state(usd_qty=Decimal("50000.00"))
    retry_res = DeferredAdmissionService.admit_decision(
        episode_def=ep,
        current_account=account2,
        proposal=prop,
        authoritative_round_id="rnd_001",
        authoritative_cutoff="2026-01-01T00:00:00Z",
        resource_to_series_map=RESOURCE_MAP,
        current_pending=pending,
    )

    assert retry_res.decision_outcome is not None
    codes = [r.code for r in retry_res.decision_outcome.rejection_reasons]
    assert REJECTION_DECISION_ID_CONFLICT in codes


def test_retry_with_drifted_target_series_returns_conflict():
    ep = _make_episode_def()
    account = _make_account_state()
    prop = _make_proposal(decision_id="dec-prop_001")

    initial_res = DeferredAdmissionService.admit_decision(
        episode_def=ep,
        current_account=account,
        proposal=prop,
        authoritative_round_id="rnd_001",
        authoritative_cutoff="2026-01-01T00:00:00Z",
        resource_to_series_map=RESOURCE_MAP,
    )
    pending = initial_res.pending_transition
    assert pending is not None

    # Caller now specifies a different series mapping for BTC
    changed_map = {"BTC": "BTC_USDT_ALTERNATIVE_SERIES", "ETH": "ETH_USDT_KLINE_1D"}
    retry_res = DeferredAdmissionService.admit_decision(
        episode_def=ep,
        current_account=account,
        proposal=prop,
        authoritative_round_id="rnd_001",
        authoritative_cutoff="2026-01-01T00:00:00Z",
        resource_to_series_map=changed_map,
        current_pending=pending,
    )

    assert retry_res.decision_outcome is not None
    codes = [r.code for r in retry_res.decision_outcome.rejection_reasons]
    assert REJECTION_DECISION_ID_CONFLICT in codes


def test_retry_with_missing_stored_hash_returns_conflict():
    ep = _make_episode_def()
    account = _make_account_state()
    prop = _make_proposal(decision_id="dec-prop_001")

    # Active pending with missing proposal_hash in admission_evidence
    pending_missing_hash = PendingTransitionRecord(
        pending_transition_id="pnd_missing_hash",
        decision_id=prop.decision_id,
        round_id="rnd_001",
        policy_id=prop.policy_id,
        policy_version_id=prop.policy_version_id,
        knowledge_cutoff="2026-01-01T00:00:00Z",
        admitted_at="2026-01-01T00:00:00Z",
        predecessor_account_hash=account.compute_hash(),
        requested_action=prop.requested_actions[0],
        target_bar_rule=TargetBarRule(
            series_id="BTC_USDT_KLINE_1D",
            selection_rule="FIRST_OPEN_GE_CUTOFF",
        ),
        admission_evidence={},  # No proposal_hash!
        status=PendingStatus.ADMITTED_PENDING,
    )

    retry_res = DeferredAdmissionService.admit_decision(
        episode_def=ep,
        current_account=account,
        proposal=prop,
        authoritative_round_id="rnd_001",
        authoritative_cutoff="2026-01-01T00:00:00Z",
        resource_to_series_map=RESOURCE_MAP,
        current_pending=pending_missing_hash,
    )

    assert retry_res.decision_outcome is not None
    codes = [r.code for r in retry_res.decision_outcome.rejection_reasons]
    assert REJECTION_DECISION_ID_CONFLICT in codes


def test_multiple_rejection_reasons_are_sorted_deterministically_without_prices():
    ep = _make_episode_def(max_transition_count_per_round=0)
    account = _make_account_state(policy_id="pol-def_alpha")
    # Proposal with multiple violations:
    # 1. foreign policy
    # 2. wrong round_id
    # 3. desired_allocations present
    # 4. transition count limit exceeded
    # 5. multiple actions
    prop = _make_proposal(
        policy_id="pol-def_external",
        round_id="rnd_999",
        desired_allocations=(DesiredAllocation(resource_id="BTC", target_quantity=Decimal("1.0")),),
        requested_actions=(
            RequestedAction(
                action_type=ActionType.ALLOCATE, resource_id="BTC", quantity=Decimal("1.0")
            ),
            RequestedAction(
                action_type=ActionType.ALLOCATE, resource_id="ETH", quantity=Decimal("2.0")
            ),
        ),
    )

    res = DeferredAdmissionService.admit_decision(
        episode_def=ep,
        current_account=account,
        proposal=prop,
        authoritative_round_id="rnd_001",
        authoritative_cutoff="2026-01-01T00:00:00Z",
        resource_to_series_map=RESOURCE_MAP,
    )

    outcome = res.decision_outcome
    assert outcome is not None
    assert outcome.status == DecisionStatus.REJECTED
    reasons = outcome.rejection_reasons
    assert len(reasons) > 1

    # Check deterministic sort: (r.code, r.violating_field or "", r.message)
    expected_sort = sorted(reasons, key=lambda r: (r.code, r.violating_field or "", r.message))
    assert list(reasons) == expected_sort

    # Verify no prices/marks/money in messages
    for r in reasons:
        assert "$" not in r.message
        assert "price" not in r.message.lower()
        assert "mark" not in r.message.lower()

    # Verify outcome schema validation
    errs = validate_data(outcome.to_dict(), DECISION_OUTCOME_SCHEMA)
    assert errs == []


# ==============================================================================
# 9. Caller context errors raise ValueError / TypeError
# ==============================================================================


def test_invalid_caller_context_raises_explicit_exceptions():
    ep = _make_episode_def()
    account = _make_account_state()
    prop = _make_proposal()

    # Non-EpisodeDefinition
    with pytest.raises(TypeError, match="episode_def must be an EpisodeDefinition"):
        DeferredAdmissionService.admit_decision(
            episode_def={},  # type: ignore[arg-type]
            current_account=account,
            proposal=prop,
            authoritative_round_id="rnd_001",
            authoritative_cutoff="2026-01-01T00:00:00Z",
            resource_to_series_map=RESOURCE_MAP,
        )

    # Malformed authoritative round ID
    with pytest.raises(ValueError, match="authoritative_round_id is malformed"):
        DeferredAdmissionService.admit_decision(
            episode_def=ep,
            current_account=account,
            proposal=prop,
            authoritative_round_id="round_invalid_prefix",
            authoritative_cutoff="2026-01-01T00:00:00Z",
            resource_to_series_map=RESOURCE_MAP,
        )

    # Account timestamp later than cutoff
    future_account = _make_account_state(as_of_time="2026-01-05T00:00:00Z")
    with pytest.raises(ValueError, match="cannot be later than authoritative_cutoff"):
        DeferredAdmissionService.admit_decision(
            episode_def=ep,
            current_account=future_account,
            proposal=prop,
            authoritative_round_id="rnd_001",
            authoritative_cutoff="2026-01-01T00:00:00Z",
            resource_to_series_map=RESOURCE_MAP,
        )

    # Foreign policy pending supplied as current policy pending
    foreign_pending = PendingTransitionRecord(
        pending_transition_id="pnd_foreign_001",
        decision_id="dec-prop_foreign",
        round_id="rnd_001",
        policy_id="pol-def_foreign_policy",  # foreign!
        policy_version_id="pol-ver_foreign_v1",
        knowledge_cutoff="2026-01-01T00:00:00Z",
        admitted_at="2026-01-01T00:00:00Z",
        predecessor_account_hash="sha256:" + "0" * 64,
        requested_action=RequestedAction(
            action_type=ActionType.ALLOCATE,
            resource_id="BTC",
            quantity=Decimal("1.0"),
        ),
        target_bar_rule=TargetBarRule(
            series_id="BTC_USDT_KLINE_1D",
            selection_rule="FIRST_OPEN_GE_CUTOFF",
        ),
        admission_evidence={"proposal_hash": "sha256:" + "1" * 64},
        status=PendingStatus.ADMITTED_PENDING,
    )
    with pytest.raises(ValueError, match="does not match current_account policy_id"):
        DeferredAdmissionService.admit_decision(
            episode_def=ep,
            current_account=account,
            proposal=prop,
            authoritative_round_id="rnd_001",
            authoritative_cutoff="2026-01-01T00:00:00Z",
            resource_to_series_map=RESOURCE_MAP,
            current_pending=foreign_pending,
        )

    # Malformed resource mapping
    with pytest.raises(ValueError, match="resource_to_series_map keys must be non-empty strings"):
        DeferredAdmissionService.admit_decision(
            episode_def=ep,
            current_account=account,
            proposal=prop,
            authoritative_round_id="rnd_001",
            authoritative_cutoff="2026-01-01T00:00:00Z",
            resource_to_series_map={"": "SERIES_1"},
        )


# ==============================================================================
# 10. Immutability: input account & configuration preservation
# ==============================================================================


def test_input_account_is_never_mutated():
    ep = _make_episode_def()
    account = _make_account_state()
    account_hash_before = account.compute_hash()
    account_dict_before = copy.deepcopy(account.to_dict())

    prop = _make_proposal()
    res = DeferredAdmissionService.admit_decision(
        episode_def=ep,
        current_account=account,
        proposal=prop,
        authoritative_round_id="rnd_001",
        authoritative_cutoff="2026-01-01T00:00:00Z",
        resource_to_series_map=RESOURCE_MAP,
    )

    assert account.compute_hash() == account_hash_before
    assert account.to_dict() == account_dict_before
    assert res.is_newly_admitted is True


def test_mapping_mutation_after_call_does_not_affect_emitted_pending():
    ep = _make_episode_def()
    account = _make_account_state()
    prop = _make_proposal()
    mapping = dict(RESOURCE_MAP)

    res = DeferredAdmissionService.admit_decision(
        episode_def=ep,
        current_account=account,
        proposal=prop,
        authoritative_round_id="rnd_001",
        authoritative_cutoff="2026-01-01T00:00:00Z",
        resource_to_series_map=mapping,
    )

    assert res.pending_transition is not None
    # Now mutate mapping
    mapping["BTC"] = "MUTATED_SERIES"
    assert res.pending_transition.target_bar_rule.series_id == "BTC_USDT_KLINE_1D"


# ==============================================================================
# 11. Determinism, exclusive result types & canonical hashing
# ==============================================================================


def test_deterministic_id_generation_and_reproducibility():
    ep = _make_episode_def()
    account = _make_account_state()
    prop = _make_proposal()

    res1 = DeferredAdmissionService.admit_decision(
        episode_def=ep,
        current_account=account,
        proposal=prop,
        authoritative_round_id="rnd_001",
        authoritative_cutoff="2026-01-01T00:00:00Z",
        resource_to_series_map=RESOURCE_MAP,
    )
    res2 = DeferredAdmissionService.admit_decision(
        episode_def=ep,
        current_account=account,
        proposal=prop,
        authoritative_round_id="rnd_001",
        authoritative_cutoff="2026-01-01T00:00:00Z",
        resource_to_series_map=RESOURCE_MAP,
    )

    assert res1.pending_transition is not None
    assert res2.pending_transition is not None
    assert (
        res1.pending_transition.pending_transition_id
        == res2.pending_transition.pending_transition_id
    )
    assert res1.pending_transition.compute_hash() == res2.pending_transition.compute_hash()


def test_result_dto_invariant_enforcement():
    # Attempt to build result that violates exclusivity
    with pytest.raises(ValueError, match="Result cannot be both newly admitted and reused pending"):
        DeferredAdmissionResult(
            pending_transition=None,
            decision_outcome=None,
            is_newly_admitted=True,
            is_reused_pending=True,
        )

    with pytest.raises(
        ValueError,
        match="Admitted or reused pending cannot have an immediate decision outcome",
    ):
        dummy_outcome = DecisionOutcome(
            outcome_id="dec-out_test",
            decision_id="dec-prop_test",
            round_id="rnd_test",
            policy_id="pol-def_test",
            status=DecisionStatus.ACCEPTED,
            rejection_reasons=(),
            evaluated_at="2026-01-01T00:00:00Z",
        )
        DeferredAdmissionResult(
            pending_transition=None,
            decision_outcome=dummy_outcome,
            is_newly_admitted=True,
            is_reused_pending=False,
        )
