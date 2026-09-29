"""Explicit, reversible entity alignment."""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .model import Graph, ModelError, load_graph
from .report import atomic_text


def _rules(path: Path, graph: Graph) -> dict[str, str]:
    try:
        value = json.loads(path.read_bytes())
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ModelError(f"Cannot read alignment rules {path}: {exc}") from exc
    if not isinstance(value, dict) or set(value) != {"version", "groups"} or value.get("version") != 1 or not isinstance(value["groups"], list):
        raise ModelError("Alignment rules must contain version=1 and groups")
    known = {node.id for node in graph.nodes}
    if any(not isinstance(group, dict) or set(group) != {"canonical", "aliases"}
           for group in value["groups"]):
        raise ModelError("Alignment groups are malformed")
    canonicals = [group["canonical"] for group in value["groups"]]
    if any(not isinstance(canonical, str) for canonical in canonicals):
        raise ModelError("Canonical entities must be string IDs")
    if len(set(canonicals)) != len(canonicals):
        raise ModelError("Canonical entities must be unique")
    mapping: dict[str, str] = {}
    for index, group in enumerate(value["groups"]):
        if (not isinstance(group["aliases"], list)
                or any(not isinstance(alias, str) for alias in group["aliases"])):
            raise ModelError(f"groups[{index}] is invalid")
        canonical = group["canonical"]
        aliases = group["aliases"]
        if canonical not in known or not aliases or any(alias not in known or alias == canonical for alias in aliases):
            raise ModelError(f"groups[{index}] references invalid entities")
        for alias in aliases:
            if alias in mapping or alias in canonicals:
                raise ModelError(f"Entity {alias} appears in multiple alignment roles")
            mapping[alias] = canonical
    return mapping


def align(graph_path: Path, rules_path: Path, output: Path, ledger: Path) -> dict[str, Any]:
    graph = load_graph(graph_path)
    mapping = _rules(rules_path, graph)
    kept_nodes = [asdict(node) for node in graph.nodes if node.id not in mapping]
    kept_edges = []
    removed_self_edges = []
    for edge in graph.edges:
        source, target = mapping.get(edge.source, edge.source), mapping.get(edge.target, edge.target)
        if source == target:
            removed_self_edges.append(edge.id)
            continue
        kept_edges.append({"id": edge.id, "from": source, "to": target, "relation": edge.relation,
                           "status": edge.status, "confidence": edge.confidence, "evidence": asdict(edge.evidence)})
    value = {"version": 1, "nodes": kept_nodes, "edges": kept_edges}
    encoded = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    original = graph.path.read_bytes()
    log = {"version": 1, "operation": "entity-alignment", "mapping": mapping,
           "removed_self_edges": removed_self_edges,
           "original_sha256": hashlib.sha256(original).hexdigest(),
           "aligned_sha256": hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
           "original_bytes_base64": base64.b64encode(original).decode("ascii")}
    if output.resolve() in {graph.path, rules_path.resolve()} or ledger.resolve() in {graph.path, rules_path.resolve(), output.resolve()}:
        raise ModelError("Alignment output and ledger must not overwrite inputs or each other")
    atomic_text(output.resolve(), encoded)
    load_graph(output)
    atomic_text(ledger.resolve(), json.dumps(log, ensure_ascii=False, indent=2) + "\n")
    return log


def undo(aligned: Path, ledger: Path, output: Path) -> None:
    try:
        log = json.loads(ledger.read_bytes())
        aligned_bytes = aligned.read_bytes()
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ModelError(f"Cannot read alignment artifacts: {exc}") from exc
    if (not isinstance(log, dict) or log.get("version") != 1 or log.get("operation") != "entity-alignment"
            or hashlib.sha256(aligned_bytes).hexdigest() != log.get("aligned_sha256")):
        raise ModelError("Alignment ledger does not match the aligned graph")
    try:
        original = base64.b64decode(log["original_bytes_base64"], validate=True)
    except (KeyError, ValueError) as exc:
        raise ModelError(f"Alignment ledger cannot restore original graph: {exc}") from exc
    if hashlib.sha256(original).hexdigest() != log.get("original_sha256"):
        raise ModelError("Original graph bytes in alignment ledger are corrupt")
    if output.resolve() in {aligned.resolve(), ledger.resolve()}:
        raise ModelError("Undo output must not overwrite alignment artifacts")
    atomic_text(output.resolve(), original.decode("utf-8"))
    load_graph(output)
