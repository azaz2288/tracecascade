"""Strict versioned models for graphs and change scenarios."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Any


class ModelError(Exception):
    """Input graph or scenario is malformed or unsafe."""


IDENTIFIER = re.compile(r"[a-z][a-z0-9_-]{0,63}\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def _identifier(value: Any, label: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ModelError(f"{label} must match [a-z][a-z0-9_-]{{0,63}}")
    return value


def _text(value: Any, label: str, limit: int = 500) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ModelError(f"{label} must be nonempty text up to {limit} characters")
    return value.strip()


def _relative_path(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value or value.startswith("/"):
        raise ModelError(f"{label} must be a relative POSIX path")
    parts = value.split("/")
    if any(part in ("", ".", "..") or ":" in part or part[-1] in (" ", ".")
           or PureWindowsPath(part).is_reserved() for part in parts):
        raise ModelError(f"{label} contains a forbidden path segment")
    return value


@dataclass(frozen=True)
class Node:
    id: str
    kind: str
    title: str
    description: str


@dataclass(frozen=True)
class Evidence:
    source: str
    quote: str
    line_start: int
    line_end: int
    sha256: str | None


@dataclass(frozen=True)
class Edge:
    id: str
    source: str
    target: str
    relation: str
    status: str
    confidence: float
    evidence: Evidence


@dataclass(frozen=True)
class Graph:
    path: Path
    root: Path
    raw_bytes: bytes
    nodes: tuple[Node, ...]
    edges: tuple[Edge, ...]


@dataclass(frozen=True)
class Change:
    node: str
    operation: str
    description: str


@dataclass(frozen=True)
class Scenario:
    path: Path
    raw_bytes: bytes
    title: str
    changes: tuple[Change, ...]


def _load_json(path: Path) -> tuple[bytes, Any]:
    try:
        raw = path.read_bytes()
        return raw, json.loads(raw)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ModelError(f"Cannot read JSON {path}: {exc}") from exc


def load_graph(path: Path) -> Graph:
    path = path.resolve()
    raw, value = _load_json(path)
    if (not isinstance(value, dict) or set(value) != {"version", "nodes", "edges"}
            or type(value.get("version")) is not int or value["version"] != 1):
        raise ModelError("Graph must contain only version=1, nodes and edges")
    if not isinstance(value["nodes"], list) or not value["nodes"]:
        raise ModelError("Graph nodes must be a nonempty list")
    nodes = []
    for index, item in enumerate(value["nodes"]):
        label = f"nodes[{index}]"
        if not isinstance(item, dict) or set(item) - {"id", "kind", "title", "description"}:
            raise ModelError(f"{label} has unknown fields or is not an object")
        nodes.append(Node(_identifier(item.get("id"), f"{label}.id"),
                          _identifier(item.get("kind"), f"{label}.kind"),
                          _text(item.get("title"), f"{label}.title", 200),
                          _text(item.get("description", "Not provided"), f"{label}.description", 1000)))
    node_ids = {node.id for node in nodes}
    if len(node_ids) != len(nodes):
        raise ModelError("Node IDs must be unique")
    if not isinstance(value["edges"], list):
        raise ModelError("Graph edges must be a list")
    edges = []
    for index, item in enumerate(value["edges"]):
        label = f"edges[{index}]"
        required = {"id", "from", "to", "relation", "status", "confidence", "evidence"}
        if not isinstance(item, dict) or set(item) != required:
            raise ModelError(f"{label} must contain exactly {', '.join(sorted(required))}")
        source = _identifier(item["from"], f"{label}.from")
        target = _identifier(item["to"], f"{label}.to")
        if source not in node_ids or target not in node_ids:
            raise ModelError(f"{label} references an unknown node")
        if source == target:
            raise ModelError(f"{label} cannot be a self-edge")
        status = item["status"]
        if status not in ("confirmed", "inferred"):
            raise ModelError(f"{label}.status must be confirmed or inferred")
        confidence = item["confidence"]
        if type(confidence) not in (int, float) or not 0 < confidence <= 1:
            raise ModelError(f"{label}.confidence must be greater than 0 and at most 1")
        evidence = item["evidence"]
        evidence_fields = {"source", "quote", "line_start", "line_end"}
        if not isinstance(evidence, dict) or set(evidence) - (evidence_fields | {"sha256"}) or not evidence_fields <= set(evidence):
            raise ModelError(f"{label}.evidence has invalid fields")
        start, end = evidence["line_start"], evidence["line_end"]
        if type(start) is not int or type(end) is not int or start < 1 or end < start:
            raise ModelError(f"{label}.evidence line range is invalid")
        digest = evidence.get("sha256")
        if digest is not None and (not isinstance(digest, str) or not SHA256.fullmatch(digest)):
            raise ModelError(f"{label}.evidence.sha256 is invalid")
        edges.append(Edge(_identifier(item["id"], f"{label}.id"), source, target,
                          _identifier(item["relation"], f"{label}.relation"), status, float(confidence),
                          Evidence(_relative_path(evidence["source"], f"{label}.evidence.source"),
                                   _text(evidence["quote"], f"{label}.evidence.quote", 2000), start, end, digest)))
    if len({edge.id for edge in edges}) != len(edges):
        raise ModelError("Edge IDs must be unique")
    return Graph(path, path.parent, raw, tuple(nodes), tuple(edges))


def load_scenario(path: Path, graph: Graph) -> Scenario:
    path = path.resolve()
    raw, value = _load_json(path)
    if (not isinstance(value, dict) or set(value) != {"version", "title", "changes"}
            or type(value.get("version")) is not int or value["version"] != 1):
        raise ModelError("Scenario must contain only version=1, title and changes")
    if not isinstance(value["changes"], list) or not value["changes"]:
        raise ModelError("Scenario changes must be a nonempty list")
    known = {node.id for node in graph.nodes}
    changes = []
    for index, item in enumerate(value["changes"]):
        label = f"changes[{index}]"
        if not isinstance(item, dict) or set(item) != {"node", "operation", "description"}:
            raise ModelError(f"{label} has invalid fields")
        node = _identifier(item["node"], f"{label}.node")
        if node not in known:
            raise ModelError(f"{label} references unknown node {node}")
        if item["operation"] not in ("modify", "remove", "replace"):
            raise ModelError(f"{label}.operation must be modify, remove or replace")
        changes.append(Change(node, item["operation"], _text(item["description"], f"{label}.description", 1000)))
    if len({change.node for change in changes}) != len(changes):
        raise ModelError("A scenario can change each node only once")
    return Scenario(path, raw, _text(value["title"], "scenario.title", 200), tuple(changes))
