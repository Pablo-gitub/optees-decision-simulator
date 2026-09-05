# Optees Decision Simulator Roadmap

## Document Status

- **State:** in progress
- **Authority:** this document owns Simulator sequencing and cross-repository
  integration gates
- **Latest completed detailed work unit:** `roadmaps/deterministic-episode-kernel.md`
- **Current detailed work unit:** `roadmaps/market-dataset-and-baseline-evidence.md`
- **Optees program dependency:** `docs/roadmaps/case-study/ROADMAP.md`
  in the sibling Optees repository
- **Current implementation:** core contracts and deterministic episode kernel
  implemented; market-data integration and later phases remain planned

## Product Thesis

### Completed cross-repository review corrections

- [x] Enforce conditional schemas and reject unsupported validator vocabulary.
- [x] Align pending signed `TRANSFER` quantities with existing accounting.
- [x] Identify open-time normalization as `1.1.0` and prevent legacy receipt reuse.

These corrections preserve the record-foundation gate. The
[DS-02D2B1 admission plan](roadmaps/deferred-admission-services.md) has been
implemented and reviewed after retry corrections; settlement detailing is next.

- [x] Freeze B1 admission scope, action semantics, retry behavior and test gate.
- [x] Implement and review B1, including HOLD identity, episode and target-rule retry regressions.
- [ ] Detail B2 settlement; no B2 implementation is authorized yet.

Build a local-first, reproducible case study showing how versioned Optees
capabilities can be orchestrated into repeated decisions over time. The same
experiments must expose mathematical, contractual, and workflow limitations
that should guide the next bounded expansion of Optees.

The first domain uses frozen public market time series—initially daily crypto
or similarly tractable data—because they are accessible and stress forecasting,
risk, robust decisions, discrete transitions, and repeated orchestration. The
Simulator remains paper-only: no credentials, order placement, real
transactions, personalized advice, or profitability claims.

## Success Has Two Outputs

1. A fair, replayable comparison of decision policies under identical
   knowledge-time information.
2. A capability-gap record showing where Optees contracts, algorithms,
   validation, or reusable workflow infrastructure should improve.

A negative or neutral performance result is valid evidence. The project must
not select favorable periods or redefine success after observing private or
forward results.

## Ownership Boundary

The Simulator owns time, market-data interpretation, episode state, policies,
virtual accounting, transition costs, scoring, replay, and comparison. Optees
owns domain-neutral mathematical capabilities, versioned contracts, solver
execution, validation, artifacts, reports, and the future registration of
externally defined validated workflows.

The Simulator may discover an orchestration with an agent or implement it in a
program. Optees Workflow Registry may later validate, freeze, version, and
recall that definition; it must not invent or preinstall the market policy.

## Workstream Model

Two repositories may advance in parallel when they do not define opposite
sides of the same unfrozen contract.

| Simulator work | Parallel Optees work | Synchronization rule |
| --- | --- | --- |
| Core contracts, time, accounting | QP contract and vertical slice | Independent until QP fixture gate |
| Dataset adapter and baselines | QP implementation | No QP production DTOs before `QP-I` |
| Persistence, replay, fake client | Robust contract design | Fake fixtures clearly marked provisional |
| QP policies | QP GUI/packaging hardening | Consume frozen public contract only |
| Robust policies | Forecasting expansion | Share frozen scenario packages |
| MIQP policies | MIQP implementation | Wait for `MIQP-I` fixtures |
| Registered policy execution | Workflow Registry | Wait for `WF-R` lifecycle contract |

Each integration checkpoint records repository commits, Optees version,
capability ID, contract versions, fixture hashes, and verification results.

## Progress Overview

Latest transition-v2 review: strict decimal-string decoding and cost-type validation
are covered by regressions. The canonical transition now matches the pending
quantity and predecessor hash; a cross-record test verifies links and cash deltas.
The record bridge is complete; runtime enforcement remains DS-02D2B/DS-02D2C.

| Done | Phase | Current state |
| --- | --- | --- |
| [x] | `DS-00` — Core Contracts And Threat Model | `DS-C` satisfied |
| [x] | `DS-01` — Deterministic Episode Kernel | `DS-K` satisfied |
| [ ] | `DS-02` — Market Dataset And Baseline Evidence | `DS-D3A` satisfied; `DS-02D2B1` implemented (review pending) |
| [ ] | `DS-03` — Persistence, API, And Existing Optees Capabilities | Not started |
| [ ] | `DS-04` — Convex QP Policy Family | QP prerequisite satisfied; not started |
| [ ] | `DS-05` — Scenario Min-max And Max-min Policies | Awaiting `ROBUST-C` |
| [ ] | `DS-06` — Evidence-driven Forecasting Expansion | Awaiting `FC-E` scope |
| [ ] | `DS-07` — Convex MIQP Policy Family | Awaiting `MIQP-I` |
| [ ] | `DS-08` — Workflow Registration Study | Awaiting `WF-R` |
| [ ] | `DS-09` — Web Inspection And Publishable Case Study | Not started |
| [ ] | `DS-10` — Generalization Decisions | Not started |

## Phase DS-00 — Core Contracts And Threat Model

- **Status:** Complete (Gate `DS-C` satisfied)
- Freeze episode, policy, round, observation, decision, transition, account,
  metric, dataset-manifest, capability-call, and replay-report semantics.
- Freeze event, knowledge, execution, and effective time.
- Define canonical JSON, hashing, immutability, versioning, and replay versus
  numerical re-execution.
- Define ports for dataset, clock, persistence, and Optees without selecting
  concrete frameworks as domain owners.
- Threat-model temporal leakage, policy contamination, malformed imports,
  process failure, resource exhaustion, report injection, and secret exposure.
- Decide Python package layout and verification tooling.

Delivered artifacts:
- [Core contracts & time semantics](contracts/core-contracts.md)
- [Threat model](contracts/threat-model.md)
- [Schema inventory](contracts/schemas/schema_inventory.json)
- Detailed plan: [Core contracts and time semantics roadmap](roadmaps/core-contracts-and-time-semantics.md).

**Gate DS-C (Satisfied):** contracts can be reviewed without FastAPI, SQLite, React, MCP,
or a market provider.

## Phase DS-01 — Deterministic Episode Kernel

- **Status:** Complete (Gate `DS-K` satisfied)
- Implemented immutable episode configuration and isolated policy state.
- Implemented deterministic rounds, virtual accounts, transitions, and costs.
- Delivered identical eligible observations to every policy at each cutoff.
- Added pause between rounds, idempotent resume, cancellation, canonical export,
  and divergence-aware replay.
- Added static, cash, equal-allocation, and simple reactive baseline policies.
- Proved temporal leakage and cross-policy contamination are rejected.
- Verified schema roundtrip for all 15 core entities and architectural boundary isolation.

Delivered artifacts:
- Python backend package: `apps/backend/src/simulator/` (domain, application, infrastructure layers)
- Backend test suite: `apps/backend/tests/` (45 passed tests covering unit,
  integration, and contract suites after review corrections)
- Detailed plan: [Deterministic episode kernel](roadmaps/deterministic-episode-kernel.md).

**Gate DS-K (Satisfied):** a synthetic analytic episode completes and replays without
Optees, a database, network, or web UI.

Review corrected two gate-level defects before acceptance: round records and
run progress now publish through one application-owned transactional commit,
and run-scoped record identifiers no longer collide when multiple runs share a
store. Final metrics cover the complete trajectory, timing uses `ClockPort`,
and the analytic episode asserts committed golden round and account hashes.
The subsequent integrity review made all JSON-like record fields deeply immutable and
made execution/replay preserve and verify policy-version identity and configuration.

`DS-K` integrity review checklist:

- [x] Deeply freeze JSON-like fields before hashing or persistence.
- [x] Return fresh mutable containers only at public serialization boundaries.
- [x] Verify policy and policy-version identity before episode execution.
- [x] Reuse the same immutable policy configuration during execution and replay.
- [x] Distinguish incompatible policy versions from same-version behavioral divergence.
- [x] Pass all backend domain, application, integration, and contract tests.

## Phase DS-02 — Market Dataset And Baseline Evidence

- **Status:** In Progress (Micro-gates through `DS-02C3` complete; `DS-02D` remains in review correction because the synchronous kernel cannot yet apply an evidenced future-open transition causally; Gates through `DS-D2` are satisfied)
- Selected Binance Public Historical Data Archive (`data.binance.vision`) 1d spot klines for liquid multi-asset universe (BTC, ETH, SOL, BNB quoted in USDT).
- Frozen dataset provenance contract, zero-credential unauthenticated retrieval, 24/7 continuous calendar, and field semantics in [`contracts/market-dataset-provenance.md`](contracts/market-dataset-provenance.md).
- Defined conservative four-time temporal semantics, upstream replacement handling, and three-tier SHA-256 hash boundaries.
- Frozen chronological historical partitions: Exploratory (P0: 2024-H1), Calibration (P1: 2024-H2), Retrospective Holdout (P2: 2025-H1), Retrospective Stress (P3: 2025-H2); a true prospective interval must be precommitted later.
- Implemented pure market kline infrastructure normalizer (`simulator.infrastructure.adapters.market_normalizer`), exact sub-second timestamp boundary decoding (ms < 2025 <= us), and D+2 knowledge cutoff anti-leakage eligibility.
- Built and validated synthetic fixtures (stable, trend, reversal, volatile, missing-day, structural-break) and verified schema roundtrip against real v1 contracts.
- Implemented pure provider-neutral acquisition evidence verification (`simulator.application.services.acquisition`), added `acquisition_receipt.v1.json` schema and inventory entry, and verified constant-time hash linkage from raw bytes to canonical manifest hash.
- Implemented pure bounded ZIP/CSV archive decoder (`simulator.infrastructure.adapters.archive_decoder`), enforcing strict resource bounds, zip bomb streaming protection, 12-column headerless CSV parsing, and typed immutable output.
- Implemented immutable offline snapshot store (`simulator.infrastructure.adapters.fs_snapshot_store`) and offline `DatasetPort` adapter (`simulator.infrastructure.adapters.offline_dataset`), ensuring atomic staging, verified reopen, and exact byte-for-byte observation and manifest parity.
- Implemented bounded streaming HTTPS acquisition transport (`simulator.infrastructure.adapters.https_acquisition_transport`) and provider acquisition service (`simulator.application.services.provider_acquisition`), with strict security bounds, redirect rejection, sanitized error categories, and idempotent immutable publication.
- Implemented the reviewed foundation for market valuation and paper-transition pricing (`simulator.application.ports.pricing`, `simulator.infrastructure.adapters.market_pricing`, `simulator.infrastructure.adapters.synthetic_pricing`), including evidenced marks, strict future-open selection, explicit rejection, fractional quantities and single-fee accounting.
- Review found that `EpisodeRunner` still applies every transition at the decision cutoff. Under the frozen D+2 availability rule, a strictly future bar cannot also be available at that instant.
- Completed and froze the authoritative [Deferred Paper Settlement Contract](contracts/deferred-settlement-contract.md) (Gate `DS-D3T`), formalizing the five-time temporal model, `open_time` retention in payload, pending transition lifecycle, single-pending policy invariant, feasibility verification at fill, settlement-before-next-decision priority, and 9 pure decision probes.
- Review selected dedicated immutable pending-transition and settlement-outcome records,
  reconciled cancellation with terminal rejection, and replaced the premature test-local
  engine with declarative contract probes.
- `DS-02D2A1` delivered runtime records and open-time evidence, and `DS-02D2A2`
  added `transition.v2` to bridge applied deferred settlements to terminal `set-out_`
  outcomes with separate `economic_fill_time` and `effective_time`. Gate `DS-D3A` is satisfied.
- Next authorized work is `DS-02D2B` (admission and settlement application services),
  followed by `DS-02D2C` (runner/replay integration). `DS-02E` is not authorized.

Detailed plan: [Market dataset and baseline evidence](roadmaps/market-dataset-and-baseline-evidence.md).

**Micro-gate DS-D0 (Satisfied after review correction):** dataset decision,
licence-handling boundary, retrieval method, and provenance contract are frozen
and reviewable without production code. Raw archive redistribution is not asserted.
**Micro-gate DS-D1 (Satisfied after review correction):** synthetic raw records normalize deterministically into
episode-ready existing v1 observations and manifests; production eligibility,
schema, canonicalization, and hashing code prove determinism and the conservative anti-leakage boundary.
**Micro-gate DS-D2A (Satisfied after review correction):** production canonicalization plus pure byte/hash probes bind
one raw artifact to one existing normalized manifest without I/O or unsupported legal claims.
Acceptance now requires caller-supplied normalized snapshot bytes whose computed digest
matches the existing manifest; omission or mismatch is a rejected evidence outcome.
**Micro-gate DS-D2B1 (Satisfied after review correction):** synthetic accepted ZIP bytes decode deterministically under
strict resource and archive-shape limits without filesystem or network access; malformed CSV parser failures remain inside the stable adapter error contract.
**Medium gate DS-D2B (Satisfied):** interrupted or malicious writes publish nothing, accepted
content cannot be overwritten, and a synthetic acquisition reopens offline to
reproduce byte-for-byte observations, manifest, receipt, and hashes.
**Medium gate DS-D2C (Satisfied after review correction):** fake-transport tests prove provider-neutral acquisition transport,
strict HTTPS URL validation, streaming size boundaries, redirect rejection, sanitized error categories,
and idempotent immutable publication without touching live networks.
**Medium gate DS-D2 (Satisfied after review correction):** full acquisition evidence pipeline (`DS-D2A` + `DS-D2B` + `DS-D2C`)
is verified and complete.
**Correction gate DS-D3T (Satisfied):** one reviewed temporal contract proves that no policy input,
execution price or account mutation crosses its authorized time boundary and defines a lossless
implementation path with 9 pure decision probes.
**Micro-gate DS-D3A (Satisfied after review correction and transition bridge):** the full record chain `PendingTransitionRecord` -> `SettlementOutcome` <-> `DeferredTransitionRecord` is schema-valid, immutable, canonically hashable and bidirectionally linked. `transition.v2.json` preserves v1 accounting semantics, replaces `outcome_id` with `settlement_outcome_id`, and distinguishes `economic_fill_time` from `effective_time`, leaving all v1 schemas, examples and hashes unchanged.
Review correction freezes one ID prefix per record, the sole target-bar rule and
admission-time equality, rejects schema/nested-field drift, and requires complete
causal execution evidence for every settled outcome.
**Medium gate DS-D3 (Open after review):** adapter, accounting determinism, and the deferred settlement contract are complete; production runner and replay deferred settlement kernel implementation remain for `DS-02D2`.

- [x] Implement bounded provider acquisition and immutable publication in `DS-02C3`.
- [ ] Complete market valuation and paper-transition rules in `DS-02D`.
  - [x] Select evidenced latest-close marks and strictly future-open execution prices.
  - [x] Remove non-reference `1.00` price fallbacks and reject unavailable prices safely.
  - [x] Preserve fractional quantities and apply the existing fee model exactly once.
  - [x] Prove deterministic adapter and accounting outputs for explicit valid pricing inputs.
  - [x] Freeze deferred-settlement time, state, failure, record and replay semantics (`DS-D3T`).
  - [ ] Implement a causal pending/delayed-transition lifecycle (`DS-02D2`).
    - [x] Complete immutable runtime linkage and exact open-time evidence (`DS-02D2A` / `DS-D3A`).
      - [x] Add pending/settlement records and retain open time (`DS-02D2A1`).
      - [x] Add the versioned deferred-transition reverse link (`DS-02D2A2`).
    - [ ] Implement pure admission and settlement application services (`DS-02D2B` / `DS-D3B`).
      - [x] Implement admission service (`DS-02D2B1`, review pending).
      - [ ] Detail and implement settlement service (`DS-02D2B2`).
    - [ ] Integrate runner, round hashing and replay (`DS-02D2C` / `DS-D3`).
  - [ ] Prove normalized D+2 observations execute end to end without temporal leakage (`DS-D3`).

`DS-02D` correction sequence:

- [x] `DS-02D1`: freeze deferred-settlement time, state, failure, record and replay semantics (`DS-D3T`).
- [x] `DS-02D2A`: complete runtime records and exact open-time evidence; prove `DS-D3A`.
  - [x] `DS-02D2A1`: pending/settlement records and open-time retention.
  - [x] `DS-02D2A2`: versioned deferred-transition bridge.
- [ ] `DS-02D2B`: implement admission and settlement services; prove `DS-D3B`.
  - [x] `DS-02D2B1`: implement admission service; independent review pending.
  - [ ] `DS-02D2B2`: detail and implement settlement service.
- [ ] `DS-02D2C`: integrate runner and replay; prove `DS-D3`.
- [ ] Authorize `DS-02E` only after both correction gates pass review.

`DS-D2A`, `DS-D2B`, and `DS-D2C` completion checklist:

- [x] Bind raw bytes to the strict publisher checksum and exact byte size.
- [x] Compute the normalized snapshot digest from caller-supplied bytes.
- [x] Bind the computed normalized digest and canonical manifest hash.
- [x] Preserve rejected evidence without fabricated timestamps, sizes, or digests.
- [x] Bind licence text to the reviewed manifest.
- [x] Restrict evidence URIs to credential-free HTTPS and exact basenames.
- [x] Validate the receipt schema, examples, determinism, and failure reasons.
- [x] Implement the pure bounded ZIP/CSV decoder in `DS-02C2A`.
- [x] Implement the immutable store and offline `DatasetPort` adapter in medium gate `DS-02C2B`.
- [x] Review path containment, deep immutability, verified existence, storage bounds, and pruning failures.
- [x] Implement bounded provider acquisition transport and orchestration service in `DS-02C3`.
- [x] Review acquisition identity, exception containment, timeout enforcement, and transport redaction.
**Gate DS-D (Planned):** the same frozen observations and valuations reproduce the same baseline episode hashes.

## Phase DS-03 — Persistence, API, And Existing Optees Capabilities

- Add SQLite behind application-owned repository ports and immutable version
  records.
- Add FastAPI as a thin loopback interface over application services.
- Implement `FakeOpteesClient`, then MCP stdio and REST parity adapters.
- Pin descriptors and persist exact payload/result hashes and validation
  receipts.
- Add current Forecasting, LP, and MILP policies with explicit fallback rules.
- Record capability gaps without silently changing a policy objective.

MCP usability is not the research question; prior Claude and Qwen work already
established practical agent orchestration. Transport parity remains a
regression requirement.

**Gate DS-O:** baseline and released-capability policies complete the identical
episode with reproducible provenance.

## Phase DS-04 — Convex QP Policy Family

Optees gate `QP-I` is satisfied; this phase has not started.

- Consume the frozen Convex QP descriptor and fixtures.
- Add domain-specific formulators for return/risk, concentration, target
  tracking, and quadratic transition penalties.
- Keep estimated inputs, policy coefficients, constraints, and assumptions
  visible.
- Compare LP/MILP and QP policies across identical rounds and cost rules.
- Sweep risk and transition coefficients only on the declared calibration
  interval; never tune on private or forward periods.

**Gate DS-QP:** every QP decision can be reconstructed from visible inputs and
the retained Optees problem/result pair.

## Phase DS-05 — Scenario Min-max And Max-min Policies

Blocked until Optees gate `ROBUST-C`.

- Build one versioned scenario package shared by expected-value and worst-case
  policies.
- Add `maximize_minimum_reward` and `minimize_maximum_loss` policies without
  treating them as interchangeable labels.
- Report scenario values, binding scenarios, guarantee, costs, and realized
  outcome separately.
- Compare robustness, return, drawdown, volatility, and turnover without a
  hidden combined score.
- Record when worst-case protection reduces performance without improving the
  declared risk measure.

## Phase DS-06 — Evidence-driven Forecasting Expansion

Consume only Forecasting outputs that pass Optees gate `FC-E`.

- Compare level, return, and volatility information where supported.
- Evaluate every forecast chronologically and retain its training cutoff.
- Test whether improved predictive metrics improve downstream decisions.
- Separate forecast uncertainty from decision risk.
- Reject post-hoc method selection and future-data leakage.

This phase may overlap DS-05 when scenario construction needs newly frozen
forecast outputs.

## Phase DS-07 — Convex MIQP Policy Family

Blocked until Optees gate `MIQP-I`.

- Add cardinality, fixed transition, minimum quantity, and discrete rebalance
  policies.
- Retain incumbent, best bound, gap, time limit, and validation status.
- Compare expressiveness and solution cost against continuous QP and linear
  MILP alternatives.
- Freeze behavior for feasible incumbents, timeout without incumbent,
  infeasibility, and validation failure.

## Phase DS-08 — Workflow Registration Study

Blocked until Optees gate `WF-R`.

- Select orchestrations already implemented and validated in prior phases.
- Serialize candidate definitions outside Optees.
- Validate and promote immutable versions through Workflow Registry.
- Recall and execute registered versions without an agent.
- Compare direct program, agent-built, and registered execution for result
  parity, latency, tool calls, tokens, failures, auditability, and replay.
- Keep episode scheduling, accounts, and scoring in the Simulator.

The Registry does not ship preimplemented market workflows. It stores and
recalls definitions promoted after external validation.

## Phase DS-09 — Web Inspection And Publishable Case Study

- Build React/TypeScript views only after backend episode and replay contracts
  are stable.
- Expose configuration, immutable policy versions, round timeline, accounts,
  forecasts, decisions, scenario results, validation, failures, and provenance.
- Keep official accounting and scoring server-side.
- Export complete machine-readable evidence and compact human reports.
- Publish manifests, checksums, negative results, limitations, and the exact
  Optees versions used.
- State prominently that market experiments are paper simulations and not
  evidence of future profitability.

## Phase DS-10 — Generalization Decisions

After the first case study:

- test at least one structurally different non-market dataset;
- decide whether QP, robust, Forecasting, MIQP, and Registry evidence justifies
  further Optees investment;
- consider CVaR only after loss/probability semantics are frozen;
- evaluate decision trees, ensembles, deep learning, DP/MDP, bandits, or an
  external policy engine only against specific measured limitations;
- keep domain adapters outside Optees and the Simulator core.

## Capability-gap Record

Every proposed Optees improvement must retain:

- episode, round, and policy identifiers;
- Optees capability and contract versions;
- observed limitation and reproducible fixture;
- workaround, if any;
- effect on validity, performance, robustness, or operability;
- frequency and cross-domain generality;
- proposed owner: Simulator, Optees capability, Workflow Registry, or dataset
  adapter;
- acceptance evidence required to close the gap.

## Program Completion Gate

The first program is successful when:

- baseline, current Optees, QP, robust, and MIQP policies receive identical
  eligible information and complete reproducible episodes;
- registered versions of previously validated orchestrations run without an
  LLM and retain full provenance;
- replay reproduces state hashes or explains numerical divergence;
- assumptions, failures, costs, statuses, and negative results remain visible;
- no real-world execution or secret-bearing connector exists;
- the evidence supports a concrete next decision about Optees rather than an
  open-ended expansion of mathematics.
