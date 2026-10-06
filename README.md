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

### Depth-bounded propagation (v1.0.3)

`--max-depth N` limits evidence hops, not nodes visited. A shallower, weaker prefix must still be expanded even if a stronger path already reaches its middle node at the depth limit; otherwise downstream impact can be missed. v1.0.3 uses layered relaxation for explicitly bounded runs. Changed nodes are independent roots, not transit/report targets. At equal scores bounded mode prefers fewer hops, then lexicographic edge IDs and origin. With no `--max-depth`, the existing heap algorithm and edge-ID/origin tie rule are unchanged; equal-score report paths can therefore differ between the two modes even with a large explicit bound.

An independent simple-path oracle checks240 synthetic six-node graphs at6 depths (1440 comparisons), plus targeted weak-prefix, cycles, parallel edges, multi-root, ordering and CLI regressions. Randomized scores are exactly representable powers of two; this does not establish extreme floating-point precision or real-world graph completeness. Large cyclic graphs may require many depth layers: worst-case bounded work scales with the depth limit and edges, and full evidence-path report size remains a separate cost. Local benchmark instructions: `python -m benchmarks.scale --nodes 10000 --max-depth 1` or `--nodes 500 --topology chain --max-depth 100`. Timings are observations, not performance SLAs.

The engine chooses the strongest simple path from any changed node, multiplying edge confidence. Cycles terminate, depth is bounded and equal paths use stable edge-ID ordering:

- `confirmed-impact`: every relation is confirmed and cumulative confidence is at least 0.8.
- `likely-impact`: confidence is at least 0.5 with some uncertainty.
- `review-required`: confidence is below 0.5.

These are rankings of declared relations, not proof of causality. An incomplete graph produces incomplete conclusions.

## Review, audit and recovery

v1.0.2 bounds source-copy reads to predeclared file size and checks file identity/size/mtime; rejects growing files before encrypted output publication. Traversal checks links/junctions before descending, instead of discovering them after recursive walking. Stop writers before backup: these guards still do not create an atomic directory snapshot.

Review actions are `confirm`, `reject` and `expire`. A policy maps actors to roles and actions. Events are append-only JSONL with a SHA-256 chain; set `require_hmac: true` and provide `TRACECASCADE_AUDIT_KEY` to authenticate them. `apply-reviews` creates a new graph and requires the same policy used to verify the log.

Encrypted backups use AES-256-GCM and scrypt. The password is read only from `TRACECASCADE_BACKUP_PASSWORD`. Unsafe paths, symlinks, oversized archives, nonempty restore targets and modified ciphertext are rejected.

v1.0.1 validates raw ZIP names before Windows normalization, rejects drive/stream/device/control paths, case-colliding directories and file-parent conflicts, and preflights100,000-file/100MB limits before creating a destination. Linked source roots/entries and linked restore targets (including Windows junctions) are refused. Valid old archives remain readable; nonportable archives previously accepted must be reviewed rather than normalized silently. This is not an atomic filesystem snapshot or a malicious concurrent-path sandbox; ancestor indirection is not hardened. An I/O error after extraction starts may leave a partial new/empty destination; inspect it before retrying, without assuming successful recovery.

## Honest boundary

TraceCascade does not prove causality, replace legal/security judgment, execute untrusted code, or provide hosted multi-tenant identity and operations. Its completed 1.0 boundary is a secure, auditable local/small-team product. See [PROJECT_PLAN.md](PROJECT_PLAN.md) for the delivered architecture and possible future work.
