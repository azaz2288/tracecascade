"""Independent verification for local evidence references."""

from __future__ import annotations

import hashlib
from pathlib import Path

from .model import Graph


def _source_path(root: Path, relative: str) -> Path:
    target = root.joinpath(*relative.split("/"))
    resolved_root = root.resolve()
    if not target.resolve(strict=False).is_relative_to(resolved_root):
        raise ValueError(f"Evidence source escapes graph root: {relative}")
    current = root
    for part in relative.split("/"):
        current = current / part
        if current.is_symlink():
            raise ValueError(f"Evidence source uses a symbolic link: {relative}")
    return target


def verify_evidence(graph: Graph) -> list[str]:
    issues: list[str] = []
    for edge in graph.edges:
        evidence = edge.evidence
        try:
            path = _source_path(graph.root, evidence.source)
            raw = path.read_bytes()
            text = raw.decode("utf-8")
        except (OSError, UnicodeError, ValueError) as exc:
            issues.append(f"{edge.id}: cannot read evidence: {exc}")
            continue
        if evidence.sha256 is not None and hashlib.sha256(raw).hexdigest() != evidence.sha256:
            issues.append(f"{edge.id}: evidence source SHA-256 mismatch")
        lines = text.splitlines()
        if evidence.line_end > len(lines):
            issues.append(f"{edge.id}: evidence line range exceeds source ({len(lines)} lines)")
            continue
        excerpt = "\n".join(lines[evidence.line_start - 1:evidence.line_end])
        if evidence.quote not in excerpt:
            issues.append(f"{edge.id}: evidence quote not found in declared line range")
    return issues
