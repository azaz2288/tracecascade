# TraceCascade working plan

## Goal
Build a local-first change-impact simulator that turns evidence-backed dependency graphs into explainable, auditable what-if reports.

## Current phase
Complete-v1 public release. Implementation, local acceptance, clean wheel installation and Windows/Linux GitHub CI are complete.

## Phases
- R0 core graph and impact engine: complete and publicly released; Windows/Linux CI passed.
- R1 document/CSV/JSON ingestion and reversible entity alignment: complete.
- R2 version diff and scenario comparison: complete.
- R3 human review workbench: complete.
- R4 read-only connectors and ReproForge export: complete and exercised end to end.
- R5 permissions, audit integrity, performance benchmark and recovery documentation: complete for local/small-team v1; remote multi-tenant deployment remains out of scope.

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
| Complete v1 means a secure local/small-team product | A hosted multi-tenant SaaS requires operational infrastructure outside this repository; it is not a truthful single-machine acceptance target. |

## Errors
| Error | Attempt | Resolution |
|---|---:|---|
| None yet | 1 | — |
| `git status` reported this new directory is not a repository | 1 | Expected before R0 review; initialize Git only after tests, docs and package verification. |
| First CI passed Ubuntu but Windows failed pinned evidence verification | 1 | Git line-ending conversion changed source bytes; add `.gitattributes` to enforce LF for cross-platform evidence hashes, then rerun CI. |
| The first 10,000-node chain benchmark exceeded the interactive wait | 1 | The full-path report is inherently quadratic on a chain; add explicit fan-out/deep-chain topologies, publish both observations and document the boundary. |
| End-to-end ReproForge validation could not import the sibling project from TraceCascade's environment | 1 | Point `PYTHONPATH` at the local ReproForge checkout, then validate and execute the exported two-task DAG successfully. |
