# TraceCascade working plan

## Goal
Build a local-first change-impact simulator that turns evidence-backed dependency graphs into explainable, auditable what-if reports.

## Current phase
R0 release verification and public repository setup.

## Phases
- R0 core graph and impact engine: complete locally; publication/CI pending.
- R1 document/CSV/JSON ingestion and reversible entity alignment: pending.
- R2 version diff and scenario comparison: pending.
- R3 human review workbench: pending.
- R4 read-only connectors and ReproForge export: pending.
- R5 collaboration, permissions, security and scale validation: pending.

## Acceptance for R0
- Invalid nodes, edges, evidence and scenarios fail with actionable errors.
- Cyclic dependency graphs terminate and produce deterministic results.
- Every affected node includes a path back to the changed node and evidence for each hop.
- Confirmed and inferred relations are clearly separated; uncertainty is not presented as fact.
- Local evidence references can be independently checked against source bytes and line numbers.
- JSON and Markdown reports agree and tests pass on Windows and Linux.

## Decisions
| Decision | Rationale |
|---|---|
| Python 3.12+, standard library first | Cross-platform and locally auditable. |
| Directed property graph in versioned JSON | Portable, reviewable and easy to generate from future parsers. |
| Maximum-confidence simple path with depth bound | Explainable propagation that terminates on cycles. |
| Evidence required on every edge | Prevent unsupported relationships from becoming invisible assumptions. |
| Read-only R0 | External writes and connectors need separate permissions and audit design. |

## Errors
| Error | Attempt | Resolution |
|---|---:|---|
| None yet | 1 | — |
| `git status` reported this new directory is not a repository | 1 | Expected before R0 review; initialize Git only after tests, docs and package verification. |
| First CI passed Ubuntu but Windows failed pinned evidence verification | 1 | Git line-ending conversion changed source bytes; add `.gitattributes` to enforce LF for cross-platform evidence hashes, then rerun CI. |
