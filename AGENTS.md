# Repository Agent Instructions

These instructions apply to every automated coding agent working in this
repository. Keep stable policy here and detailed project decisions in the
canonical documents below.

## Sources of truth

Read the relevant sources before changing the repository:

- Product boundaries: `docs/PRODUCT_SPEC.md`
- Architecture and dependency direction: `docs/ARCHITECTURE.md`
- Core records, time, hashing, and replay: `docs/contracts/core-contracts.md`
- Security and residual risks: `docs/contracts/threat-model.md`
- Optees boundary and transports: `docs/OPTEES_INTEGRATION.md`
- Experiment rules: `docs/BENCHMARK_PROTOCOL.md`
- Current sequencing: `docs/ROADMAP.md` and its referenced detailed work unit

Documentation must distinguish implemented behavior from planned behavior.
When a change affects a frozen contract, architecture, command, threat,
benchmark rule, or roadmap gate, update its authoritative document in the same
work unit.

## Architecture and engineering

- Inspect existing contracts, fixtures, and patterns before designing a change.
- Preserve the inward dependency direction. Domain code must not import web,
  database, provider, MCP, REST, UI, or Optees protocol implementations.
- Keep the core domain-neutral. Market interpretation belongs in dataset,
  valuation, transition, and policy adapters rather than core records.
- The Simulator owns time, episode state, policy isolation, accounting,
  acceptance, replay, and evaluation. Optees owns mathematical capabilities,
  solver execution, and independent solution validation.
- Treat knowledge-time eligibility, cross-policy isolation, canonical JSON,
  hashing, immutable history, accounting, replay, and public schemas as
  high-risk surfaces requiring focused regression coverage.
- Do not add real transactions, broker SDKs, credentials, personalized advice,
  or other external side effects. The case study remains paper-only.
- Presentation code must not call Optees directly, hold backend credentials,
  compute authoritative scores or account state, or hide failures and rejected
  decisions.
- Keep changes scoped and preserve unrelated user work. Prefer existing ports,
  fixtures, schemas, helpers, and components over parallel implementations.
- Run focused checks while iterating and broader gates in proportion to the
  blast radius. Report dependencies or environments that prevent a check; do
  not describe an incomplete run as passed.

## Work-unit discipline

- Treat planning, implementation, and review as distinct task roles even when
  one agent performs more than one of them.
- A planning work unit freezes scope, dependencies, stop conditions, required
  evidence, and its completion gate. It must not implement the planned phase
  unless the user explicitly combines the roles.
- An implementation work unit follows one ready plan, does not silently widen
  its scope, and does not begin the next roadmap item.
- A review work unit reproduces important checks, challenges unsupported
  claims, and places material corrections in a separate atomic commit.
- Respect explicit ownership recorded by the user or roadmap. Agents may review
  another owner's work but must not take over its implementation without
  reassignment.

## Local commits

- Create a local commit only for a coherent, reviewed, and appropriately tested
  work unit. Keep commits atomic and use concise imperative messages.
- Inspect the staged diff and exclude unrelated files, generated output,
  secrets, credentials, datasets not approved for redistribution, and local
  configuration.
- Do not add AI attribution to any commit subject, body, or trailer. This
  includes `Co-authored-by`, `Generated-by`, agent or model names, vendor names,
  Anthropic identities, or similar metadata.
- Preserve the repository's existing Git author, committer, signing, hooks, and
  credential configuration.

## Remote publication

- Never push `main`, publish branches or tags, create releases, trigger
  deployments, or change remotes.
- When a local state is ready to publish, report the exact user-run commands
  separately from the completed local work.

## Completion standard

A task is complete only when implementation, focused verification, relevant
documentation, and local Git state agree. Report changes, checks, incomplete
checks, local commits, remaining risks, and the next manual step. Do not start
the next roadmap work unit automatically.
