# TraceCascade

TraceCascade is a local-first, evidence-backed change-impact simulator. Before a team changes a contract, field, workflow, module or API, it answers: **what else can break, why, and what should be checked next?**

Version 1.0 is a complete local/small-team workflow—not a hosted SaaS. It combines strict evidence graphs, deterministic impact propagation, reversible entity alignment, graph/report diffs, role-gated human review, tamper-evident audit logs, read-only source connectors, encrypted recovery, and executable ReproForge plans.

## Why it is useful

- Make hidden downstream dependencies visible before a change ships.
- Preserve the exact quote, source range and optional source hash behind every relation.
- Separate confirmed impact, likely impact and review-required conclusions.
- Turn uncertain relations into explicit human decisions without mutating the source graph.
- Export affected work as a validated execution DAG instead of a loose checklist.

## Install and test

Requires Python 3.12 or newer.

```sh
python -m pip install .
python -m unittest discover -s tests -v
tracecascade --help
```

The test suite covers validation, evidence drift, cycles, deterministic path selection, ingestion conflicts, alignment/undo, diffs, concurrent audit writers, permissions, HMAC tamper detection, CSRF defenses, connector bounds, ReproForge export and encrypted recovery.

## Five-minute workflow

The complete example is in `examples/v1-workflow`:

```sh
tracecascade ingest examples/v1-workflow/source.md \
  --out examples/v1-workflow/graph.generated.json
tracecascade verify-evidence examples/v1-workflow/graph.generated.json
tracecascade align examples/v1-workflow/graph.generated.json \
  examples/v1-workflow/alignment.json \
  --out examples/v1-workflow/aligned.generated.json \
  --ledger examples/v1-workflow/alignment-ledger.generated.json
tracecascade simulate examples/v1-workflow/aligned.generated.json \
  examples/v1-workflow/scenario.json \
  --json-out examples/v1-workflow/report.generated.json \
  --markdown-out examples/v1-workflow/report.generated.md
tracecascade serve-review examples/v1-workflow/aligned.generated.json \
  --actor demo-reviewer --policy examples/v1-workflow/review-policy.json \
  --log examples/v1-workflow/reviews.generated.jsonl
tracecascade export-reproforge examples/v1-workflow/report.generated.json \
  examples/v1-workflow/reproforge-mapping.json \
  --out examples/v1-workflow/reproforge.generated.json
```

Open the loopback URL printed by `serve-review`; it never binds to a public interface. See [OPERATIONS.md](OPERATIONS.md) for signed audit logs, encrypted backup/restore and benchmark guidance.

## Inputs and connectors

`ingest` merges version-1 JSON graphs, CSV rows and Markdown directives. Conflicting IDs fail closed. Markdown uses:

```text
@node id kind | title | description
@edge id from relation to status confidence | literal evidence quote
```

`scan-python` builds a local module dependency graph from Python ASTs. `snapshot-github` makes bounded, GET-only UTF-8 snapshots of `.py`, `.md`, `.json` and `.csv` files; it never requests remote write access. Snapshot first, then ingest or scan locally.

## Graph and impact semantics

Every edge requires `from`, `to`, relation, `confirmed`/`inferred` status, confidence and evidence. Evidence paths are relative POSIX paths and cannot traverse upward or pass through symlinks. `verify-evidence` checks line ranges, quotes and optional SHA-256 digests; `simulate` refuses failed evidence.

The engine chooses the strongest simple path from any changed node, multiplying edge confidence. Cycles terminate, depth is bounded and equal paths use stable edge-ID ordering:

- `confirmed-impact`: every relation is confirmed and cumulative confidence is at least 0.8.
- `likely-impact`: confidence is at least 0.5 with some uncertainty.
- `review-required`: confidence is below 0.5.

These are rankings of declared relations, not proof of causality. An incomplete graph produces incomplete conclusions.

## Review, audit and recovery

Review actions are `confirm`, `reject` and `expire`. A policy maps actors to roles and actions. Events are append-only JSONL with a SHA-256 chain; set `require_hmac: true` and provide `TRACECASCADE_AUDIT_KEY` to authenticate them. `apply-reviews` creates a new graph and requires the same policy used to verify the log.

Encrypted backups use AES-256-GCM and scrypt. The password is read only from `TRACECASCADE_BACKUP_PASSWORD`. Unsafe paths, symlinks, oversized archives, nonempty restore targets and modified ciphertext are rejected.

## Honest boundary

TraceCascade does not prove causality, replace legal/security judgment, execute untrusted code, or provide hosted multi-tenant identity and operations. Its completed 1.0 boundary is a secure, auditable local/small-team product. See [PROJECT_PLAN.md](PROJECT_PLAN.md) for the delivered architecture and possible future work.
