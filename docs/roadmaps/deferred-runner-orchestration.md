# Deferred Runner Orchestration and Atomic Persistence

## Work unit

- ID: `DS-02D2C1`.
- State: corrected plan independently reviewed; implementation is the next
  authorized work unit.
- Prerequisites: reviewed B1/B2 (`d365cd8`) and C0 (`d2243bb`);
  `DS-D3B` satisfied.
- Contracts: [deferred settlement](../contracts/deferred-settlement-contract.md)
  and [terminal record](../contracts/deferred-run-terminal-contract.md).
- C2 replay and DS-02E evidence remain blocked until C1 is implemented and
  reviewed.

C1 integrates the existing admission, settlement and round-v2 components.
It preserves the synchronous v1 execution path and does not implement replay,
REST, SQLite, UI, live acquisition or Optees policies.

## Implementation surface

Permitted production changes:

- add `application/contracts/deferred_configuration.py` for strict parsing of
  the versioned episode metadata profile;
- add `domain/deferred_terminal.py` and its exports;
- add terminal schema, inventory entry, codec/examples and validation tests;
- extend `application/ports/persistence.py`;
- extend `infrastructure/adapters/in_memory_store.py`;
- add `application/services/account_valuation.py`;
- extend `application/services/runner.py`;
- extend `application/services/evaluator.py`;
- add focused runner, persistence, configuration, valuation and terminal tests;
- update authoritative documentation and roadmap state.

Frozen behavior:

- B1 admission and B2 settlement arithmetic;
- C0 `deferred_round.py` and `round.v2.json`;
- v1 domain records and schemas;
- replay service;
- synchronous runner results and byte behavior.

If implementation proves a frozen component cannot satisfy this plan, stop and
report the exact incompatibility rather than widening C1 silently.

## Deferred configuration

A deferred episode has exactly one strict object at
`EpisodeDefinition.metadata["deferred_settlement"]`:

```json
{
  "schema_version": "1.0.0",
  "settlement_mode": "deferred",
  "calendar_identity": "cal_binance_spot_1d_utc_v1",
  "calendar_sha256": "sha256:<64 lowercase hex>",
  "resource_to_series_map": {"res_btc": "series_btc_usdt_1d"},
  "scheduled_openings": {
    "2026-08-01T00:00:00Z": "2026-08-01T00:00:00Z"
  },
  "scheduled_deadlines": {
    "2026-08-01T00:00:00Z": "2026-08-03T00:00:00Z"
  },
  "deadline_policy": "inclusive"
}
```

Absence selects the existing synchronous path. Presence requires exact fields,
no unknown keys, version `1.0.0`, canonical UTC values, an exact key for every
cutoff at which an actionable proposal may be admitted, openings not before
their cutoff, deadlines not before openings, and a mapping for every tradable
resource. The parser returns an immutable typed value; the runner does not
interpret an arbitrary dictionary repeatedly.

The complete metadata is already covered by the immutable episode-definition
hash. `calendar_sha256` additionally binds the externally prepared schedule
artifact; `calendar_identity` alone is descriptive.

B1 continues to create a pending record whose target rule has no expected open.
The runner creates the C0 `PendingStateReference` from the frozen schedule and
passes that exact `expected_open_time` to B2. A new runner reconstructs the
profile from the stored episode and the pending reference from committed
history; it never relies on process-local schedule state.

Deadline is inclusive. At simulated cutoff `T`:

- attempt settlement against observations eligible at `T`;
- if the exact target observation has `knowledge_time <= deadline`, it remains
  eligible for settlement even when first inspected after the deadline;
- otherwise, when `T > deadline`, terminate as `MISSING_EXECUTION_BAR`;
- at `T == deadline`, absence remains WAITING.

The runner must filter the B2 candidate observations so an exact target first
known after the deadline cannot settle.

## Valuation before settlement and policy delivery

Each deferred round resolves one authoritative valuation mark per held
non-reference resource from observations eligible at the cutoff, using the
existing pricing port and frozen staleness rules. A new pure
`AccountValuationService` mints a round account snapshot with:

- identical policy, balances, cumulative costs and reference resource;
- unchanged reservations;
- the current round index and cutoff;
- reference valuation recomputed with Decimal `ROUND_HALF_EVEN` conventions;
- provenance-bearing `PriceEvidence` supplied by the pricing boundary.

Missing/invalid required marks fail the round before policy invocation and
before persistence. The runner must not contain duplicate valuation arithmetic.

The revalued account becomes B2's `current_account`; the original
hash-addressed admission account is supplied as `admission_account`.
B2 already verifies that balances and costs did not change while pending.
A successful settlement returns its own newly valued account. WAITING,
settlement rejection, or no pending retains the revalued account.
That account—not a stale admission valuation—is delivered to the policy and
recorded as the policy entry's account-after state.

No duplicate account is appended when its canonical hash already exists; an
exact reference is sufficient. Tests must prove mark-to-market changes affect
equity without creating trade volume or fees.

## Causal round flow

For policies in strict lexicographic order:

1. Resolve the stored account, active `pending_after`, pending record and
   admission account. Validate run/policy/hash ownership.
2. Resolve eligible observations and marks, then revalue the account.
3. If pending exists, attempt B2 settlement before policy invocation. Interpret
   `is_settled=True` as settled, `is_still_pending=True` as waiting, and both
   false as rejected. Clear pending only for terminal outcomes.
4. Construct `PolicyContext` with the resulting account and eligible
   observations, then obtain exactly one proposal.
5. Invoke B1 with the still-active pending, if any:
   - new admission: stage pending and scheduled reference, no immediate outcome;
   - admissible HOLD with active pending: stage ACCEPTED HOLD and carry the exact
     reference;
   - different actionable proposal with active pending: stage rejection and
     carry the exact reference;
   - exact retry applies only to idempotent re-evaluation of the same admission
     context; it is not a normal cross-round state.
6. Construct the C0 policy entry. A settled/rejected old pending may coexist
   with one newly admitted pending; a waiting pending cannot be replaced.
7. Build the sorted v2 round and Merkle root.

All records remain staged until complete cross-record validation succeeds.

## Persistence boundaries

`RoundCommit` remains backward compatible and accepts either round version plus
additive deferred collections. It also has optional
`terminal_record: DeferredRunTerminalRecord | None`.
Its existing `settlement_outcomes` collection may contain both the settlement
of `pending_before` and, on the final round only, the terminal rejection of
`pending_after`; references make the distinction explicit.

`TerminalCommit` is used only for cancellation between rounds/genesis:

```python
@dataclass(frozen=True)
class TerminalCommit:
    expected_run_hash: str
    run: EpisodeRun
    terminal_record: DeferredRunTerminalRecord
    settlement_outcomes: tuple[SettlementOutcome, ...] = ()
    metrics: tuple[MetricRecord, ...] = ()
```

The port exposes run-scoped getters for pending records, settlement outcomes,
deferred transitions, account state by hash, active pending reference and
terminal record. Round-produced records have no public individual-save path;
they become visible only through an atomic commit.

Before changing any map/index, the in-memory adapter validates:

- expected prior run hash/status and exact next round index;
- parent hash, run/episode/policy ownership and strict policy ordering;
- every hash reference and typed payload, including staged references;
- schedule values against pending references;
- before/after account and transition/outcome links;
- Merkle roots and terminal final-state binding;
- no orphan pending, duplicate terminal outcome or dangling record;
- all IDs against both existing and staged records.

Validation builds complete candidate copies (or an equivalent transaction-local
state) and publishes only after every check passes. Fault injection at each
stage must leave all maps, derived indices, metrics and run progress unchanged.

An exact retry compares the complete commit, including updated run, metrics and
terminal data. Identical content is a no-op; any same-ID drift fails as immutable
mutation. A stale `expected_run_hash`, status, index or parent rejects a
concurrent commit. Derived active-pending indices are never authoritative and
must agree with the latest committed round/terminal record.

## Atomic completion and cancellation

For the final round, one `RoundCommit` contains:

- the final v2 round and all ordinary round records;
- any new pending record;
- terminal rejection outcomes for pending remaining after the policy phase;
- the terminal record linked to the staged final round;
- final deferred metrics;
- the COMPLETED run whose `final_state_hash` is the terminal record hash.

There is no intermediate visible COMPLETED run or final round with an active
unclosed pending. A failed commit exposes neither round nor termination.

Cancellation uses `TerminalCommit` with the latest committed run/round as its
expected parent. With pending, call B2 `terminate_unsettled` using the latest
committed round ID and simulation frontier cutoff, plus the admission anchor.
At genesis no pending/outcome exists and frontier/parent are null.
Repeated identical cancellation returns existing terminal state; changed retry
content fails. Cancelling a completed run is an invalid lifecycle transition.

The terminal record's [contract](../contracts/deferred-run-terminal-contract.md)
defines reason/status/time and hashing invariants.

## Deferred evaluation

Add a typed `DeferredEvaluationContext` rather than fabricating v1 transitions.
It contains run/policy identity, initial and chronological account snapshots,
proposal outcomes, settlement outcomes, deferred transitions, terminal policy
entry, elapsed wall seconds and calculation timestamp.

Metrics obey:

- costs and traded volume come only from SETTLED deferred transitions;
- admission and terminal rejection contribute no cost/volume;
- rejected proposal and rejected settlement counts remain separately derivable;
- the public v1 metric total may aggregate them only with a documented mapping;
- the equity curve uses the revalued snapshots in chronological order;
- one snapshot per round is selected deterministically even if settlement also
  minted an intermediate account;
- final metrics are computed from existing plus staged records before the atomic
  completion/termination commit.

Do not claim Sharpe, drawdown or trading-specific measures in C1; those belong
to the later evidence protocol.

## Terminal schema delivery

C1 implements, rather than merely documents:

- `deferred_run_terminal_record.v1.json`;
- schema inventory entry;
- valid clean/completed/cancelled examples;
- invalid status/reason, time/parent, ordering, co-presence and hash-reference
  cases;
- strict domain model/codec round trips;
- documentation-link and secret scanning.

JSON Schema validates expressible structure and conditionals. Domain/persistence
validation owns hashes and cross-record references.

## Required tests and stop conditions

Focused evidence must cover:

- normal admit → wait → settle → new proposal;
- exact deadline, late inspection of timely evidence, late target publication
  and missing-bar expiry;
- insufficient funds, short prohibition, missing marks and settlement rejection;
- HOLD/actionable proposal behavior while pending;
- periodic revaluation without false trade/cost;
- final clean completion, final admission, old settlement plus new final
  admission, and carried pending;
- mid-run cancellation, genesis cancellation, repeated cancellation and
  completed-run cancellation;
- new runner recovery, multi-run/policy isolation and admission-account lookup;
- exact retry, mutated retry, stale parent and fault injection;
- schema/codec invalid corpus and hash tampering;
- unchanged synchronous reference behavior.

Run the backend suite, contract validator, Ruff and format checks, and
`git diff --check`. Update general and detailed roadmap checkboxes before the
atomic implementation commit. Do not detail or begin C2.

Stop if C1 would require changing B1/B2/C0 semantics, a v1 schema, or replay.
Report the incompatibility for a new reviewed planning unit.

## Gate

The plan and terminal design are independently reviewed. The next and only
authorized step is implementation of `DS-02D2C1` within this boundary.
Completion requires all evidence above and a separate independent review.

Planning-review verification: 339 backend tests, the 20-schema/15-example
contract validator, Ruff, formatting and diff checks pass. These protect the
existing implementation; they are not C1 runtime evidence.
