# Optees Integration

## Decision

Use MCP stdio as the primary integration and authenticated loopback REST as an
alternative adapter. Do not let the web client call either transport directly.

The backend depends on a simulator-owned `OpteesClientPort`, not on MCP protocol
objects. This keeps tests deterministic and permits REST/MCP parity checks.

## Required Capability Flow

Every Optees-backed policy must:

1. list or retrieve the pinned capability descriptor;
2. verify expected problem and result contract versions;
3. construct a complete versioned problem;
4. call validation before execution;
5. create the job;
6. poll boundedly until a terminal status;
7. retrieve the result and independent validation;
8. request optional artifacts only when declared by the policy;
9. persist canonical payloads, receipts, identifiers, and hashes.

The simulator must not infer success from transport completion alone.

## Initial Capabilities

The MVP is designed around released Optees functionality:

- `ml.forecasting.univariate` for point forecasting and chronological
  evaluation;
- `lp.continuous` or `milp.linear` for constrained decisions;
- result artifacts and report composition where available.

The exact capability inventory must be discovered at runtime and checked
against the episode manifest. Documentation must not make runtime availability
assumptions authoritative.

## MCP Runtime

The backend owns the MCP subprocess and communicates over stdio.

Configuration must include:

- executable or command;
- startup timeout;
- operation timeout;
- maximum restarts;
- expected Optees version range;
- allowed capability identifiers;
- environment allowlist.

The child process receives a minimal environment. Standard error is captured
with bounded retention and secret redaction.

## REST Runtime

The REST adapter is intended for:

- integration debugging;
- externally managed Optees sessions;
- cross-transport parity tests;
- environments where stdio process spawning is unavailable.

Its base URL must be loopback by default. Bearer tokens remain backend-only and
must never be returned to the React client or persisted in episode exports.

## Failure Semantics

Normalize failures into simulator-owned categories:

- unavailable transport;
- incompatible Optees or contract version;
- invalid problem;
- rejected job;
- timeout or cancellation;
- solver terminal failure;
- independent validation failure;
- artifact or report failure.

Policies define frozen behavior for each category. The simulator must not
silently substitute another solver or change an objective.

## Current And Future Support

| Simulator stage | Optees requirement | Status |
|---|---|---|
| Static/reactive baselines | None | Implementable now |
| Point forecast policy | Univariate forecasting | Implementable now |
| Transition-aware decision | LP/MILP | Implementable now |
| Forecast charts and reports | Result artifacts/reporting | Implementable now |
| Calibrated uncertainty policy | Intervals, quantiles, or scenarios | Waiting on Optees |
| Robust policy | Generic max-min/scenario optimization | Waiting on Optees |
| Diversification/risk policy | Convex QP, later MIQP | Waiting on Optees |
| Token-free registered policy | Workflow Registry | Waiting on Optees |
| Persistent adaptive loop | Experiment Ledger and ex-post evaluation | Waiting on Optees |
| Sequential adaptive policy | DP/MDP/bandit capability or external policy engine | Future design |

## Contract Testing

- Run the same analytic policy through fake, MCP, and REST clients.
- Compare normalized requests, results, validation, and error categories.
- Pin fixture contracts by version.
- Fail visibly when Optees adds an incompatible schema.
- Include packaged MCP smoke tests before claiming installer compatibility.
