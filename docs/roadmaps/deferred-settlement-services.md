# Deferred Settlement Services

## Work unit

- ID: `DS-02D2B2`; status: implementation and independent review complete.
- Initial implementation owner: Claude, by temporary backend reassignment.
- Review corrections: Codex. Prerequisite: reviewed B1 (`40308b4`).
- Parent: [market plan](market-dataset-and-baseline-evidence.md).
- Contract: [deferred settlement](../contracts/deferred-settlement-contract.md).
- Gate `DS-D3B`: satisfied for pure admission and settlement services.
- Next: detail `DS-02D2C`; runner/replay implementation is not authorized here.

## Scope and boundaries

Production service:
`apps/backend/src/simulator/application/services/deferred_settlement.py`.
Tests:
`apps/backend/tests/unit/application/test_deferred_settlement.py`.

The service is pure and application-owned. It reuses domain records, canonical
hashing, UTC parsing and PriceEvidence. It does not call or change ExecutionService,
B1, providers, pricing adapters, runner, replay, persistence, API, UI or Optees.
No real transactions, I/O, new dependency, or public record schema is introduced.

## Reviewed input contract

`attempt_settlement` takes episode, current account, pending, settlement round
ID/index/time, observations and valuation marks. It additionally requires the
keyword `expected_open_time`: the authoritative first scheduled opening at or
after admission cutoff, supplied from frozen market/calendar configuration.
It is NOT inferred from available observations or from decision-round spacing.
Daily, irregular and closed-market calendars remain the caller's responsibility.
No parsing of opaque interval strings or guessing of a missing slot is allowed.

The required opening must be strict UTC, not precede admission cutoff, and
must agree with any expected opening retained in the pending target rule.
B1 records may leave that optional field absent. The caller must preserve the
target across attempts; future runner/replay must freeze and replay its source.

Both entry points validate policy ownership, episode-scoped pending identity
(using the same full canonical digest as B1), pinned policy version, strict
times and supported nonzero trade syntax. Cash-resource trades are invalid.
An episode with different identity cannot settle or terminate this pending.

### Admission anchor versus current account

By default the current account must have the pending's predecessor hash.
If a later round has revalued/reidentified the account, supply the optional
`admission_account` to either entry point. Its hash must equal the admission
anchor. Current policy, balances (including reservations), cumulative costs
and reference unit must match that anchor. Timestamps must be ordered.
Only valuation/round metadata may differ: no pending proceeds, purchases or
fees may already have entered the balances.

Successful transition before-hash and new account parent hash reference the
CURRENT account, not the admission snapshot. Pending predecessor remains the
original admission hash. This service verifies local anchors, not the entire
persisted history; verifying that history is a future integration obligation.

## Exact target selection

1. Consider only the episode's dataset snapshot and pending series.
2. Parse retained open_time as strict UTC; malformed/missing times cannot fill.
3. Consider only the supplied expected opening, and require open < knowledge.
4. Keep revisions whose knowledge_time <= settlement_time.
5. If no eligible matching revision exists, return WAITING with original
   account and no terminal records. Never fall through to a later opening.
6. Select highest revision, then observation ID deterministically. Conflicting
   payloads sharing revision and identity fail explicitly, regardless of
   input order; identical duplicates do not change the result.

Missing the first bar entirely is no longer an accepted skipping limitation.
Malformed, foreign-snapshot, future or absent target data cannot substitute a
later bar. The caller decides timeout/cancellation and uses terminate_unsettled.

## Economics and deterministic arithmetic

The entire evaluation uses an isolated Decimal context: precision 64,
ROUND_HALF_EVEN, exponent limits -999999/+999999, fixed InvalidOperation,
DivisionByZero and Overflow traps, empty initial flags. Caller precision,
rounding and traps are neither inherited nor changed. This is a bounded
decimal arithmetic profile, not arbitrary-precision exact rational arithmetic.

For signed asset quantity q and positive finite opening price p:

- notional = round_to_cents(abs(q) * p);
- proportional fee = round_to_cents(notional * fee_rate);
- fixed fee = round_to_cents(configured fixed fee);
- total fee = proportional + fixed fee;
- buy cash delta = -(notional + total fee);
- sell cash delta = notional - total fee;
- asset delta = q.

ALLOCATE requires q > 0; TRANSFER requires q != 0. Valuations and cash are
rounded to cents; fractional asset units are retained. Every quantize has
explicit HALF_EVEN rounding. Fixed sub-cent fees follow this same currency
rounding rule (an explicit refinement of the synchronous service conventions).
Inputs outside the supported Decimal range fail; they are not clamped.

PriceEvidence marks must identify the mapped resource and cannot have future
knowledge time. Bare Decimal marks remain a trusted caller-owned valuation
boundary. Every required held/traded non-reference resource needs a positive
finite mark. Shorting/borrowing flags control resulting asset/cash feasibility.

## WAITING, REJECTED, SETTLED

The immutable result enforces mutually exclusive states:

- WAITING: no outcome or transition, same input account and pending.
- REJECTED: one rejected outcome, no transition, same input account.
- SETTLED: one outcome and one bidirectionally linked DeferredTransitionRecord,
  plus the newly minted account.

Invalid price has empty execution evidence because the frozen schema cannot
encode a partial/invalid priced observation. Financial/mark rejections preserve
valid observation evidence but report total_fee_deducted = 0.00. This field
never means hypothetical fees. Insufficient-funds cash_required includes the
computed costs, while balances and cumulative costs stay untouched.

terminate_unsettled accepts only MISSING_EXECUTION_BAR,
UNSETTLED_EPISODE_TERMINATION or EPISODE_CANCELLED. It validates the same
episode/account anchors, emits rejection and never decides a deadline itself.

## Identity and publication

Outcome, transition and account IDs have their schema prefixes followed by
the full canonical SHA-256 digest of:
`{"pending_transition_id": pending_id, "settlement_round_id": round_id}`.
The pending identity already includes episode/decision identity. Different
episodes or orders cannot collide merely by reusing round/policy labels.

Repeated pure evaluation of the same inputs returns identical results.
Persisted terminal deduplication and atomic publication are NOT implemented.
The caller must not publish competing evaluations of one pending as independent
settlements. Service completion does not prove runner ordering or replay.

## Verification and completion

Review evidence: 314 backend tests pass (including architecture, schemas,
legacy regressions and 44 settlement cases); contract validation, Ruff lint,
formatting and diff whitespace checks pass. No native UI or live market/network
tests are needed or claimed for this pure backend work unit.

- [x] Production B1-to-B2 buy/sell lifecycle and authoritative schema round-trip.
- [x] Exact opening selection, missing/late target, no later-bar fallback.
- [x] Eligible revisions and deterministic conflict rejection.
- [x] Foreign episode/snapshot exclusion and expected-target mismatch checks.
- [x] Decimal isolation at precision 6/28/80 with alternate rounding and traps.
- [x] Correct-sign cash/asset deltas, fees, insufficient cash, forbidden shorts.
- [x] Rejected operations record zero deducted fees and preserve the account.
- [x] Revaluation anchor and current before-hash; balance drift rejected.
- [x] Invalid prices, valuation evidence, terminal reasons and caller context.
- [x] Independent review corrections and documentation completed.
- [ ] Runner, round hashing, persisted deduplication and replay: future D2C.

Run from the repository in the configured Python environment:

```bash
PYTHONPATH=apps/backend/src python -m pytest apps/backend/tests -q
python tools/validate_contracts.py
ruff check apps/backend tools/validate_contracts.py
ruff format --check apps/backend tools/validate_contracts.py
git diff --check
```

Update both roadmaps before each atomic local commit. No remote publication or
AI commit attribution. Do not implement D2C without its reviewed detailed plan.
