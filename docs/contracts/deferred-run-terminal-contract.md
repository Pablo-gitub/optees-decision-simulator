# Deferred Run Terminal Contract

## Status

- Work unit: `DS-02D2C1`.
- State: design reviewed; implementation and registered JSON Schema pending.
- Authority: [deferred settlement contract](deferred-settlement-contract.md).
- Companion: [runner orchestration plan](../roadmaps/deferred-runner-orchestration.md).
- Version proposed for implementation: `1.0.0`.

## Purpose

A `DeferredPolicyRoundRecord` can describe settlement of `pending_before`
and admission of `pending_after`, but cannot attach a second settlement
outcome to the newly admitted order. Cancellation may also occur between
declared rounds. The simulator therefore needs an additive immutable terminal
event without rewriting a committed round or inventing an extra calendar round.

Every deferred run ends with exactly one `DeferredRunTerminalRecord`, including
clean completion. Synchronous v1 runs retain their current final-round binding.

## Proposed records

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
    terminal_status: str
    reason_code: str
    reason_message: str
    simulation_frontier_time: str | None
    execution_timestamp: str
    parent_round_hash: str | None
    policy_terminal_records: tuple[PolicyTerminalRecord, ...]
    terminal_state_merkle_hash: str
    schema_version: str = "1.0.0"
```

The implementation must add a Draft 2020-12 schema, inventory entry, strict
codec and invalid examples. This document is not itself a registered schema.

## Identity, time and links

- `terminal_record_id` is `term_` plus the full SHA-256 of canonical identity
  fields `run_id`, `terminal_status` and `parent_round_hash`. An exact retry
  reproduces the ID; different terminal content under that ID fails closed.
- `terminal_status` is `COMPLETED` or `CANCELLED`.
- `reason_code` is:
  - `CLEAN_COMPLETION` only for completed runs with no pending orders;
  - `UNSETTLED_EPISODE_TERMINATION` for completed runs with at least one pending;
  - `EPISODE_CANCELLED` only for cancelled runs.
- `simulation_frontier_time` is the latest committed/staged round cutoff.
  It is null only for a genesis cancellation with no committed round.
  It is not the wall-clock time at which cancellation was requested.
- `execution_timestamp` and the terminal `EpisodeRun.ended_at` use the same
  value from the injected `ClockPort`.
- `parent_round_hash` is the latest round hash. During final-round atomic
  publication it is the hash of the round staged in that same commit. It is null
  only at genesis.
- `EpisodeRun.final_state_hash` is the terminal record hash.

For a terminal rejection, the existing `SettlementOutcome.round_id` remains
the latest causal round ID: the staged final round on completion, or the latest
committed round on cancellation. It does not identify the terminal event.
The terminal record provides the actual event identity and wall timestamp.
A pending cancellation cannot occur at genesis because no proposal has run.

## Policy entry invariants

- Entries are sorted strictly by `policy_id`, contain every policy exactly
  once, and match the episode/run ownership.
- `account_state_hash` resolves within the same run and policy.
- With no active pending, both pending/outcome hashes are null.
- With active pending, both hashes are non-null. The pending hash resolves to
  the latest `pending_after`; the outcome resolves to exactly one REJECTED
  `SettlementOutcome` for that pending and policy.
- Completed terminal outcomes use `UNSETTLED_EPISODE_TERMINATION`; cancelled
  outcomes use `EPISODE_CANCELLED`. They apply no transition and no fee debit.
- The account hash remains unchanged by terminal rejection. No new account
  state is fabricated merely to terminate an order.

## Hashing

Policy leaves are canonical record hashes in declared lexicographic order:

```python
leaves = [compute_record_hash(entry.to_dict()) for entry in policy_entries]
terminal_state_merkle_hash = compute_state_merkle_hash(parent_round_hash, leaves)
```

The terminal record hash covers its Merkle root and all other serialized fields.
Domain validation recomputes the root and enforces all cross-field constraints;
JSON Schema supplies structural checks but cannot replace referenced-record
validation.

## Atomic publication

Final-round completion is one transaction:

```text
final DeferredRoundRecord
+ round proposals/outcomes/transitions/accounts
+ terminal settlement outcomes
+ DeferredRunTerminalRecord
+ final metrics
+ COMPLETED EpisodeRun bound to terminal hash
```

All items are validated before any map or index changes. A crash or validation
failure exposes none of them. The final round must never be committed first and
“cleaned up” with a later terminal commit.

Cancellation between rounds or at genesis uses a separate `TerminalCommit`
because there is no round to publish. It atomically publishes terminal outcomes,
the terminal record, final metrics if defined, and the CANCELLED run.
It rejects a race if the expected parent/run state changed.

## Lifecycle cases

| Case | Publication | Result |
| --- | --- | --- |
| Clean final round | final `RoundCommit` | terminal record, no terminal outcome |
| Final round admits pending | final `RoundCommit` | pending and terminal rejection visible together |
| Old pending settles then new pending admitted | final `RoundCommit` | old settlement plus distinct terminal rejection |
| Old pending still waiting | final `RoundCommit` | terminal rejection of carried pending |
| Cancellation between rounds | `TerminalCommit` | optional pending rejection and CANCELLED run |
| Genesis cancellation | `TerminalCommit` | null frontier/parent, no pending outcome |
| Exact repeated termination | same commit payload | idempotent no-op |
| Changed repeated termination | same identity, changed payload | immutable collision |
| Cancellation after completion | none | invalid lifecycle transition |

Independent implementation tests must cover each case, cross-policy isolation,
reference tampering, atomic fault injection and a stale-parent race.
