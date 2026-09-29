"""Graph and impact-report comparison."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from .model import Graph


def graph_diff(before: Graph, after: Graph) -> dict[str, Any]:
    old_nodes = {node.id: asdict(node) for node in before.nodes}
    new_nodes = {node.id: asdict(node) for node in after.nodes}
    old_edges = {edge.id: asdict(edge) for edge in before.edges}
    new_edges = {edge.id: asdict(edge) for edge in after.edges}

    def compare(old: dict[str, dict], new: dict[str, dict]) -> dict[str, Any]:
        common = set(old) & set(new)
        return {"added": [new[key] for key in sorted(set(new) - set(old))],
                "removed": [old[key] for key in sorted(set(old) - set(new))],
                "changed": [{"id": key, "before": old[key], "after": new[key]}
                            for key in sorted(common) if old[key] != new[key]]}

    nodes = compare(old_nodes, new_nodes)
    edges = compare(old_edges, new_edges)
    return {"version": 1, "nodes": nodes, "edges": edges,
            "summary": {"nodes_added": len(nodes["added"]), "nodes_removed": len(nodes["removed"]),
                        "nodes_changed": len(nodes["changed"]), "edges_added": len(edges["added"]),
                        "edges_removed": len(edges["removed"]), "edges_changed": len(edges["changed"])}}


def impact_diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    for label, value in (("before", before), ("after", after)):
        if not isinstance(value, dict) or value.get("version") != 1 or not isinstance(value.get("impacts"), list):
            raise ValueError(f"{label} is not a TraceCascade impact report")
    old = {item["node"]["id"]: item for item in before["impacts"]}
    new = {item["node"]["id"]: item for item in after["impacts"]}
    changed = []
    for key in sorted(set(old) & set(new)):
        if (old[key].get("classification"), old[key].get("score"), old[key].get("path")) != (
                new[key].get("classification"), new[key].get("score"), new[key].get("path")):
            changed.append({"node": key, "before": old[key], "after": new[key]})
    return {"version": 1,
            "added": [new[key] for key in sorted(set(new) - set(old))],
            "removed": [old[key] for key in sorted(set(old) - set(new))],
            "changed": changed,
            "summary": {"added": len(set(new) - set(old)), "removed": len(set(old) - set(new)),
                        "changed": len(changed)}}
