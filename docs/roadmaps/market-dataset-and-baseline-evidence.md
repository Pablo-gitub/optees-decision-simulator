# Market Dataset And Baseline Evidence Plan

## Work Unit

- **ID:** `DS-02`
- **State:** Gate `DS-D3B` satisfied; B1 and B2 implemented and reviewed; D2C detail next
- **Type:** backend data provenance, market interpretation and baseline evidence; no UI
- **Parent roadmap:** `../ROADMAP.md`
- **Prerequisite:** `DS-K` satisfied by `DS-01`
- **Parallel Optees work:** scenario capability and UI complete; forecasting awaits Simulator evidence
- **Implementation owner:** Gemini
- **Review:** Codex after every micro-gate
- **Completion gate:** `DS-D` (gates through `DS-D3A` satisfied; `DS-02D2B` in progress)

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
- [x] `DS-02C2A` pure bounded ZIP/CSV decoder.
- [x] `DS-02C2B` immutable offline snapshot pipeline (store plus `DatasetPort` adapter).

Only after review may `DS-02C3` begin.

### Micro-gate C2 — Bounded Offline Snapshot Adapter (`DS-02C2`)

This stage contains the reviewed pure decoder followed by one medium offline
pipeline gate. The accepted `AcquisitionReceipt`, exact raw and normalized byte
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

**Gate `DS-D2B1` (Satisfied after review correction):** synthetic accepted ZIP bytes decode deterministically under
strict resource and archive-shape limits without filesystem or network access.

### Gate `DS-D2B1` Evidence Delivered:
- **Pure Infrastructure Decoder:** Implemented `simulator.infrastructure.adapters.archive_decoder.decode_kline_archive` with zero filesystem and zero network access.
- **Pre-decompression Invariants & Defense-in-Depth:** Re-verifies accepted receipt status, zero active failure reasons, exact raw byte size, exact SHA-256 digest (`hmac.compare_digest`), member count (`MAX_MEMBER_COUNT=1`), compression method (`ZIP_STORED` / `ZIP_DEFLATED`), unencrypted status, non-directory, non-symlink/special, flat member filename matching expected `{archive_basename}.csv`.
- **Resource Limits:** `MAX_RAW_ARCHIVE_BYTES=10MB`, `MAX_COMPRESSED_MEMBER_BYTES=10MB`, `MAX_UNCOMPRESSED_MEMBER_BYTES=25MB`, `MAX_COMPRESSION_RATIO=50.0`, `MAX_CSV_ROW_COUNT=10,000`, `MAX_CELL_LENGTH=256`, `EXPECTED_CSV_COLUMN_COUNT=12`.
- **Streaming Decompression & Bomb Prevention:** Reads in 64 KB chunks, tracking total uncompressed bytes and compression ratio in real time before memory exhaustion.
- **Sanitization & CSV Strictness:** Strict UTF-8 validation, NUL byte detection, headerless 12-column parsing, cell length enforcement, integer timestamp validation.
- **Typed Immutable Output:** Returns `DecodedArchivePackage` containing `tuple[RawKlineRecord, ...]` without premature observation or manifest generation.
- **Unit Test Suite:** 25 unit tests in `apps/backend/tests/unit/infrastructure/test_archive_decoder.py` covering all positive, negative, and edge-case invariants with 108 total backend tests passing.
- **Integrity review:** strict CSV parsing converts malformed quoting and other parser failures into the bounded `CSV_PARSE_ERROR` contract instead of leaking `_csv.Error`.

#### Medium gate C2B — Immutable Offline Snapshot Pipeline (`DS-02C2B`)

Implement the storage boundary and its first consumer together, in the internal
order below, while keeping intermediate tests green and delivering one coherent
commit:

1. define the narrow application-owned snapshot-storage port and immutable
   receipt/raw/normalized package DTOs required by the offline use case;
2. implement bounded filesystem storage under a caller-supplied private root,
   with checksum-first staging, atomic publication, immutable acquisition-version
   identities, verified reopen, deterministic bounded retention, and injected
   failure seams;
3. implement the offline `DatasetPort` adapter that reopens one accepted
   acquisition, invokes the reviewed decoder and market normalizer, and returns
   the existing observations and manifest with exact receipt and hash parity.

Do not expose absolute paths in domain or application records. Validate every
derived path component before filesystem access; reject traversal, symlinks,
special files, identity/hash mismatch, overwrite attempts, partial packages,
and post-publication tampering. Staging failure, interrupted replacement, and
retention failure must never make a partial acquisition observable. Existing
accepted content is immutable; identical republishing is an explicit idempotent
success without file modification, while any conflicting republishing is stably
rejected with `OVERWRITE_FORBIDDEN`.

Required tests use temporary private roots and deterministic synthetic archives.
Cover successful publish/reopen, exact byte and canonical hash parity, repeated
reopen determinism, collision/overwrite behavior, malicious identities, symlink
and special-file substitution, corrupted receipt/raw/normalized content,
failure injection before and during atomic publication, cleanup of staging
artifacts, retention boundaries, and one end-to-end `DatasetPort` read that
reproduces the existing observations and manifest byte for byte. Use the real
decoder and normalizer only in the end-to-end adapter tests; focused store tests
must not couple storage to market semantics.

Explicit exclusions: no HTTP/provider fetcher, live Binance access, database,
FastAPI, CLI, Optees integration, frontend, new observation/manifest contract,
or mutable cache API.

Stop if safe publication cannot be expressed behind an application-owned port,
if the existing `DatasetPort` cannot preserve the frozen observation/manifest
contract, if retention could delete the package being opened, or if hash parity
requires changing an accepted receipt.

**Gate `DS-D2B` (Satisfied after review correction):** interrupted or malicious writes publish nothing, accepted
content cannot be overwritten, and a synthetic acquisition reopens offline to
reproduce byte-for-byte observations, manifest, receipt, and hashes.

### Gate `DS-D2B` Evidence Delivered:
- **Application Port & DTOs:** Defined `SnapshotStorePort` and `StoredAcquisitionPackage` in `simulator.application.ports.snapshot_store` with zero filesystem or path leaks.
- **Filesystem Store Adapter:** Implemented `FileSystemSnapshotStore` under a caller-supplied private root with component-safe containment, explicit raw/normalized byte limits, checksum-first staging, atomic rename, and verified reopen.
- **Identical Republish Decision:** Frozen as idempotent no-op on identical content, and stable `OVERWRITE_FORBIDDEN` rejection on conflicting hashes/content.
- **Failure Injection & Defense-in-Depth:** Verified failure seams (`SnapshotStoreFailureInjector`) before staging, after staging, and during atomic rename; confirmed complete staging cleanup and zero partial publication.
- **Offline Dataset Adapter:** Implemented `OfflineDatasetAdapter` fulfilling `DatasetPort`, producing exact byte-for-byte canonical `ObservationRecord` and `DatasetSnapshotManifest` items with strict cryptographic parity.
- **Integrity review:** immutable packages defensively copy mutable byte inputs, `exists` requires verified content, prefix-sibling symlink escapes are rejected, and pruning reports deletion failures honestly.
- **Verification Suite:** 16 focused store tests and 3 end-to-end adapter tests with 127/127 backend tests passing.

Only after review may `DS-02C3` begin.

### Medium gate C3 — Optional Provider Acquisition (`DS-02C3`)

After `DS-D2B` review, add the optional provider acquisition boundary from
bounded HTTPS retrieval through immutable publication. Keep transport,
verification/normalization orchestration, and storage as separate roles:

1. define an application-owned, provider-neutral acquisition transport port
   with immutable request/response DTOs and stable transport failure categories;
2. implement one concrete streaming HTTPS adapter for the frozen Binance archive
   host, with no ambient credentials and no filesystem ownership;
3. implement one application acquisition service that retrieves archive and
   checksum evidence, invokes the reviewed decoder, market normalizer,
   manifest builder, `verify_acquisition_evidence`, and `SnapshotStorePort`, and
   returns the accepted receipt plus immutable publication identity;
4. prove that a second upstream artifact creates a new acquisition and that no
   path can overwrite an already accepted package.

The HTTPS adapter must require `https`, an exact allowlisted hostname and port,
credential-free URLs, provider-approved path prefixes and basenames, and no
query or fragment. Redirects are disabled by default; if the selected client
surfaces a redirect, reject it rather than following it. Freeze separate archive
and checksum byte limits, connect/read/total timeouts, allowed content types,
status handling, chunk size, and bounded sanitized error metadata. Reject
missing or conflicting `Content-Length`, length overflow while streaming,
wrong archive/checksum basename, compression/content-type mismatch, truncated
responses, TLS/timeout/connection failures, and unexpected status codes. Never
include response bodies, credentials, local paths, or raw exception text in
domain/application records.

The application service must accept an explicit retrieval timestamp from an
injected clock or caller; wall-clock access does not belong in the transport.
It must build normalized bytes using the existing canonical observation
serialization, verify all receipt/manifest/hash bindings before publication,
store only `ACCEPTED` evidence, and return rejected evidence without publishing
anything. Re-fetching identical evidence follows the reviewed idempotent store
semantics: because acquisition identity is derived from snapshot identity and
raw digest, an already accepted identical artifact returns the first immutable
receipt rather than attempting to replace its retrieval timestamp. Changed
upstream bytes produce a distinct acquisition identity and never replace
history.

Required deterministic tests use a scripted fake transport and small in-memory
ZIP/checksum fixtures. Cover successful acquisition/publication/reopen,
identical retry, changed upstream artifact, rejected checksum, malformed ZIP,
normalization failure, store failure, exact call order and byte limits, timeout,
TLS/connection error, redirect, non-200 status, disallowed host/path/port,
credentials/query/fragment, wrong content type/name, declared and streamed size
overflow, truncation, secret/path redaction, and zero publication on every
failure. Focused concrete-adapter tests must use a fake HTTP engine or local
stub abstraction and must not access the public network.

Explicit exclusions: no scheduler or background refresh, retry/backoff,
provider SDK, credentials, live trading/broker endpoint, database, FastAPI,
CLI, Optees, frontend, UI, valuation, baseline episode, or automatic replacement
policy. A live `data.binance.vision` smoke is optional, separately marked,
manually enabled, and never gate evidence.

Stop if the chosen HTTP client cannot disable or expose redirects, cannot bound
streaming before buffering, or cannot sanitize failure metadata; if the frozen
provider contract conflicts with actual documented archive behavior; or if an
accepted receipt would need mutation after immutable publication.

**Gate `DS-D2C` (Satisfied after review correction):** fake-transport tests prove provider-neutral acquisition transport,
strict HTTPS URL validation, streaming size boundaries, redirect rejection, sanitized error categories,
and idempotent immutable publication without touching live networks. The integrity
review binds acquisition identity to snapshot plus raw digest, preserves unexpected
programming failures, applies distinct connect/read settings and an explicit total
deadline, and removes attacker-controlled metadata from transport messages.

**Gate `DS-D2` (Satisfied after review correction):** achieved across `DS-D2A` (evidence verification), `DS-D2B` (bounded archive
decoding and offline snapshot storage), and `DS-D2C` (optional streaming HTTPS provider acquisition).

## Micro-gate D — Market Valuation And Transition Rules (`DS-02D`)

Implement one deterministic market interpretation boundary around the existing
domain-neutral execution kernel. `ExecutionService` remains the sole owner of
decision feasibility, balance mutations, transaction costs, transition records
and account hashes; do not create a second portfolio/accounting engine.

### Frozen v1 market rules

- The market universe remains `BTC`, `ETH`, `SOL` and `BNB`, quoted in `USDT`.
  `USDT` is the reference resource and always has mark `1` in its own unit.
- A valuation mark at decision cutoff `T` is the latest eligible daily close
  for `{ASSET}USDT` with `event_time <= T` and `knowledge_time <= T`, after the
  production eligibility/revision rules have been applied. The selected mark
  carries its source observation identity, event time and an explicit
  non-negative staleness duration; it is never silently forward-filled into a
  synthetic observation.
- A paper transition decided at `T` executes at the first eligible daily bar
  whose event is strictly after `T`: use that bar's `open` as the unadjusted
  execution price and its exact event/knowledge identity as evidence. The
  transition cannot become effective before that observation is available to
  the simulation clock. Never execute at the already-known day-D close.
- Version 1 uses no invented market-impact model: slippage is explicitly zero.
  Transaction fees remain exactly the episode's existing linear plus fixed
  fee model and are applied once by `ExecutionService`; holding cost remains
  unchanged and outside this gate. A later non-zero slippage model requires a
  versioned contract change, not an implicit constant.
- Source prices and quantities are finite positive `Decimal` values. Monetary
  amounts and fees retain the kernel's existing two-decimal reference-unit
  quantization. Asset balance quantities retain the action quantity supplied
  by the frozen episode contract; this gate must not silently round them to two
  decimals. Any required exchange lot-size/tick-size model is deferred until
  provider evidence is frozen.
- A missing, malformed, non-positive or unavailable mark/execution price is a
  stable rejected-decision outcome with no transition and no balance mutation.
  Existing non-reference holdings also require a mark before the next account
  valuation. Delete every implicit `1.00` fallback for a non-reference
  resource; zero, stale or absent data must never fabricate value.

### Architecture and implementation boundary

Add immutable application-owned price/evidence value types and a narrow market
pricing port (or equivalent protocol). Implement the Binance-kline-specific
selection adapter in infrastructure using the already normalized observation
payload and production eligibility semantics. The application service passes
the resulting complete mark/execution-price set into the existing
`ExecutionService`; market series naming and OHLC payload knowledge must not
enter domain models or generic accounting logic.

Refactor `ExecutionService` only as needed to consume explicit validated prices
and preserve fractional asset quantities. Keep its public behavior for
non-market synthetic episodes available through an explicit deterministic
pricing implementation used by those episodes; do not retain the current
implicit lookup/default path. Do not change frozen record schemas unless a
reviewed incompatibility makes the evidence impossible to represent.

### Required evidence

Use synthetic observations only. Add hand-calculated cases for buy/allocation,
partial/full liquidation, fixed plus linear fees, fractional quantities,
multiple holdings and `USDT` conservation. Prove:

- latest eligible mark selection, revision handling and deterministic ties;
- strict future-open execution selection and absence of day-D close leakage;
- effective-time availability, source-evidence retention and staleness;
- stable rejection for missing/malformed/non-positive mark or execution price;
- no mutation on rejection, no shorting/borrowing regression and no duplicate
  application of costs;
- conservation identity: account value change equals market revaluation less
  recorded costs under the frozen zero-slippage model;
- identical inputs and input permutations produce identical valuations,
  transitions, account states and hashes;
- existing synthetic kernel episodes remain deterministic through their
  explicit pricing implementation.

Run focused market-pricing/execution tests, the complete backend suite,
contract validation, architecture boundaries, Ruff and formatting checks.

Explicit exclusions: network calls, real Binance archives, baseline policies or
episodes (`DS-02E`), persistence/API, Optees integration, broker semantics,
profitability claims, non-zero slippage calibration, lot/tick-size claims and UI.

Stop without guessing if normalized observations cannot distinguish the future
bar open from the valuation close, if availability cannot be represented
without lookahead, if the existing transition/account contracts cannot retain
the minimum source evidence needed for deterministic replay, or if preserving
fractional quantities requires a frozen schema change. Report the conflict and
do not fabricate prices, timestamps, precision or provenance.

**Gate `DS-D3` (Open after review):** identical normalized observations and account inputs produce
identical valuations, costs, transitions and hashes.

### `DS-D3` implementation evidence and remaining blocker
- **Application Pricing Port:** Implemented immutable `PriceEvidence`, `PriceResolutionResult`, and abstract `PricingPort` in `simulator.application.ports.pricing`.
- **Market Kline Pricing Adapter:** Implemented `MarketKlinePricingAdapter` in `simulator.infrastructure.adapters.market_pricing` resolving latest eligible daily close mark (`event_time <= T` and `knowledge_time <= T`) with explicit staleness duration, and paper execution price as the first strictly future daily bar open (`event_time > T` and `knowledge_time <= effective_time`).
- **Synthetic Pricing Adapter:** Implemented `SyntheticPricingAdapter` in `simulator.infrastructure.adapters.synthetic_pricing` providing domain-neutral, explicit pricing for non-market synthetic episodes and benchmarks.
- **ExecutionService Refactoring:** Preserved `ExecutionService` as the single owner of accounting, feasibility, balance mutations, transition records, and virtual account hashes; eliminated all implicit 1.00 fallbacks for non-reference resources; added stable deterministic rejections on missing/invalid marks and execution prices; preserved fractional asset quantities without arbitrary 2-decimal truncation while retaining 2-decimal reference cash/fee quantization; enforced zero-slippage single fee application and accounting conservation invariant.
- **Test Coverage & Verification:** focused adapter and accounting tests prove deterministic behavior when valid mark and future execution evidence are supplied explicitly.
- **Review blocker:** production `EpisodeRunner` fixes `effective_time` to the decision cutoff. The market adapter correctly requires the execution observation to have `event_time > cutoff` and `knowledge_time <= effective_time`; with the frozen D+2 historical availability rule those conditions cannot hold at the same cutoff. The isolated tests used a manually later effective time and therefore did not prove an executable market episode.
- **Required correction:** freeze a versioned pending/delayed-transition lifecycle, including account visibility between decision and settlement, feasibility reservation, failure handling, round/effective-time records, replay and hashing. Do not weaken the future-open or D+2 rules to make the synchronous kernel pass.

### Correction gate D1 — Deferred Settlement Contract (`DS-02D1`)

Before changing runtime code, freeze the smallest causal lifecycle that closes
the review blocker. This is a contract-and-decision gate: production Python,
schemas, normalizers and adapters must not be modified here.

The decision document must reconcile these facts explicitly:

1. a normalized daily observation currently uses the upstream close timestamp
   as `event_time`, while its payload contains an `open` price but not the
   upstream `open_time`;
2. a policy at cutoff `T` may use only observations with
   `knowledge_time <= T`;
3. an execution fill must occur after the decision and cannot reuse the known
   close;
4. under conservative historical D+2 availability, the complete future bar is
   processed later than its market open;
5. the synchronous kernel currently proposes, accepts and mutates the account
   at one cutoff and has no pending state.

Freeze, with state diagrams and one canonical timeline, all of the following:

- whether `open_time` must be retained in the normalized observation payload,
  how its millisecond/microsecond precision is preserved, and which normalizer
  or fixture version changes;
- the distinction among decision cutoff, proposal creation, economic fill
  time, observation knowledge/processing time and account settlement time;
- a closed pending-transition lifecycle and stable identifiers/statuses;
- whether initial acceptance means syntactic admission rather than financial
  feasibility, and exactly when price-dependent cash, short-position, fee and
  quantity checks occur;
- the rule for account visibility while a transition is pending. The v1
  default should permit at most one pending non-HOLD decision per policy and
  must not allow a later policy decision to spend unsettled proceeds or bypass
  an unknown execution price;
- missing future bar, delayed publication, invalid open, insufficient funds at
  fill, cancellation, end-of-episode and dataset-exhaustion behavior;
- ordering when settlement and a later decision share a timestamp;
- immutable records, parent hashes, round Merkle coverage and deterministic
  replay/re-execution behavior;
- whether existing v1 records can represent the lifecycle losslessly or which
  minimally versioned schema additions are required. Never overload
  `DecisionStatus.ACCEPTED` or backdate a stored mutation with undocumented
  semantics.

The default candidate to assess is deferred paper settlement: admit the
proposal at `T`, select the first bar whose retained `open_time` is at or after
`T`, process the fill only when that observation is available, and prohibit the
next decision for that policy until settlement or terminal rejection. The
document must either adopt this model with a proof of causality or reject it
with a more conservative alternative. It must compare and explicitly reject
same-cutoff execution, execution at the already-known close, and any rule that
lets a policy observe the future price.

Required evidence is documentation plus pure decision probes only: normal day,
missing day, D+2 availability, revision, insufficient cash after price change,
pending decision at episode end, and deterministic replay ordering. Probes may
demonstrate current incompatibility but must not implement the future engine.

Update `core-contracts.md`, `market-dataset-provenance.md`, `threat-model.md`,
`ARCHITECTURE.md`, this detailed roadmap and the general roadmap wherever the
decision changes their planned semantics. Planned records and schema versions
must remain clearly marked planned.

**Gate `DS-D3T` (Satisfied):** one reviewed temporal contract proves that no policy input,
execution price or account mutation crosses its authorized time boundary and
defines a lossless implementation path.

### Gate `DS-D3T` Evidence Delivered:
- **Authoritative Contract Specification:** Shipped [`docs/contracts/deferred-settlement-contract.md`](../contracts/deferred-settlement-contract.md), freezing the five-time temporal model ($T_{\text{cutoff}} = t_{\text{prop}} \le t_{\text{fill}} < t_{\text{knowledge}} \le t_{\text{settle}}$), sub-second `open_time` retention in observation payload, the closed pending transition state machine (`ADMITTED_PENDING`, `SETTLED`, `REJECTED`), single-pending policy invariant, and feasibility verification timing.
- **Pure Decision Probes Suite:** Added `apps/backend/tests/unit/domain/test_deferred_settlement_contract.py` containing declarative decision probes, without a test-local implementation of the future kernel, verifying:
  1. Standard D+2 lifecycle and causal inequality ($T_{\text{cutoff}} \le t_{\text{fill}} < t_{\text{knowledge}} \le t_{\text{settle}}$);
  2. Missing day timeout and terminal rejection without account mutation;
  3. Pre-settlement revision handling vs post-settlement historical immutability;
  4. Fill price movement causing insufficient cash and terminal rejection;
  5. Unsettled order at episode termination;
  6. Episode cancellation as terminal `REJECTED` with `EPISODE_CANCELLED`;
  7. Deterministic ordering: settlement strictly precedes policy proposals at shared timestamps;
  8. Cryptographic reproducibility and state Merkle root determinism;
  9. Rejection of second trading decision while an order is pending settlement.
- **Contract & Architecture Alignment:** Updated `core-contracts.md`, `market-dataset-provenance.md`, `threat-model.md`, `ARCHITECTURE.md`, and `ROADMAP.md` with explicit distinction of planned v1.1 structures.
- **Review correction:** selected dedicated immutable `pending_transition.v1` and
  `settlement_outcome.v1` records as the one lossless implementation path; removed the
  premature test-local settlement engine and reconciled cancellation with the closed
  `SETTLED`/`REJECTED` terminal state set.

### Correction gate D2 — Deferred Settlement Kernel (`DS-02D2`)

This correction is divided into three independently reviewed units. Do not
combine them: the record boundary must be executable before account behavior is
added, and account behavior must be verified before the episode runner and
replay orchestration change.

#### D2A — Runtime Records And Open-Time Evidence (`DS-02D2A`)

Review correction completion:

Verification: 225 backend tests passed, including architecture and legacy
fixture checks; contract validation and Ruff lint/format gates passed.

- [x] Schema-only negative tests enforce terminal settlement conditions;
  the dependency-free validator checks `allOf`/`if`/`then`/`else` and rejects
  unknown vocabulary even in unvisited branches (not a full JSON Schema engine).
- [x] Signed `TRANSFER` quantities round-trip in domain and schema; other
  action kinds continue rejecting negative quantities.
- [x] Open-time receipts use normalizer `1.1.0`; mismatched legacy versions
  require a new snapshot and cannot be silently reused or overwritten.

No admission, settlement, runner or replay service was added. The next work
unit remains refinement of `DS-02D2B`.

Implement only the immutable record/schema foundation selected by `DS-D3T` and
preserve exact upstream `open_time` in newly normalized market observations.
There is no pending-settlement service or runner behavior in this unit.

Before editing, compare the frozen deferred-settlement contract with the actual
v1 proposed-decision, decision-outcome, transition, round, observation and
account schemas/models; the schema inventory and canonical examples; market
normalizer timestamp decoding; canonical hashing and immutable JSON helpers.
Record how identity, enum, decimal, UTC and deep-immutability conventions are
reused. Do not create alternate primitives.

Authorized implementation:

- Add authoritative `pending_transition.v1.json` and
  `settlement_outcome.v1.json`, inventory entries, immutable domain records and
  canonical valid examples matching the exact selected design in
  `deferred-settlement-contract.md`.
- Freeze stable ID prefixes and explicit links among proposal/decision, policy,
  predecessor account, pending admission, terminal settlement outcome and
  optional applied transition. Enforce `SETTLED` requires exactly one transition
  identity and no rejection reasons; `REJECTED` forbids a transition and requires
  at least one bounded machine-readable reason.
- Validate finite non-negative quantities where permitted, exact uppercase UTC
  timestamps, causal timestamp order, supported terminal statuses, immutable
  evidence mappings and collision-free record identities. Constructors must
  reject invalid states rather than normalize or repair them.
- Extend only new normalizer output to retain exact ISO-8601 UTC
  `payload["open_time"]` decoded from the already supplied upstream timestamp,
  preserving millisecond/microsecond precision. Existing v1 fixtures and hashes
  remain immutable; update/add explicitly versioned market fixtures rather than
  rewriting historical evidence.
- Provide codecs/serialization only where the existing domain contract pattern
  requires them for lossless schema round-trip. No transport registration is
  needed yet.

Required evidence:

- real-schema round-trip for both records and every valid example;
- invalid fixtures/tests for missing or mismatched links, illegal status,
  transition/rejection exclusivity, ambiguous/non-UTC or causally invalid times,
  booleans/non-finite quantities, mutable nested input and unknown fields;
- canonical hash determinism, input-permutation invariance where mappings are
  unordered, semantic-mutation sensitivity and deep immutability;
- exact `open_time` boundary tests before and from 2025, input permutation,
  schema round-trip and proof that close `event_time` semantics are unchanged;
- regression proof that legacy v1 fixture bytes/hashes do not change;
- complete contract validation, focused normalizer/domain tests, architecture,
  Ruff and formatting gates, followed by the backend suite.

Explicit exclusions: no admission queue, pending repository, settlement service,
account reservation/mutation, fee calculation, runner/replay changes, API,
database, Optees integration, baseline policy, real dataset/network access or UI.
Do not extend `decision_outcome.v1` or silently replace the dedicated two-record
design. Stop if lossless round coverage requires a third record or a change to a
frozen v1 schema and report the exact incompatibility.

**Gate `DS-D3A` (Reopened after integration-boundary review):** both new records (`pending_transition.v1` and
`settlement_outcome.v1`) are schema-valid, immutable and canonically hashable;
normalized observations retain exact open-time evidence
without changing legacy artifacts. All contract validations, schema roundtrip,
Ruff lint/formatting, and domain unit tests pass.
The independent review correction reduced each record to one stable ID prefix,
enforced the fixed target-bar rule and exact admission cutoff, rejected schema
version and nested-field drift, bounded rejection details, and made complete
observation/revision/fill/knowledge/price evidence mandatory for `SETTLED`.

Integration-boundary review found that `transition.v1` requires an `outcome_id`
with the `dec-out_` identity family. It therefore cannot point back to the new
terminal `settlement_outcome` (`set-out_`) without fabricating a second terminal
outcome, misusing an identity family, or rewriting the frozen v1 schema. The
one-way `settlement_outcome.applied_transition_id` reference is insufficient for
the audit and replay invariant.

##### D2A2 — Deferred Transition Version Bridge (`DS-02D2A2`)

Before application services, add the smallest versioned transition contract for
deferred settlement. Compare `TransitionRecord`, `transition.v1.json`, account
hashing, cost/delta records, settlement outcome, schema inventory/examples and
all persistence/replay consumers. Freeze the compatibility rule in the deferred
settlement contract before production edits.

Authorized implementation:

- keep `transition.v1.json`, its examples, hashes and synchronous runtime behavior
  byte-for-byte unchanged;
- add `transition.v2.json` and an immutable domain representation preserving every
  v1 accounting field but replacing the v1 decision-outcome link with required
  `settlement_outcome_id` (`set-out_`) and adding `economic_fill_time` distinct
  from settlement/effective time;
- require exact links to round, policy, before/after account hashes and settlement
  outcome; enforce `economic_fill_time <= effective_time` and one stable v2 ID family;
- choose one non-ambiguous Python representation: a dedicated deferred-transition
  type or a rigorously versioned existing type. Never permit hybrid v1/v2 fields;
- register the schema, add canonical examples and strict round-trip, hash and
  deep-immutability tests; prove v1 fixtures and behavior remain unchanged.

Explicit exclusions: no admission/settlement service, no `ExecutionService`
refactor or invocation, no account calculation, runner, persistence adapter,
replay, API, database, baseline, Optees integration or UI. Stop if v2 cannot
retain v1 accounting semantics exactly or requires changing a frozen v1 record.

**Gate `DS-D3A` (Satisfied after transition bridge):** pending admission (`pending_transition.v1`),
terminal settlement (`settlement_outcome.v1`) and applied deferred transition (`transition.v2`)
form an unambiguous, bidirectionally linked, immutable and canonically hashable record chain.
All v1 schemas, examples and hashes remain unchanged.

#### D2B — Admission And Settlement Application Services (`DS-02D2B`)

After the corrected `DS-D3A` review, implement pure application-owned admission and settlement
services over injected pricing/accounting dependencies. Verify the single-pending
rule, zero mutation before settlement, terminal rejection paths and exactly-once
accounting. Do not modify runner or replay in this unit.

- [x] `DS-02D2B1` planning: [admission service specification](deferred-admission-services.md).
- [x] `DS-02D2B1` implementation and review complete after retry corrections (270 backend tests passed).
- [x] `DS-02D2B2` planning: [settlement service specification](deferred-settlement-services.md).
- [x] `DS-02D2B2` implementation and independent review complete after correction.

B1 is a complete admission behavior block, not settlement or durable exactly-once
publication. B1 and B2 are reviewed. The corrected B2 contract requires a frozen
expected opening from the caller: missing bars cannot cause a later-bar fill.
Episode identity, Decimal isolation, rejection fee evidence and revaluation
anchors are regression-tested. Gate `DS-D3B` is satisfied for pure services only.

**Gate `DS-D3B`:** deterministic services reproduce the frozen lifecycle and
account invariants without episode orchestration.

#### D2C — Runner, Round Hashing And Replay Integration (`DS-02D2C`)

- [x] C0 record-bridge plan frozen: [deferred round v2](deferred-round-records.md).
- [x] C0 record-bridge implemented and reviewed: [deferred round v2](deferred-round-records.md); 339 backend tests pass after identity, schema and execution-time corrections.
- [x] C1 corrected plan independently reviewed: [runner orchestration and atomic persistence](deferred-runner-orchestration.md) and [terminal record contract](../contracts/deferred-run-terminal-contract.md).
- [ ] C1 implementation and review (next executable block).
- [ ] C2 detail and implementation: replay and end-to-end evidence.

The v1 round requires an immediate outcome and cannot encode settlement of an
old pending followed by a new admission. C0 is therefore a required record
prerequisite, not authorization to change runner/replay in the same commit.

After `DS-D3B` review, integrate settlement-before-proposal ordering into the
production runner, persistence boundary and both replay modes. Add normalized
synthetic D+2 episodes covering settlement and every terminal rejection. Its
executable detail will be refined after D2B review.

**Gate `DS-D3`:** a normalized synthetic D+2 market episode admits, settles or
rejects each decision causally and reproduces identical records and hashes.

## Micro-gate E — Baseline Episodes And Frozen Evidence (`DS-02E`)

Run static, cash/reference, equal-allocation and simple reactive baselines on
the declared periods. Retain manifests, configuration, policy versions,
trajectory hashes, costs and metrics. Do not tune on private/forward periods
or add Optees-backed policies. Negative and neutral results remain valid.

**Gate `DS-D`:** the same frozen observations and valuation rules reproduce
the same baseline episode hashes. Only then may `DS-03` persistence/API work
or production Optees policies begin.

## Next implementation boundary

Transition-v2 review corrected permissive numeric decoding and missing direct
cost-type validation. Canonical evidence now matches the pending request's 1.5
asset units and predecessor hash. Cross-record regression coverage verifies the
settlement/transition links and expected cash delta. All 217 backend tests pass;
legacy v1 schema and example bytes are unchanged. This proves the record bridge,
not runtime settlement enforcement, which remains in D2B/D2C.

`DS-02D2A1`, `DS-02D2A2`, `DS-02D2B1`, and `DS-02D2B2` implementation are
complete and reviewed. The corrected
Gate `DS-D3B` is satisfied. `DS-02D2C0` implementation and review are complete.
The [DS-02D2C1 runner orchestration and persistence plan](deferred-runner-orchestration.md)
freezes reviewed schedule, valuation, terminal-record, persistence and evaluator
decisions. C1 implementation is the next authorized block. C2 still requires
detailed planning. `DS-02E` remains blocked until `DS-D3` is satisfied.
