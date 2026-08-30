# Market Dataset And Baseline Evidence Plan

## Work Unit

- **ID:** `DS-02`
- **State:** `DS-02A`, `DS-02B`, `DS-02C1`, `DS-02C2`, and `DS-02C3` completed (Gates `DS-D0`, `DS-D1`, `DS-D2A`, `DS-D2B`, `DS-D2C`, and `DS-D2` satisfied); `DS-02D` is next
- **Type:** backend data provenance, market interpretation and baseline evidence; no UI
- **Parent roadmap:** `../ROADMAP.md`
- **Prerequisite:** `DS-K` satisfied by `DS-01`
- **Parallel Optees work:** `OPT-DS-03A` robust-scenario contract decision
- **Implementation owner:** Gemini
- **Review:** Codex after every micro-gate
- **Completion gate:** `DS-D` (Current micro-gates: `DS-D0`, `DS-D1`, `DS-D2A`, `DS-D2B`, `DS-D2C`, and `DS-D2` Satisfied)

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

**Gate `DS-D2C` (Satisfied):** fake-transport tests prove provider-neutral acquisition transport,
strict HTTPS URL validation, streaming size boundaries, redirect rejection, sanitized error categories,
and idempotent immutable publication without touching live networks.

**Gate `DS-D2` (Satisfied):** achieved across `DS-D2A` (evidence verification), `DS-D2B` (bounded archive
decoding and offline snapshot storage), and `DS-D2C` (optional streaming HTTPS provider acquisition).

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

`DS-02A`, `DS-02B`, `DS-02C1`, `DS-02C2` (`DS-02C2A` & `DS-02C2B`), and `DS-02C3` are complete.
`DS-02D` (Market Valuation and Transition Rules / Gate `DS-D3`) is the next and only authorized
implementation boundary.
