"""PersistencePort interface for immutable append-only experiment history."""

from abc import ABC, abstractmethod
from dataclasses import dataclass

from simulator.domain.models import (
    DecisionOutcome,
    DeferredRoundRecord,
    DeferredRunTerminalRecord,
    DeferredTransitionRecord,
    DivergenceReport,
    EpisodeDefinition,
    EpisodeRun,
    MetricRecord,
    OpteesCallReceipt,
    PendingStateReference,
    PendingTransitionRecord,
    PolicyDefinition,
    PolicyVersion,
    ProposedDecision,
    ReplayReport,
    RoundRecord,
    SettlementOutcome,
    TransitionRecord,
    VirtualAccountState,
)


@dataclass(frozen=True)
class RoundCommit:
    """All records that become visible atomically for one completed round."""

    run: EpisodeRun
    round_record: RoundRecord | DeferredRoundRecord
    proposed_decisions: tuple[ProposedDecision, ...] = ()
    decision_outcomes: tuple[DecisionOutcome, ...] = ()
    transitions: tuple[TransitionRecord, ...] = ()
    account_states: tuple[VirtualAccountState, ...] = ()
    metrics: tuple[MetricRecord, ...] = ()
    pending_transitions: tuple[PendingTransitionRecord, ...] = ()
    settlement_outcomes: tuple[SettlementOutcome, ...] = ()
    deferred_transitions: tuple[DeferredTransitionRecord, ...] = ()
    terminal_record: DeferredRunTerminalRecord | None = None


@dataclass(frozen=True)
class TerminalCommit:
    """Atomic publication of mid-episode or genesis cancellation."""

    expected_run_hash: str
    run: EpisodeRun
    terminal_record: DeferredRunTerminalRecord
    settlement_outcomes: tuple[SettlementOutcome, ...] = ()
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

    @abstractmethod
    def commit_terminal(self, commit: TerminalCommit) -> None:
        """Publish mid-episode or genesis cancellation as one atomic unit."""
        raise NotImplementedError

    @abstractmethod
    def get_pending_transition(self, pending_id: str) -> PendingTransitionRecord | None:
        raise NotImplementedError

    @abstractmethod
    def get_pending_transitions(
        self, run_id: str, policy_id: str | None = None
    ) -> list[PendingTransitionRecord]:
        raise NotImplementedError

    @abstractmethod
    def get_settlement_outcome(self, outcome_id: str) -> SettlementOutcome | None:
        raise NotImplementedError

    @abstractmethod
    def get_settlement_outcomes(
        self, run_id: str, policy_id: str | None = None
    ) -> list[SettlementOutcome]:
        raise NotImplementedError

    @abstractmethod
    def get_deferred_transition(self, transition_id: str) -> DeferredTransitionRecord | None:
        raise NotImplementedError

    @abstractmethod
    def get_deferred_transitions(
        self, run_id: str, policy_id: str | None = None
    ) -> list[DeferredTransitionRecord]:
        raise NotImplementedError

    @abstractmethod
    def get_account_state_by_hash(self, run_id: str, state_hash: str) -> VirtualAccountState | None:
        raise NotImplementedError

    @abstractmethod
    def get_active_pending_reference(
        self, run_id: str, policy_id: str
    ) -> PendingStateReference | None:
        raise NotImplementedError

    @abstractmethod
    def get_terminal_record(self, run_id: str) -> DeferredRunTerminalRecord | None:
        raise NotImplementedError
