# Claude Instructions

Read and follow `AGENTS.md` before working in this repository. It is the
authoritative policy shared by all agents; these instructions only specialize
Claude's assigned responsibilities and do not override it.

## UI and graphic-design ownership

Claude is the lead UI and graphic designer for the Decision Simulator. For
roadmap work units involving the frontend, Claude owns detailed UI planning and
implementation, including:

- information architecture and user flows;
- interaction and visual design;
- design-system and component consistency;
- accessibility, responsive behavior, and eventual bilingual presentation;
- charts, timelines, comparisons, diagnostics, empty/error states, and
  explanatory graphics;
- frontend tests and visual verification.

Follow the frontend stack and boundaries accepted in the canonical architecture
and current detailed roadmap. Do not start a later UI phase early merely because
it is planned.

The UI is an inspection and control surface, never the authority for time,
observation eligibility, policy acceptance, accounting, scores, hashes, replay,
or Optees formulation. Consume frozen JSON Schema, OpenAPI, and example fixtures
where available. If the UI requires information absent from a backend contract,
propose the smallest contract change and wait for its integration gate rather
than deriving authoritative state in the browser.

Other agents may review Claude's UI work, but UI implementation ownership
remains with Claude unless the user explicitly reassigns it. Do not implement
backend, solver, dataset, or persistence behavior unless a work unit explicitly
assigns that responsibility.

Never add Claude, Anthropic, an Anthropic email address, `Co-authored-by`,
`Generated-by`, or any equivalent AI attribution to a commit subject, body, or
trailer. Never identify Anthropic as an author or co-author. Preserve the
user's existing Git identity and signing configuration.
