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

| Done | Phase | Current state |
| --- | --- | --- |
| [x] | `DS-00` — Core Contracts And Threat Model | `DS-C` satisfied |
| [x] | `DS-01` — Deterministic Episode Kernel | `DS-K` satisfied |
| [ ] | `DS-02` — Market Dataset And Baseline Evidence | `DS-02A` ready |
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

## Phase DS-02 — Market Dataset And Baseline Evidence

- **Status:** In Progress (Micro-gates `DS-02A` and `DS-02B` complete; Gates `DS-D0` and `DS-D1` satisfied)
- Selected Binance Public Historical Data Archive (`data.binance.vision`) 1d spot klines for liquid multi-asset universe (BTC, ETH, SOL, BNB quoted in USDT).
- Frozen dataset provenance contract, zero-credential unauthenticated retrieval, 24/7 continuous calendar, and field semantics in [`contracts/market-dataset-provenance.md`](contracts/market-dataset-provenance.md).
- Defined conservative four-time temporal semantics, upstream replacement handling, and three-tier SHA-256 hash boundaries.
- Frozen chronological historical partitions: Exploratory (P0: 2024-H1), Calibration (P1: 2024-H2), Retrospective Holdout (P2: 2025-H1), Retrospective Stress (P3: 2025-H2); a true prospective interval must be precommitted later.
- Implemented pure market kline infrastructure normalizer (`simulator.infrastructure.adapters.market_normalizer`), exact sub-second timestamp boundary decoding (ms < 2025 <= us), and D+2 knowledge cutoff anti-leakage eligibility.
- Built and validated synthetic fixtures (stable, trend, reversal, volatile, missing-day, structural-break) and verified schema roundtrip against real v1 contracts.
- Next authorized micro-gate: `DS-02C1` (Acquisition Evidence Contract).
  Retrieval is decomposed into `DS-02C1` evidence, `DS-02C2` bounded offline
  replay, and `DS-02C3` optional provider fetching. Later gates remain
  `DS-02D` (Market Valuation & Transition Rules) and `DS-02E` (Baseline Episodes).

Detailed plan: [Market dataset and baseline evidence](roadmaps/market-dataset-and-baseline-evidence.md).

**Micro-gate DS-D0 (Satisfied after review correction):** dataset decision,
licence-handling boundary, retrieval method, and provenance contract are frozen
and reviewable without production code. Raw archive redistribution is not asserted.
**Micro-gate DS-D1 (Satisfied after review correction):** synthetic raw records normalize deterministically into
episode-ready existing v1 observations and manifests; production eligibility,
schema, canonicalization, and hashing code prove determinism and the conservative anti-leakage boundary.
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
