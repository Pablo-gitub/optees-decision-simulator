"""PersistencePort interface for immutable append-only experiment history."""

from abc import ABC, abstractmethod
from dataclasses import dataclass

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


@dataclass(frozen=True)
class RoundCommit:
    """All records that become visible atomically for one completed round."""

    run: EpisodeRun
    round_record: RoundRecord
    proposed_decisions: tuple[ProposedDecision, ...]
    decision_outcomes: tuple[DecisionOutcome, ...]
    transitions: tuple[TransitionRecord, ...]
    account_states: tuple[VirtualAccountState, ...]
    metrics: tuple[MetricRecord, ...] = ()


class PersistencePort(ABC):
    """Port for storing and retrieving immutable simulation records."""

    @abstractmethod
    def save_episode_definition(self, episode: EpisodeDefinition) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_episode_definition(self, episode_id: str) -> EpisodeDefinition | None:
        raise NotImplementedError

    @abstractmethod
    def save_policy_definition(self, policy: PolicyDefinition) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_policy_definition(self, policy_id: str) -> PolicyDefinition | None:
        raise NotImplementedError

    @abstractmethod
    def save_policy_version(self, version: PolicyVersion) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_policy_version(self, policy_version_id: str) -> PolicyVersion | None:
        raise NotImplementedError

    @abstractmethod
    def save_episode_run(self, run: EpisodeRun) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_episode_run(self, run_id: str) -> EpisodeRun | None:
        raise NotImplementedError

    @abstractmethod
    def append_round(self, round_record: RoundRecord) -> None:
        raise NotImplementedError

    @abstractmethod
    def commit_round(self, commit: RoundCommit) -> None:
        """Publish a complete round and its run progress as one atomic unit."""
        raise NotImplementedError

    @abstractmethod
    def get_rounds(self, run_id: str) -> list[RoundRecord]:
        raise NotImplementedError

    @abstractmethod
    def save_proposed_decision(self, decision: ProposedDecision) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_proposed_decision(self, decision_id: str) -> ProposedDecision | None:
        raise NotImplementedError

    @abstractmethod
    def save_decision_outcome(self, outcome: DecisionOutcome) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_decision_outcome(self, outcome_id: str) -> DecisionOutcome | None:
        raise NotImplementedError

    @abstractmethod
    def get_decision_outcomes(
        self, run_id: str, policy_id: str | None = None
    ) -> list[DecisionOutcome]:
        raise NotImplementedError

    @abstractmethod
    def save_transition(self, transition: TransitionRecord) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_transition(self, transition_id: str) -> TransitionRecord | None:
        raise NotImplementedError

    @abstractmethod
    def get_transitions(self, run_id: str, policy_id: str | None = None) -> list[TransitionRecord]:
        raise NotImplementedError

    @abstractmethod
    def save_account_state(self, run_id: str, state: VirtualAccountState) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_latest_account_state(self, run_id: str, policy_id: str) -> VirtualAccountState | None:
        raise NotImplementedError

    @abstractmethod
    def get_account_states(self, run_id: str, policy_id: str) -> list[VirtualAccountState]:
        raise NotImplementedError

    @abstractmethod
    def save_metric_record(self, metric: MetricRecord) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_metric_records(self, run_id: str, policy_id: str | None = None) -> list[MetricRecord]:
        raise NotImplementedError

    @abstractmethod
    def save_optees_call_receipt(self, receipt: OpteesCallReceipt) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_optees_call_receipt(self, receipt_id: str) -> OpteesCallReceipt | None:
        raise NotImplementedError

    @abstractmethod
    def save_replay_report(self, report: ReplayReport) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_replay_report(self, report_id: str) -> ReplayReport | None:
        raise NotImplementedError

    @abstractmethod
    def save_divergence_report(self, report: DivergenceReport) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_divergence_reports(self, replay_report_id: str) -> list[DivergenceReport]:
        raise NotImplementedError
