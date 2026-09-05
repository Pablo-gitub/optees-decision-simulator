# Deferred Run Terminal Contract

- Status: Frozen design specification; implementation scheduled for `DS-02D2C1`.
- Authority: [Deferred Settlement Contract](deferred-settlement-contract.md).
- Companion: [Deferred Runner Orchestration Roadmap](../roadmaps/deferred-runner-orchestration.md).

---

## 1. Problem and Purpose

The round v2 contract ([`round.v2.json`](schemas/round.v2.json), `DeferredPolicyRoundRecord`) was frozen in `DS-02D2C0`.
Its invariants establish:
1. `policy_round_records[i].settlement_outcome_hash` refers strictly to the settlement of `pending_before`.
2. A single round entry contains at most one `settlement_outcome_hash` and at most one `decision_outcome_hash`.
3. An admitted pending trade produces a `pending_after` reference and explicitly forbids an immediate decision outcome.

Consequently, when an episode reaches its final calendar round (or is cancelled between rounds or before round execution):
- A policy may have an active pending order remaining in `pending_after` (either newly admitted in the final round, or carried over from an unsettled trade).
- Under Section 8.5 of `deferred-settlement-contract.md`, such orders must reach terminal `REJECTED` status with reason `UNSETTLED_EPISODE_TERMINATION` (or `EPISODE_CANCELLED`).
- This terminal settlement outcome cannot be recorded inside the final round's `DeferredPolicyRoundRecord` without violating C0 invariants (an entry cannot host two settlement outcomes, nor attach an outcome to `pending_after`).
- The final round cannot be rewritten or backdated after commit, and undeclared rounds cannot be appended to the frozen episode calendar.

To resolve this without modifying frozen v1 or v2 round schemas, the simulator introduces an immutable, additive terminal event record: **`DeferredRunTerminalRecord`**.

---

## 2. Record Specification

### 2.1 JSON Schema Specification (Draft 2020-12)

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://optees.org/schemas/simulator/v1/deferred_run_terminal_record.v1.json",
  "title": "DeferredRunTerminalRecord",
  "description": "Immutable record capturing final episode termination, cancellation, and terminal clearance of pending transitions under deferred settlement.",
  "type": "object",
  "required": [
    "$type",
    "schema_version",
    "terminal_record_id",
    "run_id",
    "episode_id",
    "terminal_status",
    "reason_code",
    "reason_message",
    "simulated_effective_time",
    "execution_timestamp",
    "parent_round_hash",
    "policy_terminal_records",
    "terminal_state_merkle_hash"
  ],
  "additionalProperties": false,
  "properties": {
    "$type": {
      "type": "string",
      "const": "deferred_run_terminal_record"
    },
    "schema_version": {
      "type": "string",
      "const": "1.0.0"
    },
    "terminal_record_id": {
      "type": "string",
      "pattern": "^term_[a-zA-Z0-9_-]+$"
    },
    "run_id": {
      "type": "string",
      "pattern": "^ep-run_[a-zA-Z0-9_-]+$"
    },
    "episode_id": {
      "type": "string",
      "pattern": "^ep-def_[a-zA-Z0-9_-]+$"
    },
    "terminal_status": {
      "type": "string",
      "enum": ["COMPLETED", "CANCELLED"]
    },
    "reason_code": {
      "type": "string",
      "enum": [
        "CLEAN_COMPLETION",
        "UNSETTLED_EPISODE_TERMINATION",
        "EPISODE_CANCELLED"
      ]
    },
    "reason_message": {
      "type": "string",
      "minLength": 1,
      "maxLength": 1000
    },
    "simulated_effective_time": {
      "type": "string",
      "pattern": "^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}(\\.\\d+)?Z$"
    },
    "execution_timestamp": {
      "type": "string",
      "pattern": "^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}(\\.\\d+)?Z$"
    },
    "parent_round_hash": {
      "type": ["string", "null"],
      "pattern": "^sha256:[a-f0-9]{64}$"
    },
    "policy_terminal_records": {
      "type": "array",
      "minItems": 1,
      "items": {
        "type": "object",
        "required": [
          "policy_id",
          "account_state_hash",
          "pending_transition_hash",
          "settlement_outcome_hash"
        ],
        "additionalProperties": false,
        "properties": {
          "policy_id": {
            "type": "string",
            "pattern": "^pol-def_[a-zA-Z0-9_-]+$"
          },
          "account_state_hash": {
            "type": "string",
            "pattern": "^sha256:[a-f0-9]{64}$"
          },
          "pending_transition_hash": {
            "type": ["string", "null"],
            "pattern": "^sha256:[a-f0-9]{64}$"
          },
          "settlement_outcome_hash": {
            "type": ["string", "null"],
            "pattern": "^sha256:[a-f0-9]{64}$"
          }
        }
      }
    },
    "terminal_state_merkle_hash": {
      "type": "string",
      "pattern": "^sha256:[a-f0-9]{64}$"
    }
  }
}
```

---

## 3. Structural Invariants

1. **Policy Ordering and Uniqueness:**
   `policy_terminal_records` must be sorted in strict lexicographic order of `policy_id`.
   Duplicate `policy_id` entries are strictly forbidden.
2. **Terminal Pending Co-Presence:**
   For each policy entry:
   - If `pending_transition_hash is None`, then `settlement_outcome_hash` must be `None` (clean termination with no outstanding order).
   - If `pending_transition_hash is not None`, then `settlement_outcome_hash` must be a valid SHA-256 hash of a `SettlementOutcome` whose status is `REJECTED` with reason `UNSETTLED_EPISODE_TERMINATION` or `EPISODE_CANCELLED`.
3. **Parent Round Linkage:**
   - If the episode executed $\ge 1$ rounds, `parent_round_hash` must equal `latest_round.compute_hash()`.
   - If the episode executed $0$ rounds (cancellation before round 0), `parent_round_hash` must be `None`.
4. **State Merkle Hashing:**
   The `terminal_state_merkle_hash` is computed using the canonical `compute_state_merkle_hash` primitive:
   ```python
   leaf_hashes = [compute_record_hash(p.to_dict()) for p in sorted_policy_records]
   terminal_state_merkle_hash = compute_state_merkle_hash(parent_round_hash, leaf_hashes)
   ```
5. **Run Final State Binding:**
   The terminal record's hash (`compute_record_hash(terminal_record.to_dict())`) is stored as `EpisodeRun.final_state_hash`.

---

## 4. Lifecycle Scenarios

| Scenario | Rounds Run | Pending Before Term | Reason Code | Parent Round Hash | Terminal Settlement Outcome? |
|---|---|---|---|---|---|
| **Clean Completion** | $K$ rounds | None | `CLEAN_COMPLETION` | Hash of Round $K-1$ | None |
| **Unsettled Final Admission** | $K$ rounds | Yes (admitted round $K-1$) | `UNSETTLED_EPISODE_TERMINATION` | Hash of Round $K-1$ | Yes (`UNSETTLED_EPISODE_TERMINATION`) |
| **Old Pending Still Unsettled** | $K$ rounds | Yes (unsettled from $K-2$) | `UNSETTLED_EPISODE_TERMINATION` | Hash of Round $K-1$ | Yes (`UNSETTLED_EPISODE_TERMINATION`) |
| **Cancellation Between Rounds** | $r$ rounds ($0 < r < K$) | Yes or None | `EPISODE_CANCELLED` | Hash of Round $r-1$ | Yes if pending, else None |
| **Cancellation at Genesis** | $0$ rounds | None | `EPISODE_CANCELLED` | `None` | None |
