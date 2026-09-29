"""Deterministic, cycle-safe change-impact propagation."""

from __future__ import annotations

import hashlib
import heapq
from dataclasses import asdict
from typing import Any

from .model import Edge, Graph, Scenario


def _classification(score: float, confirmed: bool) -> str:
    if confirmed and score >= 0.8:
        return "confirmed-impact"
    if score >= 0.5:
        return "likely-impact"
    return "review-required"


def simulate(graph: Graph, scenario: Scenario, max_depth: int | None = None) -> dict[str, Any]:
    """Find the strongest explainable path from any changed node to every reachable node."""
    if max_depth is not None and (type(max_depth) is not int or max_depth < 0):
        raise ValueError("max_depth must be a nonnegative integer")
    nodes = {node.id: node for node in graph.nodes}
    outgoing: dict[str, list[Edge]] = {node_id: [] for node_id in nodes}
    for edge in graph.edges:
        outgoing[edge.source].append(edge)
    for edges in outgoing.values():
        edges.sort(key=lambda edge: (edge.target, edge.id))
    depth_limit = min(max_depth if max_depth is not None else max(len(nodes) - 1, 0), max(len(nodes) - 1, 0))
    best: dict[str, tuple[float, tuple[str, ...], tuple[Edge, ...], str]] = {}
    queue: list[tuple[float, tuple[str, ...], str, tuple[str, ...], tuple[Edge, ...], str]] = []
    changed = {change.node for change in scenario.changes}
    for change in sorted(scenario.changes, key=lambda item: item.node):
        heapq.heappush(queue, (-1.0, (change.node,), change.node, (), (), change.node))
    while queue:
        negative_score, path_nodes, current, queued_signature, path_edges, origin = heapq.heappop(queue)
        score = -negative_score
        current_best = best.get(current)
        if current not in changed and current_best is not None and (score, queued_signature) != (current_best[0], current_best[1]):
            continue
        for edge in outgoing[current]:
            if edge.target in path_nodes or len(path_edges) >= depth_limit:
                continue
            new_score = score * edge.confidence
            new_nodes = (*path_nodes, edge.target)
            new_edges = (*path_edges, edge)
            signature = tuple(item.id for item in new_edges)
            prior = best.get(edge.target)
            if prior is not None and (new_score < prior[0] or (new_score == prior[0] and signature >= prior[1])):
                continue
            best[edge.target] = (new_score, signature, new_edges, origin)
            heapq.heappush(queue, (-new_score, new_nodes, edge.target, signature, new_edges, origin))
    impacts = []
    for node_id, (score, _, path_edges, origin) in best.items():
        if node_id in changed:
            continue
        confirmed = all(edge.status == "confirmed" for edge in path_edges)
        impacts.append({
            "node": asdict(nodes[node_id]),
            "origin": origin,
            "score": round(score, 6),
            "classification": _classification(score, confirmed),
            "all_relations_confirmed": confirmed,
            "depth": len(path_edges),
            "path": [{"edge": edge.id, "from": edge.source, "to": edge.target,
                      "relation": edge.relation, "status": edge.status,
                      "confidence": edge.confidence, "evidence": asdict(edge.evidence)}
                     for edge in path_edges],
        })
    order = {"confirmed-impact": 0, "likely-impact": 1, "review-required": 2}
    impacts.sort(key=lambda item: (order[item["classification"]], -item["score"], item["node"]["id"]))
    return {
        "version": 1,
        "graph_sha256": hashlib.sha256(graph.raw_bytes).hexdigest(),
        "scenario_sha256": hashlib.sha256(scenario.raw_bytes).hexdigest(),
        "scenario": {"title": scenario.title, "changes": [asdict(change) for change in scenario.changes]},
        "summary": {
            "changed_nodes": len(changed),
            "affected_nodes": len(impacts),
            "confirmed_impacts": sum(item["classification"] == "confirmed-impact" for item in impacts),
            "likely_impacts": sum(item["classification"] == "likely-impact" for item in impacts),
            "review_required": sum(item["classification"] == "review-required" for item in impacts),
            "max_depth": depth_limit,
        },
        "impacts": impacts,
    }
