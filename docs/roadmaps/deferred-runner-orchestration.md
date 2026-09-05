# Deferred Runner Orchestration and Atomic Persistence

## Work unit and review status

- ID: `DS-02D2C1`; status: plan frozen, ready for independent review.
- Prerequisite: reviewed C0 (`d2243bb`) and B1/B2 (`d365cd8`); Gate `DS-D3B` satisfied.
- Parent: [market plan](market-dataset-and-baseline-evidence.md).
- Authority: [deferred settlement contract](../contracts/deferred-settlement-contract.md) and [deferred run terminal contract](../contracts/deferred-run-terminal-contract.md).
- Next authorized work: independent review of this specification; implementation begins only upon review acceptance.
- C2 replay and DS-02E market episodes remain blocked; `DS-D3` is not satisfied.

---

## 1. Frozen Architecture and Boundaries

### 1.1 Permitted production files for future C1 implementation

The future implementation of `DS-02D2C1` may modify or create ONLY the following files:

1. `apps/backend/src/simulator/domain/deferred_terminal.py`: [NEW] Domain dataclass and codec for `DeferredRunTerminalRecord`.
2. `apps/backend/src/simulator/domain/models.py`: [MODIFY] Export `DeferredRunTerminalRecord` and `PolicyTerminalRecord`.
3. `apps/backend/src/simulator/application/ports/persistence.py`: [MODIFY] Add deferred persistence signatures, `TerminalCommit`, and additive `RoundCommit` fields.
4. `apps/backend/src/simulator/infrastructure/adapters/in_memory_store.py`: [MODIFY] Implement run-scoped deferred storage, index lookups, exact-retry idempotency, and atomic candidate validation for `RoundCommit` and `TerminalCommit`.
5. `apps/backend/src/simulator/application/services/runner.py`: [MODIFY] Implement `_execute_next_round_deferred`, terminal execution on episode completion/cancellation, and deterministic schedule resolution.
6. `apps/backend/src/simulator/application/services/evaluator.py`: [MODIFY] Add `DeferredEvaluationContext` and `calculate_deferred_metrics`.
7. `apps/backend/tests/unit/application/test_deferred_runner.py`: [NEW] Unit and integration tests for deferred runner orchestration.
8. `apps/backend/tests/unit/infrastructure/test_deferred_persistence.py`: [NEW] Persistence, atomic commit, fault-injection, and retry tests.

### 1.2 Explicitly forbidden files

- `apps/backend/src/simulator/domain/deferred_round.py`: FROZEN in `DS-02D2C0` (commit `d2243bb`).
- `apps/backend/src/simulator/application/services/deferred_admission.py`: FROZEN in `DS-02D2B1` (commit `40308b4`).
- `apps/backend/src/simulator/application/services/deferred_settlement.py`: FROZEN in `DS-02D2B2` (commit `d365cd8`).
- `apps/backend/src/simulator/application/services/replay.py`: Reserved exclusively for `DS-02D2C2`.
- `apps/backend/src/simulator/domain/models.py` (v1 classes): `RoundRecord`, `TransitionRecord`, `DecisionOutcome` definitions must NOT be modified.
- `docs/contracts/schemas/*.v1.json`: All v1 JSON schemas remain strictly frozen.
- `docs/contracts/schemas/round.v2.json`: Frozen in `DS-02D2C0`.
- Presentation layer, SQLite/database ports, live REST/Binance API connectors, or Optees solver integration.

---

## 2. Decision 1: Deferred Configuration and Schedule Provenance

### 2.1 Explicit Versioned Configuration in `EpisodeDefinition.metadata`

To ensure deterministic recovery across runner restarts, execution mode and schedule are NOT passed via mutable constructor arguments.
Instead, an episode requiring deferred settlement MUST define an explicit, typed dictionary under `episode_def.metadata["deferred_settlement"]`:

```python
{
    "schema_version": "1.0.0",
    "settlement_mode": "deferred",
    "calendar_identity": "cal_binance_daily_utc",
    "calendar_frequency": "1d",
    "resource_to_series_map": {
        "BTC": "BTC_USDT_PRICE_1D",
        "ETH": "ETH_USDT_PRICE_1D",
        "SOL": "SOL_USDT_PRICE_1D",
        "BNB": "BNB_USDT_PRICE_1D",
    },
    "scheduled_openings": {
        "2026-08-01T00:00:00Z": "2026-08-02T00:00:00Z",
        "2026-08-02T00:00:00Z": "2026-08-03T00:00:00Z",
        "2026-08-03T00:00:00Z": "2026-08-04T00:00:00Z",
    },
    "scheduled_deadlines": {
        "2026-08-01T00:00:00Z": "2026-08-05T00:00:00Z",
        "2026-08-02T00:00:00Z": "2026-08-06T00:00:00Z",
        "2026-08-03T00:00:00Z": "2026-08-07T00:00:00Z",
    },
    "deadline_policy": "INCLUSIVE",
}
```

### 2.2 Schedule Invariants and Retrieval

1. **Recovery from Store:**
   Any `EpisodeRunner` instance (whether initial or reconstructed after process restart) retrieves `episode_def = self._persistence.get_episode_definition(run.episode_id)`.
   If `episode_def.metadata.get("deferred_settlement")` is absent, the runner executes legacy synchronous logic (`execute_next_round` calling existing synchronous flow).
   If present, it validates `schema_version == "1.0.0"` and enforces all required schedule keys.
2. **Deterministic `expected_open_time`:**
   When admitting a proposal at cutoff $T_r$, the runner obtains `expected_open_time = scheduled_openings[T_r]`.
   It is NEVER inferred from available observations, bar arrival times, or round interval math. If $T_r$ is missing from `scheduled_openings`, admission fails immediately with `InvalidDecisionContextError`.
3. **Deterministic `settlement_deadline` and INCLUSIVE Policy:**
   `settlement_deadline = scheduled_deadlines[T_r]`.
   - **Inclusive Deadline Rule:** An observation is eligible for settlement if and only if:
     $$t_{\text{knowledge}}(\text{obs}) \le \text{settlement\_deadline}$$
   - **Late Discovery Rule:** If a target bar was published with $t_{\text{knowledge}} \le \text{settlement\_deadline}$, but the runner first inspects it at a round cutoff $T_{\text{eval}} > \text{settlement\_deadline}$ (e.g. skipped or delayed round evaluation), the trade **MUST STILL SETTLE**.
   - **Exogenous Timeout (`MISSING_EXECUTION_BAR`):** Only if at cutoff $T_{\text{eval}}$ NO eligible bar exists with $t_{\text{knowledge}} \le \text{settlement\_deadline}$ AND $T_{\text{eval}} > \text{settlement\_deadline}$, the pending order is terminated as `REJECTED` with reason `MISSING_EXECUTION_BAR`.

---

## 3. Decision 2: Persistence Boundary, Run-Scoped Indexing, and Atomic Retry

### 3.1 PersistencePort Additive Signatures

```python
class PersistencePort(ABC):
    # Existing methods remain unchanged ...

    @abstractmethod
    def save_pending_transition(self, pending: PendingTransitionRecord) -> None: ...

    @abstractmethod
    def get_pending_transition(
        self, pending_id: str
    ) -> PendingTransitionRecord | None: ...

    @abstractmethod
    def get_pending_transitions(
        self, run_id: str, policy_id: str | None = None
    ) -> list[PendingTransitionRecord]: ...

    @abstractmethod
    def save_settlement_outcome(self, outcome: SettlementOutcome) -> None: ...

    @abstractmethod
    def get_settlement_outcome(
        self, outcome_id: str
    ) -> SettlementOutcome | None: ...

    @abstractmethod
    def get_settlement_outcomes(
        self, run_id: str, policy_id: str | None = None
    ) -> list[SettlementOutcome]: ...

    @abstractmethod
    def save_deferred_transition(
        self, transition: DeferredTransitionRecord
    ) -> None: ...

    @abstractmethod
    def get_deferred_transition(
        self, transition_id: str
    ) -> DeferredTransitionRecord | None: ...

    @abstractmethod
    def get_deferred_transitions(
        self, run_id: str, policy_id: str | None = None
    ) -> list[DeferredTransitionRecord]: ...

    @abstractmethod
    def get_active_pending_reference(
        self, run_id: str, policy_id: str
    ) -> PendingStateReference | None: ...

    @abstractmethod
    def get_account_state_by_hash(
        self, run_id: str, state_hash: str
    ) -> VirtualAccountState | None: ...

    @abstractmethod
    def commit_terminal(self, commit: TerminalCommit) -> None: ...

    @abstractmethod
    def get_terminal_record(
        self, run_id: str
    ) -> DeferredRunTerminalRecord | None: ...
```

### 3.2 Additive Atomic Commit Shapes

```python
@dataclass(frozen=True)
class RoundCommit:
    run: EpisodeRun
    round_record: RoundRecord | DeferredRoundRecord
    proposed_decisions: tuple[ProposedDecision, ...] = ()
    decision_outcomes: tuple[DecisionOutcome, ...] = ()
    transitions: tuple[TransitionRecord, ...] = ()
    account_states: tuple[VirtualAccountState, ...] = ()
    metrics: tuple[MetricRecord, ...] = ()
    # Additive deferred fields:
    pending_transitions: tuple[PendingTransitionRecord, ...] = ()
    settlement_outcomes: tuple[SettlementOutcome, ...] = ()
    deferred_transitions: tuple[DeferredTransitionRecord, ...] = ()


@dataclass(frozen=True)
class TerminalCommit:
    run: EpisodeRun
    terminal_record: DeferredRunTerminalRecord
    settlement_outcomes: tuple[SettlementOutcome, ...] = ()
    metrics: tuple[MetricRecord, ...] = ()
```

### 3.3 InMemoryStore Validation and Invariants

1. **Pre-commit Fail-Closed Candidate Validation:**
   Before updating ANY internal map, `commit_round` and `commit_terminal` perform complete structural validation:
   - Run identifier matches across all staged items.
   - For `RoundCommit`: `round_record.round_index` strictly equals `existing_rounds[-1].round_index + 1` (or `0` if empty).
   - `round_record.parent_round_hash` strictly equals `existing_rounds[-1].compute_hash()` (or `None` if empty).
   - Candidate record IDs checked against existing records.
   - For `DeferredRoundRecord`: validates that `state_merkle_hash` matches `compute_deferred_state_merkle_hash(parent_round_hash, policy_round_records)`.
2. **Exact Retry Idempotency (Lost ACK handling):**
   If `commit.round_record.round_id` already exists in `self._rounds[run_id]`:
   - The store compares `commit.round_record.compute_hash()` with the existing round's hash.
   - If identical, and all staged items match existing records bit-for-bit, `commit_round` returns cleanly as an **idempotent no-op**.
   - If IDs match but hashes/payloads differ, the store raises `FrozenRecordMutationError` or `DuplicateIdentityError`.
3. **Concurrency Conflict Prevention:**
   If `commit.round_record.parent_round_hash != current_parent_hash`, the commit is rejected with `FrozenRecordMutationError("Parent round hash mismatch: concurrency conflict")`.
4. **Run-Scoped State and Recovery:**
   `_account_states_by_hash: dict[tuple[str, str], VirtualAccountState]` indexes states by `(run_id, state_hash)`.
   `_active_pending: dict[tuple[str, str], PendingStateReference | None]` tracks the active pending reference for each `(run_id, policy_id)`.
   On restart, a new `EpisodeRunner` reads `latest_round = store.get_rounds(run_id)[-1]`.
   For each policy, it restores `active_ref = policy_entry.pending_after`. If present, it resolves the underlying `PendingTransitionRecord` and `admission_account` from store indices.

---

## 4. Decision 3: Deferred Run Terminal Record

See [`docs/contracts/deferred-run-terminal-contract.md`](../contracts/deferred-run-terminal-contract.md) for full authoritative schema and field patterns.

### 4.1 Specification of `DeferredRunTerminalRecord`

```python
@dataclass(frozen=True)
class PolicyTerminalRecord:
    policy_id: str
    account_state_hash: str
    pending_transition_hash: str | None
    settlement_outcome_hash: str | None


@dataclass(frozen=True)
class DeferredRunTerminalRecord:
    terminal_record_id: str
    run_id: str
    episode_id: str
    terminal_status: str  # "COMPLETED" or "CANCELLED"
    reason_code: str  # "CLEAN_COMPLETION", "UNSETTLED_EPISODE_TERMINATION", "EPISODE_CANCELLED"
    reason_message: str
    simulated_effective_time: str
    execution_timestamp: str
    parent_round_hash: str | None
    policy_terminal_records: tuple[PolicyTerminalRecord, ...]
    terminal_state_merkle_hash: str
    schema_version: str = "1.0.0"
```

### 4.2 Handling the 7 Terminal Scenarios

1. **Pending order active at final round completion:**
   - In Round $K-1$, `pending_after` retains the pending reference. Round $K-1$ commits.
   - The runner detects `current_round_index >= total_rounds`.
   - For policies with active pending, it calls:
     `DeferredSettlementService.terminate_unsettled(..., reason_code=REJECTION_UNSETTLED_EPISODE_TERMINATION, settlement_time=final_cutoff)`.
   - The terminal `SettlementOutcome` is staged into `TerminalCommit`.
   - `PolicyTerminalRecord` records `pending_transition_hash` and `settlement_outcome_hash`.
   - Atomic commit via `store.commit_terminal(TerminalCommit)`.
2. **Old pending settled, new proposal admitted in final round:**
   - Round $K-1$ settles old pending (`settlement_outcome_hash` in Round $K-1$) and admits new trade (`pending_after`). Round $K-1$ commits cleanly.
   - In terminal transition, the newly admitted pending is terminated via `UNSETTLED_EPISODE_TERMINATION` in `DeferredRunTerminalRecord`.
   - No conflict: each outcome occupies its own unique, lossless record.
3. **New admission in final round (without prior pending):**
   - Round $K-1$ records admission in `pending_after`.
   - Terminal record terminates it with `UNSETTLED_EPISODE_TERMINATION`.
4. **Cancellation between rounds:**
   - Runner calls `cancel_run(run_id, reason="User cancelled")`.
   - Active pending orders terminated with `EPISODE_CANCELLED`.
   - `DeferredRunTerminalRecord` has `terminal_status = "CANCELLED"`, `parent_round_hash = latest_round.compute_hash()`.
   - Committed atomically via `commit_terminal`.
5. **Zero-round run (cancellation at genesis):**
   - `parent_round_hash = None`.
   - All `policy_terminal_records` have `pending_transition_hash = None`, `settlement_outcome_hash = None`.
   - Run transitions to `CANCELLED`.
6. **Repeated cancellation:**
   - Calling `cancel_run` on a run already `CANCELLED` is an idempotent no-op returning the existing `EpisodeRun`.
7. **Cancellation of already completed run:**
   - Calling `cancel_run` on a run with `lifecycle_status == COMPLETED` raises `InvalidLifecycleTransitionError`.

---

## 5. Decision 4: Causal Step-by-Step Round Execution Flow

For each round $r$ at cutoff $T_r$:

```text
Step 1: Time & Eligibility
  - Simulated cutoff = T_r. Execution timestamps recorded via clock.
  - Eligible observations = { obs | obs.knowledge_time <= T_r }.

Step 2: Settlement Phase (Strictly precedes policy invocation)
  For each policy (in lexicographical policy_id order):
    - Retrieve current VirtualAccountState and active PendingStateReference.
    - If active pending exists:
        - Check deadline: If NO eligible target bar exists with knowledge_time <= deadline
          AND T_r > deadline:
            Call DeferredSettlementService.terminate_unsettled(reason_code=MISSING_EXECUTION_BAR).
            Outcome staged. next_account = current_account. Active pending cleared.
        - Else:
            Call DeferredSettlementService.attempt_settlement(...).
            If is_settled:
                Outcome & DeferredTransition staged. next_account minted. Active pending cleared.
            Elif is_still_pending:
                No outcome/transition. next_account = current_account. Active pending retained.
            Else (both False -> REJECTED):
                Outcome staged. No transition. next_account = current_account. Active pending cleared.
    - If no active pending:
        next_account = current_account.

Step 3: Policy Delivery Phase
  - Construct PolicyContext with account_state = next_account (reflecting settled funds!)
    and eligible observations.

Step 4: Policy Proposal Phase
  - proposal = policy.propose_decision(context).
  - Call DeferredAdmissionService.admit_decision(..., current_pending=active_pending).
  - If is_newly_admitted:
      Create PendingStateReference(expected_open_time, settlement_deadline from schedule).
      Stage PendingTransitionRecord. pending_after = new_ref. decision_outcome = None.
  - Elif is_reused_pending (same-round exact retry):
      pending_after = pending_before. decision_outcome = None.
  - Else (HOLD or rejection):
      Stage DecisionOutcome.
      If active pending exists: pending_after = pending_before (HOLD carries order forward).
      Else: pending_after = None.

Step 5: Assemble Policy Entries & Merkle Root
  - Construct DeferredPolicyRoundRecord for each policy.
  - Compute state_merkle_hash = compute_deferred_state_merkle_hash(parent_round_hash, sorted_entries).
  - Construct DeferredRoundRecord.

Step 6: Atomic Commit
  - Publish RoundCommit via self._persistence.commit_round(commit).
```

---

## 6. Decision 5: Typed Evaluator Integration

### 6.1 `DeferredEvaluationContext`

`EvaluatorService` MUST NOT accept fabricated v1 `TransitionRecord`s. An explicit adapter `calculate_deferred_metrics` accepts:

```python
@dataclass(frozen=True)
class DeferredEvaluationContext:
    run_id: str
    policy_id: str
    initial_account: VirtualAccountState
    account_states: tuple[VirtualAccountState, ...]
    proposal_outcomes: tuple[DecisionOutcome, ...]
    settlement_outcomes: tuple[SettlementOutcome, ...]
    deferred_transitions: tuple[DeferredTransitionRecord, ...]
    wall_time_seconds: float = 0.0
    calculated_at: str = "2026-08-01T00:00:00Z"
```

### 6.2 Metric Accounting Rules

1. **Turnover & Transaction Costs:**
   Calculated strictly and exclusively from `deferred_transitions` (which exist only for `SETTLED` trades).
   Admitted pending transitions and rejected settlements contribute ZERO to volume or costs.
2. **Equity Curve:**
   Constructed from `initial_account` and subsequent `account_states`. Intermediate rounds without trades preserve net value based on valuation marks.
3. **Rejected Decision Count:**
   $$\text{rejected\_decision\_count} = \sum [\text{status} == \text{REJECTED} \text{ in } \text{proposal\_outcomes}] + \sum [\text{status} == \text{REJECTED} \text{ in } \text{settlement\_outcomes}]$$
   Separately tracked in explanatory breakdown without violating `metric_record.v1.json`.

---

## 7. Decision 6: Simulated Time vs Injected Wall Clock

1. **Simulated Time (Domain Invariants):**
   - Round cutoffs, `admitted_at`, `settled_at`, `as_of_time`, and `simulated_effective_time` derive strictly from `episode_def.calendar.round_cutoffs`.
   - They NEVER advance or query wall clock time.
2. **Wall Clock (Execution Tracking):**
   - `execution_start_time`, `execution_end_time`, and `execution_timestamp` are obtained exclusively through `self._clock.now_utc()`.
3. **Byte-Identical Reproducibility:**
   - In deterministic tests and benchmarks, an `InMemoryClock` with pinned or step-advanced time is injected.
   - Under an identical injected clock and dataset, execution reproduces 100% byte-identical records, SHA-256 hashes, and Merkle roots.

---

## 8. Edge-Case Matrix and Fault-Injection Verification

| Test Scenario | Trigger Condition | Expected Behavior |
|---|---|---|
| **Exact Deadline Fill** | $t_{\text{knowledge}} == \text{settlement\_deadline}$ | SETTLED (Inclusive rule). |
| **Late Discovery** | Target bar $t_{\text{knowledge}} \le \text{deadline}$, inspected at $T > \text{deadline}$ | SETTLED (Eligible evidence respected). |
| **Missing Bar Expiry** | Target bar not published and $T > \text{deadline}$ | REJECTED (`MISSING_EXECUTION_BAR`), zero fee debit. |
| **Mid-Episode Cancellation** | `cancel_run` with active pending | Terminated with `EPISODE_CANCELLED`, `TerminalCommit` published. |
| **Genesis Cancellation** | `cancel_run` before round 0 | `DeferredRunTerminalRecord` with `parent_round_hash=None`. |
| **Completed Run Cancellation** | `cancel_run` on completed episode | Raises `InvalidLifecycleTransitionError`. |
| **Duplicate Commit Retry** | Identical `RoundCommit` re-submitted | Idempotent no-op success. |
| **Mutated Commit Collision** | Same `round_id` with drifted payload | Fails closed with `FrozenRecordMutationError`. |
| **Stale Parent Race** | Commit parent hash != store's last round hash | Fails closed with concurrency error. |
| **Store Fault Injection** | Exception during candidate validation | Store maps and indices completely unmutated. |
| **Restart Recovery** | New runner initialized on existing store | Resumes run from committed state without drift. |

---

## 9. Gate DS-D3C1 Completion Standard

A future implementation work unit is complete only when:

1. `DeferredRunTerminalRecord` and `TerminalCommit` implemented and exported.
2. `PersistencePort` and `InMemoryStore` support all deferred records and atomic commits.
3. `EpisodeRunner` orchestrates multi-round deferred episodes and clean/cancelled termination.
4. `EvaluatorService` computes metrics via `DeferredEvaluationContext`.
5. All 11 edge cases above pass regression testing.
6. All baseline backend tests (339 tests) pass with zero regressions.
7. Contract validation (`validate_contracts.py`), Ruff check, format, and git diff checks pass cleanly.
8. Implementation independently reviewed.

**Next Authorized Step:** Independent review of this frozen plan. Runtime implementation is not authorized until review acceptance.
