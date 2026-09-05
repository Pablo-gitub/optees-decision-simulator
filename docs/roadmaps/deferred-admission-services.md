# Deferred Admission Services

## Work unit

- ID: `DS-02D2B1`, first coherent service block within `DS-02D2B`.
- Status: implementation and independent review complete after retry corrections.
- Owner: Gemini (backend). Independent review: Codex.
- Prerequisite: reviewed `DS-D3A`, including commit `e9f425e`.
- Parent: [market plan](market-dataset-and-baseline-evidence.md).
- Contract: [deferred settlement](../contracts/deferred-settlement-contract.md).
- Stop after admission tests and documentation. `DS-D3B` is NOT complete until
  the subsequent settlement service block is independently reviewed.

## Read before editing

Read `AGENTS.md`, `docs/ARCHITECTURE.md`, `docs/PRODUCT_SPEC.md`,
`docs/contracts/core-contracts.md`, `docs/contracts/threat-model.md`,
`docs/OPTEES_INTEGRATION.md`, `docs/BENCHMARK_PROTOCOL.md`, `docs/ROADMAP.md`,
the parent plan and deferred contract. Inspect these real implementations:

- `domain/models.py`: episode rules, pinned policy references, proposed decision,
  requested action, account, pending record, target-bar rule and decision outcome;
- `domain/time.py`, `domain/canonical.py`, `domain/lifecycle.py`;
- `application/services/execution.py`: existing action and rejection conventions;
- deferred-record tests, schema round-trip tests, authoritative schemas/examples;
- the latest review diff and `tools/validate_contracts.py`.

Write a short preflight summary of reused primitives and boundaries. Do not
create another decimal parser, hash implementation, enum or UTC parser.

## Scope and files

Implement a pure, application-owned admission service and immutable internal
result/context DTOs, preferably together in
`apps/backend/src/simulator/application/services/deferred_admission.py`.
Tests belong in `apps/backend/tests/unit/application/test_deferred_admission.py`.
Small focused contract tests are permitted. Update this plan, the parent,
general roadmap and relevant architecture/contract references at completion.

Do not modify existing execution, runner, replay, persistence, pricing,
normalization, policy implementations, public schemas, domain records or tools.
Do not add a queue, database, network, CLI/API, dependency, UI or Optees call.
If a frozen record cannot represent the result, stop with the exact mismatch;
do not repair it by inventing a public record or overloading an existing status.

## Input boundary

Use typed existing domain records and explicit caller-provided context:
episode definition, current account, proposal, authoritative round ID and cutoff,
resource-to-series mapping, and optional current pending record for that policy.
No clock, observations or price dependency is needed or permitted.

The mapping is configuration, not inferred from symbols or future data; copy it
into immutable state if retained. Reference-resource membership comes from the
episode. Tradable resources are mapping keys excluding the reference resource.
Do not hardcode market symbols in application code.

Reject invalid caller context with explicit ValueError/TypeError before work:
malformed domain objects/IDs, invalid UTC cutoff, account timestamp later than
cutoff, pending state belonging to another policy, or malformed mapping. A
foreign pending supplied as this policy's state is a caller error, not a new
proposal's rejection. Do not silently discard it. Use existing strict parsers.

Structurally representable but inadmissible proposals produce explicit rejection
reasons, not exceptions or a fabricated success. Compare timestamps as instants;
use the authoritative cutoff spelling for newly generated timestamps.

## Frozen admission semantics

1. Check proposal policy equals account policy and appears in the episode's
   pinned references; its policy-version ID must equal that pinned ID.
2. Require proposal round ID equals the authoritative round ID; cutoff and
   generated_at both equal the authoritative cutoff as UTC instants. These
   checks must not be reduced to comparing the proposal with itself.
3. Reject nonempty `desired_allocations`: this block accepts explicit actions,
   not target-weight planning. Never silently ignore a second instruction channel.
4. First profile: exactly one explicit action per proposal. Reject empty or
   multi-action proposals; do not pick the first or split a basket into orders.
   Also enforce the episode's max_transition_count_per_round when present,
   counting the supplied actions as the existing execution service does.
5. Supported actions: `ALLOCATE` with strictly positive finite Decimal quantity;
   `TRANSFER` with nonzero finite signed Decimal quantity; `HOLD` with zero
   finite Decimal quantity. Reject `ADJUST` explicitly: a domain enum member is
   not evidence that its execution semantics are implemented. Zero-size trades
   are invalid, not queued no-ops. Reject booleans, floats, NaN and infinities.
6. For trades require a configured tradable resource. Direct trades in the
   reference resource are invalid. HOLD may name the reference or a configured
   resource. Do not infer missing series. Reject unsupported parameters;
   the only permitted parameter is `source_policy_id`, which must equal the
   account policy if present (otherwise cross-policy rejection).
7. Do not check cash, asset availability, shorting, borrowing, fees or price-based
   allocation limits here. Even an unaffordable buy or oversized sale may be
   structurally admitted; settlement must later reject financial infeasibility.
8. A valid HOLD returns an accepted v1 `DecisionOutcome`, no applied transition,
   and no newly created pending record. Preserve any already active pending.
   Invalid HOLDs are rejected; HOLD is not an escape from identity checks.
9. With an active pending, a different valid trade is rejected with
   `POLICY_HAS_PENDING_SETTLEMENT`; return the original pending unchanged.
10. Without a pending, an admissible trade creates one `PendingTransitionRecord`:
    links come from validated context, predecessor hash is current_account's
    actual hash, requested action is preserved, and target rule is
    `FIRST_OPEN_GE_CUTOFF` with the configured series. Leave expected_open_time
    absent: choosing a bar or computing a daily schedule belongs to settlement.
    Store `proposal_hash` in admission_evidence using the existing canonical
    proposal hash. Do not add a v1 ACCEPTED outcome for a merely pending trade.

Use the established rejection codes where applicable:
`CROSS_POLICY_ACCOUNT_CONTAMINATION`, `UNSUPPORTED_RESOURCE`,
`INVALID_ACTION_SYNTAX`, `TRANSITION_LIMIT_EXCEEDED`,
`POLICY_HAS_PENDING_SETTLEMENT`. Use `POLICY_VERSION_MISMATCH`,
`INVALID_DECISION_CONTEXT`, `UNSUPPORTED_DESIRED_ALLOCATIONS` and
`DECISION_ID_CONFLICT` for the corresponding distinct conditions. Document these
application-owned codes; do not add a second domain lifecycle enum. Sort multiple
reasons deterministically by code, field and message, and never include prices.

## Results, identity and repeated requests

An internal immutable result carries the current pending (possibly unchanged),
an optional immediate `DecisionOutcome`, and an explicit indication of whether
a pending was created/reused. Enforce exclusive outcomes: a new/reused admission
has no immediate outcome; HOLD/rejection has exactly one immediate outcome and
never creates a new pending. Returning an existing pending with HOLD/rejection
does not mean that the rejected proposal owns it.

Create IDs deterministically with valid prefixes and the full existing SHA-256
digest of a structured canonical identity input (no random IDs, clock or lossy
string concatenation). Include episode, authoritative round, policy and decision
identity; include proposal content for the immediate outcome identity. Keep
pending identity stable for a decision identity so content drift is detected,
not converted into a second order. Document the exact identity input in tests.

After context/action validation, a retry of the active pending's decision ID
must compare the complete stored proposal hash and its policy/version/round/time,
requested action, target series and predecessor hash with this request/context.
Exact match returns the same pending object and no new outcome; content or
linkage drift returns `DECISION_ID_CONFLICT` without replacing the pending.
Never use ID equality alone. Missing stored hash is not proof of a safe retry.

This is pure determinism and active-pending retry handling, NOT durable
exactly-once execution: the caller supplies authoritative state. Completed
decision deduplication, persistence and atomic state publication belong to later
integration. Do not claim this service prevents duplicate settlement.

No branch mutates, replaces, reserves or revalues the account. Do not call
ExecutionService to simulate admission and then discard its transition.

## Required evidence

Tests must call the production service, not a local reproduction of its logic.
Use explicit expected values and actual authoritative schemas for emitted records.

- [x] Positive buy and signed sell produce expected immutable pending links,
  account hash, series rule, evidence and deterministic IDs.
- [x] Unaffordable buy and sale exceeding holdings are admitted without pricing.
- [x] HOLD without/with active pending has an accepted outcome, no transition,
  no new pending; original pending is preserved by identity when present.
- [x] Policy contamination (including parameters), wrong pinned version, round,
  cutoff and generated_at are rejected; equivalent UTC spellings are tested.
- [x] Empty/multiple actions, desired allocations, unsupported ADJUST/parameters,
  zero trades, nonzero HOLD, unknown resource and direct cash trade are rejected.
- [x] Boolean/float/non-finite and wrong-sign ALLOCATE inputs cannot escape as
  valid pending records; signed TRANSFER remains accepted.
- [x] Transition count limit 0/1 and unset is tested, including HOLD.
- [x] New decision while pending is rejected; identical retry reuses the pending;
  same-ID changed quantity/resource/version/target/predecessor cannot be admitted.
- [x] Invalid caller context fails explicitly, including foreign-policy pending.
- [x] Every path preserves input account bytes/hash/balances/costs; nested
  configuration mutation cannot change an already emitted record or result.
- [x] Output schema validation, canonical hash determinism and repeated execution
  tests use the repository helpers. Unknown schema vocabulary must not be ignored.
- [x] Full backend, architecture, contracts, lint and formatting gates pass.

Commands (use the available environment; do not install dependencies blindly):

```bash
PYTHONPATH=apps/backend/src python -m pytest apps/backend/tests/unit/application/test_deferred_admission.py -q
PYTHONPATH=apps/backend/src python -m pytest apps/backend/tests -q
python tools/validate_contracts.py
ruff check apps/backend tools/validate_contracts.py
ruff format --check apps/backend tools/validate_contracts.py
git diff --check
```

## Handoff and completion

Baseline at planning: 225 backend tests passed; contract and Ruff gates passed.
Do not use a test count as the acceptance criterion. Report exact commands,
results, changed files, schema evidence, and any skipped/blocked checks.

- [x] Planning: admission semantics, scope, exclusions and evidence frozen.
- [x] Implementation and focused regressions complete.
- [x] Independent review accepted after retry corrections.

Review correction evidence: 270 backend tests pass. Same-ID HOLD is rejected
as content drift, while a new-ID HOLD still preserves the active pending.
Retry checks recompute the pending identity from the authoritative episode,
round, policy and decision and require the B1 target rule's absent expected
open time. Changed episode, pending ID or expected open time cannot be reused.
Regression tests validate rejection schemas and unchanged account hashes.
No settlement, durable deduplication or runner behavior is added.

Before a local atomic commit, update roadmap checkboxes honestly: implementation
may become complete, independent review remains pending. No push or AI commit
attribution. Stop after handoff; `DS-02D2B2` settlement/accounting needs its own
detail after this review, and `DS-02D2C` runner/replay remains blocked.
