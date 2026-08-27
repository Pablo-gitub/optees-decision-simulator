# Deterministic Episode Kernel Plan

## Work Unit

- **ID:** `DS-01`
- **State:** ready
- **Type:** backend domain and application implementation; no UI
- **Parent roadmap:** `../ROADMAP.md`
- **Prerequisite:** `DS-C` satisfied by `DS-00`
- **Parallel Optees work:** `OPT-DS-02` capability stage through `QP-I`
- **Owner:** Gemini
- **Review:** Codex
- **Completion gate:** `DS-K`

## Objective

Implement the framework-independent deterministic kernel that executes a
complete synthetic episode with multiple isolated policies and reproduces its
history from immutable canonical records. The kernel must prove time
eligibility, lifecycle safety, accounting isolation, exact transition
semantics, hash chaining, idempotent resume, cancellation between rounds, and
divergence-aware replay without SQLite, FastAPI, React, a market provider,
network access, or Optees.

This work unit establishes executable domain truth. It does not select the
production dataset, persistence engine, API, solver integration, or UI.

## Architectural Boundary

Create only the backend application skeleton needed by the accepted monorepo
architecture:

```text
apps/backend/
├── src/simulator/
│   ├── domain/
│   ├── application/
│   ├── infrastructure/
│   ├── interfaces/
│   └── bootstrap/
└── tests/
```

For `DS-01`:

- `domain` owns pure entities, value objects, invariants, lifecycle rules,
  account transitions, canonical values, hashes, and domain errors;
- `application` owns commands, queries, episode/round orchestration, replay
  services, policies, and abstract ports;
- `infrastructure` contains only deterministic in-memory adapters and the
  synthetic fixture adapter needed by `DS-K`;
- `interfaces` and `bootstrap` may contain package placeholders but no
  FastAPI, CLI, database, or process integration.

The dependency direction is `application -> domain`; infrastructure implements
application-owned ports. Domain imports no framework, ORM, provider, protocol,
or Optees class. Do not create a generic repository/helper layer that bypasses
these boundaries.

## Frozen Contracts as Authority

Implementation must follow the v1 schemas and semantic definitions in
`docs/contracts/core-contracts.md`. JSON Schemas remain the public contract;
Python classes are internal representations and must round-trip without
silently changing identifiers, timestamps, decimal strings, optional fields,
or enum values.

Before implementing behavior:

- map every v1 record to its owning layer and lifecycle;
- identify schema constraints that need additional semantic validation;
- reuse the DS-C canonicalization vectors and invalid fixtures;
- stop if a schema cannot express the behavior required by its frozen
  semantics rather than introducing an incompatible private interpretation.

## Required Implementation

### 1. Domain values, records, and errors

Implement immutable typed representations for the records exercised by the
kernel, including episode/run identities, policy versions, observations,
rounds, proposals, outcomes, transitions, account states, metrics, replay and
divergence reports.

Provide explicit domain values for:

- strict UTC timestamps with uppercase `Z` serialization;
- stable typed identifiers and duplicate-identity rejection;
- finite binary64 values only where the public contract permits JSON numbers;
- exact quantities, balances, prices, fees, and costs parsed from canonical
  decimal strings and calculated with `Decimal` under a frozen precision and
  rounding policy;
- SHA-256 record identifiers and parent hashes;
- lifecycle, decision, replay, and divergence enums;
- structured errors with stable machine-readable codes.

Records become immutable once accepted. Do not use mutable default containers,
wall-clock calls, random identifiers, global registries, or process-dependent
hashes in domain behavior.

### 2. Canonical JSON and hash chains

Implement the production canonicalization path used by the kernel and prove it
against all representative DS-C RFC 8785 vectors. The implementation must:

- preserve Unicode without normalization and reject lone surrogates;
- use ECMAScript-compatible binary64 serialization and normalize negative
  zero;
- reject NaN and infinities before serialization;
- include type and schema version in every record hash;
- emit lowercase `sha256:` digests over canonical UTF-8 bytes;
- build round and account parent chains without self-referential hash fields;
- produce identical bytes independent of Python mapping insertion order.

Do not maintain a second divergent canonicalizer in tests. If the DS-C tool is
factored into reusable production code, preserve the validation command and
its independent golden vectors. Add a Python/Node cross-runtime comparison
when Node is available; absence of Node must be reported, not treated as a
kernel failure.

### 3. Episode freeze and lifecycle

Implement and test the allowed lifecycle:

`CONFIGURED -> RUNNING <-> PAUSED -> COMPLETED | FAILED | CANCELLED`.

- Starting freezes dataset identity/hash, calendar, rule set, policy versions,
  initial accounts, failure behavior, and deterministic configuration.
- Pause and cancellation requests take effect only at documented safe
  boundaries between rounds.
- Resume is idempotent: replaying the same resume command must not execute or
  append a round twice.
- Terminal runs cannot resume or mutate.
- Previously committed round/account records never change after a lifecycle
  transition.
- Execution timestamps come from `ClockPort`; simulation cutoffs/effective
  times come from the frozen episode calendar.

### 4. Observation eligibility and delivery

Implement one canonical eligibility service using knowledge time:

`t_knowledge <= round.knowledge_cutoff`.

It must also apply the frozen revision and deterministic ordering rules. Create
the eligible observation tuple once per round and deliver the same immutable
value to every policy. Policy-local transformations may not alter raw
visibility for another policy.

Reject and test:

- future-knowledge observations entering a policy context;
- ambiguous/non-UTC timestamps;
- duplicate observation identities;
- nondeterministic ordering at equal knowledge times;
- a policy attempting to request a policy-specific raw observation set;
- retrospective mutation of a prior round after a late revision arrives.

### 5. Policy and adapter boundaries

Define an application-owned `PolicyPort` receiving only its own immutable
policy context, account snapshot, eligible observations, and deterministic
round metadata. A policy returns a proposal; it never mutates accounts or
marks its own proposal accepted.

Implement deterministic, domain-neutral fixture policies sufficient for
kernel evidence:

- hold/static allocation;
- all-reference/cash equivalent;
- equal allocation across allowed synthetic resources;
- a simple reactive policy driven only by the latest eligible synthetic
  observation.

These are test/reference policies, not registered market strategies. Keep them
outside the core entities and make their versions/configuration explicit.

Define application-owned ports for clock, dataset/observation access,
persistence/history, canonical export, and future Optees execution as frozen
by `DS-C`. Implement only in-memory/synthetic adapters in this work unit. The
Optees port must not be invoked by `DS-01` policies.

### 6. Proposal, acceptance, and transition pipeline

Implement the frozen stages as separate testable operations:

1. prepare identical eligible observations;
2. execute one isolated policy;
3. structurally and semantically validate its proposal;
4. evaluate acceptance under frozen account/transition rules;
5. create an explicit accepted, rejected, or fallback outcome;
6. apply an accepted transition exactly once at effective time;
7. create the next immutable account state and explanatory metrics.

Use a small domain-neutral synthetic transition-rule adapter for `DS-K`.
Account validation must reject wrong policy/account ownership, unknown
resources, insufficient balances where borrowing is disabled, forbidden
negative quantities, non-finite or malformed amounts, unbalanced deltas, and
costs inconsistent with the frozen rule version.

A rejected decision must remain visible and must not mutate the account.
Fallback behavior must be explicit in the episode definition and outcome; do
not silently replace a failed proposal. Policy execution order must not change
any policy's inputs, outputs, or final state.

### 7. Deterministic episode runner

Implement an application service that:

- validates and freezes a configured episode;
- executes rounds in frozen calendar order;
- executes policies in a deterministic order while preserving isolation;
- appends proposals, outcomes, transitions, metrics, round hashes, and account
  hashes atomically to an application-owned history port;
- supports safe pause, idempotent resume, and cancellation between rounds;
- converts known domain/application failures to explicit run outcomes;
- never leaves a partially committed round visible;
- returns a deterministic final manifest and per-policy final account hash.

In-memory persistence must enforce the same uniqueness, append-only, and
compare-before-append assumptions expected later from SQLite. Do not let tests
pass through direct mutation of backing dictionaries.

### 8. Replay and divergence

Implement at least:

- **record replay:** reconstruct each account trajectory solely from retained
  records, verify links and hashes, and never invoke policies;
- **deterministic re-execution:** rerun the deterministic fixture policies and
  compare canonical records and final hashes;
- explicit `INCOMPATIBLE_REPLAY` when required policy/code provenance is not
  available.

Generate structured divergence records for broken parent links, record hash
mismatch, account/transition mismatch, policy decision difference, validation
status change, and exact match. Replays are read-only and never repair or
overwrite original history. Numerical Optees rerun remains out of scope until
solver integration.

## Required Synthetic Evidence

Create a compact analytic fixture with:

- at least two resources, two policies, and three decision rounds;
- observations before, exactly at, and after knowledge cutoffs;
- equal knowledge timestamps requiring the full tie-break order;
- a delayed revision visible only in a later round;
- one accepted decision and one retained rejected/fallback decision;
- non-zero deterministic transition cost;
- distinct isolated policy trajectories from identical raw observations;
- pause/resume and cancellation variants;
- expected canonical record hashes committed as versioned golden evidence.

Expected values and hashes must be derived from readable fixture semantics,
not copied blindly from the first implementation output. Add a small
independent calculation or explicit manual derivation for balances and costs.

## Verification Matrix

### Domain and property tests

- frozen record immutability and legal/illegal lifecycle transitions;
- exact decimal arithmetic and frozen rounding;
- UTC parsing, finite-number rejection, identifiers, and enum validation;
- canonical JSON golden vectors and semantic hash mutation;
- round/account parent-chain construction and tamper detection;
- proposal and transition invariants.

### Application tests

- identical observation tuple for every policy;
- cutoff boundary and late-revision behavior;
- cross-policy account access and state contamination rejection;
- policy-order permutation produces equivalent per-policy histories;
- rejected/fallback proposals remain visible without account mutation;
- atomic round append under injected policy/transition failure;
- pause boundary, duplicate resume, cancellation, and terminal-state behavior;
- complete synthetic episode with expected balances, costs, metrics, and hashes;
- record replay exact match and deterministic re-execution;
- tampered records produce the expected divergence category.

### Architecture and contract tests

- import-boundary test preventing domain/application imports of FastAPI,
  SQLite/ORM, React, provider, MCP, or Optees modules;
- Python record-to-schema serialization for every exercised v1 type;
- existing valid and invalid DS-C fixtures remain valid demonstrations;
- documentation links and `tools/validate_contracts.py` remain green;
- Ruff and the complete backend test suite pass.

Tests must not depend on network, current time, hash randomization, locale,
machine timezone, filesystem order, database, GUI, or Optees availability.

## Documentation Outputs

- mark the backend folders actually created in `docs/ARCHITECTURE.md` while
  leaving later infrastructure/interfaces clearly planned;
- document the executable lifecycle, transition boundary, canonicalization
  implementation, and replay modes without duplicating the core contract;
- update `docs/ROADMAP.md` and this plan only when `DS-K` evidence is complete;
- add focused backend test commands and package/bootstrap instructions to the
  README or a dedicated development guide;
- keep planned SQLite, FastAPI, dataset, Optees, and UI behavior labelled as
  planned.

## Explicitly Out of Scope

- real market data, provider selection, downloads, or licensing;
- market valuation, portfolio terminology, or trading policy claims;
- SQLite schema, migrations, FastAPI routes, CLI, REST, MCP, or subprocesses;
- any Optees capability call, QP DTO, solver fixture, or fallback;
- React/Vite scaffolding, MVVM view models, design system, charts, or other UI;
- production metrics beyond the minimal deterministic synthetic evidence;
- parallel policy execution, distributed workers, arbitrary executable policy
  imports, plugin loading, or workflow registration;
- numerical replay, stochastic policies, tuning, forecasting, or optimization.

Claude is not an implementation owner for `DS-01`; there is no UI surface to
design or review at this gate. Claude's first Simulator planning input begins
after `DS-K`, when stable kernel states can inform information architecture.

## Stop Conditions

Stop and request a decision if:

- an implemented Python record cannot round-trip through the frozen v1 schema;
- exact account arithmetic conflicts with the canonical decimal-string rules;
- Python and JavaScript cannot reproduce canonical bytes for a frozen vector;
- idempotent resume would require mutating committed round history;
- one policy cannot be isolated without duplicating or filtering raw facts;
- an atomic round cannot be represented through the application port;
- the synthetic transition model would force market semantics into the core;
- the work requires SQLite, FastAPI, Optees, React, or a contract version bump;
- scope expands into provider, optimization, or UI implementation.

## Completion Gate `DS-K`

`DS-K` is satisfied only when a fresh checkout can run the documented backend
commands and produce the committed synthetic episode evidence; every policy
received identical eligible observations; account histories remain isolated;
pause/resume/cancel behavior is deterministic; rejected decisions remain
auditable; record replay and deterministic re-execution reproduce the expected
hashes; injected tampering yields structured divergence; all focused and full
backend gates pass; documentation describes shipped behavior honestly; and the
implementation is one reviewed atomic commit.

After `DS-K`, stop. Do not start dataset selection, SQLite/API work, Optees
integration, or frontend design in the same execution task.
