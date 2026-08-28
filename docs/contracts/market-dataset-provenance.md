# Market Dataset Decision and Provenance Contract (v1)

## Document status

- **Work unit:** `DS-02A`
- **Gate:** `DS-D0`
- **State:** frozen after review correction
- **Selected source:** Binance Public Data archive (`data.binance.vision`), spot daily klines
- **Implementation status:** retrieval and normalization remain planned for `DS-02B` and `DS-02C`

This contract freezes the first case-study dataset decision without claiming
that the retrieval adapter, acquisition receipts, or market execution model
already exist. Core simulator records remain domain-neutral.

## 1. Decision and evidence boundary

Binance's public archive is selected because it supports credential-free,
file-addressable historical retrieval and publishes a `.CHECKSUM` companion for
each archive. The authoritative upstream descriptions are:

- <https://github.com/binance/binance-public-data> (accessed 2026-08-28);
- <https://data.binance.vision/> (accessed 2026-08-28).

The upstream README also states two constraints that are part of this contract:

- daily files are available **the next day**, but no exact publication instant is promised;
- archived files can be updated, and spot timestamps from 2025-01-01 onward are expressed in microseconds rather than milliseconds.

The GitHub repository is labelled MIT. That fact is not treated as an explicit
licence grant to redistribute the raw market archives. Consequently this
repository commits only contracts, manifests, and synthetic fixtures. A user or
CI acquisition job fetches upstream files directly. Reports attribute the data
to “Binance Public Data archive (`data.binance.vision`)”.

Other candidates remain non-primary because they add one or more unnecessary
constraints for this first reproducible case study: credentials, dynamic
paginated responses, lack of publisher checksums, equity-calendar complexity,
or unclear redistribution terms. This is an engineering selection, not a broad
legal conclusion about those services.

## 2. Frozen universe and denomination

The initial universe contains `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, and `BNBUSDT`
spot klines at interval `1d`. Resource IDs are `BTC`, `ETH`, `SOL`, `BNB`, and
`USDT`; series IDs are respectively `BTC_USDT_PRICE_1D`,
`ETH_USDT_PRICE_1D`, `SOL_USDT_PRICE_1D`, and `BNB_USDT_PRICE_1D`.

USDT is the quote and accounting unit. The simulator does **not** assert that
one USDT is always worth one US dollar. Any future conversion to USD requires a
separate observation series and valuation rule.

## 3. Upstream archive and raw fields

Daily files use these URL patterns:

```text
https://data.binance.vision/data/spot/daily/klines/{SYMBOL}/1d/{SYMBOL}-1d-{YYYY-MM-DD}.zip
https://data.binance.vision/data/spot/daily/klines/{SYMBOL}/1d/{SYMBOL}-1d-{YYYY-MM-DD}.zip.CHECKSUM
```

The headerless CSV fields, in order, are `open_time`, `open`, `high`, `low`,
`close`, `volume`, `close_time`, `quote_volume`, `count`,
`taker_buy_volume`, `taker_buy_quote_volume`, and `ignore`.

Timestamp units must be decoded without loss:

- records before 2025-01-01 use Unix milliseconds;
- spot records from 2025-01-01 onward use Unix microseconds;
- the parser must reject a value whose unit cannot be determined consistently from its magnitude and expected calendar range.

Prices must be finite positive decimal strings. Volumes are finite
non-negative decimal strings and trade count is a non-negative integer. Decimal
text is preserved until explicit domain conversion; binary floats are not used
as the canonical financial representation.

## 4. Four-time semantics and anti-leakage rule

For a daily bar on UTC day `D`:

- `event_time` is the exact upstream `close_time`, including millisecond or microsecond precision;
- `retrieval_time` is the actual UTC instant at which the archive bytes were acquired;
- the archive does not publish a per-bar publication timestamp, so historical replay assigns conservative `knowledge_time = (D+2)T00:00:00Z`;
- `execution_time` is when a policy runs, and `effective_time` is when an accepted virtual transition is applied.

The extra day is a deliberate reproducibility lag: “available the next day” is
insufficient evidence for `(D+1)T00:00:00Z`. If a future adapter captures a
verifiable first-observed publication instant, it may use that instant instead,
but it must record the evidence and may never backdate knowledge.

An observation is eligible for cutoff `T` iff `knowledge_time <= T`. For a
normal historical replay, the day-D bar first becomes eligible at
`(D+2)T00:00:00Z`. Delayed retrieval does not change the frozen historical
knowledge rule, but retrieval after a round's execution prevents that snapshot
from being used in that already-completed round.

Upstream archive replacement is not mutation of an accepted snapshot. A newly
downloaded byte sequence receives a new acquisition identity, retrieval time,
raw hash, normalized snapshot identity, and observation revisions. Previous
snapshots and episode records remain immutable.

## 5. Valuation versus simulated execution

The eligible day-D `close` is the mark used to value holdings at the decision
cutoff. It is **not** also an executable day-D close price: that would trade at
a price known only after the bar closed.

The price and timestamp used for a transition are a separate market-execution
contract owned by `DS-02D`. Its minimum invariant is that the execution price is
drawn from an observation whose event is at or after the decision cutoff and
whose availability is compatible with the simulation clock. Until `DS-02D`
freezes that rule, market rebalancing results must not be presented as valid.

## 6. Missing data and calendar rules

Crypto trading is continuous, but the contract does not assume that every
expected archive is present. Missing bars are not forward-filled into policy
observations. Valuation may use the last eligible mark only with an explicit
staleness indicator. Duplicate `(series_id, event_time, revision)` identities
are rejected. Delisting and outage behavior remains explicit rather than being
silently converted into zero prices.

## 7. Cryptographic provenance

Three logical boundaries are frozen:

1. `raw_artifact_hash`: SHA-256 of each downloaded archive, checked against the publisher companion checksum;
2. `normalized_snapshot_hash`: `checksum_sha256` in `DatasetSnapshotManifest`, computed over canonical normalized observations;
3. `manifest_hash`: SHA-256 of the canonical manifest representation.

The current `dataset_snapshot.v1.json` schema represents boundary 2. Boundaries
1 and 3 require an acquisition receipt/sidecar in `DS-02C`; they are not fields
silently invented in the existing manifest. The adapter must retain source URI,
publisher checksum bytes, computed raw hash, retrieval time, normalizer version,
normalized hash, and manifest hash. Any mismatch fails closed. Placeholder
hashes in documentation examples are illustrative and never evidence of a real
acquisition.

## 8. Evaluation partitions

Because all 2024–2025 observations are historical as of this contract date,
they cannot honestly be called private or forward data:

| Partition | Interval | Permitted use |
|---|---|---|
| `P0` exploratory | 2024-01-01 through 2024-06-30 | Pipeline exploration and model design |
| `P1` calibration | 2024-07-01 through 2024-12-31 | Parameter estimation and freezing |
| `P2` retrospective holdout | 2025-01-01 through 2025-06-30 | Untuned comparison, labelled retrospective |
| `P3` retrospective stress | 2025-07-01 through 2025-12-31 | Regime stress, labelled retrospective |

These fixed intervals improve repeatability but do not erase selection hindsight.
A true prospective forward partition begins only after all compared policy
versions, episode settings, and its UTC start instant have been committed before
the first included observation becomes known. Its end is frozen at creation or
defined by a precommitted duration. No tuning is permitted on `P2`, `P3`, or the
prospective partition after their outcomes are inspected.

## 9. Offline and failure semantics

Simulation consumes only a locally accepted, checksum-verified snapshot; it
does not perform live fallback downloads. Missing cache entries, checksum
mismatches, and unavailable sources fail explicitly. Concrete exception names
and cache paths remain planned for `DS-02C` and must not be described as shipped
runtime behavior before that gate is implemented.
