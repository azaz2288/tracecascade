# TraceCascade

TraceCascade is a local-first change-impact simulator. It answers a practical question before a team changes a contract, data field, workflow or API: **what else can break, and what evidence supports that conclusion?**

Unlike a document search tool, TraceCascade works on a directed dependency graph. Every relation carries a source file, exact quote, line range, optional source hash, confidence and `confirmed`/`inferred` status. A what-if scenario propagates through that graph and produces a deterministic JSON report plus a readable evidence path for every affected item.

This repository currently delivers **R0**, the first vertical slice. The larger [project plan](PROJECT_PLAN.md) includes ingestion, version comparison, human review, connectors and multi-user security; those later stages are not claimed complete.

## Try it

```sh
python -m tracecascade validate examples/customer-tier/graph.json --scenario examples/customer-tier/scenario.json
python -m tracecascade verify-evidence examples/customer-tier/graph.json
python -m tracecascade simulate examples/customer-tier/graph.json examples/customer-tier/scenario.json \
  --json-out examples/customer-tier/out/report.json \
  --markdown-out examples/customer-tier/out/report.md
python -m unittest discover -s tests -v
```

The example asks what happens if a three-tier CRM field becomes a 0–100 score. TraceCascade identifies the discount job, revenue dashboard and renewal commitment as confirmed impacts, then marks the account playbook as likely because that last relation is inferred. The graph intentionally contains a cycle; propagation still terminates.

## Graph format

The version-1 graph contains `nodes` and `edges`. Node IDs, kinds and edge relations use stable lowercase identifiers. Each edge requires:

```json
{
  "id": "tier_to_discount",
  "from": "customer_tier",
  "to": "discount_job",
  "relation": "configures",
  "status": "confirmed",
  "confidence": 1.0,
  "evidence": {
    "source": "docs/architecture.md",
    "quote": "discount job reads customer_tier",
    "line_start": 3,
    "line_end": 3,
    "sha256": "optional-lowercase-source-digest"
  }
}
```

Evidence paths are relative to the graph file and cannot traverse upward or pass through symbolic links. `verify-evidence` confirms the optional SHA-256 and ensures the quote exists in the declared line range. `simulate` refuses to run on failed evidence.

## Impact semantics

The engine selects the strongest path from any changed node, multiplying edge confidence along the path. It never revisits a node within a path and bounds depth to the number of nodes, so cyclic graphs terminate. Equal paths use stable edge-ID ordering.

- `confirmed-impact`: every relation is confirmed and cumulative confidence is at least 0.8.
- `likely-impact`: cumulative confidence is at least 0.5, but the path contains uncertainty or falls below the confirmed threshold.
- `review-required`: cumulative confidence is below 0.5.

These labels rank declared relationships; they do not prove real-world causality. Incorrect or incomplete graphs produce incomplete conclusions. R0 is read-only and does not modify external systems.
