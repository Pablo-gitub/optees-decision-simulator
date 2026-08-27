"""In-memory persistence adapter enforcing immutability and record uniqueness."""

from __future__ import annotations

from simulator.application.ports.persistence import PersistencePort
from simulator.domain.errors import (
    DuplicateIdentityError,
    FrozenRecordMutationError,
)
from simulator.domain.models import (
    DecisionOutcome,
    DivergenceReport,
    EpisodeDefinition,
    EpisodeRun,
    MetricRecord,
    OpteesCallReceipt,
    PolicyDefinition,
    PolicyVersion,
    ProposedDecision,
    ReplayReport,
    RoundRecord,
    TransitionRecord,
    VirtualAccountState,
)


class InMemoryStore(PersistencePort):
    """In-memory experiment store enforcing immutable append-only semantics."""

    def __init__(self) -> None:
        self._episode_definitions: dict[str, EpisodeDefinition] = {}
        self._policy_definitions: dict[str, PolicyDefinition] = {}
        self._policy_versions: dict[str, PolicyVersion] = {}
        self._episode_runs: dict[str, EpisodeRun] = {}
        self._rounds: dict[str, list[RoundRecord]] = {}
        self._proposed_decisions: dict[str, ProposedDecision] = {}
        self._decision_outcomes: dict[str, DecisionOutcome] = {}
        self._transitions: dict[str, TransitionRecord] = {}
        self._account_states: dict[
            tuple[str, str], list[VirtualAccountState]
        ] = {}  # (run_id, policy_id) -> states
        self._metrics: dict[str, list[MetricRecord]] = {}  # run_id -> metrics
        self._optees_receipts: dict[str, OpteesCallReceipt] = {}
        self._replay_reports: dict[str, ReplayReport] = {}
        self._divergence_reports: dict[str, list[DivergenceReport]] = {}

    def save_episode_definition(self, episode: EpisodeDefinition) -> None:
        if episode.episode_id in self._episode_definitions:
            existing = self._episode_definitions[episode.episode_id]
            if existing.compute_hash() != episode.compute_hash():
                raise FrozenRecordMutationError(
                    f"EpisodeDefinition {episode.episode_id} is already frozen"
                )
            return
        self._episode_definitions[episode.episode_id] = episode

    def get_episode_definition(self, episode_id: str) -> EpisodeDefinition | None:
        return self._episode_definitions.get(episode_id)

    def save_policy_definition(self, policy: PolicyDefinition) -> None:
        if policy.policy_id in self._policy_definitions:
            existing = self._policy_definitions[policy.policy_id]
            if existing.compute_hash() != policy.compute_hash():
                raise FrozenRecordMutationError(
                    f"PolicyDefinition {policy.policy_id} is already frozen"
                )
            return
        self._policy_definitions[policy.policy_id] = policy

    def get_policy_definition(self, policy_id: str) -> PolicyDefinition | None:
        return self._policy_definitions.get(policy_id)

    def save_policy_version(self, version: PolicyVersion) -> None:
        if version.policy_version_id in self._policy_versions:
            existing = self._policy_versions[version.policy_version_id]
            if existing.compute_hash() != version.compute_hash():
                raise FrozenRecordMutationError(
                    f"PolicyVersion {version.policy_version_id} is already frozen"
                )
            return
        self._policy_versions[version.policy_version_id] = version

    def get_policy_version(self, policy_version_id: str) -> PolicyVersion | None:
        return self._policy_versions.get(policy_version_id)

    def save_episode_run(self, run: EpisodeRun) -> None:
        self._episode_runs[run.run_id] = run

    def get_episode_run(self, run_id: str) -> EpisodeRun | None:
        return self._episode_runs.get(run_id)

    def append_round(self, round_record: RoundRecord) -> None:
        run_id = round_record.run_id
        if run_id not in self._rounds:
            self._rounds[run_id] = []

        rounds = self._rounds[run_id]
        if rounds and rounds[-1].round_index >= round_record.round_index:
            raise FrozenRecordMutationError(
                f"Round {round_record.round_index} cannot be appended after "
                f"round {rounds[-1].round_index}"
            )
        rounds.append(round_record)

    def get_rounds(self, run_id: str) -> list[RoundRecord]:
        return list(self._rounds.get(run_id, []))

    def save_proposed_decision(self, decision: ProposedDecision) -> None:
        if decision.decision_id in self._proposed_decisions:
            raise DuplicateIdentityError(f"ProposedDecision {decision.decision_id} already exists")
        self._proposed_decisions[decision.decision_id] = decision

    def get_proposed_decision(self, decision_id: str) -> ProposedDecision | None:
        return self._proposed_decisions.get(decision_id)

    def save_decision_outcome(self, outcome: DecisionOutcome) -> None:
        if outcome.outcome_id in self._decision_outcomes:
            raise DuplicateIdentityError(f"DecisionOutcome {outcome.outcome_id} already exists")
        self._decision_outcomes[outcome.outcome_id] = outcome

    def get_decision_outcome(self, outcome_id: str) -> DecisionOutcome | None:
        return self._decision_outcomes.get(outcome_id)

    def save_transition(self, transition: TransitionRecord) -> None:
        if transition.transition_id in self._transitions:
            raise DuplicateIdentityError(
                f"TransitionRecord {transition.transition_id} already exists"
            )
        self._transitions[transition.transition_id] = transition

    def get_transition(self, transition_id: str) -> TransitionRecord | None:
        return self._transitions.get(transition_id)

    def save_account_state(self, run_id: str, state: VirtualAccountState) -> None:
        key = (run_id, state.policy_id)
        if key not in self._account_states:
            self._account_states[key] = []
        self._account_states[key].append(state)

    def get_latest_account_state(self, run_id: str, policy_id: str) -> VirtualAccountState | None:
        states = self._account_states.get((run_id, policy_id), [])
        return states[-1] if states else None

    def get_account_states(self, run_id: str, policy_id: str) -> list[VirtualAccountState]:
        return list(self._account_states.get((run_id, policy_id), []))

    def save_metric_record(self, metric: MetricRecord) -> None:
        if metric.run_id not in self._metrics:
            self._metrics[metric.run_id] = []
        self._metrics[metric.run_id].append(metric)

    def get_metric_records(self, run_id: str, policy_id: str | None = None) -> list[MetricRecord]:
        metrics = self._metrics.get(run_id, [])
        if policy_id is None:
            return list(metrics)
        return [m for m in metrics if m.policy_id == policy_id]

    def save_optees_call_receipt(self, receipt: OpteesCallReceipt) -> None:
        if receipt.receipt_id in self._optees_receipts:
            raise DuplicateIdentityError(f"OpteesCallReceipt {receipt.receipt_id} already exists")
        self._optees_receipts[receipt.receipt_id] = receipt

    def get_optees_call_receipt(self, receipt_id: str) -> OpteesCallReceipt | None:
        return self._optees_receipts.get(receipt_id)

    def save_replay_report(self, report: ReplayReport) -> None:
        self._replay_reports[report.report_id] = report

    def get_replay_report(self, report_id: str) -> ReplayReport | None:
        return self._replay_reports.get(report_id)

    def save_divergence_report(self, report: DivergenceReport) -> None:
        if report.replay_report_id not in self._divergence_reports:
            self._divergence_reports[report.replay_report_id] = []
        self._divergence_reports[report.replay_report_id].append(report)

    def get_divergence_reports(self, replay_report_id: str) -> list[DivergenceReport]:
        return list(self._divergence_reports.get(replay_report_id, []))
