"""Contract test: validates domain entity dictionaries against the authoritative v1 JSON Schemas."""

import importlib.util
import json
from decimal import Decimal
from pathlib import Path

from simulator.application.policies.reactive import ReactiveObservationPolicy
from simulator.application.policies.static import StaticBaselinePolicy
from simulator.application.services.runner import EpisodeRunner
from simulator.domain.lifecycle import (
    ActionType,
    DivergenceCategory,
    PendingStatus,
    PolicyType,
    ReplayMode,
    ReplayStatus,
    SettlementStatus,
)
from simulator.domain.models import (
    DivergenceReport,
    EpisodeDefinition,
    OpteesCallReceipt,
    PendingTransitionRecord,
    PolicyDefinition,
    PolicyVersion,
    RejectionReason,
    ReplayReport,
    RequestedAction,
    SettlementOutcome,
    TargetBarRule,
    TimingSpec,
    ValidationReceipt,
)
from simulator.infrastructure.adapters.in_memory_clock import InMemoryClock
from simulator.infrastructure.adapters.in_memory_store import InMemoryStore
from simulator.infrastructure.adapters.synthetic_dataset import SyntheticDatasetAdapter
from simulator.infrastructure.adapters.synthetic_pricing import SyntheticPricingAdapter

REPO_ROOT = Path(__file__).resolve().parents[4]

# Dynamically import validate_data from tools/validate_contracts.py
validator_path = REPO_ROOT / "tools" / "validate_contracts.py"
spec = importlib.util.spec_from_file_location("validate_contracts", str(validator_path))
validate_contracts = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
spec.loader.exec_module(validate_contracts)  # type: ignore[union-attr]
validate_data = validate_contracts.validate_data


def _load_schema(schema_filename: str) -> dict:
    schema_path = REPO_ROOT / "docs" / "contracts" / "schemas" / schema_filename
    with open(schema_path, "r", encoding="utf-8") as f:
        return json.load(f)


def test_all_18_entities_schema_conformance(synthetic_episode_def: EpisodeDefinition) -> None:
    # Set up and execute a 3-round episode to populate all runtime domain models
    store = InMemoryStore()
    dataset = SyntheticDatasetAdapter()
    clock = InMemoryClock()
    policies = {
        "pol-def_static_baseline": StaticBaselinePolicy(),
        "pol-def_reactive_baseline": ReactiveObservationPolicy(),
    }
    runner = EpisodeRunner(store, dataset, clock, policies, SyntheticPricingAdapter())
    ep_def = synthetic_episode_def
    run_id = "ep-run_schema_test"

    runner.initialize_episode(ep_def, run_id)
    runner.run_all_rounds(run_id)

    # 1. EpisodeDefinition
    schema_ep_def = _load_schema("episode_definition.v1.json")
    errs = validate_data(ep_def.to_dict(), schema_ep_def)
    assert not errs, f"EpisodeDefinition errors: {errs}"

    # 2. EpisodeRun
    schema_ep_run = _load_schema("episode_run.v1.json")
    run_rec = store.get_episode_run(run_id)
    assert run_rec is not None
    errs = validate_data(run_rec.to_dict(), schema_ep_run)
    assert not errs, f"EpisodeRun errors: {errs}"

    # 3. PolicyDefinition
    schema_pol_def = _load_schema("policy_definition.v1.json")
    pol_def = PolicyDefinition(
        policy_id="pol-def_static_baseline",
        name="Static Baseline",
        description="Holds positions",
        author="Simulator Test",
        created_at="2026-08-01T00:00:00Z",
    )
    errs = validate_data(pol_def.to_dict(), schema_pol_def)
    assert not errs, f"PolicyDefinition errors: {errs}"

    # 4. PolicyVersion
    schema_pol_ver = _load_schema("policy_version.v1.json")
    pol_ver = PolicyVersion(
        policy_version_id="pol-ver_static_v1",
        policy_id="pol-def_static_baseline",
        version="1.0.0",
        policy_type=PolicyType.STATIC_BASELINE,
        required_capabilities=(),
        required_observations=(),
        hyperparameters={},
        code_provenance={
            "repository_uri": "https://github.com/example/repo",
            "commit_hash": "16bd48ee0bbbb8f6eca4855624a32ab662d53ae8",
            "entrypoint": "simulator.application.policies.static:StaticBaselinePolicy",
            "artifact_hash": (
                "sha256:0000000000000000000000000000000000000000000000000000000000000000"
            ),
        },
        declared_tolerances={"numerical_epsilon": 0.000001},
        created_at="2026-08-01T00:00:00Z",
    )
    errs = validate_data(pol_ver.to_dict(), schema_pol_ver)
    assert not errs, f"PolicyVersion errors: {errs}"

    # 5. DatasetSnapshotManifest
    schema_ds_snap = _load_schema("dataset_snapshot.v1.json")
    manifest = dataset.get_manifest()
    errs = validate_data(manifest.to_dict(), schema_ds_snap)
    assert not errs, f"DatasetSnapshotManifest errors: {errs}"

    # 6. ObservationRecord
    schema_obs = _load_schema("observation.v1.json")
    for obs in dataset.get_all_observations():
        errs = validate_data(obs.to_dict(), schema_obs)
        assert not errs, f"ObservationRecord errors: {errs}"

    # 7. RoundRecord
    schema_round = _load_schema("round.v1.json")
    rounds = store.get_rounds(run_id)
    assert len(rounds) == 3
    for r in rounds:
        errs = validate_data(r.to_dict(), schema_round)
        assert not errs, f"RoundRecord errors: {errs}"

    # 8. ProposedDecision
    schema_prop = _load_schema("proposed_decision.v1.json")
    for prop in store._proposed_decisions.values():
        errs = validate_data(prop.to_dict(), schema_prop)
        assert not errs, f"ProposedDecision errors: {errs}"

    # 9. DecisionOutcome
    schema_out = _load_schema("decision_outcome.v1.json")
    for out in store._decision_outcomes.values():
        errs = validate_data(out.to_dict(), schema_out)
        assert not errs, f"DecisionOutcome errors: {errs}"

    # 10. TransitionRecord
    schema_trans = _load_schema("transition.v1.json")
    for trn in store._transitions.values():
        errs = validate_data(trn.to_dict(), schema_trans)
        assert not errs, f"TransitionRecord errors: {errs}"

    # 11. VirtualAccountState
    schema_acc = _load_schema("virtual_account_state.v1.json")
    for state_list in store._account_states.values():
        for state in state_list:
            errs = validate_data(state.to_dict(), schema_acc)
            assert not errs, f"VirtualAccountState errors: {errs}"

    # 12. MetricRecord
    schema_metric = _load_schema("metric_record.v1.json")
    metrics = store.get_metric_records(run_id)
    assert len(metrics) > 0
    for m in metrics:
        errs = validate_data(m.to_dict(), schema_metric)
        assert not errs, f"MetricRecord errors: {errs}"

    # 13. OpteesCallReceipt
    schema_receipt = _load_schema("optees_call_receipt.v1.json")
    receipt = OpteesCallReceipt(
        receipt_id="rcp-opt_receipt_001",
        round_id="rnd_0",
        policy_id="pol-def_test",
        capability_id="forecast_lp",
        contract_versions={
            "problem_schema": "1.0.0",
            "result_schema": "1.0.0",
        },
        transport="MCP_STDIO",
        request_hash="sha256:0000000000000000000000000000000000000000000000000000000000000000",
        response_hash="sha256:1111111111111111111111111111111111111111111111111111111111111111",
        validation_receipt=ValidationReceipt(
            status="VALID", validator_version="1.0.0", diagnostics=()
        ),
        solver_status="OPTIMAL",
        timing=TimingSpec("2026-08-01T00:00:00Z", "2026-08-01T00:00:01Z", 1000.0),
        redacted_transport_metadata={"transport_sanitized": True},
    )
    errs = validate_data(receipt.to_dict(), schema_receipt)
    assert not errs, f"OpteesCallReceipt errors: {errs}"

    # 14. ReplayReport
    schema_rep = _load_schema("replay_report.v1.json")
    rep = ReplayReport(
        report_id="rep-rep_test_01",
        original_run_id=run_id,
        replay_mode=ReplayMode.RECORD_REPLAY,
        executed_at="2026-08-01T00:00:00Z",
        overall_status=ReplayStatus.MATCH,
        rounds_evaluated=3,
        matched_round_count=3,
        diverged_round_count=0,
        initial_state_hash_match=True,
        final_state_hash_match=True,
        divergence_report_ids=(),
    )
    errs = validate_data(rep.to_dict(), schema_rep)
    assert not errs, f"ReplayReport errors: {errs}"

    # 15. DivergenceReport
    schema_div = _load_schema("divergence_report.v1.json")
    div = DivergenceReport(
        divergence_id="div_test_01",
        replay_report_id="rep-rep_test_01",
        round_index=1,
        policy_id="pol-def_reactive_baseline",
        category=DivergenceCategory.DECISION_DIVERGENCE,
        declared_epsilon=0.0,
        observed_max_delta=0.0,
        field_path="proposed_decision",
        original_value_hash="sha256:0000000000000000000000000000000000000000000000000000000000000000",
        replayed_value_hash="sha256:1111111111111111111111111111111111111111111111111111111111111111",
        details={"reason": "Sample divergence"},
    )
    errs = validate_data(div.to_dict(), schema_div)
    assert not errs, f"DivergenceReport errors: {errs}"

    # 16. PendingTransitionRecord
    schema_pnd = _load_schema("pending_transition.v1.json")
    pnd = PendingTransitionRecord(
        pending_transition_id="pnd_test_01",
        decision_id="dec-prop_round0_reactive_accept",
        round_id="rnd_round_0",
        policy_id="pol-def_reactive_baseline",
        policy_version_id="pol-ver_reactive_v1",
        knowledge_cutoff="2026-08-01T00:00:00Z",
        admitted_at="2026-08-01T00:00:00Z",
        predecessor_account_hash="sha256:0000000000000000000000000000000000000000000000000000000000000000",
        requested_action=RequestedAction(
            action_type=ActionType.ALLOCATE,
            resource_id="BTC",
            quantity=Decimal("1.50000000"),
            parameters={"target_series": "BTC_USDT_PRICE_1D"},
        ),
        target_bar_rule=TargetBarRule(
            series_id="BTC_USDT_PRICE_1D",
            selection_rule="FIRST_OPEN_GE_CUTOFF",
            expected_open_time="2026-08-01T00:00:00.000Z",
        ),
        admission_evidence={"syntax_validation_passed": True},
        status=PendingStatus.ADMITTED_PENDING,
    )
    errs = validate_data(pnd.to_dict(), schema_pnd)
    assert not errs, f"PendingTransitionRecord errors: {errs}"

    # 17. SettlementOutcome (SETTLED)
    schema_set = _load_schema("settlement_outcome.v1.json")
    set_outcome = SettlementOutcome(
        settlement_outcome_id="set-out_test_01",
        pending_transition_id="pnd_test_01",
        decision_id="dec-prop_round0_reactive_accept",
        round_id="rnd_round_2",
        policy_id="pol-def_reactive_baseline",
        status=SettlementStatus.SETTLED,
        settled_at="2026-08-03T00:00:01Z",
        applied_transition_id="trn_round2_reactive_transition",
        rejection_reasons=(),
        settlement_evidence={
            "observation_id": "obs_BTC_20260801_r1",
            "selected_revision": 1,
            "execution_fill_time": "2026-08-01T00:00:00Z",
            "observation_knowledge_time": "2026-08-03T00:00:00Z",
            "execution_price": "60000.00",
        },
    )
    errs = validate_data(set_outcome.to_dict(), schema_set)
    assert not errs, f"SettlementOutcome (SETTLED) errors: {errs}"

    # 18. SettlementOutcome (REJECTED)
    rej_outcome = SettlementOutcome(
        settlement_outcome_id="set-out_test_02",
        pending_transition_id="pnd_test_01",
        decision_id="dec-prop_round0_reactive_accept",
        round_id="rnd_round_2",
        policy_id="pol-def_reactive_baseline",
        status=SettlementStatus.REJECTED,
        settled_at="2026-08-03T00:00:01Z",
        applied_transition_id=None,
        rejection_reasons=(
            RejectionReason(
                code="INSUFFICIENT_FUNDS_AT_SETTLEMENT",
                message="Account balance insufficient at settlement fill price",
            ),
        ),
        settlement_evidence={
            "observation_id": "obs_BTC_20260801_r1",
            "selected_revision": 1,
            "execution_fill_time": "2026-08-01T00:00:00Z",
            "observation_knowledge_time": "2026-08-03T00:00:00Z",
            "execution_price": "75000.00",
        },
    )
    errs = validate_data(rej_outcome.to_dict(), schema_set)
    assert not errs, f"SettlementOutcome (REJECTED) errors: {errs}"
