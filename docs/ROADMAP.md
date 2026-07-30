# Delivery Roadmap

## Strategy

Build a deterministic harness first, then add Optees-backed policies, and only
then depend on future Optees capabilities. Each phase must leave a usable,
testable product increment.

## Phase 0 - Contracts And Threat Model

- [ ] Freeze episode, policy, round, observation, decision, transition, account,
  and metric schemas.
- [ ] Freeze event, knowledge, execution, and effective time semantics.
- [ ] Define dataset adapter and deterministic clock ports.
- [ ] Define `OpteesClientPort` and normalized failure categories.
- [ ] Define persistence, canonical JSON, hashing, and replay rules.
- [ ] Threat-model leakage, malformed datasets, cross-policy contamination,
  process failure, resource exhaustion, and report injection.
- [ ] Decide workspace tooling and package layout.

## Phase 1 - Deterministic Backend MVP

Available without new Optees work:

- [ ] Implement virtual accounts and deterministic transitions.
- [ ] Implement episodes and isolated decision rounds.
- [ ] Implement SQLite persistence and immutable version records.
- [ ] Add static and reactive baselines.
- [ ] Add machine-readable export and deterministic replay.
- [ ] Add FastAPI endpoints over application services.
- [ ] Add unit, property, temporal-leakage, and replay tests.

## Phase 2 - Optees MCP Vertical Slice

Available with released Optees capabilities:

- [ ] Implement the MCP stdio client adapter.
- [ ] Implement the REST parity adapter.
- [ ] Discover and pin capability contracts per episode.
- [ ] Add univariate point forecasting.
- [ ] Add LP/MILP decision formulation with transition costs.
- [ ] Persist validation receipts and result provenance.
- [ ] Add hard transition-count and penalized-transition policies.
- [ ] Verify fake/MCP/REST behavioral parity on analytic cases.

## Phase 3 - Web MVP

- [ ] Scaffold React, TypeScript, and Vite.
- [ ] Add episode configuration and validation.
- [ ] Add policy inventory and immutable version details.
- [ ] Add round timeline and virtual-account views.
- [ ] Add policy value trajectories and separate explanatory metrics.
- [ ] Show Optees assumptions, validation, and failures.
- [ ] Add export and report requests.
- [ ] Verify desktop and mobile browser layouts.

## Phase 4 - First Publishable Benchmark

- [ ] Add one licensed public time-series adapter.
- [ ] Add one synthetic analytic adapter.
- [ ] Freeze an exploratory, calibration, private, and forward interval.
- [ ] Run baseline and Optees policies over identical information.
- [ ] Publish full manifests, checksums, negative results, and limitations.
- [ ] Produce a compact web demonstration without operational claims.

## Phase 5 - Forecast Uncertainty

Blocked until Optees exposes calibrated uncertainty:

- [ ] Consume forecast intervals, quantiles, or scenarios.
- [ ] Evaluate empirical coverage chronologically.
- [ ] Add forecast-fan and calibration views.
- [ ] Separate forecast uncertainty from decision risk.

## Phase 6 - Robust And Stochastic Policies

Blocked until corresponding Optees contracts exist:

- [ ] Add robust max-min decisions over common scenarios.
- [ ] Add expected-value optimization.
- [ ] Add CVaR with explicit confidence and loss semantics.
- [ ] Compare all policies using identical scenario packages.

## Phase 7 - QP And MIQP Policies

Blocked until Optees adds convex QP and later MIQP:

- [ ] Add quadratic concentration and diversification penalties.
- [ ] Add risk-return trade-off policies with visible coefficients.
- [ ] Add fixed transition decisions through MIQP.
- [ ] Preserve exact solver status and independent validation.

## Phase 8 - Workflow Registry And Experiment Ledger

Blocked until the Optees workflow platform is available:

- [ ] Register reviewed policies as immutable workflows.
- [ ] Run routine episodes without frontier-model reasoning.
- [ ] Link later observations to earlier forecasts and decisions.
- [ ] Add idempotent restart, promotion, rollback, and comparison.
- [ ] Import signed workflow versions without arbitrary Python execution.

## Phase 9 - Sequential Adaptation Study

- [ ] Define deterministic degradation and review triggers.
- [ ] Compare frozen policies with explicitly approved revisions.
- [ ] Add generic ex-post forecast and decision evaluation.
- [ ] Evaluate DP, MDP, bandit, or external policy-engine approaches.
- [ ] Ensure adaptive policies cannot learn from private future intervals.

## Phase 10 - Multi-Dataset Generalization

- [ ] Add structurally different non-market datasets.
- [ ] Test stable, growing, declining, seasonal, and volatile regimes.
- [ ] Compare episode variance across windows.
- [ ] Report where forecasting improves predictions but not decisions.
- [ ] Keep domain adapters outside Optees and the simulator core.

## Release Gate For The MVP

- [ ] One baseline and two Optees-backed policies complete the same episode.
- [ ] Temporal leakage and policy isolation tests pass.
- [ ] Replay reproduces all round and final hashes.
- [ ] MCP and REST adapters normalize the same results.
- [ ] The web UI exposes assumptions, failures, and validation.
- [ ] No real-world execution path or secret-bearing connector exists.
