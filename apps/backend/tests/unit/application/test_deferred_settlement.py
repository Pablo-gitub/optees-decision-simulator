"""Unit and contract tests for DeferredSettlementService (DS-02D2B2).

Verifies the frozen settlement semantics from
`docs/roadmaps/deferred-settlement-services.md`:

1. Full D+2 lifecycle settles an admission-produced pending (Probe DP-01).
2. Still-pending when the target bar is not yet knowledge-eligible.
3. Deterministic, non-skipping target-bar selection: an earlier bar present
   but not yet eligible blocks settlement against a later, already-eligible
   bar; the accepted limitation for an entirely-absent earlier bar is
   documented explicitly, not silently passed.
4. `open_time` — never `event_time` — governs bar selection.
5. `terminate_unsettled` records `MISSING_EXECUTION_BAR` (DP-02),
   `UNSETTLED_EPISODE_TERMINATION` (DP-05) and `EPISODE_CANCELLED` (DP-06).
6. Revision resolution uses the highest knowledge-eligible revision (DP-03).
7. Insufficient funds (DP-04) and short-position rejections at settlement,
   with zero mutation and full evidence.
8. Invalid execution price produces empty settlement_evidence (a domain-model
   constraint, not an implementation choice).
9. Missing valuation marks for untouched holdings block settlement.
10. Signed TRANSFER (credit and debit) and ALLOCATE settle with exact
    ROUND_HALF_EVEN-quantized Decimal evidence.
11. Invalid caller context fails explicitly before any evaluation.
12. Deep immutability, schema validation, bidirectional links and hash
    determinism against the real, authoritative schemas.
"""

from __future__ import annotations

import copy
import importlib.util
import json
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from simulator.application.services.deferred_admission import DeferredAdmissionService
from simulator.application.services.deferred_settlement import (
    REJECTION_EPISODE_CANCELLED,
    REJECTION_INSUFFICIENT_FUNDS_AT_SETTLEMENT,
    REJECTION_INVALID_EXECUTION_PRICE,
    REJECTION_MISSING_EXECUTION_BAR,
    REJECTION_MISSING_VALUATION_MARK,
    REJECTION_SHORT_POSITIONS_FORBIDDEN,
    REJECTION_UNSETTLED_EPISODE_TERMINATION,
    DeferredSettlementResult,
    DeferredSettlementService,
)
from simulator.domain.lifecycle import ActionType, PendingStatus, SettlementStatus
from simulator.domain.models import (
    AccountBalanceSpec,
    BalanceItem,
    CalendarSpec,
    ConstraintsSpec,
    CostModelSpec,
    CumulativeCostItem,
    DatasetSnapshotRef,
    DecisionRationale,
    EpisodeDefinition,
    EpisodeRulesSpec,
    FailurePolicySpec,
    InitialAccountSpec,
    ObservationRecord,
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


SETTLEMENT_OUTCOME_SCHEMA = _load_schema("settlement_outcome.v1.json")
TRANSITION_V2_SCHEMA = _load_schema("transition.v2.json")

SERIES_ID = "BTC_USDT_KLINE_1D"
RESOURCE_MAP = {"BTC": SERIES_ID}


def _make_episode_def(
    policy_id: str = "pol-def_alpha",
    policy_version_id: str = "pol-ver_alpha_v1",
    reference_resource_id: str = "USD",
    allow_borrowing: bool = False,
    allow_short_positions: bool = False,
) -> EpisodeDefinition:
    return EpisodeDefinition(
        episode_id="ep_settlement_test",
        title="Settlement Test Episode",
        description="Episode for settlement testing",
        created_at="2026-01-01T00:00:00Z",
        dataset_snapshot=DatasetSnapshotRef(
            snapshot_id="dss_settlement_test",
            source_uri="file:///test/snapshot",
            checksum_sha256="sha256:" + "0" * 64,
            retrieval_time="2026-01-01T00:00:00Z",
            calendar_frequency="1d",
        ),
        calendar=CalendarSpec(
            round_cutoffs=(
                "2026-08-01T00:00:00Z",
                "2026-08-02T00:00:00Z",
                "2026-08-03T00:00:00Z",
                "2026-08-04T00:00:00Z",
            ),
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
            allow_short_positions=allow_short_positions,
            allow_borrowing=allow_borrowing,
            cost_model=CostModelSpec(
                linear_transaction_fee_rate=Decimal("0.001"),
                fixed_transaction_fee=Decimal("1.00"),
                holding_cost_rate=Decimal("0.0"),
            ),
            failure_policy=FailurePolicySpec(),
            constraints=ConstraintsSpec(),
        ),
    )


def _make_account_state(
    policy_id: str = "pol-def_alpha",
    round_index: int = 1,
    as_of_time: str = "2026-08-01T00:00:00Z",
    usd_qty: Decimal = Decimal("100000.00"),
    btc_qty: Decimal = Decimal("0.00"),
) -> VirtualAccountState:
    balances = [BalanceItem(resource_id="USD", quantity=usd_qty)]
    if btc_qty != Decimal("0.00"):
        balances.append(BalanceItem(resource_id="BTC", quantity=btc_qty))
    return VirtualAccountState(
        account_state_id=f"acc-state_rnd_{round_index:03d}_{policy_id}",
        policy_id=policy_id,
        round_index=round_index,
        as_of_time=as_of_time,
        balances=tuple(balances),
        cumulative_costs=(CumulativeCostItem(cost_type="TRANSACTION_FEE", amount=Decimal("0.00")),),
        reference_valuation=ReferenceValuation(
            reference_resource_id="USD",
            unallocated_cash=usd_qty,
            allocated_resources_value=Decimal("0.00"),
            net_total_value=usd_qty,
        ),
        parent_state_hash=None,
    )


def _make_observation(
    *,
    series_id: str = SERIES_ID,
    open_time: str,
    event_time: str,
    knowledge_time: str,
    open_price: str,
    close_price: str = "0.00",
    revision: int = 1,
    observation_id: str | None = None,
) -> ObservationRecord:
    obs_id = observation_id or f"obs_{series_id}_{open_time}_{revision}"
    return ObservationRecord(
        observation_id=obs_id,
        snapshot_id="dss_settlement_test",
        series_id=series_id,
        event_time=event_time,
        knowledge_time=knowledge_time,
        revision=revision,
        payload={"open_time": open_time, "open": open_price, "close": close_price},
    )


def _admit_pending(
    episode: EpisodeDefinition,
    account: VirtualAccountState,
    *,
    action: RequestedAction,
    round_id: str = "rnd_001",
    cutoff: str = "2026-08-01T00:00:00Z",
    decision_id: str = "dec-prop_001",
) -> PendingTransitionRecord:
    proposal = ProposedDecision(
        decision_id=decision_id,
        round_id=round_id,
        policy_id=account.policy_id,
        policy_version_id="pol-ver_alpha_v1",
        knowledge_cutoff=cutoff,
        generated_at=cutoff,
        desired_allocations=(),
        requested_actions=(action,),
        rationale=DecisionRationale(method="test_settlement"),
    )
    result = DeferredAdmissionService.admit_decision(
        episode, account, proposal, round_id, cutoff, RESOURCE_MAP
    )
    assert result.is_newly_admitted
    return result.pending_transition


def _make_pending_directly(
    *,
    policy_id: str = "pol-def_alpha",
    policy_version_id: str = "pol-ver_alpha_v1",
    round_id: str = "rnd_001",
    cutoff: str = "2026-08-01T00:00:00Z",
    predecessor_account_hash: str,
    action: RequestedAction,
    decision_id: str = "dec-prop_001",
    series_id: str = SERIES_ID,
) -> PendingTransitionRecord:
    return PendingTransitionRecord(
        pending_transition_id=f"pnd_{decision_id}",
        decision_id=decision_id,
        round_id=round_id,
        policy_id=policy_id,
        policy_version_id=policy_version_id,
        knowledge_cutoff=cutoff,
        admitted_at=cutoff,
        predecessor_account_hash=predecessor_account_hash,
        requested_action=action,
        target_bar_rule=TargetBarRule(series_id=series_id),
        admission_evidence={"proposal_hash": "sha256:" + "3" * 64},
        status=PendingStatus.ADMITTED_PENDING,
    )


# ==============================================================================
# 1. Full D+2 lifecycle (Probe DP-01)
# ==============================================================================


def test_full_lifecycle_settles_allocate_buy():
    episode = _make_episode_def()
    account = _make_account_state()
    action = RequestedAction(ActionType.ALLOCATE, "BTC", Decimal("1.5"))
    pending = _admit_pending(episode, account, action=action)

    distractor_before = _make_observation(
        open_time="2026-07-31T00:00:00Z",
        event_time="2026-07-31T23:59:59.999Z",
        knowledge_time="2026-08-02T00:00:00Z",
        open_price="59000.00",
        close_price="60000.00",
    )
    target = _make_observation(
        open_time="2026-08-01T00:00:00.000Z",
        event_time="2026-08-01T23:59:59.999Z",
        knowledge_time="2026-08-03T00:00:00Z",
        open_price="62000.00",
        close_price="63000.00",
    )
    all_obs = (distractor_before, target)

    result = DeferredSettlementService.attempt_settlement(
        episode,
        account,
        pending,
        settlement_round_id="rnd_003",
        settlement_round_index=3,
        settlement_time="2026-08-03T00:00:00Z",
        all_observations=all_obs,
        valuation_marks={"BTC": Decimal("63000.00")},
    )

    assert result.is_settled
    assert not result.is_still_pending
    outcome = result.settlement_outcome
    transition = result.deferred_transition
    assert outcome.status == SettlementStatus.SETTLED
    assert outcome.applied_transition_id == transition.transition_id
    assert transition.settlement_outcome_id == outcome.settlement_outcome_id
    assert outcome.settlement_evidence["execution_price"] == "62000.00"
    assert outcome.settlement_evidence["execution_fill_time"] == "2026-08-01T00:00:00.000Z"
    assert outcome.settlement_evidence["observation_knowledge_time"] == "2026-08-03T00:00:00Z"
    assert outcome.settlement_evidence["total_fee_deducted"] == "94.00"

    assert transition.economic_fill_time == "2026-08-01T00:00:00.000Z"
    assert transition.effective_time == "2026-08-03T00:00:00Z"
    assert transition.total_cost_reference_unit == Decimal("94.00")

    new_account = result.next_account
    balances = {b.resource_id: b.quantity for b in new_account.balances}
    assert balances["USD"] == Decimal("6906.00")
    assert balances["BTC"] == Decimal("1.5")
    assert new_account.reference_valuation.allocated_resources_value == Decimal("94500.00")
    assert new_account.reference_valuation.net_total_value == Decimal("101406.00")
    assert new_account.parent_state_hash == account.compute_hash()

    assert validate_data(outcome.to_dict(), SETTLEMENT_OUTCOME_SCHEMA) == []
    assert validate_data(transition.to_dict(), TRANSITION_V2_SCHEMA) == []

    # Repeated identical call is deterministic (hash-idempotent, not durable dedup).
    repeat = DeferredSettlementService.attempt_settlement(
        episode,
        account,
        pending,
        settlement_round_id="rnd_003",
        settlement_round_index=3,
        settlement_time="2026-08-03T00:00:00Z",
        all_observations=all_obs,
        valuation_marks={"BTC": Decimal("63000.00")},
    )
    assert repeat.settlement_outcome.compute_hash() == outcome.compute_hash()
    assert repeat.deferred_transition.compute_hash() == transition.compute_hash()
    assert repeat.next_account.compute_hash() == new_account.compute_hash()


# ==============================================================================
# 2. Still-pending
# ==============================================================================


def test_still_pending_when_bar_not_yet_eligible():
    episode = _make_episode_def()
    account = _make_account_state()
    action = RequestedAction(ActionType.ALLOCATE, "BTC", Decimal("1.5"))
    pending = _admit_pending(episode, account, action=action)

    target_not_yet_eligible = _make_observation(
        open_time="2026-08-01T00:00:00.000Z",
        event_time="2026-08-01T23:59:59.999Z",
        knowledge_time="2026-08-05T00:00:00Z",
        open_price="62000.00",
    )

    result = DeferredSettlementService.attempt_settlement(
        episode,
        account,
        pending,
        settlement_round_id="rnd_003",
        settlement_round_index=3,
        settlement_time="2026-08-03T00:00:00Z",
        all_observations=(target_not_yet_eligible,),
        valuation_marks={},
    )

    assert result.is_still_pending
    assert not result.is_settled
    assert result.settlement_outcome is None
    assert result.deferred_transition is None
    assert result.pending_transition is pending
    assert result.next_account.compute_hash() == account.compute_hash()


def test_still_pending_when_no_bar_ingested_at_all():
    episode = _make_episode_def()
    account = _make_account_state()
    action = RequestedAction(ActionType.ALLOCATE, "BTC", Decimal("1.5"))
    pending = _admit_pending(episode, account, action=action)

    result = DeferredSettlementService.attempt_settlement(
        episode,
        account,
        pending,
        settlement_round_id="rnd_003",
        settlement_round_index=3,
        settlement_time="2026-08-03T00:00:00Z",
        all_observations=(),
        valuation_marks={},
    )
    assert result.is_still_pending


# ==============================================================================
# 3. Deterministic, non-skipping target-bar selection
# ==============================================================================


def test_no_skip_when_earlier_bar_present_but_ineligible():
    """An earlier (correct) bar exists but isn't knowledge-eligible yet; a later,
    already-eligible bar for the same series must NOT be substituted for it."""
    episode = _make_episode_def()
    account = _make_account_state()
    action = RequestedAction(ActionType.ALLOCATE, "BTC", Decimal("1.5"))
    pending = _admit_pending(episode, account, action=action)

    earlier_not_yet_eligible = _make_observation(
        open_time="2026-08-01T00:00:00.000Z",
        event_time="2026-08-01T23:59:59.999Z",
        knowledge_time="2026-08-05T00:00:00Z",
        open_price="62000.00",
    )
    later_already_eligible = _make_observation(
        open_time="2026-08-02T00:00:00.000Z",
        event_time="2026-08-02T23:59:59.999Z",
        knowledge_time="2026-08-02T12:00:00Z",
        open_price="99999.00",
    )

    result = DeferredSettlementService.attempt_settlement(
        episode,
        account,
        pending,
        settlement_round_id="rnd_003",
        settlement_round_index=3,
        settlement_time="2026-08-03T00:00:00Z",
        all_observations=(earlier_not_yet_eligible, later_already_eligible),
        valuation_marks={"BTC": Decimal("99999.00")},
    )

    assert result.is_still_pending, (
        "must wait for the true first bar, not settle against the later, already-eligible one"
    )


def test_accepted_limitation_absent_earlier_bar_settles_against_later_one():
    """Documents the accepted limitation from the frozen plan: when the true
    first bar was never ingested at all (e.g. an exchange halt), this pure
    service has no local signal to detect the gap and settles against the
    next available bar instead. Closing this requires the round-cutoff-aware
    runner (DS-02D2C), which is out of scope for DS-02D2B2. This test exists
    to make the limitation visible and regression-tested, not to endorse it
    as correct settlement economics.
    """
    episode = _make_episode_def()
    account = _make_account_state()
    action = RequestedAction(ActionType.ALLOCATE, "BTC", Decimal("1.5"))
    pending = _admit_pending(episode, account, action=action)

    # The 2026-08-01 bar is entirely absent from the dataset snapshot.
    later_already_eligible = _make_observation(
        open_time="2026-08-02T00:00:00.000Z",
        event_time="2026-08-02T23:59:59.999Z",
        knowledge_time="2026-08-02T12:00:00Z",
        open_price="30000.00",
    )

    result = DeferredSettlementService.attempt_settlement(
        episode,
        account,
        pending,
        settlement_round_id="rnd_003",
        settlement_round_index=3,
        settlement_time="2026-08-03T00:00:00Z",
        all_observations=(later_already_eligible,),
        valuation_marks={"BTC": Decimal("30000.00")},
    )

    assert result.is_settled
    assert result.settlement_outcome.settlement_evidence["execution_price"] == "30000.00"


def test_open_time_governs_not_event_time():
    """A bar whose open_time is before cutoff but event_time (close) is after
    cutoff must be excluded; a bar whose open_time is at/after cutoff but
    event_time is also after cutoff must be selected on open_time alone."""
    episode = _make_episode_def()
    account = _make_account_state()
    action = RequestedAction(ActionType.ALLOCATE, "BTC", Decimal("1.5"))
    pending = _admit_pending(episode, account, action=action)

    # open_time before cutoff, event_time (close) after cutoff: must be excluded.
    stale_bar_with_late_close = _make_observation(
        open_time="2026-07-31T00:00:00.000Z",
        event_time="2026-08-01T23:59:59.999Z",
        knowledge_time="2026-08-02T00:00:00Z",
        open_price="1.00",
    )
    correct_bar = _make_observation(
        open_time="2026-08-01T00:00:00.000Z",
        event_time="2026-08-01T23:59:59.999Z",
        knowledge_time="2026-08-03T00:00:00Z",
        open_price="62000.00",
    )

    result = DeferredSettlementService.attempt_settlement(
        episode,
        account,
        pending,
        settlement_round_id="rnd_003",
        settlement_round_index=3,
        settlement_time="2026-08-03T00:00:00Z",
        all_observations=(stale_bar_with_late_close, correct_bar),
        valuation_marks={"BTC": Decimal("62000.00")},
    )

    assert result.is_settled
    assert result.settlement_outcome.settlement_evidence["execution_price"] == "62000.00"


# ==============================================================================
# 4. Exogenous terminal rejection
# ==============================================================================


def test_terminate_unsettled_missing_execution_bar():
    episode = _make_episode_def()
    account = _make_account_state()
    action = RequestedAction(ActionType.ALLOCATE, "BTC", Decimal("1.5"))
    pending = _admit_pending(episode, account, action=action)

    result = DeferredSettlementService.terminate_unsettled(
        episode,
        account,
        pending,
        settlement_round_id="rnd_005",
        settlement_time="2026-08-05T00:00:00Z",
        reason_code=REJECTION_MISSING_EXECUTION_BAR,
    )

    assert not result.is_settled and not result.is_still_pending
    assert result.settlement_outcome.status == SettlementStatus.REJECTED
    assert [r.code for r in result.settlement_outcome.rejection_reasons] == [
        REJECTION_MISSING_EXECUTION_BAR
    ]
    assert result.settlement_outcome.applied_transition_id is None
    assert result.deferred_transition is None
    assert result.next_account.compute_hash() == account.compute_hash()
    assert validate_data(result.settlement_outcome.to_dict(), SETTLEMENT_OUTCOME_SCHEMA) == []


@pytest.mark.parametrize(
    "reason_code",
    [REJECTION_UNSETTLED_EPISODE_TERMINATION, REJECTION_EPISODE_CANCELLED],
)
def test_terminate_unsettled_exogenous_reasons(reason_code):
    episode = _make_episode_def()
    account = _make_account_state()
    action = RequestedAction(ActionType.ALLOCATE, "BTC", Decimal("1.5"))
    pending = _admit_pending(episode, account, action=action)

    result = DeferredSettlementService.terminate_unsettled(
        episode,
        account,
        pending,
        settlement_round_id="rnd_002",
        settlement_time="2026-08-02T00:00:00Z",
        reason_code=reason_code,
    )
    assert result.settlement_outcome.status == SettlementStatus.REJECTED
    assert [r.code for r in result.settlement_outcome.rejection_reasons] == [reason_code]
    assert result.next_account is account


def test_terminate_unsettled_rejects_unknown_reason_code():
    episode = _make_episode_def()
    account = _make_account_state()
    action = RequestedAction(ActionType.ALLOCATE, "BTC", Decimal("1.5"))
    pending = _admit_pending(episode, account, action=action)

    with pytest.raises(ValueError):
        DeferredSettlementService.terminate_unsettled(
            episode,
            account,
            pending,
            settlement_round_id="rnd_002",
            settlement_time="2026-08-02T00:00:00Z",
            reason_code="NOT_A_REAL_CODE",
        )


# ==============================================================================
# 5. Revision resolution (Probe DP-03)
# ==============================================================================


def test_revision_resolution_uses_highest_eligible():
    episode = _make_episode_def()
    account = _make_account_state()
    action = RequestedAction(ActionType.ALLOCATE, "BTC", Decimal("1.5"))
    pending = _admit_pending(episode, account, action=action)

    revision_1 = _make_observation(
        open_time="2026-08-01T00:00:00.000Z",
        event_time="2026-08-01T23:59:59.999Z",
        knowledge_time="2026-08-03T00:00:00Z",
        open_price="62000.00",
        revision=1,
        observation_id="obs_rev1",
    )
    revision_2_not_yet_eligible = _make_observation(
        open_time="2026-08-01T00:00:00.000Z",
        event_time="2026-08-01T23:59:59.999Z",
        knowledge_time="2026-08-06T00:00:00Z",
        open_price="62500.00",
        revision=2,
        observation_id="obs_rev2",
    )

    result = DeferredSettlementService.attempt_settlement(
        episode,
        account,
        pending,
        settlement_round_id="rnd_003",
        settlement_round_index=3,
        settlement_time="2026-08-03T00:00:00Z",
        all_observations=(revision_1, revision_2_not_yet_eligible),
        valuation_marks={"BTC": Decimal("62000.00")},
    )
    assert result.is_settled
    assert result.settlement_outcome.settlement_evidence["selected_revision"] == 1
    assert result.settlement_outcome.settlement_evidence["execution_price"] == "62000.00"

    # Once revision 2 also becomes eligible, it is the highest eligible revision.
    revision_2_eligible = replace(
        revision_2_not_yet_eligible, knowledge_time="2026-08-03T00:00:00Z"
    )
    result_2 = DeferredSettlementService.attempt_settlement(
        episode,
        account,
        pending,
        settlement_round_id="rnd_003",
        settlement_round_index=3,
        settlement_time="2026-08-03T00:00:00Z",
        all_observations=(revision_1, revision_2_eligible),
        valuation_marks={"BTC": Decimal("62500.00")},
    )
    assert result_2.is_settled
    assert result_2.settlement_outcome.settlement_evidence["selected_revision"] == 2
    assert result_2.settlement_outcome.settlement_evidence["execution_price"] == "62500.00"


# ==============================================================================
# 6. Financial infeasibility at settlement (Probe DP-04, short positions)
# ==============================================================================


def test_insufficient_funds_at_settlement():
    episode = _make_episode_def()
    account = _make_account_state(usd_qty=Decimal("65000.00"))
    action = RequestedAction(ActionType.ALLOCATE, "BTC", Decimal("1.0"))
    pending = _admit_pending(episode, account, action=action)

    target = _make_observation(
        open_time="2026-08-01T00:00:00.000Z",
        event_time="2026-08-01T23:59:59.999Z",
        knowledge_time="2026-08-03T00:00:00Z",
        open_price="70000.00",
    )

    result = DeferredSettlementService.attempt_settlement(
        episode,
        account,
        pending,
        settlement_round_id="rnd_003",
        settlement_round_index=3,
        settlement_time="2026-08-03T00:00:00Z",
        all_observations=(target,),
        valuation_marks={"BTC": Decimal("70000.00")},
    )

    assert not result.is_settled and not result.is_still_pending
    outcome = result.settlement_outcome
    assert [r.code for r in outcome.rejection_reasons] == [
        REJECTION_INSUFFICIENT_FUNDS_AT_SETTLEMENT
    ]
    assert outcome.applied_transition_id is None
    assert result.deferred_transition is None
    assert result.next_account.compute_hash() == account.compute_hash()
    assert outcome.settlement_evidence["cash_available"] == "65000.00"
    assert "cash_required" in outcome.settlement_evidence
    assert validate_data(outcome.to_dict(), SETTLEMENT_OUTCOME_SCHEMA) == []


def test_short_positions_forbidden():
    episode = _make_episode_def(allow_short_positions=False)
    account = _make_account_state(btc_qty=Decimal("1.0"))
    action = RequestedAction(ActionType.TRANSFER, "BTC", Decimal("-2.0"))
    pending = _admit_pending(episode, account, action=action)

    target = _make_observation(
        open_time="2026-08-01T00:00:00.000Z",
        event_time="2026-08-01T23:59:59.999Z",
        knowledge_time="2026-08-03T00:00:00Z",
        open_price="62000.00",
    )

    result = DeferredSettlementService.attempt_settlement(
        episode,
        account,
        pending,
        settlement_round_id="rnd_003",
        settlement_round_index=3,
        settlement_time="2026-08-03T00:00:00Z",
        all_observations=(target,),
        valuation_marks={"BTC": Decimal("62000.00")},
    )

    assert not result.is_settled and not result.is_still_pending
    assert [r.code for r in result.settlement_outcome.rejection_reasons] == [
        REJECTION_SHORT_POSITIONS_FORBIDDEN
    ]
    assert result.next_account.compute_hash() == account.compute_hash()


# ==============================================================================
# 7. Invalid execution price
# ==============================================================================


@pytest.mark.parametrize(
    "open_payload",
    ["0.00", "-5.00", "not_a_number", None],
)
def test_invalid_execution_price_has_empty_evidence(open_payload):
    episode = _make_episode_def()
    account = _make_account_state()
    action = RequestedAction(ActionType.ALLOCATE, "BTC", Decimal("1.0"))
    pending = _admit_pending(episode, account, action=action)

    payload = {"open_time": "2026-08-01T00:00:00.000Z", "close": "60000.00"}
    if open_payload is not None:
        payload["open"] = open_payload
    target = ObservationRecord(
        observation_id="obs_bad_price",
        snapshot_id="dss_settlement_test",
        series_id=SERIES_ID,
        event_time="2026-08-01T23:59:59.999Z",
        knowledge_time="2026-08-03T00:00:00Z",
        revision=1,
        payload=payload,
    )

    result = DeferredSettlementService.attempt_settlement(
        episode,
        account,
        pending,
        settlement_round_id="rnd_003",
        settlement_round_index=3,
        settlement_time="2026-08-03T00:00:00Z",
        all_observations=(target,),
        valuation_marks={},
    )

    assert not result.is_settled and not result.is_still_pending
    outcome = result.settlement_outcome
    assert [r.code for r in outcome.rejection_reasons] == [REJECTION_INVALID_EXECUTION_PRICE]
    assert outcome.settlement_evidence == {}
    assert result.next_account.compute_hash() == account.compute_hash()
    assert validate_data(outcome.to_dict(), SETTLEMENT_OUTCOME_SCHEMA) == []


# ==============================================================================
# 8. Missing valuation mark
# ==============================================================================


def test_missing_valuation_mark_blocks_settlement():
    episode = _make_episode_def()
    # Account already holds ETH with no injected mark for it.
    account = VirtualAccountState(
        account_state_id="acc-state_rnd_001_pol-def_alpha",
        policy_id="pol-def_alpha",
        round_index=1,
        as_of_time="2026-08-01T00:00:00Z",
        balances=(
            BalanceItem(resource_id="USD", quantity=Decimal("100000.00")),
            BalanceItem(resource_id="ETH", quantity=Decimal("10.0")),
        ),
        cumulative_costs=(CumulativeCostItem(cost_type="TRANSACTION_FEE", amount=Decimal("0.00")),),
        reference_valuation=ReferenceValuation(
            reference_resource_id="USD",
            unallocated_cash=Decimal("100000.00"),
            allocated_resources_value=Decimal("30000.00"),
            net_total_value=Decimal("130000.00"),
        ),
        parent_state_hash=None,
    )
    action = RequestedAction(ActionType.ALLOCATE, "BTC", Decimal("1.0"))
    pending = _admit_pending(episode, account, action=action)

    target = _make_observation(
        open_time="2026-08-01T00:00:00.000Z",
        event_time="2026-08-01T23:59:59.999Z",
        knowledge_time="2026-08-03T00:00:00Z",
        open_price="62000.00",
    )

    result = DeferredSettlementService.attempt_settlement(
        episode,
        account,
        pending,
        settlement_round_id="rnd_003",
        settlement_round_index=3,
        settlement_time="2026-08-03T00:00:00Z",
        all_observations=(target,),
        valuation_marks={"BTC": Decimal("62000.00")},  # ETH mark missing
    )

    assert not result.is_settled and not result.is_still_pending
    assert [r.code for r in result.settlement_outcome.rejection_reasons] == [
        REJECTION_MISSING_VALUATION_MARK
    ]
    assert result.next_account.compute_hash() == account.compute_hash()


# ==============================================================================
# 9. Signed TRANSFER and ALLOCATE exact rounding
# ==============================================================================


def test_signed_transfer_credit_direction_settles():
    episode = _make_episode_def()
    account = _make_account_state(btc_qty=Decimal("2.0"))
    action = RequestedAction(ActionType.TRANSFER, "BTC", Decimal("-1.0"))
    pending = _admit_pending(episode, account, action=action)

    target = _make_observation(
        open_time="2026-08-01T00:00:00.000Z",
        event_time="2026-08-01T23:59:59.999Z",
        knowledge_time="2026-08-03T00:00:00Z",
        open_price="50000.00",
    )
    result = DeferredSettlementService.attempt_settlement(
        episode,
        account,
        pending,
        settlement_round_id="rnd_003",
        settlement_round_index=3,
        settlement_time="2026-08-03T00:00:00Z",
        all_observations=(target,),
        valuation_marks={"BTC": Decimal("50000.00")},
    )
    assert result.is_settled
    balances = {b.resource_id: b.quantity for b in result.next_account.balances}
    # notional = 50000.00, fee = 50.00 + 1.00 = 51.00, credited cash = 50000-51=49949.00
    assert balances["BTC"] == Decimal("1.0")
    assert balances["USD"] == Decimal("149949.00")


def test_signed_transfer_debit_direction_settles():
    episode = _make_episode_def()
    account = _make_account_state()
    action = RequestedAction(ActionType.TRANSFER, "BTC", Decimal("1.0"))
    pending = _admit_pending(episode, account, action=action)

    target = _make_observation(
        open_time="2026-08-01T00:00:00.000Z",
        event_time="2026-08-01T23:59:59.999Z",
        knowledge_time="2026-08-03T00:00:00Z",
        open_price="50000.00",
    )
    result = DeferredSettlementService.attempt_settlement(
        episode,
        account,
        pending,
        settlement_round_id="rnd_003",
        settlement_round_index=3,
        settlement_time="2026-08-03T00:00:00Z",
        all_observations=(target,),
        valuation_marks={"BTC": Decimal("50000.00")},
    )
    assert result.is_settled
    balances = {b.resource_id: b.quantity for b in result.next_account.balances}
    # notional = 50000.00, fee = 51.00, debited cash = 100000-50000-51=49949.00
    assert balances["BTC"] == Decimal("1.0")
    assert balances["USD"] == Decimal("49949.00")


# ==============================================================================
# 10. Invalid caller context
# ==============================================================================


def test_foreign_pending_raises():
    episode = _make_episode_def()
    account_a = _make_account_state(policy_id="pol-def_alpha")
    account_b = _make_account_state(policy_id="pol-def_beta")
    action = RequestedAction(ActionType.ALLOCATE, "BTC", Decimal("1.0"))
    pending_a = _admit_pending(episode, account_a, action=action)

    with pytest.raises(ValueError, match="does not match"):
        DeferredSettlementService.attempt_settlement(
            episode,
            account_b,
            pending_a,
            settlement_round_id="rnd_003",
            settlement_round_index=3,
            settlement_time="2026-08-03T00:00:00Z",
            all_observations=(),
            valuation_marks={},
        )


def test_predecessor_hash_mismatch_raises():
    episode = _make_episode_def()
    account = _make_account_state()
    action = RequestedAction(ActionType.ALLOCATE, "BTC", Decimal("1.0"))
    pending = _admit_pending(episode, account, action=action)

    drifted_account = _make_account_state(usd_qty=Decimal("999.00"))

    with pytest.raises(ValueError, match="predecessor_account_hash"):
        DeferredSettlementService.attempt_settlement(
            episode,
            drifted_account,
            pending,
            settlement_round_id="rnd_003",
            settlement_round_index=3,
            settlement_time="2026-08-03T00:00:00Z",
            all_observations=(),
            valuation_marks={},
        )


def test_malformed_round_id_raises():
    episode = _make_episode_def()
    account = _make_account_state()
    action = RequestedAction(ActionType.ALLOCATE, "BTC", Decimal("1.0"))
    pending = _admit_pending(episode, account, action=action)

    with pytest.raises(ValueError, match="settlement_round_id"):
        DeferredSettlementService.attempt_settlement(
            episode,
            account,
            pending,
            settlement_round_id="not-a-round-id",
            settlement_round_index=3,
            settlement_time="2026-08-03T00:00:00Z",
            all_observations=(),
            valuation_marks={},
        )


def test_non_utc_settlement_time_raises():
    episode = _make_episode_def()
    account = _make_account_state()
    action = RequestedAction(ActionType.ALLOCATE, "BTC", Decimal("1.0"))
    pending = _admit_pending(episode, account, action=action)

    with pytest.raises(Exception):
        DeferredSettlementService.attempt_settlement(
            episode,
            account,
            pending,
            settlement_round_id="rnd_003",
            settlement_round_index=3,
            settlement_time="2026-08-03T00:00:00+02:00",
            all_observations=(),
            valuation_marks={},
        )


def test_settlement_time_before_cutoff_raises():
    episode = _make_episode_def()
    account = _make_account_state()
    action = RequestedAction(ActionType.ALLOCATE, "BTC", Decimal("1.0"))
    pending = _admit_pending(episode, account, action=action)

    with pytest.raises(ValueError, match="cannot precede"):
        DeferredSettlementService.attempt_settlement(
            episode,
            account,
            pending,
            settlement_round_id="rnd_000",
            settlement_round_index=0,
            settlement_time="2026-07-31T00:00:00Z",
            all_observations=(),
            valuation_marks={},
        )


def test_hold_pending_is_structurally_impossible():
    episode = _make_episode_def()
    account = _make_account_state()
    hold_pending = _make_pending_directly(
        predecessor_account_hash=account.compute_hash(),
        action=RequestedAction(ActionType.HOLD, "USD", Decimal("0")),
    )
    with pytest.raises(TypeError):
        DeferredSettlementService.attempt_settlement(
            episode,
            account,
            hold_pending,
            settlement_round_id="rnd_003",
            settlement_round_index=3,
            settlement_time="2026-08-03T00:00:00Z",
            all_observations=(),
            valuation_marks={},
        )


# ==============================================================================
# 11. Immutability
# ==============================================================================


def test_input_and_output_immutability_preserved():
    episode = _make_episode_def()
    account = _make_account_state()
    account_hash_before = account.compute_hash()
    action = RequestedAction(ActionType.ALLOCATE, "BTC", Decimal("1.5"))
    pending = _admit_pending(episode, account, action=action)
    pending_hash_before = pending.compute_hash()

    target = _make_observation(
        open_time="2026-08-01T00:00:00.000Z",
        event_time="2026-08-01T23:59:59.999Z",
        knowledge_time="2026-08-03T00:00:00Z",
        open_price="62000.00",
    )
    all_obs = (target,)
    marks = {"BTC": Decimal("62000.00")}

    result = DeferredSettlementService.attempt_settlement(
        episode,
        account,
        pending,
        settlement_round_id="rnd_003",
        settlement_round_index=3,
        settlement_time="2026-08-03T00:00:00Z",
        all_observations=all_obs,
        valuation_marks=marks,
    )
    outcome_hash = result.settlement_outcome.compute_hash()
    transition_hash = result.deferred_transition.compute_hash()

    # Attempt to mutate the caller's own mutable dict/copies after the call.
    marks_copy = copy.deepcopy(marks)
    marks_copy["BTC"] = Decimal("1.00")

    assert account.compute_hash() == account_hash_before
    assert pending.compute_hash() == pending_hash_before
    assert result.settlement_outcome.compute_hash() == outcome_hash
    assert result.deferred_transition.compute_hash() == transition_hash

    with pytest.raises(TypeError):
        result.settlement_outcome.settlement_evidence["execution_price"] = "1.00"


# ==============================================================================
# 12. Result DTO exclusivity
# ==============================================================================


def test_result_dto_rejects_inconsistent_states():
    episode = _make_episode_def()
    account = _make_account_state()
    action = RequestedAction(ActionType.ALLOCATE, "BTC", Decimal("1.0"))
    pending = _admit_pending(episode, account, action=action)

    with pytest.raises(ValueError):
        DeferredSettlementResult(
            pending_transition=pending,
            settlement_outcome=None,
            deferred_transition=None,
            next_account=account,
            is_settled=True,
            is_still_pending=True,
        )
