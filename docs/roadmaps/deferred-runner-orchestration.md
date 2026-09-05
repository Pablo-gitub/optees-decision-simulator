# Deferred Runner Orchestration and Atomic Persistence

## Work unit

- ID: `DS-02D2C1`; status: planned, ready for implementation, not implemented.
- Owner: Gemini; independent review afterwards.
- Parent: [market plan](market-dataset-and-baseline-evidence.md).
- Prerequisite: reviewed C0 (`d2243bb`), reviewed B1/B2 (`d365cd8`), Gate DS-D3B.
- Contract: [deferred settlement](../contracts/deferred-settlement-contract.md).
- Next: `DS-02D2C2` (replay and end-to-end evidence); Gate `DS-D3`.

## Purpose and boundaries

`DS-02D2C0` froze the immutable `DeferredRoundRecord` (round v2) record shape and state Merkle sequencing. Pure services `DS-02D2B1` (admission) and `DS-02D2B2` (settlement) are tested and reviewed.

`DS-02D2C1` orchestrates these pure components into `EpisodeRunner` and the persistence boundary (`RoundCommit`, `PersistencePort`, `InMemoryStore`).

### What this work unit includes

1. **Persistence Boundary (`RoundCommit`, `PersistencePort`, `InMemoryStore`):**
   - Extend `RoundCommit` to support `DeferredRoundRecord` and deferred settlement entities:
     `pending_transitions: tuple[PendingTransitionRecord, ...]`,
     `settlement_outcomes: tuple[SettlementOutcome, ...]`,
     `deferred_transitions: tuple[DeferredTransitionRecord, ...]`.
   - Extend `PersistencePort` with abstract lookup and retrieval methods for deferred records:
     `save_pending_transition`, `get_pending_transition`, `get_pending_transitions`, `get_active_pending_transition`,
     `save_settlement_outcome`, `get_settlement_outcome`, `get_settlement_outcomes`,
     `save_deferred_transition`, `get_deferred_transition`, `get_deferred_transitions`.
   - Implement storage and atomic validation in `InMemoryStore`:
     - Verify uniqueness of pending, settlement outcome, and deferred transition identifiers before persisting.
     - Validate that round index is strictly monotonic and run ID matches.
     - Implement `get_active_pending_transition(run_id, policy_id)` by resolving admitted pending transitions that lack a terminal `SettlementOutcome`.
     - Ensure all records in a `RoundCommit` become visible atomically.

2. **Runner Orchestration (`EpisodeRunner`):**
   - Support deferred settlement mode without disturbing the synchronous path:
     - Inspect `episode_def.metadata.get("settlement_mode") == "deferred"` (or optional constructor injection).
     - Retain `_execute_next_round_synchronous` completely unchanged for v1 backward compatibility.
     - Implement `_execute_next_round_deferred` following the strict 6-step causal ordering:
       - **Step 1: Clock Advance:** Advance clock to round cutoff $T_{\text{cutoff}}$.
       - **Step 2: Eligibility Filtering:** Extract observations where $t_{\text{knowledge}} \le T_{\text{cutoff}}$.
       - **Step 3: Settlement Phase:**
         For each policy in lexicographic order:
         - Inspect active pending transition via `pending_before`.
         - If pending exists:
           - If $T_{\text{cutoff}} > \text{settlement\_deadline}$, terminate via `DeferredSettlementService.terminate_unsettled(..., reason_code=REJECTION_MISSING_EXECUTION_BAR)`.
           - Else attempt settlement via `DeferredSettlementService.attempt_settlement(...)`.
           - On `is_settled`: mint updated `VirtualAccountState`, record `SettlementOutcome` and `DeferredTransitionRecord`, clear active pending.
           - On `is_still_pending`: carry over `PendingStateReference` unchanged; balance remains unmutated.
         - If no pending exists: continue.
       - **Step 4: Policy Delivery Phase:**
         Deliver latest account state (`VirtualAccountState`) and eligible observations to `PolicyContext`.
       - **Step 5: Policy Proposal Phase:**
         - Policy invokes `propose_decision(context)`.
         - Pass proposal and active pending order to `DeferredAdmissionService.admit_decision(...)`.
         - On `is_newly_admitted`: stage `PendingTransitionRecord`, construct `pending_after` reference.
         - On `is_reused_pending`: carry over existing `pending_before` reference.
         - On rejection or `HOLD`: stage immediate `DecisionOutcome`.
       - **Step 6: Round Assembly & State Merkle Hashing:**
         - Construct `DeferredPolicyRoundRecord` for each policy in strict lexicographic order.
         - Compute `state_merkle_hash` via `compute_deferred_state_merkle_hash(parent_round_hash, policy_round_records)`.
         - Construct `DeferredRoundRecord` (`round.v2.json`).
       - **Step 7: Atomic Commit:**
         - Stage all produced records into `RoundCommit`.
         - Execute `self._persistence.commit_round(commit)`.
       - **Step 8: Terminal & Completion Handling:**
         - On final round completion (`current_round_index >= total_rounds`), terminate any remaining unsettled orders via `DeferredSettlementService.terminate_unsettled(..., reason_code=REJECTION_UNSETTLED_EPISODE_TERMINATION)`.
         - Compute final `MetricRecord`s using `EvaluatorService.calculate_metrics`.
         - On `cancel_run`, terminate active pending orders via `DeferredSettlementService.terminate_unsettled(..., reason_code=REJECTION_EPISODE_CANCELLED)`.

3. **Evaluator Compatibility:**
   - Verify `EvaluatorService.calculate_metrics` correctly aggregates costs and volume from `DeferredTransitionRecord` and counts terminal rejections.

### What this work unit EXCLUDES

- No modifications to `ReplayService` or divergence reporting (that is `DS-02D2C2`).
- No modifications to frozen public v1 schemas or v1 domain models.
- No historical market dataset runs or Optees solver integrations (that is `DS-02E`).
- No REST API, database, or UI implementations.

## Invariants and failure modes

1. **Causal Separation Theorem:**
   Settlement of an existing pending order strictly precedes the delivery of account state to the policy and policy proposal generation. Settled cash/assets are immediately available in the proposal phase of the same round.
2. **Single-Pending Invariant:**
   A policy with an active pending order can submit only `HOLD` or an empty proposal. Submitting an actionable proposal while an order is pending causes immediate rejection (`POLICY_HAS_PENDING_SETTLEMENT`).
3. **Lossless Round Tracking:**
   `DeferredPolicyRoundRecord` stores explicit references to both `pending_before` and `pending_after`. No fabricated `ACCEPTED` outcome is minted for pending trades.
4. **All-or-Nothing Persistence:**
   `commit_round` publishes run progress, round record, proposals, outcomes, transitions, pending records, and account states as a single atomic unit. Any failure aborts the commit with zero partial state mutation.
5. **Deterministic Re-Execution:**
   Re-running an identical deferred episode configuration with identical inputs reproduces the exact sequence of records, hashes, and Merkle roots bit-for-bit.

## Required evidence

- [ ] Unit tests for `PersistencePort` and `InMemoryStore` covering deferred record CRUD and atomic round commits.
- [ ] End-to-end multi-round execution tests in `EpisodeRunner` covering:
  - Normal D+2 delayed settlement (Round 0 admit -> Round 1 wait with HOLD -> Round 2 settle + new proposal).
  - Missing execution bar deadline timeout (`MISSING_EXECUTION_BAR`).
  - Price movement causing insufficient funds (`INSUFFICIENT_FUNDS_AT_SETTLEMENT`).
  - Short position rejection (`SHORT_POSITIONS_FORBIDDEN`).
  - Episode cancellation with pending order (`EPISODE_CANCELLED`).
  - Episode completion with unsettled order (`UNSETTLED_EPISODE_TERMINATION`).
  - Multi-policy execution with cross-policy isolation.
- [ ] Backward compatibility: all 339 existing tests pass without modification.
- [ ] Code formatting, linting, and contract validation pass cleanly.

## Completion and next boundary

- [x] Execution flow, persistence boundary, and failure modes planned.
- [ ] Implementation and unit/integration test evidence complete.
- [ ] Independent review accepted.

Next work unit to detail is `DS-02D2C2` (Replay Integration and End-to-End Evidence).
