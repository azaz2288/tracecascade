"""Stable machine-readable and human-readable impact reports."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def atomic_text(path: Path, content: str) -> None:
    temporary: Path | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="", dir=path.parent,
                                         prefix=".tmp-", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def write_json(path: Path, report: dict[str, Any]) -> None:
    atomic_text(path, json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def markdown(report: dict[str, Any]) -> str:
    scenario = report["scenario"]
    summary = report["summary"]
    lines = [f"# Impact report: {scenario['title']}", "", "## Summary", "",
             f"- Changed nodes: {summary['changed_nodes']}",
             f"- Affected nodes: {summary['affected_nodes']}",
             f"- Confirmed impacts: {summary['confirmed_impacts']}",
             f"- Likely impacts: {summary['likely_impacts']}",
             f"- Review required: {summary['review_required']}", "", "## Proposed changes", ""]
    for change in scenario["changes"]:
        lines.append(f"- `{change['node']}` — **{change['operation']}**: {change['description']}")
    lines.extend(["", "## Affected items", ""])
    if not report["impacts"]:
        lines.append("No downstream impact was found in the declared graph.")
    for impact in report["impacts"]:
        node = impact["node"]
        lines.extend([f"### {node['title']} (`{node['id']}`)", "",
                      f"Classification: **{impact['classification']}** · score `{impact['score']}` · "
                      f"depth `{impact['depth']}` · origin `{impact['origin']}`", "", node["description"], "",
                      "Evidence path:", ""])
        for step in impact["path"]:
            evidence = step["evidence"]
            lines.append(f"1. `{step['from']}` — **{step['relation']}** → `{step['to']}` "
                         f"({step['status']}, confidence {step['confidence']})")
            lines.append(f"   - `{evidence['source']}:{evidence['line_start']}` — “{evidence['quote']}”")
        lines.append("")
    lines.extend(["---", "", f"Graph SHA-256: `{report['graph_sha256']}`  ",
                  f"Scenario SHA-256: `{report['scenario_sha256']}`", ""])
    return "\n".join(lines)
