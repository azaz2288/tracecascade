"""Repeatable synthetic propagation benchmark."""

from __future__ import annotations

import argparse
import json
import tempfile
import time
import tracemalloc
from pathlib import Path

from tracecascade.engine import simulate
from tracecascade.model import load_graph, load_scenario


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--nodes", type=int, default=10_000)
    parser.add_argument("--topology", choices=("fanout", "chain"), default="fanout")
    parser.add_argument("--max-depth", type=int)
    args = parser.parse_args()
    if not 2 <= args.nodes <= 100_000:
        parser.error("--nodes must be from 2 to 100,000")
    if args.max_depth is not None and args.max_depth < 0:
        parser.error("--max-depth must be nonnegative")
    with tempfile.TemporaryDirectory(prefix="tracecascade-benchmark-") as temporary:
        root = Path(temporary)
        evidence = root / "evidence.md"
        evidence.write_text("Synthetic benchmark relation.\n", encoding="utf-8")
        pairs = ((0, index) for index in range(1, args.nodes)) if args.topology == "fanout" else (
            (index, index + 1) for index in range(args.nodes - 1))
        graph = {"version": 1,
                 "nodes": [{"id": f"n{index}", "kind": "item", "title": f"Node {index}",
                            "description": "Synthetic benchmark node"} for index in range(args.nodes)],
                 "edges": [{"id": f"e{index}", "from": f"n{origin}", "to": f"n{target}",
                            "relation": "feeds", "status": "confirmed", "confidence": 1.0,
                            "evidence": {"source": "evidence.md", "quote": "Synthetic benchmark relation",
                                         "line_start": 1, "line_end": 1}}
                           for index, (origin, target) in enumerate(pairs)]}
        scenario = {"version": 1, "title": "Synthetic root change",
                    "changes": [{"node": "n0", "operation": "modify", "description": "Benchmark"}]}
        graph_path, scenario_path = root / "graph.json", root / "scenario.json"
        graph_path.write_text(json.dumps(graph), encoding="utf-8")
        scenario_path.write_text(json.dumps(scenario), encoding="utf-8")
        loaded = load_graph(graph_path)
        loaded_scenario = load_scenario(scenario_path, loaded)
        tracemalloc.start()
        started = time.perf_counter()
        result = simulate(loaded, loaded_scenario, max_depth=args.max_depth)
        seconds = time.perf_counter() - started
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        print(json.dumps({"topology": args.topology, "nodes": args.nodes, "edges": args.nodes - 1,
                          "max_depth": args.max_depth,
                          "affected": result["summary"]["affected_nodes"],
                          "seconds": round(seconds, 3), "peak_python_bytes": peak}, indent=2))
        expected = args.nodes - 1
        if args.max_depth is not None:
            expected = min(expected, args.max_depth) if args.topology == 'chain' else expected if args.max_depth else 0
        if result["summary"]["affected_nodes"] != expected:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
