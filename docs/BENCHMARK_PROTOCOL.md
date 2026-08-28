# Benchmark Protocol

## Purpose

Define a fair, replayable comparison of decision policies. The first adapter
may use public market data, but all core terms and records remain
domain-neutral.

## Required Time Semantics

Every observation and action distinguishes:

- **event time**: when the underlying event occurred;
- **knowledge time**: when the policy was allowed to know it;
- **execution time**: when the policy ran;
- **effective time**: when an accepted decision changed state.

No observation may influence a decision before its knowledge time.

## Episode Freeze

Before execution, freeze:

- dataset source, license, checksum, and retrieval time;
- exploratory, calibration, retrospective holdout/stress, and any separately precommitted prospective intervals;
- initial resources and reference unit;
- decision calendar and cutoff;
- valuation and transition rules;
- costs, limits, divisibility, borrowing, and negative-position policy;
- missing-data, timeout, and failed-decision behavior;
- every policy version and parameter;
- random seeds where applicable.

An official episode cannot be edited after it starts.

## Initial Policy Set

1. Static baseline.
2. Reactive last-observation baseline.
3. Optees point forecast plus constrained net-value optimization.
4. Point forecast with a hard transition-count limit.
5. Point forecast with explicit transition costs.

Only policies supported by released, pinned Optees contracts may enter a
publishable episode.

## Evaluation

### Primary

- final value in the declared reference unit;
- total return relative to common initial value.

### Explanatory

- maximum drawdown;
- value volatility;
- worst round;
- transition count, turnover, and total costs;
- rejected or invalid decisions;
- forecast MAE, RMSE, MASE, and MAPE where defined;
- runtime, Optees calls, validation failures, and optional token use.

Do not combine these into a hidden synthetic score.

## Dataset Adapters and Provenance

Each adapter declares:

- schema and units;
- source, retrieval method, and redistribution terms;
- calendar and missing-value treatment;
- knowledge-time assumptions ($t_{knowledge} \le T_k$);
- reference-unit valuation;
- transition feasibility and costs;
- handling of corrections, delays, and unavailable future data;
- three-tier SHA-256 hash boundaries (raw artifact, normalized snapshot, manifest).

The authoritative specification for the initial market dataset (Binance Public 1d Spot Klines for BTC, ETH, SOL, BNB quoted in USDT) is frozen in [`contracts/market-dataset-provenance.md`](contracts/market-dataset-provenance.md).

The simulator must support at least one non-market synthetic or operational
dataset before making broad claims about policy quality.

## Anti-Leakage Rules

- chronological splits only (Exploratory P0, Calibration P1, Retrospective Holdout P2, Retrospective Stress P3, plus any separately precommitted prospective partition);
- strictly no tuning or parameter adjustment after inspecting the retrospective holdout/stress intervals (P2/P3) or any prospective interval;
- no retrospective replacement of failed decisions;
- no policy-specific data corrections;
- no selection of only favorable episode windows or asset subsets after observing strategy returns;
- no access to another policy's state;
- all exploratory, calibration, retrospective, and prospective episodes labeled
  separately.

## Publication Rules

A public result must include:

- complete episode manifest and checksums;
- policy graphs, versions, and parameters;
- dataset provenance and cutoffs;
- failures and rejected decisions;
- primary and explanatory metrics separately;
- sufficient records to replay the episode;
- a statement limiting conclusions to the measured setup.

Market-backed demonstrations must explicitly state that they are paper
simulations and not evidence of future profitability.
