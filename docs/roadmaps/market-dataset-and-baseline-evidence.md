# Market Dataset And Baseline Evidence Plan

## Work Unit

- **ID:** `DS-02`
- **State:** `DS-02A` completed (Gate `DS-D0` satisfied); awaiting review before `DS-02B`
- **Type:** backend data provenance, market interpretation and baseline evidence; no UI
- **Parent roadmap:** `../ROADMAP.md`
- **Prerequisite:** `DS-K` satisfied by `DS-01`
- **Parallel Optees work:** `OPT-DS-03A` robust-scenario contract decision
- **Implementation owner:** Gemini
- **Review:** Codex after every micro-gate
- **Completion gate:** `DS-D` (Current micro-gate: `DS-D0` Satisfied)

## Objective

Select and freeze the first reproducible daily market dataset, then extend the
deterministic kernel with market-specific normalization, valuation and honest
baseline evidence. The phase must establish data provenance and chronological
correctness before any Optees-backed QP or robust policy is introduced.

The Simulator remains paper-only. This work adds no credentials, broker API,
orders, real transactions, personalized advice or profitability claim.

## Execution Discipline

- Only one micro-gate may be assigned at a time.
- Each micro-gate ends with focused evidence and one atomic local commit.
- Codex reviews every gate before producing the next implementation prompt.
- Gemini must not implement later adapters or policies while completing an
  earlier decision gate.
- Dataset files may not be committed until license and redistribution status
  are explicitly accepted.
- Generated snapshots must never replace a documented upstream artifact.
- Material review corrections use a separate atomic commit.
- Claude is not an owner in `DS-02`; there is no stable UI surface yet.

## Architectural Boundary

- Core episode records and knowledge-time eligibility remain domain-neutral.
- Provider retrieval and raw formats belong to infrastructure adapters.
- Timestamp normalization, asset identity, calendar and correction policy are
  application/domain policies independent of HTTP clients.
- Market valuation and transition rules live outside the core kernel.
- Baseline policies are explicit versioned Simulator policies, never Optees
  capabilities or preinstalled workflows.
- Raw source, normalized snapshot and episode-ready observations retain
  separate hashes and provenance.

## Micro-gate A — Dataset Decision And Provenance Contract (`DS-02A`)

### Scope

Select the first dataset and freeze, without production retrieval code:

- candidate-source comparison and rejection rationale;
- authoritative publisher/provider and stable retrieval mechanism;
- license, attribution and redistribution constraints;
- asset universe and identity mapping;
- daily timestamp meaning, timezone and market/calendar convention;
- price/volume fields, units, quote currency and adjustment semantics;
- missing, duplicate, late, corrected and delisted observations;
- event time, knowledge time and retrieval time derivation;
- raw artifact, normalized snapshot and manifest hash boundaries;
- exploratory, calibration, private evaluation and forward-period rules;
- offline/cache behavior and source-unavailable failure semantics;
- secret-free operation and maximum download/resource bounds.

### Allowed changes

- this roadmap;
- dataset/provenance contract documentation;
- benchmark protocol, threat model or integration documentation where the
  decision changes their authoritative rules;
- schema drafts, canonical examples and focused validation tools/tests;
- roadmap status/navigation.

### Forbidden changes

- production provider clients or network calls;
- committing an unapproved dataset or large generated artifact;
- market adapters, valuation code or policies;
- SQLite, FastAPI, Optees integration or UI;
- selecting periods based on observed strategy performance.

### Required evidence

- comparison table covering at least three plausible sources;
- primary-source evidence for license and field semantics;
- one canonical manifest example with placeholder/non-production hashes;
- explicit time-line examples for normal, delayed and corrected observations;
- threat analysis for leakage, silent corrections and source disappearance;
- schema/example validation, documentation links and secret scan.

### Stop conditions

Stop if the license is ambiguous, reproducible historical retrieval is not
available, timestamp/adjustment semantics cannot be established, or the source
requires credentials for the intended public case-study path.

**Gate `DS-D0` (Satisfied):** the source and provenance contract are reviewable without
network access or production code.

### Gate `DS-D0` Evidence Delivered:
- **Candidate Comparison:** Evaluated Binance Public Data Archive, Yahoo Finance, Commercial REST Free Tiers (Alpha Vantage / Polygon.io), and Coinbase REST in [`docs/contracts/market-dataset-provenance.md`](../contracts/market-dataset-provenance.md).
- **Selection & Legal Provenance:** Selected Binance Public Historical Data Archive (`data.binance.vision`) for 1d spot klines; documented license, open retrieval protocol, zero-credential requirement, 24/7 continuous calendar, and reference quote asset `USDT`.
- **Temporal Alignment & Timelines:** Defined exact event time ($D\text{T23:59:59Z}$), knowledge time ($(D+1)\text{T00:00:00Z}$), retrieval time, and explicit sequence diagrams for normal, delayed, and corrected observations.
- **Three-Tier Checksums & Partitions:** Established three-tier SHA-256 boundaries and frozen chronological partitions (Exploratory P0, Calibration P1, Private Evaluation P2, Forward Stress P3).
- **Threat Model & Benchmark Protocol:** Updated [`docs/contracts/threat-model.md`](../contracts/threat-model.md) with Threat Vectors 13–15 and [`docs/BENCHMARK_PROTOCOL.md`](../BENCHMARK_PROTOCOL.md) with frozen market dataset rules.
- **Canonical Manifest Example:** Created [`docs/contracts/examples/valid/market_dataset_manifest.v1.json`](../contracts/examples/valid/market_dataset_manifest.v1.json) validated against `dataset_snapshot.v1.json`.

Only after review may `DS-02B` begin.

## Micro-gate B — Synthetic Market Semantics (`DS-02B`)

Implement only pure normalization and semantic rules against small synthetic
fixtures: stable, trend, reversal, volatile, missing-day and structural-break
series. Prove UTC handling, knowledge cutoffs, revisions, deterministic order,
finite values, asset identity and calendar behavior. Do not access the chosen
provider.

**Gate `DS-D1`:** synthetic raw records normalize deterministically into
episode-ready observations with frozen hashes and anti-leakage tests.

## Micro-gate C — Retrieval And Immutable Snapshot Adapter (`DS-02C`)

Implement one bounded provider adapter behind the existing dataset port. It
must retain the raw artifact, retrieval metadata, checksum, parser version and
normalized manifest; support an explicit offline replay path; and reject
unexpected schema or upstream corrections rather than silently accepting
them. Network-dependent checks are separated from the deterministic gate.

**Gate `DS-D2`:** an approved raw snapshot can be acquired once and replayed
offline into the exact normalized hash.

## Micro-gate D — Market Valuation And Transition Rules (`DS-02D`)

Add market-specific valuation and paper-transition adapters outside the core.
Freeze valuation price, quantity precision, cash/quote asset, fees, slippage
assumptions, unavailable-price behavior and accounting invariants. Verify the
rules manually and with synthetic fixtures before using real observations.

**Gate `DS-D3`:** identical normalized observations and account inputs produce
identical valuations, costs, transitions and hashes.

## Micro-gate E — Baseline Episodes And Frozen Evidence (`DS-02E`)

Run static, cash/reference, equal-allocation and simple reactive baselines on
the declared periods. Retain manifests, configuration, policy versions,
trajectory hashes, costs and metrics. Do not tune on private/forward periods
or add Optees-backed policies. Negative and neutral results remain valid.

**Gate `DS-D`:** the same frozen observations and valuation rules reproduce
the same baseline episode hashes. Only then may `DS-03` persistence/API work
or production Optees policies begin.

## First Authorized Implementation

Only `DS-02A` is currently authorized. Sections B–E define later reviewed
work units and must not be implemented by the first agent prompt.
