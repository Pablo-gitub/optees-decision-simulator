"""Declarative probes for the deferred-settlement contract (DS-D3T).

This contract gate must not implement the future settlement engine in tests.
DS-02D2 must prove these frozen decisions through production code.
"""

from dataclasses import asdict, dataclass

import pytest

from simulator.domain.canonical import compute_record_hash
from simulator.domain.time import parse_utc_timestamp


@dataclass(frozen=True)
class DeferredSettlementCase:
    case_id: str
    cutoff: str
    fill: str | None
    knowledge: str | None
    settlement: str
    terminal_status: str
    reason: str | None
    mutates_account: bool


CASES = (
    DeferredSettlementCase(
        "normal_d_plus_2",
        "2026-08-01T00:00:00Z",
        "2026-08-01T00:00:00.000Z",
        "2026-08-03T00:00:00Z",
        "2026-08-03T00:00:00Z",
        "SETTLED",
        None,
        True,
    ),
    DeferredSettlementCase(
        "missing_bar",
        "2026-08-01T00:00:00Z",
        None,
        None,
        "2026-08-04T00:00:00Z",
        "REJECTED",
        "MISSING_EXECUTION_BAR",
        False,
    ),
    DeferredSettlementCase(
        "insufficient_funds",
        "2026-08-01T00:00:00Z",
        "2026-08-01T00:00:00.000Z",
        "2026-08-03T00:00:00Z",
        "2026-08-03T00:00:00Z",
        "REJECTED",
        "INSUFFICIENT_FUNDS_AT_SETTLEMENT",
        False,
    ),
    DeferredSettlementCase(
        "episode_termination",
        "2026-08-10T00:00:00Z",
        "2026-08-10T00:00:00.000Z",
        "2026-08-12T00:00:00Z",
        "2026-08-11T00:00:00Z",
        "REJECTED",
        "UNSETTLED_EPISODE_TERMINATION",
        False,
    ),
    DeferredSettlementCase(
        "episode_cancellation",
        "2026-08-01T00:00:00Z",
        "2026-08-01T00:00:00.000Z",
        "2026-08-03T00:00:00Z",
        "2026-08-02T12:00:00Z",
        "REJECTED",
        "EPISODE_CANCELLED",
        False,
    ),
)


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.case_id)
def test_terminal_decision_matrix_is_closed(case: DeferredSettlementCase) -> None:
    assert case.terminal_status in {"SETTLED", "REJECTED"}
    assert case.mutates_account is (case.terminal_status == "SETTLED")
    assert (case.reason is None) is (case.terminal_status == "SETTLED")


@pytest.mark.parametrize(
    "case",
    [case for case in CASES if case.knowledge is not None],
    ids=lambda case: case.case_id,
)
def test_successful_settlement_never_precedes_knowledge(
    case: DeferredSettlementCase,
) -> None:
    assert parse_utc_timestamp(case.cutoff) <= parse_utc_timestamp(case.fill)
    if case.terminal_status == "SETTLED":
        assert parse_utc_timestamp(case.fill) < parse_utc_timestamp(case.knowledge)
        assert parse_utc_timestamp(case.knowledge) <= parse_utc_timestamp(case.settlement)


def test_revision_boundary_is_frozen_at_settlement() -> None:
    committed = {
        "pending_transition_id": "pnd_dec-revision",
        "selected_revision": 2,
        "execution_price": "52000.00",
        "settlement_time": "2026-08-03T00:00:00Z",
    }
    committed_hash = compute_record_hash(committed)
    late_revision = {"revision": 3, "knowledge_time": "2026-08-06T00:00:00Z"}

    assert late_revision["knowledge_time"] > committed["settlement_time"]
    assert compute_record_hash(committed) == committed_hash


def test_shared_timestamp_priority_is_frozen() -> None:
    phases = (
        "OBSERVATION_ELIGIBILITY",
        "PENDING_SETTLEMENT",
        "POLICY_DELIVERY",
        "POLICY_PROPOSAL",
        "ROUND_COMMIT",
    )
    assert phases.index("PENDING_SETTLEMENT") < phases.index("POLICY_PROPOSAL")


def test_second_non_hold_is_rejected_while_pending() -> None:
    decision = {
        "existing_pending_id": "pnd_dec-first",
        "new_action": "ALLOCATE",
        "terminal_status": "REJECTED",
        "reason": "POLICY_HAS_PENDING_SETTLEMENT",
        "mutates_account": False,
    }
    assert decision["terminal_status"] == "REJECTED"
    assert decision["reason"] == "POLICY_HAS_PENDING_SETTLEMENT"
    assert decision["mutates_account"] is False


def test_declarative_probes_are_hash_deterministic() -> None:
    payload = [asdict(case) for case in CASES]
    assert compute_record_hash(payload) == compute_record_hash([asdict(case) for case in CASES])
