# Deferred Runner Orchestration and Atomic Persistence

## Work unit and review status

- ID: `DS-02D2C1`; planning reviewed, NOT ready for runtime implementation.
- Prerequisite: reviewed C0 (`d2243bb`) and B1/B2 (`d365cd8`); `DS-D3B` satisfied.
- Parent: [market plan](market-dataset-and-baseline-evidence.md).
- Authority: [deferred settlement contract](../contracts/deferred-settlement-contract.md).
- Next authorized work: close the C1 planning decisions below, then independent review.
- C2 replay and DS-02E market episodes remain blocked; `DS-D3` is not satisfied.

Review of `07daad0` found missing schedule provenance, incompatible terminal
record assembly, and unsupported readiness claims. No runner or persistence
implementation was delivered by that commit. The 339 existing tests establish
the prior baseline, not the proposed orchestration.

## Scope and architecture

Integrate the existing pure admission and settlement services into
`application/services/runner.py` and the persistence boundary.
Do not implement new financial arithmetic in the runner. Preserve v1 records,
schemas and synchronous behavior; the current synchronous implementation is
`execute_next_round`, not an existing `_execute_next_round_synchronous` helper.

No replay implementation, REST, database, UI, live dataset acquisition or Optees
integration belongs in C1. Any necessary additive terminal-record contract must
be decided and independently reviewed before implementation, not improvised in
a persistence adapter.

## Corrections binding on the next plan

### 1. Mode, schedule and recovery

Choose one explicit, validated configuration mechanism, not
"metadata or constructor injection". Pin its version and identity with the
episode/run so a fresh runner cannot silently change mode, resource-to-series
mapping, calendar, target opening or timeout rules.

Supply B2's required `expected_open_time` from an authoritative frozen schedule.
Never infer it from the first available observation or round-cutoff spacing.
Persist the complete `PendingStateReference` (including deadline and admission
account hash), the pending record and the hash-addressable admission account.
Restore all of them from committed history, not process-local caches or merely
a search for pending IDs without outcomes. Pass `admission_account` where the
current account has since been revalued; preserve B2 balance invariants.

Freeze deadline inclusivity and late-discovery policy. Test before, exactly at,
and after deadline, including a target bar known by deadline but first inspected
at a later round. Do not reject solely because the next round skipped past the
deadline without defining which evidence remains eligible.

### 2. Ordinary round ordering

1. Select the simulated cutoff and eligible snapshot observations; wall-clock
   execution timestamps remain separate (no real clock advancement to historical time).
2. For each policy, resolve its committed account, pending reference and anchor.
3. Settle the old pending before invoking that policy. Handle all B2 results:
   WAITING carries the exact reference, SETTLED stages outcome/transition/account,
   REJECTED stages the terminal outcome without a trade or fee debit.
4. Deliver the resulting account and eligible observations to the policy.
5. Invoke admission using the actual result DTO. An actionable admitted trade
   has no immediate ACCEPTED outcome. HOLD/rejection produce immediate outcomes.
   Exact pending retries are not automatically a new admission: preserve B1
   identity semantics and prove representability in the C0 policy entry.
6. Assemble immutable v2 entries, sorted by policy ID, and Merkle evidence.
7. Validate and publish the entire batch, metrics when applicable, and run progress
   in one atomic operation. Nothing is written after that commit as a "cleanup".

Use the existing settlement flags `is_settled` and `is_still_pending`;
both false denotes rejection, not waiting. Inspect the actual admission result
fields too, and preserve the distinction between new and reused pending records.

### 3. Terminal events: unresolved representation must be decided first

The original post-commit termination step is invalid. Completion/cancellation
outcomes and pending clearance must be committed atomically with their causal
history and terminal run state.

C0 permits one settlement outcome per policy entry and forbids a settlement
without `pending_before`. A final-round new admission cannot simply be
terminated in that same entry; an old settlement plus a newly terminated
admission cannot occupy its single outcome slot either.
Cancellation between rounds also needs an explicit immutable event/round
identity and simulated time. Do not backdate, overwrite the last round, append
an undeclared calendar round, or invent immediate financial acceptance.

The next planning decision must select and document a representable lifecycle
(e.g. a separately specified terminal event), including final-round proposals,
zero-round runs, repeated cancellation, already completed runs and atomic failure.
Any contract addition must be registered and validated before runner work starts.

### 4. Persistence integrity

Extend the commit boundary additively for deferred records; no individual save
calls may expose a partially committed round. Validate the complete candidate
state before publishing any map or index:

- run/policy ownership; expected run progress, round index and parent hash;
- every referenced hash resolves to the correct typed record and policy;
- pending identity and immutable schedule agree with their admission evidence;
- settlement/transition/account links and before/after balances agree;
- no dangling references, duplicate terminal settlements or orphan pending;
- ID collisions with different payloads fail closed; exact commit retry behavior
  must be defined, including a lost acknowledgement;
- stale concurrent commits cannot advance the same parent twice.

Retrieval must be run-scoped even when record IDs exist in global maps.
Restart recovery means a fresh runner using the same in-memory store here,
not disk durability. File/database durability remains out of scope.

### 5. Evaluation and reproducibility

Inspect the existing v1 evaluator: deferred outcomes/transitions are not drop-in
replacements. Freeze an explicit adapter or typed evaluation input. Count fees
and turnover only once for actual settlements; admission is not acceptance.
Separate rejected proposals from rejected settlements, preserve policy isolation,
and define revaluation/no-trade-round equity and terminal metric semantics.
No fabricated v1 transitions may stand in for deferred execution.

Byte-identical records require identical run/policy/decision identities and a
fixed injected execution clock as well as deterministic inputs. Real wall-clock
timestamps change round hashes. C1 can prove deterministic execution under a
fixed clock; full replay evidence belongs to C2.

## Required evidence for the future implementation

- [ ] Mode and schedule configuration frozen with provenance and invalid-input cases.
- [ ] Terminal representation, final-round admission and cancellation semantics frozen.
- [ ] Persistence/read APIs, exact retry and stale-write behavior frozen.
- [ ] Evaluator input and metric semantics frozen.
- [ ] Independent review accepts the corrected implementation plan.
- [ ] Normal admit → wait → settle → new proposal sequence using real B1/B2/C0.
- [ ] Deadline boundary, missing target, late revision, financial rejection and HOLD/retry cases.
- [ ] Completion/cancellation with pending, final-round proposal and repeated termination.
- [ ] Fresh runner recovery and multi-run/multi-policy isolation.
- [ ] Fault injection proves unchanged maps, indices, metrics and progress on failure.
- [ ] Invalid hash/type/ownership references and duplicate terminal outcomes rejected.
- [ ] All existing backend tests, contracts, Ruff and diff checks pass.
- [ ] Implementation independently reviewed; only then detail C2.

## Completion

- [x] Initial proposal inspected against actual B1/B2/C0 and v1 persistence.
- [x] Unsafe ordering and unsupported implementation readiness withdrawn.
- [ ] Open decisions above closed and accepted.
- [ ] Runtime implementation and review complete.

This document is a corrected planning boundary, not a completed executable plan.

Review verification: 339 backend tests pass; 20 registered schemas and 15 valid
examples validate; backend/tool Ruff checks, formatting and diff checks pass.
Only documentation changed. These checks preserve the existing baseline and do
not satisfy the still-open C1 implementation evidence above.
