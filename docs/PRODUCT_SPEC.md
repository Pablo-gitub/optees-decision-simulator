# Product Specification

## Product Goal

Build a reproducible simulator that compares frozen decision policies under
changing observations. A policy may use Optees forecasting and optimization,
but the simulator remains responsible for time, state, virtual accounting, and
evaluation.

The product must answer:

1. Can atomic Optees capabilities be composed into useful repeated decisions?
2. Does a forecast improve decisions compared with static and reactive
   baselines?
3. How do transition costs and limits affect final value?
4. Can every decision be reproduced from information available at that time?
5. Can a policy designed once with a capable agent run later without an LLM?

## Users

- Optees maintainers validating integration and missing capabilities;
- students studying forecasting, optimization, and temporal leakage;
- engineers testing local MCP and REST orchestration;
- analysts comparing explicit policies without real-world execution.

## MVP Scope

### Included

- one replaceable time-series dataset adapter;
- deterministic episodes and decision rounds;
- identical initial virtual resources for every policy;
- static and reactive baselines;
- one Optees point-forecast policy;
- one Optees MILP policy with explicit transition costs;
- isolated policy state;
- immutable inputs, outputs, validation receipts, and timestamps;
- final reference value and explanatory metrics;
- episode replay;
- local web dashboard;
- machine-readable export and a compact human-readable report.

### Explicitly Excluded

- real transactions or external side effects;
- brokerage integration and credentials;
- personalized financial recommendations;
- autonomous model redesign during an official episode;
- hidden online tuning;
- deep learning and distributed data processing;
- claims of production forecasting accuracy;
- game theory as a prerequisite for diversification.

## Core Domain

### Episode

A frozen competition over one dataset, interval, rule set, initial state, and
set of policy versions.

### Decision Round

A round records:

1. state before the decision;
2. observations visible at the knowledge cutoff;
3. Optees calls and validation receipts;
4. proposed and accepted decision;
5. later observation used for evaluation;
6. transition costs;
7. state and reference value after evaluation.

### Policy

An immutable, versioned decision procedure declaring:

- required observations;
- capability and contract versions;
- transformations and parameters;
- objectives and constraints;
- failure behavior;
- required artifacts and reports.

### Virtual Account

An isolated collection of generic resources. A dataset adapter defines their
valuation and allowed transitions. No policy can inspect or mutate another
policy's account.

## Scoring

The primary score is final value in one declared reference unit:

\[
V_t = C_t + \sum_i q_{i,t}p_{i,t} - K_t
\]

where \(C_t\) is unallocated reference value, \(q_{i,t}\) is resource quantity,
\(p_{i,t}\) is its frozen valuation, and \(K_t\) contains realized transition
and operating costs.

Final value and total return determine the primary ranking. Drawdown,
volatility, forecast error, transition count, costs, rejected decisions,
runtime, tool calls, and validation failures remain separate explanatory
metrics. They must not be silently combined into an undocumented score.

## Functional Requirements

### Episode Management

- Create an exploratory episode from a frozen configuration.
- Validate configuration before execution.
- Start, pause safely between rounds, resume idempotently, and cancel.
- Replay a completed episode and compare deterministic hashes.
- Prevent mutation of a policy or rule set after an episode starts.

### Policy Execution

- Deliver identical eligible observations to every policy.
- Execute policies independently.
- Validate every Optees problem before solving.
- Reject invalid or late decisions according to frozen failure rules.
- Run routine frozen policies without requiring an agent.

### Inspection

- Display current and historical virtual account state.
- Display each forecast, decision, assumption, and validation result.
- Compare value trajectories without hiding failures.
- Export complete provenance and checksums.

## Non-Functional Requirements

- Local-first and single-user for the MVP.
- Deterministic behavior where dependencies permit it.
- Bounded data, process, runtime, and artifact limits.
- No secrets in browser storage, logs, reports, or committed fixtures.
- Accessible bilingual UI is desirable later; Phase 1 may start in English.
- Backend contracts must not depend on React components.
- Optees transports must be replaceable behind one application port.

## Acceptance Gate

The MVP is acceptable when:

1. a baseline and at least two Optees-backed policies complete the same episode;
2. all competitors receive identical knowledge-time inputs;
3. accounting and transitions are deterministic;
4. every Optees result retains its contract version and validation receipt;
5. replay reproduces round and final hashes;
6. failures remain visible in UI and exports;
7. replacing the dataset adapter does not change policy accounting or Optees
   capability implementations.
