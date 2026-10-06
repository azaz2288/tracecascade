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


class _Path:
    """Persistent path used to avoid quadratic tuple copies on deep graphs."""

    __slots__ = ("score", "parent", "edge", "origin", "node", "depth")

    def __init__(self, score: float, parent: _Path | None, edge: Edge | None,
                 origin: str, node: str) -> None:
        self.score = score
        self.parent = parent
        self.edge = edge
        self.origin = origin
        self.node = node
        self.depth = 0 if parent is None else parent.depth + 1

    def edge_ids(self) -> list[str]:
        result = []
        current: _Path | None = self
        while current is not None and current.edge is not None:
            result.append(current.edge.id)
            current = current.parent
        result.reverse()
        return result

    def edges(self) -> list[Edge]:
        result = []
        current: _Path | None = self
        while current is not None and current.edge is not None:
            result.append(current.edge)
            current = current.parent
        result.reverse()
        return result


class _PathOrder:
    """Heap key: lexicographic edge IDs, then origin, without retaining copied tuples."""

    __slots__ = ("path",)

    def __init__(self, path: _Path) -> None:
        self.path = path

    def __lt__(self, other: _PathOrder) -> bool:
        return (self.path.edge_ids(), self.path.origin) < (other.path.edge_ids(), other.path.origin)


def _bounded_paths(outgoing: dict[str, list[Edge]], changed: set[str],
                   depth_limit: int) -> dict[str, _Path]:
    """Layered relaxation: shallow weak prefixes must still be expanded.

    At each exact depth only the best score/edge-ID/origin prefix is needed.
    A previous (strictly shallower) score at least as strong dominates a new
    one. Positive edge weights <= 1 make cycles dominated by their prefix,
    including unit-weight cycles, so selected output paths remain simple.
    Equal scores prefer fewer hops, then edge IDs and origin. This bounded
    tie rule deliberately differs from the legacy unbounded heap rule.
    """
    frontier = {node: _Path(1.0, None, None, node, node) for node in sorted(changed)}
    best = dict(frontier)
    for _ in range(depth_limit):
        following: dict[str, _Path] = {}
        for current, path in frontier.items():
            for edge in outgoing[current]:
                if edge.target in changed:
                    continue
                candidate = _Path(path.score * edge.confidence, path, edge, path.origin, edge.target)
                earlier = best.get(edge.target)
                if earlier is not None and earlier.score >= candidate.score:
                    continue
                incumbent = following.get(edge.target)
                if (incumbent is None or candidate.score > incumbent.score
                        or (candidate.score == incumbent.score
                            and _PathOrder(candidate) < _PathOrder(incumbent))):
                    following[edge.target] = candidate
        if not following:
            break
        # Do not update best within a layer: every comparison above must be
        # against strictly shallower paths, independent of edge/input order.
        best.update(following)
        frontier = following
    return best


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
    best: dict[str, _Path] = {}
    queue: list[tuple[float, _PathOrder, str, _Path]] = []
    changed = {change.node for change in scenario.changes}
    if max_depth is not None:
        best = _bounded_paths(outgoing, changed, depth_limit)
    for change in sorted(scenario.changes, key=lambda item: item.node):
        path = _Path(1.0, None, None, change.node, change.node)
        if max_depth is None:
            heapq.heappush(queue, (-1.0, _PathOrder(path), change.node, path))
    while queue:
        _, _, current, path = heapq.heappop(queue)
        if current in best:
            continue
        best[current] = path
        if path.depth >= depth_limit:
            continue
        for edge in outgoing[current]:
            if edge.target in best or edge.target in changed:
                continue
            candidate = _Path(path.score * edge.confidence, path, edge, path.origin, edge.target)
            heapq.heappush(queue, (-candidate.score, _PathOrder(candidate), edge.target, candidate))
    impacts = []
    for node_id, path in best.items():
        if node_id in changed:
            continue
        path_edges = path.edges()
        confirmed = all(edge.status == "confirmed" for edge in path_edges)
        impacts.append({
            "node": asdict(nodes[node_id]),
            "origin": path.origin,
            "score": round(path.score, 6),
            "classification": _classification(path.score, confirmed),
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
