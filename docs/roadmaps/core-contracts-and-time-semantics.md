# Core Contracts And Time Semantics Plan

## Work Unit

- **ID:** `DS-00`
- **State:** complete
- **Type:** schema, architecture, and threat-model foundation
- **Parent roadmap:** `../ROADMAP.md`
- **Parallel Optees work:** `OPT-DS-01` QP contract decision
- **Next gate:** `DS-C` (satisfied)
- **Delivered Contracts:** [`../contracts/core-contracts.md`](../contracts/core-contracts.md)
- **Threat Model:** [`../contracts/threat-model.md`](../contracts/threat-model.md)
- **Schemas:** [`../contracts/schemas/`](../contracts/schemas/)

## Objective

Freeze the version 1 Simulator core contracts and temporal invariants before
implementing FastAPI, SQLite, MCP, React, or a concrete market provider. The
outputs must be precise enough for the deterministic kernel to implement
without redefining time, identity, immutability, hashing, or policy isolation.

## Required Decisions

### Identity and versioning

Define stable identifiers and independent schema versions for:

- episode definition and episode run;
- policy definition and policy version;
- round;
- observation and dataset snapshot;
- proposed and accepted decision;
- transition and virtual account state;
- metric record;
- Optees call receipt;
- replay and divergence report.

State which records are immutable, which are derived, and which lifecycle
transitions are permitted. Starting an episode must freeze its dataset, rule
set, policy versions, initial accounts, decision calendar, and failure rules.

### Time semantics

Freeze:

- **event time:** when the represented event occurred;
- **knowledge time:** when a policy is permitted to observe it;
- **execution time:** when computation occurred;
- **effective time:** when an accepted decision changes account state.

Specify ordering, timezone normalization, precision, interval boundaries,
late/corrected observations, and ties. No observation may influence a decision
whose knowledge cutoff precedes that observation's knowledge time.

### Observation delivery

Define the canonical visible-observation set as a function of frozen dataset,
policy requirements, and round cutoff. Every competing policy must receive the
same eligible facts; policy-local derived state must not change raw visibility.

### Decision and transition boundary

Separate:

- policy proposal;
- schema validation;
- optional Optees formulation and validation;
- acceptance/rejection under frozen episode rules;
- effective account transition;
- later valuation and evaluation.

A transport success, solver success, or forecast availability must not by
itself mean that a decision was accepted.

### Canonical JSON and hashing

Define:

- supported JSON value types and rejection of non-finite numbers;
- key ordering, Unicode normalization, number representation, and timestamp
  normalization;
- whether hashes cover schema version and type discriminator;
- hash algorithm and textual encoding;
- parent/child hash relationships for rounds and final episode state;
- redacted versus hashed fields;
- behavior for large external dataset content referenced by manifest.

Do not invent a custom algorithm where an established canonical JSON standard
can meet the requirements; record the decision and compatibility implications.

### Replay semantics

Distinguish:

1. **record replay:** rebuild state from retained accepted events without
   calling policies or solvers;
2. **deterministic re-execution:** rerun compatible policy code and compare
   canonical records;
3. **numerical re-execution:** rerun Optees and compare normalized results and
   declared tolerances;
4. **incompatible replay:** required code, capability, contract, or dataset is
   unavailable.

Define divergence categories instead of rewriting prior history.

### Ports and dependency direction

Define application-owned ports for:

- deterministic clock;
- dataset snapshots and observation delivery;
- episode/policy/run persistence;
- Optees capability execution;
- canonical export and artifact/report coordination.

Domain contracts must import no FastAPI, SQLite ORM, MCP, React, provider SDK,
or Optees protocol class.

## Threat Model

Document assets, trust boundaries, attack/failure cases, mitigations, and
residual risks for:

- temporal leakage and incorrect knowledge cutoffs;
- cross-policy state contamination;
- mutable policy or rule definitions after start;
- malformed, oversized, duplicated, corrected, or out-of-order observations;
- hash ambiguity and canonicalization mismatch;
- path traversal and untrusted imported episode files;
- arbitrary code in imported policies or workflow definitions;
- Optees subprocess failure, timeout, late result, and restart ambiguity;
- REST token, environment, stderr, log, report, and browser-storage leakage;
- resource exhaustion through episodes, rounds, policies, payloads, or
  artifacts;
- report/Markdown injection and unsafe links;
- accidental real-world side effects or secret-bearing connectors.

## Required Repository Outputs

The implementing agent should:

- create a canonical core-contract document under `docs/contracts/`;
- create a versioned schema inventory and complete valid examples for the
  records listed above;
- create a dedicated threat-model document;
- record the selected package layout and dependency rules in
  `docs/ARCHITECTURE.md` without claiming that planned folders are implemented;
- update `docs/PRODUCT_SPEC.md`, `docs/BENCHMARK_PROTOCOL.md`, and
  `docs/OPTEES_INTEGRATION.md` only where the frozen decisions require it;
- add a local schema/example validation check if a dependency-free or clearly
  justified development-only approach is available;
- update this plan and `docs/ROADMAP.md` when gate `DS-C` is reached.

## Explicitly Out Of Scope

- virtual-account transition implementation;
- SQLite tables or migrations;
- FastAPI endpoints;
- MCP or REST clients;
- React application scaffolding;
- live data downloads or provider selection;
- concrete trading policies;
- QP, robust, MIQP, or Workflow Registry DTOs;
- importing Optees source models;
- arbitrary executable policy definitions.

## Required Examples

Provide at least:

- one valid two-policy, two-round synthetic episode definition;
- visible observations around an exact knowledge cutoff;
- one accepted and one rejected decision;
- one transition and resulting account state;
- one Optees call receipt with pinned contract versions and redacted transport
  details;
- one successful record replay;
- one numerical divergence report;
- invalid examples for future leakage, duplicate identity, mutable version,
  non-finite number, timezone ambiguity, and cross-policy account reference.

## Verification

- Validate every committed example against its schema or documented invariant.
- Prove the knowledge-cutoff examples by inspection and automated checks where
  introduced.
- Verify canonical serialization produces the same bytes and hash across key
  insertion orders.
- Verify a one-field semantic change changes the corresponding record hash.
- Verify secrets and raw environment values are absent from examples.
- Run all documentation-link and schema validation checks introduced by the
  work unit.
- Report any tooling or dependency check that cannot run.

## Stop Conditions

Stop and request a decision if:

- event and knowledge time cannot represent corrected or delayed observations;
- canonical number handling would make equivalent Python/JavaScript records
  hash differently;
- replay would require retaining secrets or unrestricted executable code;
- policy and episode identities cannot remain immutable after start;
- a proposed schema embeds market-specific semantics in the core;
- Optees protocol objects would leak into simulator-owned contracts;
- package/tooling choices materially expand beyond this contract work unit.

## Completion Gate `DS-C`

This work unit is complete only when every core record has one authoritative
version 1 definition, all four times are unambiguous, observation eligibility
and policy isolation are testable, canonicalization and hashing are
reproducible, replay modes and divergence categories are frozen, threats and
residual risks are documented, framework dependencies remain outside the
domain, examples validate, and the result is one reviewable atomic commit.
