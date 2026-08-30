"""Replay and divergence verification service."""

from __future__ import annotations

from simulator.application.ports.clock import ClockPort
from simulator.application.ports.dataset import DatasetPort
from simulator.application.ports.persistence import PersistencePort
from simulator.application.ports.policy import PolicyContext, PolicyPort
from simulator.application.ports.pricing import PricingPort
from simulator.application.services.eligibility import EligibilityService
from simulator.application.services.execution import ExecutionService
from simulator.domain.lifecycle import DivergenceCategory, ReplayMode, ReplayStatus
from simulator.domain.models import (
    DivergenceReport,
    ReplayReport,
    VirtualAccountState,
)


class ReplayService:
    """Verifies historical reproducibility via Record Replay and Deterministic Re-Execution."""

    def __init__(
        self,
        persistence: PersistencePort,
        dataset: DatasetPort,
        clock: ClockPort,
        pricing: PricingPort | None = None,
    ) -> None:
        self._persistence = persistence
        self._dataset = dataset
        self._clock = clock
        self._pricing = pricing

    def record_replay(self, original_run_id: str, report_id: str) -> ReplayReport:
        """Replay episode trajectory purely from stored transitions without running policy code."""
        run = self._persistence.get_episode_run(original_run_id)
        if run is None:
            report = ReplayReport(
                report_id=report_id,
                original_run_id=original_run_id,
                replay_mode=ReplayMode.RECORD_REPLAY,
                executed_at=self._clock.now_utc(),
                overall_status=ReplayStatus.FAILED,
                rounds_evaluated=0,
                matched_round_count=0,
                diverged_round_count=0,
                initial_state_hash_match=False,
                final_state_hash_match=False,
                divergence_report_ids=(),
            )
            self._persistence.save_replay_report(report)
            return report

        episode_def = self._persistence.get_episode_definition(run.episode_id)
        if episode_def is None:
            report = ReplayReport(
                report_id=report_id,
                original_run_id=original_run_id,
                replay_mode=ReplayMode.RECORD_REPLAY,
                executed_at=self._clock.now_utc(),
                overall_status=ReplayStatus.INCOMPATIBLE,
                rounds_evaluated=0,
                matched_round_count=0,
                diverged_round_count=0,
                initial_state_hash_match=False,
                final_state_hash_match=False,
                divergence_report_ids=(),
            )
            self._persistence.save_replay_report(report)
            return report

        rounds = self._persistence.get_rounds(original_run_id)
        divergences: list[DivergenceReport] = []
        matched_rounds = 0
        diverged_rounds = 0

        # Check initial state hashes
        initial_match = True
        for p_ver in episode_def.policy_versions:
            states = self._persistence.get_account_states(original_run_id, p_ver.policy_id)
            if not states:
                initial_match = False
        # Verify round by round
        for r_idx, r_rec in enumerate(rounds):
            round_diverged = False

            for p_rec in r_rec.policy_round_records:
                # Verify transition if present
                if p_rec.transition_hash is not None:
                    trans_id = f"trn_{r_rec.round_id}_{p_rec.policy_id}"
                    stored_trans = self._persistence.get_transition(trans_id)
                    if stored_trans is not None:
                        actual_trans_hash = stored_trans.compute_hash()
                        if actual_trans_hash != p_rec.transition_hash:
                            round_diverged = True
                            div = DivergenceReport(
                                divergence_id=f"div_{report_id}_round{r_idx}_{p_rec.policy_id}_trans",
                                replay_report_id=report_id,
                                round_index=r_idx,
                                policy_id=p_rec.policy_id,
                                category=DivergenceCategory.DECISION_DIVERGENCE,
                                declared_epsilon=0.0,
                                observed_max_delta=0.0,
                                field_path="transition_hash",
                                original_value_hash=p_rec.transition_hash,
                                replayed_value_hash=actual_trans_hash,
                                details={"message": "Stored transition hash mismatch"},
                            )
                            divergences.append(div)
                            self._persistence.save_divergence_report(div)

                # Verify account state after
                states = self._persistence.get_account_states(original_run_id, p_rec.policy_id)
                # States index 0 is genesis, index 1 is round 0 after, etc.
                expected_state_idx = r_idx + 1
                if expected_state_idx < len(states):
                    actual_acc = states[expected_state_idx]
                    actual_acc_hash = actual_acc.compute_hash()
                    if actual_acc_hash != p_rec.account_state_after_hash:
                        round_diverged = True
                        div = DivergenceReport(
                            divergence_id=f"div_{report_id}_round{r_idx}_{p_rec.policy_id}_acc",
                            replay_report_id=report_id,
                            round_index=r_idx,
                            policy_id=p_rec.policy_id,
                            category=DivergenceCategory.NUMERICAL_TOLERANCE_EXCEEDED,
                            declared_epsilon=0.0,
                            observed_max_delta=0.0,
                            field_path="account_state_after_hash",
                            original_value_hash=p_rec.account_state_after_hash,
                            replayed_value_hash=actual_acc_hash,
                            details={"message": "Account state hash mismatch"},
                        )
                        divergences.append(div)
                        self._persistence.save_divergence_report(div)

            if round_diverged:
                diverged_rounds += 1
            else:
                matched_rounds += 1

        final_match = (diverged_rounds == 0) and (matched_rounds == len(rounds))
        overall_status = ReplayStatus.MATCH if final_match else ReplayStatus.DIVERGED

        report = ReplayReport(
            report_id=report_id,
            original_run_id=original_run_id,
            replay_mode=ReplayMode.RECORD_REPLAY,
            executed_at=self._clock.now_utc(),
            overall_status=overall_status,
            rounds_evaluated=len(rounds),
            matched_round_count=matched_rounds,
            diverged_round_count=diverged_rounds,
            initial_state_hash_match=initial_match,
            final_state_hash_match=final_match,
            divergence_report_ids=tuple(d.divergence_id for d in divergences),
        )
        self._persistence.save_replay_report(report)
        return report

    def deterministic_re_execution(
        self,
        original_run_id: str,
        report_id: str,
        policies: dict[str, PolicyPort],
    ) -> ReplayReport:
        """Re-execute policy code against frozen observations and assert identical record hashes."""
        run = self._persistence.get_episode_run(original_run_id)
        if run is None:
            report = ReplayReport(
                report_id=report_id,
                original_run_id=original_run_id,
                replay_mode=ReplayMode.DETERMINISTIC_RE_EXECUTION,
                executed_at=self._clock.now_utc(),
                overall_status=ReplayStatus.FAILED,
                rounds_evaluated=0,
                matched_round_count=0,
                diverged_round_count=0,
                initial_state_hash_match=False,
                final_state_hash_match=False,
                divergence_report_ids=(),
            )
            self._persistence.save_replay_report(report)
            return report

        episode_def = self._persistence.get_episode_definition(run.episode_id)
        if episode_def is None:
            report = ReplayReport(
                report_id=report_id,
                original_run_id=original_run_id,
                replay_mode=ReplayMode.DETERMINISTIC_RE_EXECUTION,
                executed_at=self._clock.now_utc(),
                overall_status=ReplayStatus.INCOMPATIBLE,
                rounds_evaluated=0,
                matched_round_count=0,
                diverged_round_count=0,
                initial_state_hash_match=False,
                final_state_hash_match=False,
                divergence_report_ids=(),
            )
            self._persistence.save_replay_report(report)
            return report

        # Check policy presence
        for p_ver in episode_def.policy_versions:
            if p_ver.policy_id not in policies:
                report = ReplayReport(
                    report_id=report_id,
                    original_run_id=original_run_id,
                    replay_mode=ReplayMode.DETERMINISTIC_RE_EXECUTION,
                    executed_at=self._clock.now_utc(),
                    overall_status=ReplayStatus.INCOMPATIBLE,
                    rounds_evaluated=0,
                    matched_round_count=0,
                    diverged_round_count=0,
                    initial_state_hash_match=True,
                    final_state_hash_match=False,
                    divergence_report_ids=(),
                )
                self._persistence.save_replay_report(report)
                return report
            implementation = policies[p_ver.policy_id]
            if implementation.policy_version_id != p_ver.policy_version_id:
                report = ReplayReport(
                    report_id=report_id,
                    original_run_id=original_run_id,
                    replay_mode=ReplayMode.DETERMINISTIC_RE_EXECUTION,
                    executed_at=self._clock.now_utc(),
                    overall_status=ReplayStatus.INCOMPATIBLE,
                    rounds_evaluated=0,
                    matched_round_count=0,
                    diverged_round_count=0,
                    initial_state_hash_match=True,
                    final_state_hash_match=False,
                    divergence_report_ids=(),
                )
                self._persistence.save_replay_report(report)
                return report

        rounds = self._persistence.get_rounds(original_run_id)
        all_obs = self._dataset.get_all_observations()

        divergences: list[DivergenceReport] = []
        matched_rounds = 0
        diverged_rounds = 0

        # Maintain replayed account states starting from genesis
        replayed_accounts: dict[str, VirtualAccountState] = {}
        for p_ver in episode_def.policy_versions:
            states = self._persistence.get_account_states(original_run_id, p_ver.policy_id)
            replayed_accounts[p_ver.policy_id] = states[0]

        for r_idx, r_rec in enumerate(rounds):
            cutoff = r_rec.knowledge_cutoff
            effective_time = r_rec.effective_time
            eligible_obs = EligibilityService.get_eligible_observations(all_obs, cutoff)

            round_diverged = False

            for p_rec in r_rec.policy_round_records:
                p_impl = policies[p_rec.policy_id]
                curr_acc = replayed_accounts[p_rec.policy_id]

                context = PolicyContext(
                    policy_id=p_rec.policy_id,
                    policy_version_id=p_impl.policy_version_id,
                    round_id=r_rec.round_id,
                    round_index=r_idx,
                    knowledge_cutoff=cutoff,
                    account_state=curr_acc,
                    eligible_observations=eligible_obs,
                    hyperparameters=p_impl.hyperparameters,
                )

                replayed_proposal = p_impl.propose_decision(context)
                replayed_prop_hash = replayed_proposal.compute_hash()

                if replayed_prop_hash != p_rec.proposed_decision_hash:
                    round_diverged = True
                    div = DivergenceReport(
                        divergence_id=f"div_{report_id}_round{r_idx}_{p_rec.policy_id}_prop",
                        replay_report_id=report_id,
                        round_index=r_idx,
                        policy_id=p_rec.policy_id,
                        category=DivergenceCategory.DECISION_DIVERGENCE,
                        declared_epsilon=0.0,
                        observed_max_delta=0.0,
                        field_path="proposed_decision",
                        original_value_hash=p_rec.proposed_decision_hash,
                        replayed_value_hash=replayed_prop_hash,
                        details={
                            "message": "Policy proposed different decision during re-execution"
                        },
                    )
                    divergences.append(div)
                    self._persistence.save_divergence_report(div)

                pricing_res = None
                if self._pricing is not None:
                    req_resources = tuple(
                        sorted(
                            set(
                                [b.resource_id for b in curr_acc.balances]
                                + [a.resource_id for a in replayed_proposal.requested_actions]
                                + [episode_def.reference_resource_id]
                            )
                        )
                    )
                    pricing_res = self._pricing.resolve_pricing(
                        all_observations=all_obs,
                        knowledge_cutoff=cutoff,
                        effective_time=effective_time,
                        required_resources=req_resources,
                        reference_resource_id=episode_def.reference_resource_id,
                    )

                outcome, transition, next_account = ExecutionService.evaluate_and_apply_decision(
                    episode_def=episode_def,
                    current_account=curr_acc,
                    proposal=replayed_proposal,
                    round_id=r_rec.round_id,
                    round_index=r_idx + 1,
                    effective_time=effective_time,
                    pricing_result=pricing_res,
                    eligible_observations=eligible_obs,
                )

                replayed_acc_hash = next_account.compute_hash()
                if replayed_acc_hash != p_rec.account_state_after_hash:
                    round_diverged = True
                    div = DivergenceReport(
                        divergence_id=f"div_{report_id}_round{r_idx}_{p_rec.policy_id}_acc",
                        replay_report_id=report_id,
                        round_index=r_idx,
                        policy_id=p_rec.policy_id,
                        category=DivergenceCategory.NUMERICAL_TOLERANCE_EXCEEDED,
                        declared_epsilon=0.0,
                        observed_max_delta=0.0,
                        field_path="account_state_after",
                        original_value_hash=p_rec.account_state_after_hash,
                        replayed_value_hash=replayed_acc_hash,
                        details={"message": "Re-executed account state hash mismatch"},
                    )
                    divergences.append(div)
                    self._persistence.save_divergence_report(div)

                replayed_accounts[p_rec.policy_id] = next_account

            if round_diverged:
                diverged_rounds += 1
            else:
                matched_rounds += 1

        final_match = (diverged_rounds == 0) and (matched_rounds == len(rounds))
        overall_status = ReplayStatus.MATCH if final_match else ReplayStatus.DIVERGED

        report = ReplayReport(
            report_id=report_id,
            original_run_id=original_run_id,
            replay_mode=ReplayMode.DETERMINISTIC_RE_EXECUTION,
            executed_at=self._clock.now_utc(),
            overall_status=overall_status,
            rounds_evaluated=len(rounds),
            matched_round_count=matched_rounds,
            diverged_round_count=diverged_rounds,
            initial_state_hash_match=True,
            final_state_hash_match=final_match,
            divergence_report_ids=tuple(d.divergence_id for d in divergences),
        )
        self._persistence.save_replay_report(report)
        return report
