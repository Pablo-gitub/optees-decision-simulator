# Deferred Round Record Bridge

- ID: `DS-02D2C0`; status: ready for implementation, not implemented.
- Owner: Gemini; independent review afterwards.
- Parent: [market plan](market-dataset-and-baseline-evidence.md).
- Prerequisite: reviewed B1/B2, Gate DS-D3B, commit d365cd8.
- This is the record prerequisite to D2C runner/replay, not a completed episode.

## Why this bridge precedes the runner

PolicyRoundRecord v1 requires decision_outcome_hash, while admission may produce
only a pending record. A deferred round may settle an older decision AND admit
a new decision; its transition cannot be falsely attached to the new proposal.
RoundCommit and replay are v1-only today. Do not repair those consumers by
fabricating ACCEPTED outcomes, overloading transition_hash, or hiding records in
metadata. Freeze and implement the lossless round record first.

## Read before editing

Read AGENTS.md, PRODUCT_SPEC, ARCHITECTURE, core-contracts, threat-model,
OPTEES_INTEGRATION, BENCHMARK_PROTOCOL, ROADMAP, parent plan and both deferred
service plans/contracts. Inspect domain PolicyRoundRecord/RoundRecord,
PendingTransitionRecord/SettlementOutcome/DeferredTransitionRecord, canonical
hash helpers; RoundCommit/PersistencePort; runner, in-memory store and replay;
round.v1 schema, schema inventory and existing schema round-trip tests.
Inspect the real B1/B2 call signatures including expected_open_time and the
optional admission_account. Do not design from logs or this description alone.

## Allowed implementation

Add a dedicated immutable DeferredPolicyRoundRecord and DeferredRoundRecord
in domain, preferably a separate domain/deferred_round.py module. Add
docs/contracts/schemas/round.v2.json and inventory entry, canonical valid example
and unit/contract tests. Update core/deferred contract documentation and roadmaps.
Use strict from_dict/to_dict and compute_hash, existing UTC/Decimal/hash/immutable
JSON primitives, exact field checking and explicit schema_version 2.0.0.

Keep round.v1, v1 classes, fixtures and hashes unchanged. Do not yet modify
RoundCommit, PersistencePort, in-memory store, runner, replay, evaluator, pricing,
B1/B2, API or UI. No new persistence, clock, calendar parser or dependencies.

## Frozen record shape

Keep all top-level v1 round fields and $type=round, with schema_version=2.0.0;
replace policy_round_records with the following dedicated v2 entries. Every
listed field is required; nullable means explicit null, not omission.

- policy_id: existing policy identity.
- account_state_before_hash, account_state_after_hash: SHA-256 record hashes.
- pending_before, pending_after: nullable immutable state reference objects,
  each with pending_transition_hash, admission_account_hash, expected_open_time,
  settlement_deadline. Hashes use the existing sha256: convention; timestamps
  are strict UTC. expected_open_time <= settlement_deadline.
- settlement_outcome_hash: nullable hash of settlement of pending_before.
- deferred_transition_hash: nullable hash, present only for successful settlement.
- proposed_decision_hash: nullable hash of the NEW proposal phase.
- decision_outcome_hash: nullable immediate rejection/HOLD outcome for that proposal.
- optees_call_receipt_hashes: tuple of hashes (empty in current scope).

This shape records the frozen caller schedule used by B2 without changing B1's
pending schema. No bar opening may be inferred from observed data or the spacing
of decision rounds. Schedule production belongs to later integration; these
records retain its exact output and deadline for replay. They contain references,
not duplicate account or pending records.

The schema enforces types, required fields, versions and expressible presence
conditions. Constructors enforce cross-field equality, ordering and hashing
that JSON Schema cannot express; tests must name which boundary rejects a case.
Local invariants:

1. Without pending_before, no settlement outcome or deferred transition.
2. A deferred transition requires a settlement outcome. Outcome status and its
   actual transition link must be checked when referenced records are resolved;
   a hash alone cannot prove status. Do not claim the constructor can do so.
3. Without a settlement outcome, pending_before must be carried unchanged into
   pending_after if present (including schedule and admission anchor).
4. A proposal has exactly one result: an immediate outcome OR a newly admitted
   pending_after. Immediate outcomes require a proposal. New admission requires
   a proposal and cannot replace an unsettled pending_before.
5. After settling/rejecting pending_before, it cannot remain pending_after.
   A different pending_after requires a new proposal with no immediate outcome.
6. No-proposal rounds are permitted for waiting/finalization: no immediate outcome
   or new pending may appear. A settlement and a later proposal can coexist.
7. Reject duplicate policy IDs, malformed hashes, unknown fields, wrong versions,
   invalid UTC and mutable aliases. Sequence order is explicit, not silently sorted
   or repaired by constructors; serialized lists become immutable tuples internally.

Reference resolution tests must additionally prove actual policy/decision links,
pending hashes, admission account hashes, B2 outcome/transition links and final
account hashes using real service outputs. Distinguish these checks from purely
local schema invariants. No production resolver or persistence is required yet.

## Hash sequencing

Add a pure helper that computes the v2 state Merkle hash using the existing
compute_state_merkle_hash primitive. For policies in lexicographic policy_id order,
append compute_record_hash(policy_entry.to_dict()) to the hash list, with the
previous ROUND record hash as parent. This covers nullable fields, frozen schedule,
all phase references, before/after account hashes and receipt order. Do not reuse
v1's proposal/outcome-only item list and omit pending state. No self-reference:
state_merkle_hash is not inside policy entries. Round compute_hash includes it.
Require supplied state_merkle_hash to agree with that helper, rather than accepting
an arbitrary plausible hash. Different serialized policy ordering must either be
rejected as noncanonical or normalized explicitly before construction by the caller;
choose rejection here (constructor requires lexicographic order).

## Required evidence

- [ ] Strict schema/codec round-trip and deterministic hashes for new admission,
  waiting with HOLD, waiting without proposal, settlement without new proposal,
  settlement followed by new admission, immediate rejection and terminal rejection.
- [ ] Use real B1/B2 output in at least one multi-round synthetic record chain.
  Resolve hashes and assert old settlement and new proposal remain distinct.
- [ ] Negative tests for impossible combinations above, unknown fields/versions,
  duplicate policies, noncanonical order, mutable nested state and malformed time.
- [ ] A changed pending, target opening, deadline, anchor or phase hash changes the
  Merkle hash; wrong supplied Merkle hash is rejected. No local mock hash algorithm.
- [ ] v1 schema/fixture hashes unchanged; all backend tests remain green.
- [ ] Contract validation, architecture, Ruff/format and diff checks pass.

Before code, summarize the field mapping and reuse points. If a required valid
lifecycle cannot be represented without adding another field, STOP and report
the exact counterexample. Do not quietly weaken an invariant or label a lost
record an accepted limitation.

## Completion and next boundary

- [x] Record shape, compatibility, hash sequencing and exclusions planned.
- [ ] Implement record bridge and required evidence.
- [ ] Independent review accepted.

Baseline: 314 backend tests. Run PYTHONPATH=apps/backend/src python -m pytest
apps/backend/tests -q; python tools/validate_contracts.py; Ruff check and format
checks on apps/backend and tools/validate_contracts.py; git diff --check.
The custom validator is a fail-closed subset: use supported schema vocabulary;
do not silently bypass unsupported keywords or weaken required negative tests.

Update roadmaps honestly before a local atomic commit, no AI attribution or push.
Then stop. Next block to DETAIL is C1 atomic persistence and runner orchestration;
C2 replay and end-to-end evidence follows. DS-D3 is not satisfied by this bridge.
