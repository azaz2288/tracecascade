"""Explicit Markdown/CSV/JSON ingestion into a version-1 evidence graph."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable

from .model import Edge, Evidence, Graph, ModelError, Node, load_graph
from .report import atomic_text


NODE_DIRECTIVE = re.compile(r"@node\s+([a-z][a-z0-9_-]*)\s+([a-z][a-z0-9_-]*)\s*\|\s*([^|]+)\s*\|\s*(.+)\Z")
EDGE_DIRECTIVE = re.compile(
    r"@edge\s+([a-z][a-z0-9_-]*)\s+([a-z][a-z0-9_-]*)\s+([a-z][a-z0-9_-]*)\s+"
    r"([a-z][a-z0-9_-]*)\s+(confirmed|inferred)\s+(0(?:\.\d+)?|1(?:\.0+)?)\s*\|\s*(.+)\Z")


def _relative(output_root: Path, source: Path) -> str:
    try:
        return source.resolve().relative_to(output_root.resolve()).as_posix()
    except ValueError as exc:
        raise ModelError(f"Input source must be inside output graph directory: {source}") from exc


def _markdown(path: Path, output_root: Path) -> tuple[list[Node], list[Edge]]:
    try:
        raw = path.read_bytes()
        lines = raw.decode("utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise ModelError(f"Cannot read Markdown source {path}: {exc}") from exc
    source = _relative(output_root, path)
    digest = hashlib.sha256(raw).hexdigest()
    nodes, edges = [], []
    for number, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith("@node"):
            match = NODE_DIRECTIVE.fullmatch(stripped)
            if not match:
                raise ModelError(f"Invalid @node directive at {source}:{number}")
            node_id, kind, title, description = match.groups()
            nodes.append(Node(node_id, kind, title.strip(), description.strip()))
        elif stripped.startswith("@edge"):
            match = EDGE_DIRECTIVE.fullmatch(stripped)
            if not match:
                raise ModelError(f"Invalid @edge directive at {source}:{number}")
            edge_id, origin, relation, target, status, confidence, quote = match.groups()
            edges.append(Edge(edge_id, origin, target, relation, status, float(confidence),
                              Evidence(source, quote.strip(), number, number, digest)))
    return nodes, edges


def _csv(path: Path, output_root: Path) -> tuple[list[Node], list[Edge]]:
    source = _relative(output_root, path)
    try:
        raw = path.read_bytes()
        text = raw.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text, newline=""), strict=True)
    except (OSError, UnicodeError, csv.Error) as exc:
        raise ModelError(f"Cannot read CSV source {path}: {exc}") from exc
    required = {"type", "id", "kind", "title", "description", "from", "to", "relation", "status", "confidence", "quote"}
    if reader.fieldnames is None or len(reader.fieldnames) != len(required) or set(reader.fieldnames) != required:
        raise ModelError(f"CSV {source} must have exactly these columns: {', '.join(sorted(required))}")
    digest = hashlib.sha256(raw).hexdigest()
    nodes, edges = [], []
    physical_lines = text.splitlines()
    previous_line = 1
    try:
        for row in reader:
            start, end = previous_line + 1, reader.line_num
            previous_line = end
            if None in row or any(value is None for value in row.values()):
                raise ModelError(f"CSV row at {source}:{start}-{end} has the wrong number of columns")
            if row["type"] == "node":
                nodes.append(Node(row["id"], row["kind"], row["title"], row["description"]))
            elif row["type"] == "edge":
                confidence = float(row["confidence"])
                quote = row["quote"].replace("\r\n", "\n").replace("\r", "\n")
                excerpt = "\n".join(physical_lines[start - 1:end])
                if quote not in excerpt:
                    raise ModelError(f"Evidence quote is not literal source text at {source}:{start}-{end}")
                edges.append(Edge(row["id"], row["from"], row["to"], row["relation"], row["status"], confidence,
                                  Evidence(source, quote, start, end, digest)))
            else:
                raise ModelError(f"Invalid record type at {source}:{start}")
    except (csv.Error, ValueError) as exc:
        raise ModelError(f"Invalid CSV value in {source}: {exc}") from exc
    return nodes, edges


def _json(path: Path, output_root: Path) -> tuple[list[Node], list[Edge]]:
    graph = load_graph(path)
    edges = []
    for edge in graph.edges:
        absolute = graph.root.joinpath(*edge.evidence.source.split("/"))
        evidence = Evidence(_relative(output_root, absolute), edge.evidence.quote, edge.evidence.line_start,
                            edge.evidence.line_end, edge.evidence.sha256)
        edges.append(Edge(edge.id, edge.source, edge.target, edge.relation, edge.status, edge.confidence, evidence))
    return list(graph.nodes), edges


def ingest(sources: Iterable[Path], output: Path) -> dict[str, Any]:
    output = output.resolve()
    root = output.parent
    nodes: dict[str, Node] = {}
    edges: dict[str, Edge] = {}
    source_list = [path.resolve() for path in sources]
    if not source_list:
        raise ModelError("At least one ingestion source is required")
    for path in source_list:
        if path == output:
            raise ModelError("Output graph cannot also be an ingestion source")
        if path.suffix.lower() in (".md", ".markdown"):
            incoming_nodes, incoming_edges = _markdown(path, root)
        elif path.suffix.lower() == ".csv":
            incoming_nodes, incoming_edges = _csv(path, root)
        elif path.suffix.lower() == ".json":
            incoming_nodes, incoming_edges = _json(path, root)
        else:
            raise ModelError(f"Unsupported ingestion source: {path}")
        for node in incoming_nodes:
            if node.id in nodes and nodes[node.id] != node:
                raise ModelError(f"Conflicting definitions for node {node.id}")
            nodes[node.id] = node
        for edge in incoming_edges:
            if edge.id in edges and edges[edge.id] != edge:
                raise ModelError(f"Conflicting definitions for edge {edge.id}")
            edges[edge.id] = edge
    known = set(nodes)
    for edge in edges.values():
        if edge.source not in known or edge.target not in known:
            raise ModelError(f"Edge {edge.id} references an unknown node")
    value = {"version": 1,
             "nodes": [asdict(nodes[key]) for key in sorted(nodes)],
             "edges": [{"id": edge.id, "from": edge.source, "to": edge.target,
                        "relation": edge.relation, "status": edge.status, "confidence": edge.confidence,
                        "evidence": asdict(edge.evidence)} for edge in sorted(edges.values(), key=lambda item: item.id)]}
    encoded = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    root.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="", dir=root,
                                         prefix=".tracecascade-validate-", suffix=".json", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(encoded)
        load_graph(temporary)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    atomic_text(output, encoded)
    return value
