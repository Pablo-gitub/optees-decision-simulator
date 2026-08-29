# Market Dataset And Baseline Evidence Plan

## Work Unit

- **ID:** `DS-02`
- **State:** `DS-02A`, `DS-02B`, and `DS-02C1` completed (Gates `DS-D0`, `DS-D1`, and `DS-D2A` satisfied); awaiting review before `DS-02C2`
- **Type:** backend data provenance, market interpretation and baseline evidence; no UI
- **Parent roadmap:** `../ROADMAP.md`
- **Prerequisite:** `DS-K` satisfied by `DS-01`
- **Parallel Optees work:** `OPT-DS-03A` robust-scenario contract decision
- **Implementation owner:** Gemini
- **Review:** Codex after every micro-gate
- **Completion gate:** `DS-D` (Current micro-gates: `DS-D0`, `DS-D1`, and `DS-D2A` Satisfied)

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
- exploratory, calibration, retrospective holdout/stress, and prospective-period rules;
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

**Gate `DS-D0` (Satisfied after review correction):** the source and provenance
contract are reviewable without production code. Primary evidence was checked
during review; raw archive redistribution is deliberately outside the contract.

### Gate `DS-D0` Evidence Delivered:
- **Candidate Comparison:** Evaluated Binance Public Data Archive, Yahoo Finance, Commercial REST Free Tiers (Alpha Vantage / Polygon.io), and Coinbase REST in [`docs/contracts/market-dataset-provenance.md`](../contracts/market-dataset-provenance.md).
- **Selection & Legal Provenance:** Selected Binance Public Data archive (`data.binance.vision`) for 1d spot klines; froze credential-free retrieval and attribution while explicitly declining to assert raw-data redistribution rights.
- **Temporal Alignment:** Preserved exact upstream close precision and assigned conservative historical knowledge time at `(D+2)T00:00:00Z`, because upstream promises only availability “the next day”.
- **Three-Tier Checksums & Partitions:** Established three-tier SHA-256 boundaries, immutable acquisition revisions, retrospective P0–P3 labels, and the rule for a separately precommitted prospective interval.
- **Threat Model & Benchmark Protocol:** Updated [`docs/contracts/threat-model.md`](../contracts/threat-model.md) with Threat Vectors 13–15 and [`docs/BENCHMARK_PROTOCOL.md`](../BENCHMARK_PROTOCOL.md) with frozen market dataset rules.
- **Canonical Manifest Example:** Created [`docs/contracts/examples/valid/market_dataset_manifest.v1.json`](../contracts/examples/valid/market_dataset_manifest.v1.json) validated against `dataset_snapshot.v1.json`.

Only after review may `DS-02B` begin.

## Micro-gate B — Synthetic Market Semantics (`DS-02B`)

Implement only deterministic normalization and semantic rules against small,
repository-owned synthetic Binance-shaped records. This gate establishes the
pure seam used by the later network adapter; it must not retrieve, cache, or
redistribute provider data.

### Required pre-implementation comparison

Before editing, record in the implementation report how the design reuses:

- `domain.models.ObservationRecord` and `DatasetSnapshotManifest`;
- `application.services.EligibilityService`;
- `application.ports.DatasetPort` and the existing `SyntheticDatasetAdapter`;
- canonical JSON, decimal, UTC, identity, and hashing helpers already shipped;
- `docs/contracts/market-dataset-provenance.md` and the v1 JSON Schemas.

Do not add a second observation, timestamp, canonicalization, or hashing model.

### Authorized implementation

- Add a pure market normalization component in `infrastructure`, behind a
  narrow input DTO representing one already-decoded 12-field kline row. It may
  depend inward on domain/application contracts but performs no I/O.
- Decode Unix milliseconds before 2025-01-01 and Unix microseconds from that
  date onward without truncating the upstream close instant. Reject ambiguous,
  inconsistent, non-integral, negative, or out-of-range timestamp values.
- Preserve price and volume text as canonical decimal strings. Require positive
  OHLC prices; allow non-negative base/quote/taker volumes and trade counts;
  reject booleans, exponent notation if outside the frozen decimal grammar,
  NaN, infinity, negative volume, malformed rows, and `high/low` contradictions.
- Map only the four frozen symbols and interval `1d` to the reviewed resource
  and series IDs. Reject unknown symbols/intervals rather than guessing.
- Assign `event_time` from exact upstream `close_time` and conservative
  historical `knowledge_time = (D+2)T00:00:00Z`. Never use retrieval time as a
  substitute for either field.
- Accept an explicit acquisition revision and snapshot ID supplied by the
  caller. Upstream replacements become new immutable revisions; the normalizer
  does not overwrite or deduplicate them.
- Normalize batches in deterministic `(series_id, event_time, revision)` order,
  reject duplicate identities, and build the existing manifest with the
  existing canonical hash helpers. Hash only normalized output at this gate;
  raw and manifest acquisition hashes remain `DS-02C` responsibilities.

### Required synthetic fixtures and tests

- Stable, trend, reversal, volatile, missing-day, and structural-break series.
- Boundary rows immediately before and from 2025-01-01 proving millisecond and
  microsecond decoding and retained sub-second precision.
- Exact D+2 knowledge cutoff tests through the production
  `EligibilityService`: D+1 is ineligible and D+2 is eligible.
- Zero-volume valid rows and invalid zero/negative prices.
- Missing day preserved as absence, with no forward fill.
- Two acquisitions of the same event produce ordered immutable revisions and
  distinct normalized hashes when content changes.
- Input permutation produces identical normalized ordering and snapshot hash;
  repeated execution is byte-for-byte deterministic.
- Schema round-trip of produced observations and manifest against the actual
  authoritative v1 schemas, not copies embedded in tests.
- Existing 45-test kernel suite, architecture-boundary test, Ruff, and format
  checks remain green.

### Explicit exclusions

- no HTTP client, network access, provider SDK, ZIP/CSV filesystem reader,
  cache directory, real archive, API key, or raw dataset committed;
- no acquisition receipt/sidecar, publisher checksum verification, or offline
  cache adapter (`DS-02C`);
- no valuation, execution price, fees, slippage, policy, baseline episode,
  database, API, Optees integration, or UI work;
- no claim that a synthetic test proves upstream availability, licence rights,
  or archive immutability.

### Stop conditions

Stop without inventing a parallel contract if the existing observation or
manifest schema cannot preserve exact event time, revision, decimal payload,
or the required normalized hash. Stop if fulfilling the gate would require a
network call, a real provider artifact, or changes to the frozen valuation and
execution-price boundary.

**Gate `DS-D1` (Satisfied after review correction):** synthetic raw records normalize deterministically into
episode-ready existing v1 observations and manifests; production eligibility,
schema, canonicalization, and hashing code—not duplicated test logic—prove
determinism and the conservative anti-leakage boundary.

### Gate `DS-D1` Evidence Delivered:
- **Pure Normalizer:** Implemented `simulator.infrastructure.adapters.market_normalizer` accepting a narrow string-preserving 12-field DTO `RawKlineRecord` with zero I/O and zero network access.
- **Timestamp Boundary & Precision:** Validated milliseconds (< 2025-01-01) and microseconds (>= 2025-01-01) decoding, preserving sub-second precision (`.999Z` and `.999999Z`) without truncation.
- **Conservative Anti-Leakage Eligibility:** Verified exact D+2 knowledge cutoff with production `EligibilityService`: bar closing on day $D$ is ineligible at cutoff $D+1$ and eligible at cutoff $D+2$.
- **Values & Invariant Validation:** Verified positive OHLC prices, non-negative volumes and trade counts, rejection of booleans, NaNs, infinities, and high/low contradictions.
- **Ordering, Uniqueness & Checksums:** Enforced deterministic batch sort `(series_id, event_time, revision)`, duplicate identity rejection, revision ordering, and pure SHA-256 snapshot hash generation over canonical RFC 8785 JSONL stream.
- **Schema Roundtrip:** Verified roundtrip validation of generated observations and manifest against real `docs/contracts/schemas/` v1 JSON schemas.
- **Synthetic Fixtures & Test Coverage:** Shipped 6 synthetic fixture families (stable, trend, reversal, volatile, missing-day, structural-break) and 18 focused tests (63 total backend tests passing).

The review corrections are complete. Only `DS-02C1` may begin next.

## Micro-gate C — Retrieval And Immutable Snapshot Adapter (`DS-02C`)

This stage is split into three separately reviewed units. A real network call
is never evidence for the deterministic gate and must not be combined with the
first two units.

### Micro-gate C1 — Acquisition Evidence Contract (`DS-02C1`)

Freeze and implement only the provider-neutral acquisition receipt and pure
hash-verification rules needed to connect raw bytes, normalized observations,
and the existing manifest. No filesystem or network I/O is authorized.

Before editing, compare and report `DatasetSnapshotManifest`, its authoritative
schema/example, canonical JSON/hash helpers, `DatasetPort`, and the reviewed
market provenance contract. Do not add raw or manifest hashes to
`dataset_snapshot.v1.json` and do not create a second manifest type.

Add one versioned acquisition-receipt schema, inventory entry, immutable Python
record, valid example, and invalid contract fixtures. Its responsibilities are:

- acquisition identity and referenced `snapshot_id`;
- exact provider archive URI/name and publisher checksum URI;
- actual UTC retrieval time supplied by the caller, never a default/current
  time read inside pure code;
- publisher-declared SHA-256, locally computed raw archive SHA-256, and raw byte size;
- normalizer identity/version and normalized snapshot SHA-256, equal to the
  existing manifest `checksum_sha256`;
- canonical hash of the existing manifest, computed with the shipped helper;
- explicit accepted/rejected verification outcome and bounded machine-readable reasons;
- licence text no stronger than the reviewed provenance contract;
- no local path, credential, response header, token, cookie, or raw content.

Pure verification accepts bytes and typed metadata from its caller, parses one
strict publisher checksum line, requires lowercase 64-hex SHA-256 values with
the repository `sha256:` prefix internally, uses constant-time digest
comparison, binds receipt/manifest snapshot IDs, and fails on mismatched raw,
normalized, or manifest hashes. Identical explicit inputs produce identical
records and hashes.

Tests load the real schemas and cover valid evidence, malformed checksum text,
wrong filename, uppercase/short/non-hex digest, raw mutation, normalized and
manifest mismatch, snapshot mismatch, ambiguous/non-UTC retrieval time,
incorrect byte size, secret/path rejection, deterministic repetition, and
schema round-trip.

Explicit exclusions: no HTTP, DNS, provider SDK, ZIP/CSV parsing,
filesystem/cache, atomic writes, extraction, real Binance bytes, `DatasetPort`
implementation, valuation, API, database, Optees, or UI.

Stop if the receipt cannot reference the existing manifest without changing
its schema, canonical manifest hashing is ambiguous, or a fact cannot be
established from caller-supplied evidence.

**Gate `DS-D2A` (Satisfied after review correction):** production canonicalization plus pure byte/hash probes bind
one raw artifact to one existing normalized manifest without I/O or unsupported
legal claims.

### Gate `DS-D2A` Evidence Delivered:
- **JSON Schema & Inventory:** Added `docs/contracts/schemas/acquisition_receipt.v1.json` and registered `acquisition_receipt` (1.0.0) in `docs/contracts/schemas/schema_inventory.json`.
- **Domain Model:** Added immutable `AcquisitionReceipt` dataclass to `simulator.domain.models` with RFC 8785 canonical hash helper and validation.
- **Pure Verification Service:** Implemented `simulator.application.services.acquisition` providing `parse_publisher_checksum_line` and `verify_acquisition_evidence`.
- **Hash & Evidence Linkage:** Constant-time comparison binds raw bytes SHA-256, publisher SHA-256, normalized snapshot SHA-256 (manifest `checksum_sha256`), and canonical manifest SHA-256 (`manifest.compute_hash()`).
- **Safety & Secret Isolation:** Rejection of local filesystem absolute paths and secret/token patterns.
- **Valid Contract Example:** Added `docs/contracts/examples/valid/acquisition_receipt.v1.json` validated by `tools/validate_contracts.py`.
- **Unit & Contract Tests:** Added 19 tests in `apps/backend/tests/unit/application/test_acquisition_receipt.py` (83 total backend tests passing).
- **Review correction:** rejected evidence now retains the caller's invalid facts instead of
  fabricating a valid timestamp, digest, or byte size; the publisher checksum grammar is frozen to
  one exact form and receipt/manifest snapshot mismatch has explicit regression coverage.
- **Integrity review:** acceptance now computes the normalized snapshot digest from explicit
  caller-supplied bytes, binds licence text to the reviewed manifest, and accepts only credential-free
  HTTPS artifact/checksum URIs with matching basenames.

Completion checklist:

- [x] Versioned receipt schema, inventory entry, Python record, and valid example.
- [x] Strict lowercase publisher checksum grammar and filename binding.
- [x] Raw archive digest and byte-size verification.
- [x] Caller-supplied normalized bytes and manifest digest binding.
- [x] Canonical manifest hashing and explicit snapshot identity binding.
- [x] Honest accepted/rejected shapes with bounded machine-readable reasons.
- [x] Manifest-owned licence and safe provider metadata.
- [x] Nineteen focused acquisition tests and complete backend regression gate.
- [ ] `DS-02C2A` pure bounded ZIP/CSV decoder.

Only after review may `DS-02C2A` begin.

### Micro-gate C2 — Bounded Offline Snapshot Adapter (`DS-02C2`)

This stage is split into three separately reviewed implementation units. Do not
combine them. The accepted `AcquisitionReceipt`, exact raw and normalized byte
hashes, current market normalizer, `DatasetPort`, immutable persistence rules,
and threat model are sources of truth.

#### Micro-gate C2A — Pure Bounded Archive Decoder (`DS-02C2A`)

Implement only a pure infrastructure decoder that receives caller-supplied ZIP
bytes plus the reviewed accepted `AcquisitionReceipt`. It performs no network
or filesystem I/O. Before decoding, recompute raw size and SHA-256 and require
exact equality with the receipt; rejected receipts are never decodable.

Freeze explicit conservative limits for raw archive bytes, member count,
compressed and uncompressed member bytes, compression ratio, CSV row count,
column count, and cell length. The v1 synthetic Binance-kline shape contains
exactly one regular CSV member whose basename matches the archive basename
without `.zip`, exactly twelve headerless columns per non-empty row, UTF-8 text,
and no NUL bytes. Return one immutable typed decoded package with deterministic
row and member ordering; do not create `ObservationRecord` or a second manifest.

Reject before publishing decoded rows:

- malformed/truncated/non-ZIP input or raw hash/size mismatch;
- empty archives, directories, multiple or duplicate members;
- absolute, nested, traversal, backslash, drive-prefixed, or mismatched names;
- symlink/special entries, encrypted members, unsupported compression methods,
  suspicious declared sizes, or exceeded byte/ratio limits;
- invalid UTF-8, NUL content, blank-only payloads, unexpected columns, excessive
  rows/cells, or parser errors.

Tests build miniature archives entirely in memory and cover one valid package,
deterministic repetition, raw mutation, rejected receipt, wrong member name,
duplicate/nested/traversal/absolute/backslash members, directory/symlink/
encrypted entries, truncation, compression-ratio and every explicit size/count
limit, invalid UTF-8/NUL, empty CSV, and eleven/thirteen-column rows. Tests must
assert stable bounded error codes and must not write temporary files.

Explicit exclusions: no filesystem/cache, temporary file, atomic write,
`DatasetPort`, market normalization, observation/manifest creation, HTTP,
provider SDK, FastAPI, database, Optees, frontend, or live Binance bytes.

Stop if Python ZIP metadata cannot establish a required safety fact before
decompression, if accepted receipt semantics must change, or if a proposed
limit contradicts the frozen dataset decision.

**Gate `DS-D2B1`:** synthetic accepted ZIP bytes decode deterministically under
strict resource and archive-shape limits without filesystem or network access.

#### Micro-gate C2B — Immutable Local Snapshot Store (`DS-02C2B`)

After `DS-D2B1` review, add bounded filesystem storage behind an
application-owned port. Use private roots, checksum-first staging, atomic
publication, immutable acquisition-version paths, verified reopen, bounded
retention and failure injection. Never expose absolute paths in domain records.

**Gate `DS-D2B2`:** interrupted or malicious writes publish nothing; accepted
content reopens with identical receipt and byte hashes and cannot be overwritten.

#### Micro-gate C2C — Offline Dataset Adapter (`DS-02C2C`)

After `DS-D2B2` review, connect the reviewed decoder, market normalizer and
store through an offline `DatasetPort` adapter. Reopen accepted acquisitions,
produce the existing observations and manifest, and prove exact hash parity
without introducing a second dataset contract.

**Gate `DS-D2B`:** a synthetic acquired snapshot reopens offline and reproduces
byte-for-byte observations, manifest, receipt, and hashes under failure injection.

### Micro-gate C3 — Optional Provider Fetcher (`DS-02C3`)

After `DS-D2B` review, add a bounded HTTPS fetcher behind an application-owned
acquisition port. Redirect, host, timeout, byte-count, content-type,
archive-name, and checksum policies are explicit. Deterministic tests use a
fake transport; a live-provider smoke is optional, marked, and never required
for offline CI or gate acceptance. Replacement creates a new immutable
acquisition and never overwrites accepted evidence.

**Gate `DS-D2C`:** fake-transport tests prove acquisition behavior; an optional
live smoke remains separate from frozen outputs.

**Gate `DS-D2`:** achieved only after `DS-D2A`, `DS-D2B`, and `DS-D2C` review.

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

## Next implementation boundary

`DS-02A/B` are complete after review. `DS-02C1` is the only next implementation
authorized here. C2–E remain later, separately reviewed work units.
