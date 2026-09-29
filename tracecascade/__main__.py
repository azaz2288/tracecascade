"""TraceCascade command-line interface."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .alignment import align, undo
from .connectors import github_snapshot, scan_python
from .diffing import graph_diff, impact_diff
from .engine import simulate
from .evidence import verify_evidence
from .export import export_reproforge
from .ingest import ingest
from .model import ModelError, load_graph, load_scenario
from .report import atomic_text, markdown, write_json
from .review import append_decision, apply_reviews, load_policy, read_events
from .secure import backup, restore
from .workbench import make_server


def _json(path: Path) -> dict:
    try:
        value = json.loads(path.read_bytes())
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ModelError(f"Cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ModelError(f"JSON root must be an object: {path}")
    return value


def _parser() -> argparse.ArgumentParser:
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
    ingest_parser = commands.add_parser("ingest")
    ingest_parser.add_argument("sources", type=Path, nargs="+")
    ingest_parser.add_argument("--out", type=Path, required=True)
    align_parser = commands.add_parser("align")
    align_parser.add_argument("graph", type=Path)
    align_parser.add_argument("rules", type=Path)
    align_parser.add_argument("--out", type=Path, required=True)
    align_parser.add_argument("--ledger", type=Path, required=True)
    undo_parser = commands.add_parser("undo-align")
    undo_parser.add_argument("aligned", type=Path)
    undo_parser.add_argument("ledger", type=Path)
    undo_parser.add_argument("--out", type=Path, required=True)
    diff_parser = commands.add_parser("diff")
    diff_parser.add_argument("before", type=Path)
    diff_parser.add_argument("after", type=Path)
    diff_parser.add_argument("--out", type=Path, required=True)
    compare = commands.add_parser("compare-reports")
    compare.add_argument("before", type=Path)
    compare.add_argument("after", type=Path)
    compare.add_argument("--out", type=Path, required=True)
    review = commands.add_parser("review")
    review.add_argument("graph", type=Path)
    review.add_argument("edge")
    review.add_argument("decision", choices=("confirm", "reject", "expire"))
    review.add_argument("--actor", required=True)
    review.add_argument("--note", required=True)
    review.add_argument("--policy", type=Path, required=True)
    review.add_argument("--log", type=Path, required=True)
    apply_parser = commands.add_parser("apply-reviews")
    apply_parser.add_argument("graph", type=Path)
    apply_parser.add_argument("log", type=Path)
    apply_parser.add_argument("--policy", type=Path, required=True)
    apply_parser.add_argument("--out", type=Path, required=True)
    serve = commands.add_parser("serve-review")
    serve.add_argument("graph", type=Path)
    serve.add_argument("--actor", required=True)
    serve.add_argument("--policy", type=Path, required=True)
    serve.add_argument("--log", type=Path, required=True)
    serve.add_argument("--port", type=int, default=8766)
    scan = commands.add_parser("scan-python")
    scan.add_argument("root", type=Path)
    scan.add_argument("--out", type=Path, required=True)
    github = commands.add_parser("snapshot-github")
    github.add_argument("repository")
    github.add_argument("output", type=Path)
    github.add_argument("--ref", default="main")
    export = commands.add_parser("export-reproforge")
    export.add_argument("report", type=Path)
    export.add_argument("mapping", type=Path)
    export.add_argument("--out", type=Path, required=True)
    audit = commands.add_parser("verify-review-log")
    audit.add_argument("log", type=Path)
    audit.add_argument("--policy", type=Path, required=True)
    backup_parser = commands.add_parser("backup")
    backup_parser.add_argument("root", type=Path)
    backup_parser.add_argument("--out", type=Path, required=True)
    restore_parser = commands.add_parser("restore")
    restore_parser.add_argument("archive", type=Path)
    restore_parser.add_argument("output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    secret = os.environ.get("TRACECASCADE_AUDIT_KEY")
    try:
        if args.command == "ingest":
            result = ingest(args.sources, args.out)
            print(f"Ingested {len(result['nodes'])} nodes and {len(result['edges'])} edges")
            return 0
        if args.command == "align":
            result = align(args.graph, args.rules, args.out, args.ledger)
            print(f"Aligned {len(result['mapping'])} aliases; removed {len(result['removed_self_edges'])} self-edges")
            return 0
        if args.command == "undo-align":
            undo(args.aligned, args.ledger, args.out)
            print(f"Restored original graph to {args.out}")
            return 0
        if args.command == "diff":
            result = graph_diff(load_graph(args.before), load_graph(args.after))
            write_json(args.out, result)
            print(json.dumps(result["summary"], sort_keys=True))
            return 0
        if args.command == "compare-reports":
            result = impact_diff(_json(args.before), _json(args.after))
            write_json(args.out, result)
            print(json.dumps(result["summary"], sort_keys=True))
            return 0
        if args.command == "scan-python":
            result = scan_python(args.root, args.out)
            print(f"Scanned {len(result['nodes'])} Python modules and {len(result['edges'])} local imports")
            return 0
        if args.command == "snapshot-github":
            result = github_snapshot(args.repository, args.output, args.ref, os.environ.get("GITHUB_TOKEN"))
            print(f"Downloaded {len(result['files'])} files ({result['total_bytes']} bytes) without remote writes")
            return 0
        if args.command == "export-reproforge":
            result = export_reproforge(args.report, args.mapping, args.out)
            print(f"Exported {len(result['tasks'])} ReproForge tasks")
            return 0
        if args.command == "verify-review-log":
            policy = load_policy(args.policy)
            events = read_events(args.log, secret, policy["require_hmac"])
            print(f"Verified {len(events)} hash-chained review events")
            return 0
        if args.command in ("backup", "restore"):
            password = os.environ.get("TRACECASCADE_BACKUP_PASSWORD")
            if not password:
                raise ModelError("Set TRACECASCADE_BACKUP_PASSWORD; passwords are not accepted on the command line")
            result = backup(args.root, args.out, password) if args.command == "backup" else restore(args.archive, args.output, password)
            print(f"{args.command.title()} complete: {result['files']} files, {result['uncompressed_bytes']} bytes")
            return 0

        graph = load_graph(args.graph)
        if args.command == "validate":
            if args.scenario:
                scenario = load_scenario(args.scenario, graph)
                print(f"Valid graph: {len(graph.nodes)} nodes, {len(graph.edges)} edges; "
                      f"scenario: {len(scenario.changes)} changes")
            else:
                print(f"Valid graph: {len(graph.nodes)} nodes, {len(graph.edges)} edges")
            return 0
        if args.command == "review":
            event = append_decision(graph, args.edge, args.decision, args.actor, args.note,
                                    args.policy, args.log, secret)
            print(f"Recorded {event['decision']} for {event['edge']} as {event['actor']}")
            return 0
        if args.command == "apply-reviews":
            result = apply_reviews(args.graph, args.log, args.policy, args.out, secret)
            print(f"Wrote reviewed graph with {len(result['edges'])} edges")
            return 0
        if args.command == "serve-review":
            if not 0 <= args.port <= 65535:
                parser.error("--port must be from 0 to 65535")
            server, _ = make_server(graph, args.actor, args.policy, args.log, secret, args.port)
            with server:
                print(f"Review workbench: http://127.0.0.1:{server.server_port}/", flush=True)
                server.serve_forever()
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
                     *(graph.root.joinpath(*edge.evidence.source.split("/")).resolve() for edge in graph.edges)}
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
