"""In-memory persistence adapter enforcing immutability and record uniqueness."""

from __future__ import annotations

from simulator.application.ports.persistence import (
    PersistencePort,
    RoundCommit,
    TerminalCommit,
)
from simulator.domain.canonical import compute_record_hash
from simulator.domain.deferred_round import (
    DeferredRoundRecord,
    compute_deferred_state_merkle_hash,
)
from simulator.domain.deferred_terminal import (
    DeferredRunTerminalRecord,
)
from simulator.domain.errors import (
    CrossPolicyContaminationError,
    DuplicateIdentityError,
    FrozenRecordMutationError,
    InvalidLifecycleTransitionError,
)
from simulator.domain.lifecycle import LifecycleStatus, SettlementStatus
from simulator.domain.models import (
    DecisionOutcome,
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


class InMemoryStore(PersistencePort):
    """In-memory experiment store enforcing immutable append-only semantics."""

    def __init__(self) -> None:
        self._episode_definitions: dict[str, EpisodeDefinition] = {}
        self._policy_definitions: dict[str, PolicyDefinition] = {}
        self._policy_versions: dict[str, PolicyVersion] = {}
        self._episode_runs: dict[str, EpisodeRun] = {}
        self._rounds: dict[str, list[RoundRecord | DeferredRoundRecord]] = {}
        self._proposed_decisions: dict[str, ProposedDecision] = {}
        self._decision_outcomes: dict[str, DecisionOutcome] = {}
        self._transitions: dict[str, TransitionRecord] = {}
        self._account_states: dict[tuple[str, str], list[VirtualAccountState]] = {}
        self._account_states_by_hash: dict[tuple[str, str], VirtualAccountState] = {}
        self._metrics: dict[str, list[MetricRecord]] = {}
        self._optees_receipts: dict[str, OpteesCallReceipt] = {}
        self._replay_reports: dict[str, ReplayReport] = {}
        self._divergence_reports: dict[str, list[DivergenceReport]] = {}

        # Deferred experiment storage
        self._pending_transitions: dict[str, PendingTransitionRecord] = {}
        self._pending_transitions_by_run: dict[str, list[PendingTransitionRecord]] = {}
        self._settlement_outcomes: dict[str, SettlementOutcome] = {}
        self._settlement_outcomes_by_run: dict[str, list[SettlementOutcome]] = {}
        self._deferred_transitions: dict[str, DeferredTransitionRecord] = {}
        self._deferred_transitions_by_run: dict[str, list[DeferredTransitionRecord]] = {}
        self._terminal_records: dict[str, DeferredRunTerminalRecord] = {}
        self._active_pending: dict[tuple[str, str], PendingStateReference | None] = {}
        self._round_commit_fingerprints: dict[tuple[str, str], str] = {}
        self._terminal_commit_fingerprints: dict[str, str] = {}

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

    def append_round(self, round_record: RoundRecord | DeferredRoundRecord) -> None:
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

    def commit_round(self, commit: RoundCommit) -> None:
        """Validate the complete batch before publishing any of its records."""
        run_id = commit.run.run_id
        if commit.round_record.run_id != run_id:
            raise FrozenRecordMutationError("Round commit run identifiers do not match")

        existing_run = self._episode_runs.get(run_id)
        if existing_run is None:
            raise FrozenRecordMutationError(f"EpisodeRun {run_id} not found")

        # --- 1. Check for Exact Retry Idempotency ---
        existing_rounds = self._rounds.get(run_id, [])
        matching_round = next(
            (r for r in existing_rounds if r.round_id == commit.round_record.round_id), None
        )
        if matching_round is not None:
            expected_fingerprint = self._round_commit_fingerprints.get(
                (run_id, commit.round_record.round_id)
            )
            if expected_fingerprint != self._round_commit_fingerprint(commit):
                raise FrozenRecordMutationError("Round commit retry payload is not identical")
            if matching_round.compute_hash() != commit.round_record.compute_hash():
                raise FrozenRecordMutationError(
                    f"Round {commit.round_record.round_id} already exists with different hash"
                )
            if existing_run.compute_hash() != commit.run.compute_hash():
                raise FrozenRecordMutationError("Round commit retry with drifted run state")

            for p in commit.proposed_decisions:
                stored_p = self._proposed_decisions.get(p.decision_id)
                if stored_p is None or stored_p.compute_hash() != p.compute_hash():
                    raise FrozenRecordMutationError(
                        f"ProposedDecision {p.decision_id} mismatch on retry"
                    )
            for o in commit.decision_outcomes:
                stored_o = self._decision_outcomes.get(o.outcome_id)
                if stored_o is None or stored_o.compute_hash() != o.compute_hash():
                    raise FrozenRecordMutationError(
                        f"DecisionOutcome {o.outcome_id} mismatch on retry"
                    )
            for t in commit.transitions:
                stored_t = self._transitions.get(t.transition_id)
                if stored_t is None or stored_t.compute_hash() != t.compute_hash():
                    raise FrozenRecordMutationError(
                        f"TransitionRecord {t.transition_id} mismatch on retry"
                    )
            for a in commit.account_states:
                stored_a = self._account_states_by_hash.get((run_id, a.compute_hash()))
                if stored_a is None:
                    raise FrozenRecordMutationError(
                        f"Account state {a.account_state_id} mismatch on retry"
                    )
            for pt in commit.pending_transitions:
                stored_pt = self._pending_transitions.get(pt.pending_transition_id)
                if stored_pt is None or stored_pt.compute_hash() != pt.compute_hash():
                    raise FrozenRecordMutationError(
                        f"PendingTransitionRecord {pt.pending_transition_id} mismatch on retry"
                    )
            for so in commit.settlement_outcomes:
                stored_so = self._settlement_outcomes.get(so.settlement_outcome_id)
                if stored_so is None or stored_so.compute_hash() != so.compute_hash():
                    raise FrozenRecordMutationError(
                        f"SettlementOutcome {so.settlement_outcome_id} mismatch on retry"
                    )
            for dt in commit.deferred_transitions:
                stored_dt = self._deferred_transitions.get(dt.transition_id)
                if stored_dt is None or stored_dt.compute_hash() != dt.compute_hash():
                    raise FrozenRecordMutationError(
                        f"DeferredTransitionRecord {dt.transition_id} mismatch on retry"
                    )
            if commit.terminal_record is not None:
                stored_term = self._terminal_records.get(run_id)
                if (
                    stored_term is None
                    or stored_term.compute_hash() != commit.terminal_record.compute_hash()
                ):
                    raise FrozenRecordMutationError("Terminal record mismatch on retry")

            # Complete payload is identical -> idempotent no-op.
            return

        # --- 2. Lifecycle and Concurrency Pre-conditions ---
        if existing_run.lifecycle_status in (LifecycleStatus.COMPLETED, LifecycleStatus.CANCELLED):
            raise FrozenRecordMutationError(
                f"Cannot commit round on run in terminal status {existing_run.lifecycle_status}"
            )

        expected_round_index = len(existing_rounds)
        if commit.round_record.round_index != expected_round_index:
            raise FrozenRecordMutationError(
                f"Round {commit.round_record.round_index} cannot be appended after "
                f"round {existing_rounds[-1].round_index if existing_rounds else 'genesis'}"
            )

        expected_parent_hash = existing_rounds[-1].compute_hash() if existing_rounds else None
        if commit.round_record.parent_round_hash != expected_parent_hash:
            raise FrozenRecordMutationError("Parent round hash mismatch: concurrency conflict")
        self._validate_run_identity(existing_run, commit.run)
        if commit.run.current_round_index != commit.round_record.round_index + 1:
            raise FrozenRecordMutationError(
                "EpisodeRun.current_round_index must follow the committed round"
            )

        for metric in commit.metrics:
            if metric.run_id != run_id:
                raise FrozenRecordMutationError("MetricRecord run_id does not match commit run")
        for record in (
            *commit.proposed_decisions,
            *commit.decision_outcomes,
            *commit.transitions,
            *commit.pending_transitions,
            *commit.settlement_outcomes,
            *commit.deferred_transitions,
        ):
            if record.round_id != commit.round_record.round_id:
                raise FrozenRecordMutationError(
                    f"{type(record).__name__} round_id does not match committed round"
                )

        # --- 3. Staged Duplicate and Collision Validations (Candidate Check) ---
        self._require_new_ids(
            (item.decision_id for item in commit.proposed_decisions),
            self._proposed_decisions,
            "ProposedDecision",
        )
        self._require_new_ids(
            (item.outcome_id for item in commit.decision_outcomes),
            self._decision_outcomes,
            "DecisionOutcome",
        )
        self._require_new_ids(
            (item.transition_id for item in commit.transitions),
            self._transitions,
            "TransitionRecord",
        )
        self._require_new_ids(
            (item.pending_transition_id for item in commit.pending_transitions),
            self._pending_transitions,
            "PendingTransitionRecord",
        )
        self._require_new_ids(
            (item.settlement_outcome_id for item in commit.settlement_outcomes),
            self._settlement_outcomes,
            "SettlementOutcome",
        )
        self._require_new_ids(
            (item.transition_id for item in commit.deferred_transitions),
            self._deferred_transitions,
            "DeferredTransitionRecord",
        )

        staged_state_ids: set[str] = set()
        for state in commit.account_states:
            if state.account_state_id in staged_state_ids:
                raise DuplicateIdentityError(
                    f"VirtualAccountState {state.account_state_id} appears twice in one commit"
                )
            staged_state_ids.add(state.account_state_id)
            existing_states = self._account_states.get((run_id, state.policy_id), [])
            if any(item.account_state_id == state.account_state_id for item in existing_states):
                raise DuplicateIdentityError(
                    f"VirtualAccountState {state.account_state_id} already exists"
                )
            if existing_states and existing_states[-1].round_index >= state.round_index:
                raise FrozenRecordMutationError(
                    f"Account state round {state.round_index} does not follow "
                    f"round {existing_states[-1].round_index}"
                )

        existing_metric_ids = {
            metric.metric_record_id for metrics in self._metrics.values() for metric in metrics
        }
        self._require_new_ids(
            (item.metric_record_id for item in commit.metrics),
            existing_metric_ids,
            "MetricRecord",
        )

        # --- 4. Deferred Round Record Invariant Checks ---
        if isinstance(commit.round_record, DeferredRoundRecord):
            merkle = compute_deferred_state_merkle_hash(
                expected_parent_hash, commit.round_record.policy_round_records
            )
            if commit.round_record.state_merkle_hash != merkle:
                raise FrozenRecordMutationError(
                    "DeferredRoundRecord state_merkle_hash does not match policy round records"
                )

            ep_def = self._episode_definitions.get(commit.run.episode_id)
            if ep_def is not None:
                expected_policies = [
                    p.policy_id for p in sorted(ep_def.policy_versions, key=lambda x: x.policy_id)
                ]
                actual_policies = [p.policy_id for p in commit.round_record.policy_round_records]
                if actual_policies != expected_policies:
                    raise FrozenRecordMutationError(
                        f"Round policies {actual_policies} do not match "
                        f"episode policies {expected_policies}"
                    )

            staged_proposals_map = {p.compute_hash(): p for p in commit.proposed_decisions}
            staged_dec_outcomes_map = {o.compute_hash(): o for o in commit.decision_outcomes}
            staged_settle_outcomes_map = {o.compute_hash(): o for o in commit.settlement_outcomes}
            staged_def_transitions_map = {t.compute_hash(): t for t in commit.deferred_transitions}
            staged_pending_map = {pt.compute_hash(): pt for pt in commit.pending_transitions}
            staged_accounts_map = {a.compute_hash(): a for a in commit.account_states}

            for p_rec in commit.round_record.policy_round_records:
                pol_id = p_rec.policy_id

                acc_before = self.get_account_state_by_hash(run_id, p_rec.account_state_before_hash)
                if acc_before is None:
                    raise FrozenRecordMutationError(
                        f"account_state_before_hash {p_rec.account_state_before_hash} not found"
                    )
                if acc_before.policy_id != pol_id:
                    raise CrossPolicyContaminationError(
                        f"account_state_before belongs to {acc_before.policy_id}, expected {pol_id}"
                    )

                if p_rec.account_state_after_hash != p_rec.account_state_before_hash:
                    acc_after = staged_accounts_map.get(p_rec.account_state_after_hash)
                    if acc_after is None:
                        raise FrozenRecordMutationError(
                            f"account_state_after_hash {p_rec.account_state_after_hash} "
                            "not found in staged accounts"
                        )
                    if acc_after.policy_id != pol_id:
                        raise CrossPolicyContaminationError(
                            f"account_state_after belongs to {acc_after.policy_id}, "
                            f"expected {pol_id}"
                        )

                if p_rec.pending_before is not None:
                    prior_active = self.get_active_pending_reference(run_id, pol_id)
                    if (
                        prior_active is None
                        or prior_active.compute_hash() != p_rec.pending_before.compute_hash()
                    ):
                        raise FrozenRecordMutationError(
                            f"pending_before does not match active pending reference for {pol_id}"
                        )
                else:
                    prior_active = self.get_active_pending_reference(run_id, pol_id)
                    if prior_active is not None:
                        raise FrozenRecordMutationError(
                            f"Policy {pol_id} has active pending but pending_before is None"
                        )

                if p_rec.settlement_outcome_hash is not None:
                    so = staged_settle_outcomes_map.get(p_rec.settlement_outcome_hash)
                    if so is None:
                        raise FrozenRecordMutationError(
                            f"settlement_outcome_hash {p_rec.settlement_outcome_hash} "
                            "not found in staged settlement outcomes"
                        )
                    if so.policy_id != pol_id:
                        raise CrossPolicyContaminationError(
                            f"settlement_outcome belongs to {so.policy_id}, expected {pol_id}"
                        )

                if p_rec.deferred_transition_hash is not None:
                    dt = staged_def_transitions_map.get(p_rec.deferred_transition_hash)
                    if dt is None:
                        raise FrozenRecordMutationError(
                            f"deferred_transition_hash {p_rec.deferred_transition_hash} "
                            "not found in staged deferred transitions"
                        )
                    if dt.policy_id != pol_id:
                        raise CrossPolicyContaminationError(
                            f"deferred_transition belongs to {dt.policy_id}, expected {pol_id}"
                        )

                if p_rec.proposed_decision_hash is not None:
                    prop = staged_proposals_map.get(p_rec.proposed_decision_hash)
                    if prop is None:
                        raise FrozenRecordMutationError(
                            f"proposed_decision_hash {p_rec.proposed_decision_hash} "
                            "not found in staged proposals"
                        )
                    if prop.policy_id != pol_id:
                        raise CrossPolicyContaminationError(
                            f"proposed_decision belongs to {prop.policy_id}, expected {pol_id}"
                        )

                if p_rec.decision_outcome_hash is not None:
                    deco = staged_dec_outcomes_map.get(p_rec.decision_outcome_hash)
                    if deco is None:
                        raise FrozenRecordMutationError(
                            f"decision_outcome_hash {p_rec.decision_outcome_hash} "
                            "not found in staged decision outcomes"
                        )
                    if deco.policy_id != pol_id:
                        raise CrossPolicyContaminationError(
                            f"decision_outcome belongs to {deco.policy_id}, expected {pol_id}"
                        )

                if p_rec.pending_after is not None:
                    pt = staged_pending_map.get(p_rec.pending_after.pending_transition_hash)
                    if pt is None:
                        pt = self.get_pending_transition(
                            p_rec.pending_after.pending_transition_hash
                        )
                    if pt is None:
                        pt = next(
                            (
                                p
                                for p in self._pending_transitions.values()
                                if p.compute_hash() == p_rec.pending_after.pending_transition_hash
                            ),
                            None,
                        )
                    if pt is None:
                        raise FrozenRecordMutationError(
                            f"pending_after transition hash "
                            f"{p_rec.pending_after.pending_transition_hash} not found"
                        )
                    if pt.policy_id != pol_id:
                        raise CrossPolicyContaminationError(
                            f"pending_after transition belongs to {pt.policy_id}, expected {pol_id}"
                        )

            policy_records = commit.round_record.policy_round_records
            referenced_proposals = {
                item.proposed_decision_hash
                for item in policy_records
                if item.proposed_decision_hash is not None
            }
            referenced_decisions = {
                item.decision_outcome_hash
                for item in policy_records
                if item.decision_outcome_hash is not None
            }
            referenced_settlements = {
                item.settlement_outcome_hash
                for item in policy_records
                if item.settlement_outcome_hash is not None
            }
            referenced_transitions = {
                item.deferred_transition_hash
                for item in policy_records
                if item.deferred_transition_hash is not None
            }
            referenced_pending = {
                item.pending_after.pending_transition_hash
                for item in policy_records
                if item.pending_after is not None
            }
            referenced_accounts = {item.account_state_after_hash for item in policy_records}
            staged_reference_pairs = (
                (set(staged_proposals_map), referenced_proposals, "proposed decision"),
                (set(staged_dec_outcomes_map), referenced_decisions, "decision outcome"),
                (set(staged_def_transitions_map), referenced_transitions, "deferred transition"),
                (set(staged_pending_map), referenced_pending, "pending transition"),
                (set(staged_accounts_map), referenced_accounts, "account state"),
            )
            for staged_hashes, referenced_hashes, label in staged_reference_pairs:
                if not staged_hashes.issubset(referenced_hashes):
                    raise FrozenRecordMutationError(
                        f"Round commit contains an unreferenced {label}"
                    )
            # Settlement outcomes can additionally be referenced by a terminal
            # record validated below.
            if commit.terminal_record is None and not set(staged_settle_outcomes_map).issubset(
                referenced_settlements
            ):
                raise FrozenRecordMutationError(
                    "Round commit contains an unreferenced settlement outcome"
                )

        # --- 5. Terminal Record Invariant Checks (if present in RoundCommit) ---
        if commit.terminal_record is not None:
            term = commit.terminal_record
            if not isinstance(commit.round_record, DeferredRoundRecord):
                raise FrozenRecordMutationError(
                    "Deferred terminal record requires a DeferredRoundRecord"
                )
            if term.run_id != run_id:
                raise FrozenRecordMutationError(
                    "Terminal record run_id does not match commit run_id"
                )
            if term.episode_id != commit.run.episode_id:
                raise FrozenRecordMutationError(
                    "Terminal record episode_id does not match commit episode_id"
                )
            if term.parent_round_hash != commit.round_record.compute_hash():
                raise FrozenRecordMutationError(
                    "Terminal record parent_round_hash must match the committed round hash"
                )
            if term.simulation_frontier_time != commit.round_record.knowledge_cutoff:
                raise FrozenRecordMutationError(
                    "Terminal record simulation_frontier_time must match committed round cutoff"
                )
            if commit.run.lifecycle_status != LifecycleStatus.COMPLETED:
                raise FrozenRecordMutationError(
                    "EpisodeRun must be in COMPLETED status when terminal_record is committed"
                )
            if commit.run.final_state_hash != term.compute_hash():
                raise FrozenRecordMutationError(
                    "EpisodeRun.final_state_hash must equal the terminal record hash"
                )

            staged_term_so_map = {so.compute_hash(): so for so in commit.settlement_outcomes}
            round_policy_map = (
                {p.policy_id: p for p in commit.round_record.policy_round_records}
                if isinstance(commit.round_record, DeferredRoundRecord)
                else {}
            )

            for pol_term in term.policy_terminal_records:
                pol_id = pol_term.policy_id
                if pol_id in round_policy_map:
                    pol_round = round_policy_map[pol_id]
                    if pol_term.account_state_hash != pol_round.account_state_after_hash:
                        raise FrozenRecordMutationError(
                            f"Policy {pol_id} terminal account_state_hash does not match "
                            "round account_state_after_hash"
                        )
                    if pol_term.pending_transition_hash is not None:
                        if (
                            pol_round.pending_after is None
                            or pol_term.pending_transition_hash
                            != pol_round.pending_after.pending_transition_hash
                        ):
                            raise FrozenRecordMutationError(
                                f"Policy {pol_id} terminal pending hash does not match "
                                "round pending_after"
                            )
                        so = staged_term_so_map.get(pol_term.settlement_outcome_hash)
                        if so is None:
                            raise FrozenRecordMutationError(
                                f"Policy {pol_id} terminal settlement outcome not found "
                                "in commit outcomes"
                            )
                        if (
                            so.status != SettlementStatus.REJECTED
                            or not so.rejection_reasons
                            or so.rejection_reasons[0].code != "UNSETTLED_EPISODE_TERMINATION"
                        ):
                            raise FrozenRecordMutationError(
                                f"Policy {pol_id} terminal settlement outcome must be REJECTED "
                                "with UNSETTLED_EPISODE_TERMINATION"
                            )
                        if so.policy_id != pol_id:
                            raise CrossPolicyContaminationError(
                                "Settlement outcome policy mismatch"
                            )
                    else:
                        if pol_round.pending_after is not None:
                            raise FrozenRecordMutationError(
                                f"Policy {pol_id} has active pending in round but null pending "
                                "in terminal record"
                            )

            self._validate_terminal_policy_set(term, commit.run.episode_id)
            referenced_terminal_outcomes = {
                p.settlement_outcome_hash
                for p in term.policy_terminal_records
                if p.settlement_outcome_hash is not None
            }
            all_referenced_outcomes = referenced_settlements | referenced_terminal_outcomes
            if all_referenced_outcomes != set(staged_term_so_map):
                raise FrozenRecordMutationError(
                    "Terminal settlement outcomes must exactly match terminal references"
                )

            if any(
                stored.terminal_record_id == term.terminal_record_id
                for stored in self._terminal_records.values()
            ):
                raise DuplicateIdentityError(
                    f"DeferredRunTerminalRecord {term.terminal_record_id} already exists"
                )

        # --- 6. Build a complete candidate state, then swap it into visibility. ---
        proposed_decisions = dict(self._proposed_decisions)
        decision_outcomes = dict(self._decision_outcomes)
        transitions = dict(self._transitions)
        account_states = {key: list(value) for key, value in self._account_states.items()}
        account_states_by_hash = dict(self._account_states_by_hash)
        pending_transitions = dict(self._pending_transitions)
        pending_by_run = {
            key: list(value) for key, value in self._pending_transitions_by_run.items()
        }
        settlement_outcomes = dict(self._settlement_outcomes)
        settlement_by_run = {
            key: list(value) for key, value in self._settlement_outcomes_by_run.items()
        }
        deferred_transitions = dict(self._deferred_transitions)
        deferred_by_run = {
            key: list(value) for key, value in self._deferred_transitions_by_run.items()
        }
        rounds = {key: list(value) for key, value in self._rounds.items()}
        metrics = {key: list(value) for key, value in self._metrics.items()}
        active_pending = dict(self._active_pending)
        terminal_records = dict(self._terminal_records)
        episode_runs = dict(self._episode_runs)
        fingerprints = dict(self._round_commit_fingerprints)

        for item in commit.proposed_decisions:
            proposed_decisions[item.decision_id] = item
        for item in commit.decision_outcomes:
            decision_outcomes[item.outcome_id] = item
        for item in commit.transitions:
            transitions[item.transition_id] = item
        for item in commit.account_states:
            account_states.setdefault((run_id, item.policy_id), []).append(item)
            account_states_by_hash[(run_id, item.compute_hash())] = item

        for item in commit.pending_transitions:
            pending_transitions[item.pending_transition_id] = item
            pending_by_run.setdefault(run_id, []).append(item)
        for item in commit.settlement_outcomes:
            settlement_outcomes[item.settlement_outcome_id] = item
            settlement_by_run.setdefault(run_id, []).append(item)
        for item in commit.deferred_transitions:
            deferred_transitions[item.transition_id] = item
            deferred_by_run.setdefault(run_id, []).append(item)

        rounds.setdefault(run_id, []).append(commit.round_record)
        for item in commit.metrics:
            metrics.setdefault(run_id, []).append(item)

        # Update active pending tracking
        if commit.terminal_record is not None:
            for p in commit.terminal_record.policy_terminal_records:
                active_pending[(run_id, p.policy_id)] = None
            terminal_records[run_id] = commit.terminal_record
        elif isinstance(commit.round_record, DeferredRoundRecord):
            for p in commit.round_record.policy_round_records:
                active_pending[(run_id, p.policy_id)] = p.pending_after

        episode_runs[run_id] = commit.run
        fingerprints[(run_id, commit.round_record.round_id)] = self._round_commit_fingerprint(
            commit
        )

        self._proposed_decisions = proposed_decisions
        self._decision_outcomes = decision_outcomes
        self._transitions = transitions
        self._account_states = account_states
        self._account_states_by_hash = account_states_by_hash
        self._pending_transitions = pending_transitions
        self._pending_transitions_by_run = pending_by_run
        self._settlement_outcomes = settlement_outcomes
        self._settlement_outcomes_by_run = settlement_by_run
        self._deferred_transitions = deferred_transitions
        self._deferred_transitions_by_run = deferred_by_run
        self._rounds = rounds
        self._metrics = metrics
        self._active_pending = active_pending
        self._terminal_records = terminal_records
        self._episode_runs = episode_runs
        self._round_commit_fingerprints = fingerprints

    def commit_terminal(self, commit: TerminalCommit) -> None:
        """Publish mid-episode or genesis cancellation as one atomic unit."""
        run_id = commit.run.run_id
        term = commit.terminal_record
        if term.run_id != run_id:
            raise FrozenRecordMutationError("Terminal record run_id does not match commit run")

        existing_run = self._episode_runs.get(run_id)
        if existing_run is None:
            raise FrozenRecordMutationError(f"EpisodeRun {run_id} not found")

        # Exact Retry Idempotency
        if run_id in self._terminal_records:
            if self._terminal_commit_fingerprints.get(run_id) != self._terminal_commit_fingerprint(
                commit
            ):
                raise FrozenRecordMutationError("Terminal commit retry payload is not identical")
            stored_term = self._terminal_records[run_id]
            if stored_term.compute_hash() != term.compute_hash():
                raise FrozenRecordMutationError(
                    f"DeferredRunTerminalRecord {term.terminal_record_id} already exists "
                    "with different hash"
                )
            if existing_run.compute_hash() != commit.run.compute_hash():
                raise FrozenRecordMutationError("Terminal commit retry with drifted run state")
            for so in commit.settlement_outcomes:
                s = self._settlement_outcomes.get(so.settlement_outcome_id)
                if s is None or s.compute_hash() != so.compute_hash():
                    raise FrozenRecordMutationError("SettlementOutcome mismatch on terminal retry")
            for m in commit.metrics:
                existing_m = self._metrics.get(run_id, [])
                if not any(em.compute_hash() == m.compute_hash() for em in existing_m):
                    raise FrozenRecordMutationError("MetricRecord mismatch on terminal retry")
            return

        # Concurrency & Lifecycle checks
        if existing_run.lifecycle_status == LifecycleStatus.COMPLETED:
            raise InvalidLifecycleTransitionError("Cannot cancel an already completed run")
        if commit.run.lifecycle_status != LifecycleStatus.CANCELLED:
            raise InvalidLifecycleTransitionError("TerminalCommit must transition run to CANCELLED")
        if commit.expected_run_hash != existing_run.compute_hash():
            raise FrozenRecordMutationError(
                f"Stale run hash: expected {commit.expected_run_hash}, "
                f"actual {existing_run.compute_hash()}"
            )
        if commit.run.final_state_hash != term.compute_hash():
            raise FrozenRecordMutationError(
                "EpisodeRun.final_state_hash must equal the terminal record hash"
            )
        self._validate_run_identity(existing_run, commit.run)
        if term.episode_id != commit.run.episode_id:
            raise FrozenRecordMutationError("Terminal record episode_id does not match commit run")
        self._validate_terminal_policy_set(term, commit.run.episode_id)
        for metric in commit.metrics:
            if metric.run_id != run_id:
                raise FrozenRecordMutationError("MetricRecord run_id does not match commit run")

        rounds = self._rounds.get(run_id, [])
        if not rounds:
            # Genesis cancellation
            if term.parent_round_hash is not None:
                raise FrozenRecordMutationError(
                    "Genesis cancellation must have parent_round_hash=None"
                )
            if term.simulation_frontier_time is not None:
                raise FrozenRecordMutationError(
                    "Genesis cancellation must have simulation_frontier_time=None"
                )
            if commit.settlement_outcomes:
                raise FrozenRecordMutationError(
                    "Genesis cancellation cannot include settlement outcomes"
                )
            for p in term.policy_terminal_records:
                state = self.get_account_state_by_hash(run_id, p.account_state_hash)
                if state is None or state.policy_id != p.policy_id:
                    raise FrozenRecordMutationError(
                        f"Terminal account state for policy {p.policy_id} is not persisted"
                    )
                if p.pending_transition_hash is not None or p.settlement_outcome_hash is not None:
                    raise FrozenRecordMutationError(
                        "Genesis policy terminal record cannot have pending or outcome"
                    )
        else:
            # Mid-episode cancellation
            latest_round = rounds[-1]
            if term.parent_round_hash != latest_round.compute_hash():
                raise FrozenRecordMutationError(
                    f"parent_round_hash mismatch: expected {latest_round.compute_hash()}, "
                    f"got {term.parent_round_hash}"
                )
            if term.simulation_frontier_time != latest_round.knowledge_cutoff:
                raise FrozenRecordMutationError(
                    "simulation_frontier_time must match latest round cutoff"
                )

            staged_so_map = {so.compute_hash(): so for so in commit.settlement_outcomes}
            for p in term.policy_terminal_records:
                active_p = self.get_active_pending_reference(run_id, p.policy_id)
                if active_p is not None:
                    if p.pending_transition_hash != active_p.pending_transition_hash:
                        raise FrozenRecordMutationError(
                            "Policy terminal pending hash does not match active pending"
                        )
                    so = staged_so_map.get(p.settlement_outcome_hash)
                    if so is None:
                        raise FrozenRecordMutationError(
                            f"Terminal settlement outcome {p.settlement_outcome_hash} "
                            "not found in staged outcomes"
                        )
                    if (
                        so.status != SettlementStatus.REJECTED
                        or not so.rejection_reasons
                        or so.rejection_reasons[0].code != "EPISODE_CANCELLED"
                    ):
                        raise FrozenRecordMutationError(
                            "Terminal settlement outcome on cancellation must be REJECTED "
                            "with EPISODE_CANCELLED"
                        )
                    if so.policy_id != p.policy_id:
                        raise CrossPolicyContaminationError("Settlement outcome policy mismatch")
                else:
                    if (
                        p.pending_transition_hash is not None
                        or p.settlement_outcome_hash is not None
                    ):
                        raise FrozenRecordMutationError(
                            "Policy without active pending cannot have terminal outcome"
                        )

                state = self.get_account_state_by_hash(run_id, p.account_state_hash)
                if state is None or state.policy_id != p.policy_id:
                    raise FrozenRecordMutationError(
                        f"Terminal account state for policy {p.policy_id} is not persisted"
                    )

            referenced_outcomes = {
                p.settlement_outcome_hash
                for p in term.policy_terminal_records
                if p.settlement_outcome_hash is not None
            }
            if referenced_outcomes != set(staged_so_map):
                raise FrozenRecordMutationError(
                    "Terminal settlement outcomes must exactly match terminal references"
                )

        self._require_new_ids(
            (item.settlement_outcome_id for item in commit.settlement_outcomes),
            self._settlement_outcomes,
            "SettlementOutcome",
        )
        existing_metric_ids = {
            metric.metric_record_id for metrics in self._metrics.values() for metric in metrics
        }
        self._require_new_ids(
            (item.metric_record_id for item in commit.metrics),
            existing_metric_ids,
            "MetricRecord",
        )
        if any(
            stored.terminal_record_id == term.terminal_record_id
            for stored in self._terminal_records.values()
        ):
            raise DuplicateIdentityError(
                f"DeferredRunTerminalRecord {term.terminal_record_id} already exists"
            )

        # Build the complete candidate state before making it visible.
        settlement_outcomes = dict(self._settlement_outcomes)
        settlement_by_run = {
            key: list(value) for key, value in self._settlement_outcomes_by_run.items()
        }
        metrics = {key: list(value) for key, value in self._metrics.items()}
        active_pending = dict(self._active_pending)
        terminal_records = dict(self._terminal_records)
        episode_runs = dict(self._episode_runs)
        fingerprints = dict(self._terminal_commit_fingerprints)
        for item in commit.settlement_outcomes:
            settlement_outcomes[item.settlement_outcome_id] = item
            settlement_by_run.setdefault(run_id, []).append(item)
        for item in commit.metrics:
            metrics.setdefault(run_id, []).append(item)
        for p in term.policy_terminal_records:
            active_pending[(run_id, p.policy_id)] = None

        terminal_records[run_id] = term
        episode_runs[run_id] = commit.run
        fingerprints[run_id] = self._terminal_commit_fingerprint(commit)

        self._settlement_outcomes = settlement_outcomes
        self._settlement_outcomes_by_run = settlement_by_run
        self._metrics = metrics
        self._active_pending = active_pending
        self._terminal_records = terminal_records
        self._episode_runs = episode_runs
        self._terminal_commit_fingerprints = fingerprints

    def _validate_terminal_policy_set(
        self, terminal: DeferredRunTerminalRecord, episode_id: str
    ) -> None:
        episode = self._episode_definitions.get(episode_id)
        if episode is None:
            raise FrozenRecordMutationError(f"EpisodeDefinition {episode_id} not found")
        expected = sorted(policy.policy_id for policy in episode.policy_versions)
        actual = [record.policy_id for record in terminal.policy_terminal_records]
        if actual != expected:
            raise FrozenRecordMutationError(
                f"Terminal policies {actual} do not match episode policies {expected}"
            )

    @staticmethod
    def _validate_run_identity(existing: EpisodeRun, candidate: EpisodeRun) -> None:
        if (
            candidate.episode_id != existing.episode_id
            or candidate.episode_definition_hash != existing.episode_definition_hash
            or candidate.total_rounds != existing.total_rounds
        ):
            raise FrozenRecordMutationError("EpisodeRun immutable identity fields changed")

    @staticmethod
    def _round_commit_fingerprint(commit: RoundCommit) -> str:
        return compute_record_hash(
            {
                "run": commit.run.compute_hash(),
                "round": commit.round_record.compute_hash(),
                "proposed_decisions": [item.compute_hash() for item in commit.proposed_decisions],
                "decision_outcomes": [item.compute_hash() for item in commit.decision_outcomes],
                "transitions": [item.compute_hash() for item in commit.transitions],
                "account_states": [item.compute_hash() for item in commit.account_states],
                "metrics": [item.compute_hash() for item in commit.metrics],
                "pending_transitions": [item.compute_hash() for item in commit.pending_transitions],
                "settlement_outcomes": [item.compute_hash() for item in commit.settlement_outcomes],
                "deferred_transitions": [
                    item.compute_hash() for item in commit.deferred_transitions
                ],
                "terminal_record": (
                    commit.terminal_record.compute_hash()
                    if commit.terminal_record is not None
                    else None
                ),
            }
        )

    @staticmethod
    def _terminal_commit_fingerprint(commit: TerminalCommit) -> str:
        return compute_record_hash(
            {
                "expected_run_hash": commit.expected_run_hash,
                "run": commit.run.compute_hash(),
                "terminal_record": commit.terminal_record.compute_hash(),
                "settlement_outcomes": [item.compute_hash() for item in commit.settlement_outcomes],
                "metrics": [item.compute_hash() for item in commit.metrics],
            }
        )

    @staticmethod
    def _require_new_ids(ids, existing, record_type: str) -> None:
        seen: set[str] = set()
        for record_id in ids:
            if record_id in seen or record_id in existing:
                raise DuplicateIdentityError(f"{record_type} {record_id} already exists")
            seen.add(record_id)

    def get_rounds(self, run_id: str) -> list[RoundRecord | DeferredRoundRecord]:
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

    def get_decision_outcomes(
        self, run_id: str, policy_id: str | None = None
    ) -> list[DecisionOutcome]:
        round_ids = {record.round_id for record in self._rounds.get(run_id, [])}
        values = [item for item in self._decision_outcomes.values() if item.round_id in round_ids]
        if policy_id is not None:
            values = [item for item in values if item.policy_id == policy_id]
        return values

    def save_transition(self, transition: TransitionRecord) -> None:
        if transition.transition_id in self._transitions:
            raise DuplicateIdentityError(
                f"TransitionRecord {transition.transition_id} already exists"
            )
        self._transitions[transition.transition_id] = transition

    def get_transition(self, transition_id: str) -> TransitionRecord | None:
        return self._transitions.get(transition_id)

    def get_transitions(self, run_id: str, policy_id: str | None = None) -> list[TransitionRecord]:
        round_ids = {record.round_id for record in self._rounds.get(run_id, [])}
        values = [item for item in self._transitions.values() if item.round_id in round_ids]
        if policy_id is not None:
            values = [item for item in values if item.policy_id == policy_id]
        return values

    def save_account_state(self, run_id: str, state: VirtualAccountState) -> None:
        key = (run_id, state.policy_id)
        states = self._account_states.setdefault(key, [])
        if any(item.account_state_id == state.account_state_id for item in states):
            raise DuplicateIdentityError(
                f"VirtualAccountState {state.account_state_id} already exists"
            )
        if states and states[-1].round_index >= state.round_index:
            raise FrozenRecordMutationError(
                f"Account state round {state.round_index} does not follow "
                f"round {states[-1].round_index}"
            )
        states.append(state)
        self._account_states_by_hash[(run_id, state.compute_hash())] = state

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

    # --- Deferred Persistence Getters ---

    def get_pending_transition(self, pending_id: str) -> PendingTransitionRecord | None:
        return self._pending_transitions.get(pending_id)

    def get_pending_transitions(
        self, run_id: str, policy_id: str | None = None
    ) -> list[PendingTransitionRecord]:
        items = self._pending_transitions_by_run.get(run_id, [])
        if policy_id is not None:
            return [it for it in items if it.policy_id == policy_id]
        return list(items)

    def get_settlement_outcome(self, outcome_id: str) -> SettlementOutcome | None:
        return self._settlement_outcomes.get(outcome_id)

    def get_settlement_outcomes(
        self, run_id: str, policy_id: str | None = None
    ) -> list[SettlementOutcome]:
        items = self._settlement_outcomes_by_run.get(run_id, [])
        if policy_id is not None:
            return [it for it in items if it.policy_id == policy_id]
        return list(items)

    def get_deferred_transition(self, transition_id: str) -> DeferredTransitionRecord | None:
        return self._deferred_transitions.get(transition_id)

    def get_deferred_transitions(
        self, run_id: str, policy_id: str | None = None
    ) -> list[DeferredTransitionRecord]:
        items = self._deferred_transitions_by_run.get(run_id, [])
        if policy_id is not None:
            return [it for it in items if it.policy_id == policy_id]
        return list(items)

    def get_account_state_by_hash(self, run_id: str, state_hash: str) -> VirtualAccountState | None:
        return self._account_states_by_hash.get((run_id, state_hash))

    def get_active_pending_reference(
        self, run_id: str, policy_id: str
    ) -> PendingStateReference | None:
        # If run is terminated, no pending order is active
        if run_id in self._terminal_records:
            return None

        # Check cached active pending
        if (run_id, policy_id) in self._active_pending:
            return self._active_pending[(run_id, policy_id)]

        # Fallback: derive authoritative active pending from latest committed round
        rounds = self._rounds.get(run_id, [])
        if rounds and isinstance(rounds[-1], DeferredRoundRecord):
            for pol_entry in rounds[-1].policy_round_records:
                if pol_entry.policy_id == policy_id:
                    self._active_pending[(run_id, policy_id)] = pol_entry.pending_after
                    return pol_entry.pending_after
        return None

    def get_terminal_record(self, run_id: str) -> DeferredRunTerminalRecord | None:
        return self._terminal_records.get(run_id)
