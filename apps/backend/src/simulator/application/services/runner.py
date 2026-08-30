"""EpisodeRunner application service orchestrating round lifecycle, isolation,
and atomic persistence.
"""

from __future__ import annotations

from decimal import Decimal

from simulator.application.ports.clock import ClockPort
from simulator.application.ports.dataset import DatasetPort
from simulator.application.ports.persistence import PersistencePort, RoundCommit
from simulator.application.ports.policy import PolicyContext, PolicyPort
from simulator.application.ports.pricing import PricingPort
from simulator.application.services.eligibility import EligibilityService
from simulator.application.services.evaluator import EvaluatorService
from simulator.application.services.execution import ExecutionService
from simulator.domain.canonical import compute_state_merkle_hash
from simulator.domain.errors import (
    InvariantViolationError,
    SimulatorError,
)
from simulator.domain.lifecycle import (
    LifecycleStatus,
    validate_lifecycle_transition,
)
from simulator.domain.models import (
    BalanceItem,
    CumulativeCostItem,
    DecisionOutcome,
    EpisodeDefinition,
    EpisodeRun,
    PolicyRoundRecord,
    ProposedDecision,
    ReferenceValuation,
    RoundRecord,
    TransitionRecord,
    VirtualAccountState,
)


class EpisodeRunner:
    """Orchestrates deterministic episode execution, policy isolation, and atomic round commits."""

    def __init__(
        self,
        persistence: PersistencePort,
        dataset: DatasetPort,
        clock: ClockPort,
        policies: dict[str, PolicyPort],
        pricing: PricingPort | None = None,
    ) -> None:
        self._persistence = persistence
        self._dataset = dataset
        self._clock = clock
        self._policies = policies
        self._pricing = pricing

    def initialize_episode(self, episode_def: EpisodeDefinition, run_id: str) -> EpisodeRun:
        """Validate, freeze, and persist episode definition and initial run record."""
        # Check policy availability
        for p_ver in episode_def.policy_versions:
            if p_ver.policy_id not in self._policies:
                raise SimulatorError(f"Policy {p_ver.policy_id} is not registered in EpisodeRunner")
            implementation = self._policies[p_ver.policy_id]
            if implementation.policy_id != p_ver.policy_id:
                raise SimulatorError(
                    f"Policy implementation identity mismatch for {p_ver.policy_id}"
                )
            if implementation.policy_version_id != p_ver.policy_version_id:
                raise SimulatorError(f"Policy version mismatch for {p_ver.policy_id}")

        ep_hash = episode_def.compute_hash()
        self._persistence.save_episode_definition(episode_def)

        # Create genesis account states (round_index = 0 / initial state before round 0)
        ref_id = episode_def.reference_resource_id
        for init_acc in episode_def.initial_accounts:
            balances: list[BalanceItem] = []
            unalloc_cash = Decimal("0.00")
            for b in init_acc.balances:
                balances.append(BalanceItem(resource_id=b.resource_id, quantity=b.quantity))
                if b.resource_id == ref_id:
                    unalloc_cash = b.quantity

            initial_state = VirtualAccountState(
                account_state_id=f"acc-state_{run_id}_genesis_{init_acc.policy_id}",
                policy_id=init_acc.policy_id,
                round_index=0,
                as_of_time=episode_def.created_at,
                balances=tuple(balances),
                cumulative_costs=(
                    CumulativeCostItem(cost_type="TRANSACTION_FEE", amount=Decimal("0.00")),
                ),
                reference_valuation=ReferenceValuation(
                    reference_resource_id=ref_id,
                    unallocated_cash=unalloc_cash,
                    allocated_resources_value=Decimal("0.00"),
                    net_total_value=unalloc_cash,
                ),
                parent_state_hash=None,
            )
            self._persistence.save_account_state(run_id, initial_state)

        run = EpisodeRun(
            run_id=run_id,
            episode_id=episode_def.episode_id,
            episode_definition_hash=ep_hash,
            lifecycle_status=LifecycleStatus.CONFIGURED,
            started_at=self._clock.now_utc(),
            ended_at=None,
            current_round_index=0,
            total_rounds=len(episode_def.calendar.round_cutoffs),
            final_state_hash=None,
        )
        self._persistence.save_episode_run(run)
        return run

    def start_run(self, run_id: str) -> EpisodeRun:
        """Transition configured episode run to RUNNING."""
        run = self._persistence.get_episode_run(run_id)
        if run is None:
            raise SimulatorError(f"Episode run {run_id} not found")

        new_status = validate_lifecycle_transition(run.lifecycle_status, LifecycleStatus.RUNNING)
        updated_run = EpisodeRun(
            run_id=run.run_id,
            episode_id=run.episode_id,
            episode_definition_hash=run.episode_definition_hash,
            lifecycle_status=new_status,
            started_at=run.started_at,
            ended_at=None,
            current_round_index=run.current_round_index,
            total_rounds=run.total_rounds,
            final_state_hash=None,
        )
        self._persistence.save_episode_run(updated_run)
        return updated_run

    def pause_run(self, run_id: str) -> EpisodeRun:
        """Pause a running episode at a safe round boundary."""
        run = self._persistence.get_episode_run(run_id)
        if run is None:
            raise SimulatorError(f"Episode run {run_id} not found")

        new_status = validate_lifecycle_transition(run.lifecycle_status, LifecycleStatus.PAUSED)
        updated_run = EpisodeRun(
            run_id=run.run_id,
            episode_id=run.episode_id,
            episode_definition_hash=run.episode_definition_hash,
            lifecycle_status=new_status,
            started_at=run.started_at,
            ended_at=None,
            current_round_index=run.current_round_index,
            total_rounds=run.total_rounds,
            final_state_hash=run.final_state_hash,
        )
        self._persistence.save_episode_run(updated_run)
        return updated_run

    def resume_run(self, run_id: str) -> EpisodeRun:
        """Idempotently resume a paused or running episode."""
        run = self._persistence.get_episode_run(run_id)
        if run is None:
            raise SimulatorError(f"Episode run {run_id} not found")

        # If already running, idempotent no-op
        if run.lifecycle_status == LifecycleStatus.RUNNING:
            return run

        new_status = validate_lifecycle_transition(run.lifecycle_status, LifecycleStatus.RUNNING)
        updated_run = EpisodeRun(
            run_id=run.run_id,
            episode_id=run.episode_id,
            episode_definition_hash=run.episode_definition_hash,
            lifecycle_status=new_status,
            started_at=run.started_at,
            ended_at=None,
            current_round_index=run.current_round_index,
            total_rounds=run.total_rounds,
            final_state_hash=run.final_state_hash,
        )
        self._persistence.save_episode_run(updated_run)
        return updated_run

    def cancel_run(self, run_id: str, reason: str = "User cancelled run") -> EpisodeRun:
        """Cancel a running or paused episode at a round boundary."""
        run = self._persistence.get_episode_run(run_id)
        if run is None:
            raise SimulatorError(f"Episode run {run_id} not found")

        new_status = validate_lifecycle_transition(run.lifecycle_status, LifecycleStatus.CANCELLED)
        updated_run = EpisodeRun(
            run_id=run.run_id,
            episode_id=run.episode_id,
            episode_definition_hash=run.episode_definition_hash,
            lifecycle_status=new_status,
            started_at=run.started_at,
            ended_at=self._clock.now_utc(),
            current_round_index=run.current_round_index,
            total_rounds=run.total_rounds,
            final_state_hash=run.final_state_hash,
            failure_reason=reason,
        )
        self._persistence.save_episode_run(updated_run)
        return updated_run

    def execute_next_round(self, run_id: str) -> RoundRecord | None:
        """Execute a single round atomically.

        Returns RoundRecord if executed, None if episode has reached terminal state.
        """
        run = self._persistence.get_episode_run(run_id)
        if run is None:
            raise SimulatorError(f"Episode run {run_id} not found")

        if run.lifecycle_status != LifecycleStatus.RUNNING:
            return None

        if run.current_round_index >= run.total_rounds:
            return None

        episode_def = self._persistence.get_episode_definition(run.episode_id)
        if episode_def is None:
            raise InvariantViolationError(f"Episode definition {run.episode_id} not found")

        round_idx = run.current_round_index
        round_id = f"rnd_{run_id}_round_{round_idx}"
        cutoff = episode_def.calendar.round_cutoffs[round_idx]
        effective_time = cutoff  # In discrete synchronous simulation, effective at cutoff

        # Parent round hash
        existing_rounds = self._persistence.get_rounds(run_id)
        parent_round_hash = existing_rounds[-1].compute_hash() if existing_rounds else None

        exec_start_time = self._clock.now_utc()
        elapsed_start = self._clock.monotonic_seconds()

        # Step 1: Extract eligible observations once for all policies
        all_obs = self._dataset.get_all_observations()
        eligible_obs = EligibilityService.get_eligible_observations(all_obs, cutoff)
        eligible_obs_hashes = tuple(obs.compute_hash() for obs in eligible_obs)

        # Stage atomic round items
        staged_proposals: list[ProposedDecision] = []
        staged_outcomes: list[DecisionOutcome] = []
        staged_transitions: list[TransitionRecord] = []
        staged_account_states: list[VirtualAccountState] = []
        policy_round_records: list[PolicyRoundRecord] = []
        round_item_hashes: list[str] = []

        # Execute policies in deterministic order (by policy_id)
        sorted_policy_refs = sorted(episode_def.policy_versions, key=lambda p: p.policy_id)

        for p_ver in sorted_policy_refs:
            policy_impl = self._policies[p_ver.policy_id]
            current_acc = self._persistence.get_latest_account_state(run_id, p_ver.policy_id)
            if current_acc is None:
                raise InvariantViolationError(f"Missing account state for policy {p_ver.policy_id}")

            context = PolicyContext(
                policy_id=p_ver.policy_id,
                policy_version_id=p_ver.policy_version_id,
                round_id=round_id,
                round_index=round_idx,
                knowledge_cutoff=cutoff,
                account_state=current_acc,
                eligible_observations=eligible_obs,
                hyperparameters=policy_impl.hyperparameters,
            )

            # Policy proposes decision
            proposal = policy_impl.propose_decision(context)
            staged_proposals.append(proposal)
            prop_hash = proposal.compute_hash()
            round_item_hashes.append(prop_hash)

            # Resolve pricing context if pricing port is configured
            pricing_res = None
            if self._pricing is not None:
                valuation_resources = tuple(
                    sorted(
                        set(
                            [b.resource_id for b in current_acc.balances]
                            + [a.resource_id for a in proposal.requested_actions]
                            + [episode_def.reference_resource_id]
                        )
                    )
                )
                execution_resources = tuple(
                    sorted(
                        {
                            action.resource_id
                            for action in proposal.requested_actions
                            if action.action_type.value != "HOLD"
                        }
                    )
                )
                pricing_res = self._pricing.resolve_pricing(
                    all_observations=all_obs,
                    knowledge_cutoff=cutoff,
                    effective_time=effective_time,
                    valuation_resources=valuation_resources,
                    execution_resources=execution_resources,
                    reference_resource_id=episode_def.reference_resource_id,
                )

            # Execute & validate decision
            outcome, transition, next_account = ExecutionService.evaluate_and_apply_decision(
                episode_def=episode_def,
                current_account=current_acc,
                proposal=proposal,
                round_id=round_id,
                round_index=round_idx + 1,
                effective_time=effective_time,
                pricing_result=pricing_res,
            )
            staged_outcomes.append(outcome)
            staged_account_states.append(next_account)
            out_hash = outcome.compute_hash()
            round_item_hashes.append(out_hash)

            trans_hash: str | None = None
            if transition is not None:
                staged_transitions.append(transition)
                trans_hash = transition.compute_hash()
                round_item_hashes.append(trans_hash)

            acc_after_hash = next_account.compute_hash()
            round_item_hashes.append(acc_after_hash)

            policy_round_records.append(
                PolicyRoundRecord(
                    policy_id=p_ver.policy_id,
                    proposed_decision_hash=prop_hash,
                    decision_outcome_hash=out_hash,
                    transition_hash=trans_hash,
                    account_state_after_hash=acc_after_hash,
                    optees_call_receipt_hashes=(),
                )
            )

        exec_end_time = self._clock.now_utc()
        state_merkle_hash = compute_state_merkle_hash(parent_round_hash, round_item_hashes)

        round_record = RoundRecord(
            round_id=round_id,
            run_id=run_id,
            round_index=round_idx,
            parent_round_hash=parent_round_hash,
            knowledge_cutoff=cutoff,
            execution_start_time=exec_start_time,
            execution_end_time=exec_end_time,
            effective_time=effective_time,
            eligible_observation_hashes=eligible_obs_hashes,
            policy_round_records=tuple(policy_round_records),
            state_merkle_hash=state_merkle_hash,
        )

        next_round_idx = round_idx + 1
        is_completed = next_round_idx >= run.total_rounds
        final_status = LifecycleStatus.COMPLETED if is_completed else LifecycleStatus.RUNNING
        final_state_hash = round_record.compute_hash() if is_completed else None

        updated_run = EpisodeRun(
            run_id=run.run_id,
            episode_id=run.episode_id,
            episode_definition_hash=run.episode_definition_hash,
            lifecycle_status=final_status,
            started_at=run.started_at,
            ended_at=self._clock.now_utc() if is_completed else None,
            current_round_index=next_round_idx,
            total_rounds=run.total_rounds,
            final_state_hash=final_state_hash,
        )
        staged_metrics = []
        if is_completed:
            wall_time = self._clock.monotonic_seconds() - elapsed_start
            for p_ver in episode_def.policy_versions:
                all_states = self._persistence.get_account_states(run_id, p_ver.policy_id) + [
                    state for state in staged_account_states if state.policy_id == p_ver.policy_id
                ]
                init_state = all_states[0]
                run_states = all_states[1:]
                outcomes = self._persistence.get_decision_outcomes(run_id, p_ver.policy_id) + [
                    o for o in staged_outcomes if o.policy_id == p_ver.policy_id
                ]
                transitions = self._persistence.get_transitions(run_id, p_ver.policy_id) + [
                    t for t in staged_transitions if t.policy_id == p_ver.policy_id
                ]

                staged_metrics.append(
                    EvaluatorService.calculate_metrics(
                        run_id=run_id,
                        policy_id=p_ver.policy_id,
                        initial_account=init_state,
                        account_states=run_states,
                        outcomes=outcomes,
                        transitions=transitions,
                        wall_time_seconds=wall_time,
                        calculated_at=self._clock.now_utc(),
                    )
                )

        self._persistence.commit_round(
            RoundCommit(
                run=updated_run,
                round_record=round_record,
                proposed_decisions=tuple(staged_proposals),
                decision_outcomes=tuple(staged_outcomes),
                transitions=tuple(staged_transitions),
                account_states=tuple(staged_account_states),
                metrics=tuple(staged_metrics),
            )
        )

        return round_record

    def run_all_rounds(self, run_id: str) -> EpisodeRun:
        """Run all remaining rounds of an episode until completion or pause/cancel."""
        run = self._persistence.get_episode_run(run_id)
        if run is None:
            raise SimulatorError(f"Episode run {run_id} not found")

        if run.lifecycle_status == LifecycleStatus.CONFIGURED:
            self.start_run(run_id)

        while True:
            r = self.execute_next_round(run_id)
            if r is None:
                break

        final_run = self._persistence.get_episode_run(run_id)
        assert final_run is not None
        return final_run
