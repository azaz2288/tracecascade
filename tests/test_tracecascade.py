import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tracecascade.engine import simulate
from tracecascade.evidence import verify_evidence
from tracecascade.model import ModelError, load_graph, load_scenario
from tracecascade.report import markdown


def write_case(root: Path, graph: dict, scenario: dict, evidence: str = "A feeds B.\nB feeds C.\n"):
    (root / "evidence.md").write_text(evidence, encoding="utf-8")
    graph_path = root / "graph.json"
    scenario_path = root / "scenario.json"
    graph_path.write_text(json.dumps(graph), encoding="utf-8")
    scenario_path.write_text(json.dumps(scenario), encoding="utf-8")
    return graph_path, scenario_path


def base_graph():
    return {"version": 1, "nodes": [
        {"id": "a", "kind": "field", "title": "A", "description": "Changed source"},
        {"id": "b", "kind": "job", "title": "B", "description": "Middle job"},
        {"id": "c", "kind": "report", "title": "C", "description": "Final report"}], "edges": [
        {"id": "ab", "from": "a", "to": "b", "relation": "feeds", "status": "confirmed", "confidence": 1,
         "evidence": {"source": "evidence.md", "quote": "A feeds B", "line_start": 1, "line_end": 1}},
        {"id": "bc", "from": "b", "to": "c", "relation": "feeds", "status": "inferred", "confidence": 0.6,
         "evidence": {"source": "evidence.md", "quote": "B feeds C", "line_start": 2, "line_end": 2}}]}


def base_scenario():
    return {"version": 1, "title": "Change A", "changes": [
        {"node": "a", "operation": "modify", "description": "Change the source definition"}]}


class ModelTests(unittest.TestCase):
    def test_rejects_unknown_nodes_duplicate_ids_and_unsafe_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            graph = base_graph()
            graph["edges"][0]["to"] = "missing"
            path, _ = write_case(root, graph, base_scenario())
            with self.assertRaisesRegex(ModelError, "unknown node"):
                load_graph(path)
            graph = base_graph()
            graph["nodes"][1]["id"] = "a"
            path.write_text(json.dumps(graph), encoding="utf-8")
            with self.assertRaisesRegex(ModelError, "unique"):
                load_graph(path)
            graph = base_graph()
            graph["edges"][0]["evidence"]["source"] = "../secret"
            path.write_text(json.dumps(graph), encoding="utf-8")
            with self.assertRaisesRegex(ModelError, "forbidden"):
                load_graph(path)

    def test_rejects_unknown_scenario_node(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            scenario = base_scenario()
            scenario["changes"][0]["node"] = "missing"
            graph_path, scenario_path = write_case(root, base_graph(), scenario)
            with self.assertRaisesRegex(ModelError, "unknown node"):
                load_scenario(scenario_path, load_graph(graph_path))

    def test_rejects_boolean_version(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            graph = base_graph()
            graph["version"] = True
            path, _ = write_case(root, graph, base_scenario())
            with self.assertRaisesRegex(ModelError, "version=1"):
                load_graph(path)


class EvidenceTests(unittest.TestCase):
    def test_evidence_passes_and_detects_quote_line_and_hash_drift(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            graph_path, _ = write_case(root, base_graph(), base_scenario())
            self.assertEqual(verify_evidence(load_graph(graph_path)), [])
            graph = base_graph()
            graph["edges"][0]["evidence"]["quote"] = "fabricated"
            graph_path.write_text(json.dumps(graph), encoding="utf-8")
            self.assertTrue(any("quote not found" in issue for issue in verify_evidence(load_graph(graph_path))))
            graph = base_graph()
            graph["edges"][0]["evidence"]["line_end"] = 99
            graph_path.write_text(json.dumps(graph), encoding="utf-8")
            self.assertTrue(any("exceeds" in issue for issue in verify_evidence(load_graph(graph_path))))
            graph = base_graph()
            graph["edges"][0]["evidence"]["sha256"] = "0" * 64
            graph_path.write_text(json.dumps(graph), encoding="utf-8")
            self.assertTrue(any("SHA-256" in issue for issue in verify_evidence(load_graph(graph_path))))


class EngineTests(unittest.TestCase):
    def test_propagates_with_classification_and_markdown_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            graph_path, scenario_path = write_case(root, base_graph(), base_scenario())
            graph = load_graph(graph_path)
            result = simulate(graph, load_scenario(scenario_path, graph))
            self.assertEqual([item["node"]["id"] for item in result["impacts"]], ["b", "c"])
            self.assertEqual(result["impacts"][0]["classification"], "confirmed-impact")
            self.assertEqual(result["impacts"][1]["classification"], "likely-impact")
            rendered = markdown(result)
            self.assertIn("A feeds B", rendered)
            self.assertIn("review", rendered.lower())

    def test_cycle_terminates_and_depth_limits(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            graph = base_graph()
            graph["edges"].append({"id": "ca", "from": "c", "to": "a", "relation": "feeds", "status": "confirmed",
                "confidence": 0.5, "evidence": {"source": "evidence.md", "quote": "B feeds C", "line_start": 2, "line_end": 2}})
            graph_path, scenario_path = write_case(root, graph, base_scenario())
            loaded = load_graph(graph_path)
            full = simulate(loaded, load_scenario(scenario_path, loaded))
            shallow = simulate(loaded, load_scenario(scenario_path, loaded), max_depth=1)
            self.assertEqual(len(full["impacts"]), 2)
            self.assertEqual([item["node"]["id"] for item in shallow["impacts"]], ["b"])
            with self.assertRaisesRegex(ValueError, "nonnegative"):
                simulate(loaded, load_scenario(scenario_path, loaded), max_depth=-1)

    def test_strongest_deterministic_path_wins(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            graph = base_graph()
            graph["edges"].append({"id": "ac", "from": "a", "to": "c", "relation": "direct", "status": "confirmed",
                "confidence": 0.9, "evidence": {"source": "evidence.md", "quote": "A feeds B", "line_start": 1, "line_end": 1}})
            graph_path, scenario_path = write_case(root, graph, base_scenario())
            loaded = load_graph(graph_path)
            result = simulate(loaded, load_scenario(scenario_path, loaded))
            c = next(item for item in result["impacts"] if item["node"]["id"] == "c")
            self.assertEqual([step["edge"] for step in c["path"]], ["ac"])

    def test_parallel_equal_edges_are_deterministic(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            graph = base_graph()
            graph["edges"].append(copy.deepcopy(graph["edges"][0]))
            graph["edges"][-1]["id"] = "ab_second"
            graph_path, scenario_path = write_case(root, graph, base_scenario())
            loaded = load_graph(graph_path)
            result = simulate(loaded, load_scenario(scenario_path, loaded))
            b = next(item for item in result["impacts"] if item["node"]["id"] == "b")
            self.assertEqual(b["path"][0]["edge"], "ab")

    def test_cli_end_to_end_and_evidence_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            graph_path, scenario_path = write_case(root, base_graph(), base_scenario())
            json_out, md_out = root / "report.json", root / "report.md"
            command = [sys.executable, "-m", "tracecascade", "simulate", str(graph_path), str(scenario_path),
                       "--json-out", str(json_out), "--markdown-out", str(md_out)]
            completed = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertTrue(json_out.is_file() and md_out.is_file())
            (root / "evidence.md").write_text("changed", encoding="utf-8")
            failed = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(failed.returncode, 2)
            self.assertIn("Evidence verification failed", failed.stderr)

    def test_cli_refuses_to_overwrite_inputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            graph_path, scenario_path = write_case(root, base_graph(), base_scenario())
            command = [sys.executable, "-m", "tracecascade", "simulate", str(graph_path), str(scenario_path),
                       "--json-out", str(graph_path), "--markdown-out", str(root / "report.md")]
            failed = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(failed.returncode, 2)
            self.assertIn("cannot overwrite", failed.stderr)
            self.assertEqual(load_graph(graph_path).nodes[0].id, "a")


if __name__ == "__main__":
    unittest.main()
