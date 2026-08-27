# Optees Decision Simulator Contracts (v1)

This directory contains the authoritative version 1 core contracts, schemas, threat models, and canonical examples for the Optees Decision Simulator.

## Contents

- [`core-contracts.md`](core-contracts.md): Authoritative specification of core domain entities, time semantics (the four times), observation delivery, JSON canonicalization (RFC 8785), SHA-256 hashing, replay modes, divergence categories, and application ports.
- [`threat-model.md`](threat-model.md): Comprehensive security analysis covering trust boundaries, 12 threat vectors, mitigations, and residual risks.
- [`schemas/`](schemas/): Formally versioned JSON Schema specifications (Draft 2020-12) for all 15 core entities:
  - [`schema_inventory.json`](schemas/schema_inventory.json): Machine-readable inventory of all v1 schemas.
  - [`episode_definition.v1.json`](schemas/episode_definition.v1.json)
  - [`episode_run.v1.json`](schemas/episode_run.v1.json)
  - [`policy_definition.v1.json`](schemas/policy_definition.v1.json)
  - [`policy_version.v1.json`](schemas/policy_version.v1.json)
  - [`dataset_snapshot.v1.json`](schemas/dataset_snapshot.v1.json)
  - [`observation.v1.json`](schemas/observation.v1.json)
  - [`round.v1.json`](schemas/round.v1.json)
  - [`proposed_decision.v1.json`](schemas/proposed_decision.v1.json)
  - [`decision_outcome.v1.json`](schemas/decision_outcome.v1.json)
  - [`transition.v1.json`](schemas/transition.v1.json)
  - [`virtual_account_state.v1.json`](schemas/virtual_account_state.v1.json)
  - [`metric_record.v1.json`](schemas/metric_record.v1.json)
  - [`optees_call_receipt.v1.json`](schemas/optees_call_receipt.v1.json)
  - [`replay_report.v1.json`](schemas/replay_report.v1.json)
  - [`divergence_report.v1.json`](schemas/divergence_report.v1.json)
- [`examples/`](examples/): Complete valid and invalid examples demonstrating schema adherence, temporal filtering, and invariant enforcement:
  - [`valid/synthetic_episode_definition.v1.json`](examples/valid/synthetic_episode_definition.v1.json)
  - [`valid/knowledge_cutoff_observations.v1.json`](examples/valid/knowledge_cutoff_observations.v1.json)
  - [`valid/decision_accepted.v1.json`](examples/valid/decision_accepted.v1.json)
  - [`valid/decision_rejected.v1.json`](examples/valid/decision_rejected.v1.json)
  - [`valid/transition_and_account_state.v1.json`](examples/valid/transition_and_account_state.v1.json)
  - [`valid/optees_call_receipt.v1.json`](examples/valid/optees_call_receipt.v1.json)
  - [`valid/record_replay_success.v1.json`](examples/valid/record_replay_success.v1.json)
  - [`valid/numerical_divergence_report.v1.json`](examples/valid/numerical_divergence_report.v1.json)
  - [`invalid/invalid_future_leakage.json`](examples/invalid/invalid_future_leakage.json)
  - [`invalid/invalid_duplicate_identity.json`](examples/invalid/invalid_duplicate_identity.json)
  - [`invalid/invalid_mutable_version.json`](examples/invalid/invalid_mutable_version.json)
  - [`invalid/invalid_non_finite_number.json`](examples/invalid/invalid_non_finite_number.json)
  - [`invalid/invalid_timezone_ambiguous.json`](examples/invalid/invalid_timezone_ambiguous.json)
  - [`invalid/invalid_cross_policy_account_reference.json`](examples/invalid/invalid_cross_policy_account_reference.json)
