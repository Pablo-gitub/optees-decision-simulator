# Deferred Settlement Services

## Work unit

- ID: `DS-02D2B2`, second and final service block within `DS-02D2B`.
- Status: implementation complete; independent review pending.
- Owner (this work unit only): Claude (backend), by explicit temporary user
  reassignment. The standing UI-only ownership boundary in `CLAUDE.md` is not
  changed by this exception. Independent review: pending, not performed by the
  implementing session.
- Prerequisite: reviewed `DS-02D2B1`, including commit `40308b4`.
- Parent: [market plan](market-dataset-and-baseline-evidence.md).
- Contract: [deferred settlement](../contracts/deferred-settlement-contract.md).
- Stop after settlement tests and documentation. `DS-D3B` is NOT satisfied until
  this block is independently reviewed, and `DS-02D2C` (runner/replay) remains
  blocked regardless of this unit's outcome.

## Read before editing

Read `AGENTS.md`, `docs/ARCHITECTURE.md`, `docs/PRODUCT_SPEC.md`,
`docs/contracts/core-contracts.md`, `docs/contracts/threat-model.md`,
`docs/OPTEES_INTEGRATION.md`, `docs/BENCHMARK_PROTOCOL.md`, `docs/ROADMAP.md`,
the parent plan, the deferred contract and the B1 plan. Inspect these real
implementations:

- `domain/models.py`: `PendingTransitionRecord`, `TargetBarRule`,
  `SettlementOutcome`, `DeferredTransitionRecord`, `VirtualAccountState`,
  `ResourceDelta`, `CostItem`, and their exact constructor invariants;
- `domain/time.py`, `domain/canonical.py`, `domain/lifecycle.py`;
- `application/services/deferred_admission.py` (B1): identity, DTO exclusivity
  and rejection-sorting conventions this unit must mirror;
- `application/services/execution.py`: the only existing accounting authority
  (fee/notional formulas, feasibility checks, balance/valuation composition,
  account-state minting) for the synchronous lifecycle;
- `application/ports/pricing.py` (`PriceEvidence`, `PriceResolutionResult`) and
  `infrastructure/adapters/market_pricing.py`: reuse the `PriceEvidence` value
  object for injected valuation marks; **do not** reuse
  `MarketKlinePricingAdapter`'s bar-selection logic (see "Why not
  `MarketKlinePricingAdapter`" below);
- `docs/contracts/schemas/pending_transition.v1.json`,
  `settlement_outcome.v1.json`, `transition.v2.json` and their canonical
  examples; `tools/validate_contracts.py`'s `validate_data`;
- `apps/backend/tests/unit/application/test_deferred_admission.py` and
  `apps/backend/tests/unit/domain/test_deferred_settlement_contract.py` (the
  nine frozen decision probes DP-01..DP-09 this unit must prove with real code).

Write a short preflight summary of reused primitives and boundaries before
writing code. Do not create another Decimal parser, hash implementation, enum,
UTC parser, or duration/calendar parser.

### Why not `MarketKlinePricingAdapter`

That adapter selects the execution bar by `event_time > cutoff` where
`event_time` is the upstream bar's **close** time — the exact conflation the
deferred-settlement contract rejects in its comparison table (row 7,
"Conflating Close Time With Open Time"). It was correct for the superseded
synchronous kernel and remains unmodified for that lifecycle. This unit
selects the target bar using the pending's own `target_bar_rule.series_id` and
the retained `payload["open_time"]` field (normalizer `1.1.0`), never
`event_time`, and is not implemented as a `PricingPort` adapter because its
job — evaluating one specific already-identified pending order against one
specific already-identified series — is narrower than `PricingPort`'s
whole-resource-universe cutoff/effective-time contract and does not fit that
interface without distorting it.

## Scope and files

Implement a pure, application-owned settlement service and immutable result
DTO, in `apps/backend/src/simulator/application/services/deferred_settlement.py`.
Tests belong in `apps/backend/tests/unit/application/test_deferred_settlement.py`.
Small focused contract tests are permitted. Update this plan, the parent,
general roadmap and relevant architecture/contract references at completion.

Do not modify `deferred_admission.py`, `execution.py`, runner, replay,
persistence, `PricingPort`, `MarketKlinePricingAdapter`, market normalizer,
policy implementations, public schemas, domain records or `tools/`. Do not add
a queue, database, network, CLI/API, dependency, UI or Optees call. Do not
touch round hashing, `RoundRecord`, or `PolicyRoundRecord` — those are
`DS-02D2C`. If a frozen record cannot represent a result, stop with the exact
mismatch; do not repair it by inventing a public record, overloading an
existing status, or fabricating a synthetic bar.

## Input boundary

Two entry points, both pure and stateless, both driven entirely by explicit
caller-supplied context. No clock, no hidden dataset scanning, no calendar
inference beyond what is described below.

### `attempt_settlement(...)`

Caller supplies: episode definition; the current account (must be exactly the
account captured at admission time — see predecessor-hash check below); the
`PendingTransitionRecord` to evaluate; the authoritative settlement round id,
settlement round index, and settlement time (`t_settle`, the round's cutoff);
the full observation set the caller has ingested so far
(`tuple[ObservationRecord, ...]`); and a mapping of injected valuation marks
(`Mapping[str, Decimal | PriceEvidence]`) for every resource the resulting
account will hold after the trade, in the same shape `ExecutionService`
already consumes.

### `terminate_unsettled(...)`

Caller supplies the same episode/account/pending/round/time context plus one
`reason_code` from the closed set `{MISSING_EXECUTION_BAR,
UNSETTLED_EPISODE_TERMINATION, EPISODE_CANCELLED}` and an optional message. No
observation set or valuation marks are needed. An unrecognized `reason_code`
is a caller/programming error (`ValueError`), not a business rejection — this
service does not decide *when* a settlement window has expired, an episode is
cancelled, or an episode has terminated; a future runner (`DS-02D2C`) decides
that and calls this entry point to record the terminal outcome correctly.

### Caller-context validation (both entry points)

Reject invalid caller context with explicit `ValueError`/`TypeError` before any
evaluation, using the existing strict parsers:

- `episode_def`, `current_account`, `pending` must be instances of
  `EpisodeDefinition`, `VirtualAccountState`, `PendingTransitionRecord`;
- `pending.policy_id != current_account.policy_id` is a foreign-pending caller
  error, exactly as in B1 — never treated as a new decision's rejection;
- **`current_account.compute_hash() != pending.predecessor_account_hash`** is a
  caller error: the account handed to settlement must be bit-identical to the
  one hashed at admission (the single-pending invariant guarantees zero
  mutation in between). This is the explicit hash-at-admission-vs-
  hash-immediately-before-settlement check the contract requires;
- `settlement_round_id` must match the existing round-id pattern;
- `settlement_time` must be strict UTC (`parse_utc_timestamp`) and its instant
  must be `>= pending.knowledge_cutoff`'s instant (settlement cannot precede
  the round in which the order was admitted);
- `pending.requested_action.action_type` must be `ALLOCATE` or `TRANSFER`. Any
  other value is structurally impossible for a real `PendingTransitionRecord`
  produced by `DeferredAdmissionService` (HOLD/ADJUST never create a pending)
  and is treated as a caller/fixture error (`TypeError`), not a rejection;
- (`attempt_settlement` only) `all_observations` must be a tuple of
  `ObservationRecord` instances; `valuation_marks` must be a `Mapping` whose
  values are `Decimal` or `PriceEvidence` (same dual-type convention
  `ExecutionService` already uses); `settlement_round_index` must be a
  non-negative `int`, not `bool`.

## Frozen settlement semantics

### 1. Target-bar selection — deterministic, non-skipping

Selection uses only `pending.target_bar_rule.series_id` and the retained
`payload["open_time"]` field, never `event_time`. It must never substitute a
later, already-eligible bar for an earlier one that has not yet become
knowledge-eligible, and must never fabricate or forward-fill a bar.

1. Filter `all_observations` to `series_id == target_bar_rule.series_id`.
2. Parse each survivor's `payload.get("open_time")` as strict UTC; drop any
   observation where this is missing or unparsable (a legacy/malformed bar
   cannot participate in `FIRST_OPEN_GE_CUTOFF` selection).
3. Keep only observations with `open_time_dt >= pending.knowledge_cutoff`'s
   instant, and drop any observation with `open_time_dt >=
   parse(obs.knowledge_time)` (a causally-inverted fixture: a bar cannot be
   known before or at the instant it opens).
4. Group the remaining survivors by exact `open_time_dt` — this is the set of
   bar slots at or after cutoff **that the dataset snapshot has ingested at
   all**, independent of each one's own knowledge-eligibility.
5. If this set is empty: **still pending** (no bar for this cutoff has been
   ingested by the caller's dataset snapshot at all — this is not a rejection).
6. Otherwise select the group with the smallest `open_time_dt`. This is *the*
   first bar per the dataset's own chronology. **Do not look at any other
   group even if a later one is already knowledge-eligible.**
7. Within that one selected group, keep only revisions with
   `knowledge_time <= settlement_time`.
   - If none are eligible yet: **still pending** — the correct first bar is
     known to exist but has not yet been ingested/published to the simulator.
     Do not fall through to a later bar.
   - If one or more are eligible: pick the highest `revision` (tie-break by
     `observation_id`) — this is Probe DP-03's pre-settlement revision rule.

One required regression case follows directly from step 6/7's "do not skip"
guarantee: an earlier bar for the series is *present* in the dataset but not
yet knowledge-eligible while a *later* bar for the same series already is
eligible — must return still-pending, not settle against the later bar.

**Accepted limitation, discovered during implementation and deliberately not
closed here:** if the true first bar is *entirely absent* from
`all_observations` (never ingested at all — e.g. an exchange halt) while a
later bar for the same series is already present and eligible, this pure
algorithm has no local signal to distinguish that from "the calendar's first
slot for this series always was the later bar" and will settle against the
later one. Closing this requires calendar knowledge (which round cutoffs were
skipped entirely) that this unit does not have and should not invent:
`CalendarSpec.interval_duration`/`evaluation_delay` are opaque,
not-yet-formally-parsed strings nowhere else in the codebase, and parsing them
here would be exactly the kind of new, unfrozen parser `AGENTS.md` warns
against. The future runner (`DS-02D2C`) already holds the explicit
`CalendarSpec.round_cutoffs` sequence and therefore can detect a fully-skipped
round without parsing anything, then call `terminate_unsettled(...,
"MISSING_EXECUTION_BAR")`. This unit's `attempt_settlement` only guarantees
non-skipping among bars the dataset snapshot has actually ingested; genuine
upstream gaps remain `DS-02D2C`'s responsibility. This is reported here
explicitly rather than silently narrowed.

### 2. Execution price and fee computation

Extract `payload["open"]` from the selected observation. If missing,
non-numeric, non-finite, or not strictly positive: terminal `REJECTED` with
`INVALID_EXECUTION_PRICE`.

> **Discovered domain-model constraint:** `SettlementOutcome.__post_init__`
> requires execution evidence (`observation_id`, `selected_revision`,
> `execution_fill_time`, `observation_knowledge_time`, `execution_price`) to be
> either completely absent or completely present-and-valid; it cannot hold an
> invalid `execution_price`. Therefore `INVALID_EXECUTION_PRICE` is recorded
> with an **empty** `settlement_evidence` — this is a property of the frozen
> `settlement_outcome.v1` record, not an implementation choice, and must be
> documented as such in the test that proves it.

Otherwise compute notional and fees with the exact formulas
`ExecutionService` already uses for `ALLOCATE`/`TRANSFER` (quantity sign rules
identical to B1's admitted action), but with **explicit** rounding on every
`Decimal.quantize` call:

```python
from decimal import ROUND_HALF_EVEN
...
notional = (abs(qty) * execution_price).quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
```

`ExecutionService`'s existing `.quantize(Decimal("0.01"))` calls rely on the
ambient (thread-global) decimal context's default rounding mode
(`ROUND_HALF_EVEN`) implicitly. This unit must not reproduce that
environment-dependence in new code: every `quantize` call in
`deferred_settlement.py` passes `rounding=ROUND_HALF_EVEN` explicitly, which
reproduces byte-identical results to `ExecutionService` under the untouched
default context while removing the dependency on ambient context state.
`execution.py` itself is out of scope and is not touched.

### 3. Valuation marks and feasibility

Seed a local marks map with `{reference_resource_id: Decimal("1.00")}` and
overlay caller-supplied `valuation_marks` (unwrapping `PriceEvidence.price`
where present — the same idiom `ExecutionService` uses). The required-marks
set is every non-reference resource currently held in `current_account`, plus
the pending action's own `resource_id`. Any resource in that set missing a
valid (positive, finite) mark produces `MISSING_VALUATION_MARK` — this mirrors
`ExecutionService`'s two existing mark checks (pre-existing balances, and the
resource being traded), collapsed into one pass since settlement only ever
evaluates a single action.

Feasibility, evaluated independently (both may fire together, exactly as
`ExecutionService` does it):

- unless `episode_def.rules.allow_borrowing`: resulting reference-resource
  balance must be `>= 0`, else `INSUFFICIENT_FUNDS_AT_SETTLEMENT`;
- unless `episode_def.rules.allow_short_positions`: resulting traded-resource
  balance must be `>= 0`, else `SHORT_POSITIONS_FORBIDDEN`.

Any rejection reason (mark or feasibility) at this stage produces terminal
`REJECTED` with **full** execution evidence (a valid priced bar was found) plus
`total_fee_deducted` (always computable once price is valid) and, for
`INSUFFICIENT_FUNDS_AT_SETTLEMENT` specifically, `cash_available` (pre-trade
reference balance) and `cash_required` (magnitude of the attempted debit). The
account is returned **unchanged** (the same object, not a re-minted copy) —
zero mutation, zero fee deduction, full balance preserved, exactly as the
contract's insufficient-funds example states.

### 4. Successful settlement

Mint the new `VirtualAccountState` using the same balance/cost/valuation
composition `ExecutionService` uses (reference-resource-first deterministic
balance ordering, cumulative `TRANSACTION_FEE` increment, `.quantize(...,
rounding=ROUND_HALF_EVEN)` throughout, fractional asset quantities preserved
without truncation). Build one `DeferredTransitionRecord` with
`economic_fill_time` = the selected bar's `open_time`, `effective_time` =
`settlement_time`, and only non-zero resource deltas (mirrors
`ExecutionService`).

**Record identity.** Because the single-pending invariant guarantees at most
one settlement per policy per round, `(settlement_round_id, policy_id)` is
already a collision-free key — exactly the key `ExecutionService` already uses
for its own `transition_id`/`outcome_id`/`account_state_id`. Reuse that exact
convention rather than inventing a new hash-based scheme (unlike B1's pending
identity, settlement has no retry/content-drift concept to protect against —
it is a one-shot terminal decision):

- `settlement_outcome_id = f"set-out_{settlement_round_id}_{pending.policy_id}"`
- `transition_id = f"trn_{settlement_round_id}_{pending.policy_id}"`
- `account_state_id = f"acc-state_{settlement_round_id}_{pending.policy_id}"`

Build the `SettlementOutcome` (`status=SETTLED`, `applied_transition_id=
transition_id`, full execution evidence plus `total_fee_deducted`,
`rejection_reasons=()`), verify (in tests) that
`deferred_transition.settlement_outcome_id == settlement_outcome.settlement_outcome_id`
and `settlement_outcome.applied_transition_id == deferred_transition.transition_id`
— the bidirectional link `DS-02D2A2` designed, proven end-to-end through real
service output for the first time.

### 5. Exogenous terminal rejection (`terminate_unsettled`)

Builds a `SettlementOutcome` with `status=REJECTED`, the given `reason_code` as
the sole rejection reason, `applied_transition_id=None`, empty
`settlement_evidence`, and returns the account **unchanged**. This is the only
path for `MISSING_EXECUTION_BAR` (the settlement-window timeout is a
scheduling policy the future runner owns — this unit does not compute
`D+2`/expected-knowledge-time deadlines), `UNSETTLED_EPISODE_TERMINATION`, and
`EPISODE_CANCELLED`. `SettlementOutcome`'s own constructor invariant (REJECTED
requires >=1 reason, forbids `applied_transition_id`) is reused as a safety
net, not re-implemented.

### 6. Results and exclusivity

```python
@dataclass(frozen=True)
class DeferredSettlementResult:
    pending_transition: PendingTransitionRecord
    settlement_outcome: SettlementOutcome | None
    deferred_transition: DeferredTransitionRecord | None
    next_account: VirtualAccountState
    is_settled: bool
    is_still_pending: bool
```

Enforce exclusivity in `__post_init__`: `is_settled` and `is_still_pending`
cannot both be `True`; `is_still_pending` implies `settlement_outcome is None`
and `deferred_transition is None`; `is_settled` implies
`settlement_outcome.status == SETTLED` and `deferred_transition is not None`;
neither flag set implies `settlement_outcome.status == REJECTED` and
`deferred_transition is None`. This is the WAITING / SETTLED / REJECTED
trichotomy the contract's closed state machine requires, expressed the same
way B1 expressed admission/reuse/reject exclusivity.

### 7. No durable exactly-once

This is pure determinism for a single evaluation, **not** durable exactly-once
settlement: the caller supplies the authoritative account, pending, dataset
slice and marks for each call. Calling `attempt_settlement` twice with
identical inputs returns identical (idempotent) output; calling it again after
the real system has already recorded a terminal outcome elsewhere is a caller
error this service cannot detect or prevent. Persisted deduplication and
atomic state publication belong to later integration (`DS-03`). Do not claim
this service prevents duplicate settlement.

No branch mutates, replaces, reserves or revalues the input account object.

## Required evidence

Tests must call the production service, not a local reproduction of its
logic, and must reuse `DeferredAdmissionService`-produced pending records as
fixtures where practical (proving the two services compose).

- [x] Full D+2 lifecycle (Probe DP-01): admission-produced pending settles
  against a two-bar observation set; schema-valid `SettlementOutcome` and
  `DeferredTransitionRecord`; exact `economic_fill_time`/`effective_time`/
  `observation_knowledge_time` evidence; resulting account hash/balances/costs.
- [x] Still-pending: target bar not yet knowledge-eligible; zero mutation;
  same `pending_transition` object returned; `is_still_pending` true.
- [x] No-skip regression: earlier bar present-but-ineligible while a later bar
  for the same series is already eligible — must return still-pending, not
  settle against the later bar.
- [x] Accepted-limitation regression: earlier bar entirely absent (never
  ingested) while a later bar is already eligible — documents, with an
  explicit comment referencing this plan's "Accepted limitation" note, that
  the service currently settles against the later bar, and that closing this
  gap requires the round-cutoff-aware runner (`DS-02D2C`), not this unit.
- [x] `event_time` vs `open_time` regression: a bar whose `open_time` is
  before cutoff but `event_time` (close) is after cutoff, and vice versa,
  proving `open_time` — never `event_time` — governs selection.
- [x] Missing bar terminal path (Probe DP-02): `terminate_unsettled(...,
  "MISSING_EXECUTION_BAR")` produces terminal `REJECTED`, zero mutation.
- [x] Revision handling (Probe DP-03): two revisions of the same bar, only the
  knowledge-eligible one usable; highest eligible revision wins.
- [x] Insufficient funds at settlement (Probe DP-04): execution price higher
  than the mark used at admission time triggers
  `INSUFFICIENT_FUNDS_AT_SETTLEMENT`; zero mutation; full cash preserved;
  evidence includes `cash_available`/`cash_required`.
- [x] Short-sale forbidden: oversized `TRANSFER` sale triggers
  `SHORT_POSITIONS_FORBIDDEN`; zero mutation.
- [x] Invalid execution price: non-positive/non-finite/missing `open` field
  triggers `INVALID_EXECUTION_PRICE` with empty `settlement_evidence`
  (documents the domain-model constraint above); zero mutation.
- [x] Missing valuation mark for an untouched existing holding blocks
  settlement of an unrelated trade with `MISSING_VALUATION_MARK`; zero
  mutation.
- [x] Signed `TRANSFER` settles correctly in both credit and debit directions
  with correct-sign resulting balance and cash delta; `ALLOCATE` settles with
  exact hand-computed `ROUND_HALF_EVEN`-quantized Decimal strings.
- [x] `terminate_unsettled` for `UNSETTLED_EPISODE_TERMINATION` (Probe DP-05)
  and `EPISODE_CANCELLED` (Probe DP-06); unrecognized `reason_code` raises
  `ValueError`.
- [x] Invalid caller context fails explicitly before any evaluation: foreign
  pending, mismatched predecessor-account hash, malformed round id, non-UTC or
  causally-early `settlement_time`, and a structurally-impossible
  HOLD/ADJUST pending.
- [x] Every path preserves input account/pending/episode bytes/hash; nested
  `admission_evidence`/observation-payload mutation cannot change an
  already-emitted result (deep immutability, mirrors B1 evidence #10).
- [x] Output schema validation against `settlement_outcome.v1.json` and
  `transition.v2.json` using the repository's `validate_data` helper; forward
  and backward bidirectional-link verification between
  `SettlementOutcome.applied_transition_id` and
  `DeferredTransitionRecord.settlement_outcome_id`; canonical hash determinism
  across repeated calls with identical inputs (Probe DP-08).
- [x] Shared-timestamp ordering (Probe DP-07) and second-order-while-pending
  (Probe DP-09) are already covered by `test_deferred_settlement_contract.py`
  and B1's admission tests respectively; this unit does not re-derive them but
  may cross-reference them in its module docstring.
- [x] Full backend, architecture, contracts, lint and formatting gates pass.

Commands (use the available environment; do not install dependencies blindly):

```bash
PYTHONPATH=apps/backend/src python -m pytest apps/backend/tests/unit/application/test_deferred_settlement.py -q
PYTHONPATH=apps/backend/src python -m pytest apps/backend/tests -q
python tools/validate_contracts.py
ruff check apps/backend tools/validate_contracts.py
ruff format --check apps/backend tools/validate_contracts.py
git diff --check
```

## Handoff and completion

Baseline at planning: 270 backend tests passed (per B1's review-correction
evidence); contract and Ruff gates passed. Do not use a test count as the
acceptance criterion.

Implementation evidence: 298 backend tests pass (270 baseline + 28 new
settlement tests), including the full D+2 lifecycle, non-skipping target-bar
selection with its accepted absent-bar limitation documented and regression
tested, revision resolution, both feasibility rejections, the domain-model-
forced empty-evidence behavior for `INVALID_EXECUTION_PRICE`, missing
valuation marks, signed `TRANSFER` in both directions, all three exogenous
`terminate_unsettled` reasons, and invalid-caller-context rejection. Contract
validation, Ruff lint/format, and `git diff --check` all pass. No admission
service, execution service, runner, replay, persistence, pricing adapter,
public schema, or tool was modified.

- [x] Planning: settlement semantics, scope, exclusions, identity scheme and
  evidence frozen.
- [x] Implementation and focused regressions complete.
- [ ] Independent review.

Before a local atomic commit for implementation, update roadmap checkboxes
honestly: implementation may become complete, independent review remains
pending. No push or AI commit attribution. Stop after handoff;
`DS-02D2C` (runner, round hashing, replay integration) remains blocked until
this unit is independently reviewed and Gate `DS-D3B` is satisfied.
