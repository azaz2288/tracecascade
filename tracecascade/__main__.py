"""TraceCascade command-line interface."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .engine import simulate
from .evidence import verify_evidence
from .model import ModelError, load_graph, load_scenario
from .report import atomic_text, markdown, write_json


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Simulate evidence-backed change impact")
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate")
    validate.add_argument("graph", type=Path)
    validate.add_argument("--scenario", type=Path)
    verify = commands.add_parser("verify-evidence")
    verify.add_argument("graph", type=Path)
    run = commands.add_parser("simulate")
    run.add_argument("graph", type=Path)
    run.add_argument("scenario", type=Path)
    run.add_argument("--json-out", type=Path, required=True)
    run.add_argument("--markdown-out", type=Path, required=True)
    run.add_argument("--max-depth", type=int)
    args = parser.parse_args(argv)
    try:
        graph = load_graph(args.graph)
        if args.command == "validate":
            if args.scenario:
                scenario = load_scenario(args.scenario, graph)
                print(f"Valid graph: {len(graph.nodes)} nodes, {len(graph.edges)} edges; "
                      f"scenario: {len(scenario.changes)} changes")
            else:
                print(f"Valid graph: {len(graph.nodes)} nodes, {len(graph.edges)} edges")
            return 0
        issues = verify_evidence(graph)
        if args.command == "verify-evidence":
            if issues:
                for issue in issues:
                    print(issue)
                return 1
            print(f"Verified evidence for {len(graph.edges)} edges")
            return 0
        if issues:
            raise ModelError(f"Evidence verification failed: {issues[0]}")
        if args.max_depth is not None and args.max_depth < 0:
            parser.error("--max-depth must be nonnegative")
        scenario = load_scenario(args.scenario, graph)
        destinations = (args.json_out.resolve(), args.markdown_out.resolve())
        protected = {graph.path, scenario.path,
                     *(graph.root.joinpath(*edge.evidence.source.split("/")).resolve()
                       for edge in graph.edges)}
        if destinations[0] == destinations[1]:
            raise ModelError("JSON and Markdown output paths must differ")
        if any(destination in protected for destination in destinations):
            raise ModelError("Output paths cannot overwrite graph, scenario or evidence sources")
        result = simulate(graph, scenario, args.max_depth)
        write_json(args.json_out, result)
        atomic_text(args.markdown_out, markdown(result))
        print(f"Affected {result['summary']['affected_nodes']} nodes: "
              f"{result['summary']['confirmed_impacts']} confirmed, "
              f"{result['summary']['likely_impacts']} likely, "
              f"{result['summary']['review_required']} need review")
        return 0
    except (ModelError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
