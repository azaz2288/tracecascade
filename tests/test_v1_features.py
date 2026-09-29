import http.client
import json
import os
import tempfile
import threading
import unittest
import urllib.parse
import concurrent.futures
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from zipfile import ZIP_DEFLATED, ZipFile

from tracecascade.alignment import align, undo
from tracecascade.connectors import github_snapshot, scan_python
from tracecascade.diffing import graph_diff, impact_diff
from tracecascade.engine import simulate
from tracecascade.evidence import verify_evidence
from tracecascade.export import export_reproforge
from tracecascade.ingest import ingest
from tracecascade.model import ModelError, load_graph, load_scenario
from tracecascade.review import append_decision, apply_reviews, read_events
from tracecascade.secure import backup, restore
from tracecascade.workbench import make_server


def fixture(root: Path):
    evidence = root / "evidence.md"
    evidence.write_text("A feeds B.\nB feeds C.\n", encoding="utf-8")
    graph = {"version": 1, "nodes": [
        {"id": "a", "kind": "field", "title": "A", "description": "source"},
        {"id": "b", "kind": "job", "title": "B", "description": "middle"},
        {"id": "c", "kind": "report", "title": "C", "description": "report"}], "edges": [
        {"id": "ab", "from": "a", "to": "b", "relation": "feeds", "status": "confirmed", "confidence": 1,
         "evidence": {"source": "evidence.md", "quote": "A feeds B", "line_start": 1, "line_end": 1}},
        {"id": "bc", "from": "b", "to": "c", "relation": "feeds", "status": "inferred", "confidence": 0.6,
         "evidence": {"source": "evidence.md", "quote": "B feeds C", "line_start": 2, "line_end": 2}}]}
    scenario = {"version": 1, "title": "Change A", "changes": [
        {"node": "a", "operation": "modify", "description": "change source"}]}
    graph_path, scenario_path = root / "graph.json", root / "scenario.json"
    graph_path.write_text(json.dumps(graph), encoding="utf-8")
    scenario_path.write_text(json.dumps(scenario), encoding="utf-8")
    return graph_path, scenario_path


class IngestionTests(unittest.TestCase):
    def test_markdown_and_csv_ingestion_produce_verified_graph(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            markdown = root / "system.md"
            markdown.write_text("\n".join([
                "@node source field | Source | Original field",
                "@node job pipeline | Job | Consuming job",
                "@edge source_job source feeds job confirmed 1.0 | source feeds job",
            ]) + "\n", encoding="utf-8")
            csv_path = root / "more.csv"
            csv_path.write_text(
                "type,id,kind,title,description,from,to,relation,status,confidence,quote\n"
                "node,report,report,Report,Final report,,,,,,\n"
                "edge,job_report,,,,job,report,feeds,inferred,0.7,job feeds report\n",
                encoding="utf-8")
            graph_path = root / "combined.json"
            result = ingest([markdown, csv_path], graph_path)
            self.assertEqual((len(result["nodes"]), len(result["edges"])), (3, 2))
            self.assertEqual(verify_evidence(load_graph(graph_path)), [])

    def test_conflicting_ingestion_fails(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first, second = root / "one.md", root / "two.md"
            first.write_text("@node a field | First | one\n", encoding="utf-8")
            second.write_text("@node a field | Second | two\n", encoding="utf-8")
            with self.assertRaisesRegex(ModelError, "Conflicting"):
                ingest([first, second], root / "out.json")

    def test_invalid_ingestion_does_not_replace_existing_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "invalid.csv"
            source.write_text(
                "type,id,kind,title,description,from,to,relation,status,confidence,quote\n"
                "node,BAD,field,Title,Description,,,,,,\n", encoding="utf-8")
            output = root / "graph.json"
            output.write_text("keep this file", encoding="utf-8")
            with self.assertRaisesRegex(ModelError, "must match"):
                ingest([source], output)
            self.assertEqual(output.read_text(encoding="utf-8"), "keep this file")


class AlignmentAndDiffTests(unittest.TestCase):
    def test_alignment_is_reversible_and_diff_is_explicit(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            graph_path, _ = fixture(root)
            rules = root / "rules.json"
            rules.write_text(json.dumps({"version": 1, "groups": [{"canonical": "a", "aliases": ["b"]}]}), encoding="utf-8")
            aligned, ledger, restored = root / "aligned.json", root / "ledger.json", root / "restored.json"
            original = graph_path.read_bytes()
            log = align(graph_path, rules, aligned, ledger)
            self.assertEqual(log["removed_self_edges"], ["ab"])
            change = graph_diff(load_graph(graph_path), load_graph(aligned))
            self.assertEqual(change["summary"]["nodes_removed"], 1)
            undo(aligned, ledger, restored)
            self.assertEqual(restored.read_bytes(), original)

    def test_impact_report_comparison(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            graph_path, scenario_path = fixture(root)
            graph = load_graph(graph_path)
            scenario = load_scenario(scenario_path, graph)
            full = simulate(graph, scenario)
            shallow = simulate(graph, scenario, max_depth=1)
            delta = impact_diff(shallow, full)
            self.assertEqual([item["node"]["id"] for item in delta["added"]], ["c"])


class ReviewTests(unittest.TestCase):
    def policy(self, root: Path, require_hmac=True):
        path = root / "policy.json"
        path.write_text(json.dumps({"version": 1, "users": {"alice": "reviewer", "bob": "viewer"},
            "roles": {"reviewer": ["confirm", "reject", "expire"], "viewer": []},
            "require_hmac": require_hmac}), encoding="utf-8")
        return path

    def test_signed_review_log_permissions_tamper_and_application(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            graph_path, _ = fixture(root)
            graph, policy, log = load_graph(graph_path), self.policy(root), root / "review.jsonl"
            secret = "strong-test-key"
            append_decision(graph, "bc", "confirm", "alice", "Checked with owner", policy, log, secret)
            self.assertEqual(len(read_events(log, secret, True)), 1)
            with self.assertRaisesRegex(ModelError, "not allowed"):
                append_decision(graph, "bc", "reject", "bob", "No", policy, log, secret)
            reviewed = root / "reviewed.json"
            value = apply_reviews(graph_path, log, policy, reviewed, secret)
            self.assertEqual(next(item for item in value["edges"] if item["id"] == "bc")["status"], "confirmed")
            text = log.read_text(encoding="utf-8")
            log.write_text(text.replace("Checked", "Tampered"), encoding="utf-8")
            with self.assertRaisesRegex(ModelError, "hash mismatch"):
                read_events(log, secret, True)

    def test_review_workbench_get_post_and_csrf(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            graph_path, _ = fixture(root)
            policy, log = self.policy(root, require_hmac=False), root / "review.jsonl"
            server, token = make_server(load_graph(graph_path), "alice", policy, log, port=0)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                connection = http.client.HTTPConnection("127.0.0.1", server.server_port)
                connection.request("GET", "/")
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                self.assertIn("Content-Security-Policy", response.headers)
                response.read()
                bad = urllib.parse.urlencode({"token": "wrong", "edge": "bc", "decision": "confirm", "note": "ok"})
                connection.request("POST", "/review", bad, {"Content-Type": "application/x-www-form-urlencoded"})
                self.assertEqual(connection.getresponse().status, 403)
                good = urllib.parse.urlencode({"token": token, "edge": "bc", "decision": "confirm", "note": "checked"})
                connection.request("POST", "/review", good, {"Content-Type": "application/x-www-form-urlencoded"})
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                response.read()
                self.assertEqual(len(read_events(log)), 1)
                connection.close()
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

    def test_workbench_ignores_decisions_for_a_different_graph(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            graph_path, _ = fixture(root)
            policy, log = self.policy(root, require_hmac=False), root / "review.jsonl"
            graph = load_graph(graph_path)
            append_decision(graph, "bc", "confirm", "alice", "old graph", policy, log)
            value = json.loads(graph_path.read_text(encoding="utf-8"))
            value["nodes"][0]["description"] = "new version"
            graph_path.write_text(json.dumps(value), encoding="utf-8")
            server, _ = make_server(load_graph(graph_path), "alice", policy, log, port=0)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                connection = http.client.HTTPConnection("127.0.0.1", server.server_port)
                connection.request("GET", "/")
                response = connection.getresponse()
                body = response.read().decode("utf-8")
                self.assertEqual(response.status, 200)
                self.assertIn("unreviewed", body)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

    def test_concurrent_review_writers_keep_one_valid_chain(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            graph_path, _ = fixture(root)
            graph, policy, log = load_graph(graph_path), self.policy(root), root / "review.jsonl"
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
                futures = [pool.submit(append_decision, graph, "bc", "confirm", "alice",
                                       f"review {index}", policy, log, "strong-test-key")
                           for index in range(24)]
                for future in futures:
                    future.result()
            events = read_events(log, "strong-test-key", True)
            self.assertEqual(len(events), 24)
            self.assertEqual(len({event["event_hash"] for event in events}), 24)


class ConnectorExportTests(unittest.TestCase):
    def test_python_scan_direction_and_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "pkg").mkdir()
            (root / "pkg" / "b.py").write_text("VALUE = 1\n", encoding="utf-8")
            (root / "pkg" / "a.py").write_text("import pkg.b\n", encoding="utf-8")
            output = root / "python-graph.json"
            result = scan_python(root, output)
            self.assertEqual(len(result["edges"]), 1)
            titles = {node["id"]: node["title"] for node in result["nodes"]}
            edge = result["edges"][0]
            self.assertEqual((titles[edge["from"]], titles[edge["to"]]), ("pkg/b.py", "pkg/a.py"))
            self.assertEqual(verify_evidence(load_graph(output)), [])

    def test_python_scan_resolves_relative_and_most_specific_imports(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "pkg").mkdir()
            (root / "pkg" / "__init__.py").write_text("", encoding="utf-8")
            (root / "pkg" / "b.py").write_text("VALUE = 1\n", encoding="utf-8")
            (root / "pkg" / "a.py").write_text("from . import b\n", encoding="utf-8")
            result = scan_python(root, root / "python-graph.json")
            titles = {node["id"]: node["title"] for node in result["nodes"]}
            relations = {(titles[edge["from"]], titles[edge["to"]]) for edge in result["edges"]}
            self.assertIn(("pkg/b.py", "pkg/a.py"), relations)
            self.assertNotIn(("pkg/__init__.py", "pkg/a.py"), relations)

    def test_reproforge_export_requires_every_mapping(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            graph_path, scenario_path = fixture(root)
            graph = load_graph(graph_path)
            report = simulate(graph, load_scenario(scenario_path, graph))
            report_path = root / "report.json"
            report_path.write_text(json.dumps(report), encoding="utf-8")
            mapping = root / "mapping.json"
            mapping.write_text(json.dumps({"version": 1, "tasks": {
                "b": {"command": ["python", "fix_b.py"], "inputs": [], "outputs": ["b.done"]},
                "c": {"command": ["python", "fix_c.py"], "inputs": [], "outputs": ["c.done"]}}}), encoding="utf-8")
            result = export_reproforge(report_path, mapping, root / "reproforge.json")
            self.assertEqual(result["tasks"][1]["depends_on"], ["b"])
            mapping.write_text(json.dumps({"version": 1, "tasks": {"b": {"command": []}}}), encoding="utf-8")
            with self.assertRaisesRegex(ModelError, "Missing"):
                export_reproforge(report_path, mapping, root / "bad.json")

    def test_github_snapshot_is_bounded_get_only_and_atomic_before_download(self):
        class Response:
            def __init__(self, payload):
                self.payload = payload

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self, size=-1):
                return self.payload[:size] if size >= 0 else self.payload

        tree = json.dumps({"truncated": False, "tree": [
            {"type": "blob", "path": "README.md", "sha": "abc"},
            {"type": "blob", "path": "ignored.bin", "sha": "def"}]}).encode()
        requests = []

        def opener(request, timeout):
            requests.append(request)
            return Response(tree if "api.github.com" in request.full_url else b"hello\n")

        with tempfile.TemporaryDirectory() as temporary, patch("tracecascade.connectors.urlopen", opener):
            root = Path(temporary) / "snapshot"
            result = github_snapshot("owner/repo", root, ref="release/v1", token="secret")
            self.assertEqual([item["path"] for item in result["files"]], ["README.md"])
            self.assertEqual((root / "README.md").read_bytes(), b"hello\n")
            self.assertTrue(all(request.method == "GET" for request in requests))
            self.assertEqual(requests[1].headers["Authorization"], "Bearer secret")
        with tempfile.TemporaryDirectory() as temporary:
            output_file = Path(temporary) / "file"
            output_file.write_text("keep", encoding="utf-8")
            with self.assertRaisesRegex(ModelError, "empty directory"):
                github_snapshot("owner/repo", output_file)
            self.assertEqual(output_file.read_text(encoding="utf-8"), "keep")


class SecureBackupTests(unittest.TestCase):
    def test_encrypted_backup_restore_and_wrong_password(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            project = base / "project"
            project.mkdir()
            (project / "graph.json").write_text('{"safe": true}\n', encoding="utf-8")
            (project / "nested").mkdir()
            (project / "nested" / "evidence.md").write_text("proof\n", encoding="utf-8")
            archive = base / "backup.enc"
            result = backup(project, archive, "correct horse battery")
            self.assertEqual(result["files"], 2)
            with self.assertRaisesRegex(ModelError, "wrong or archive was modified"):
                restore(archive, base / "wrong", "incorrect password")
            restored = base / "restored"
            result = restore(archive, restored, "correct horse battery")
            self.assertEqual(result["files"], 2)
            self.assertEqual((restored / "nested" / "evidence.md").read_text(encoding="utf-8"), "proof\n")

    def test_restore_rejects_modified_ciphertext_existing_file_and_unsafe_archive(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "project"
            project.mkdir()
            (project / "file.txt").write_text("safe", encoding="utf-8")
            archive = root / "backup.enc"
            backup(project, archive, "correct horse battery")
            envelope = json.loads(archive.read_text(encoding="utf-8"))
            ciphertext = bytearray(__import__("base64").b64decode(envelope["ciphertext"]))
            ciphertext[-1] ^= 1
            envelope["ciphertext"] = __import__("base64").b64encode(ciphertext).decode("ascii")
            archive.write_text(json.dumps(envelope), encoding="utf-8")
            with self.assertRaisesRegex(ModelError, "archive was modified"):
                restore(archive, root / "tampered", "correct horse battery")

            safe_archive = root / "safe.enc"
            backup(project, safe_archive, "correct horse battery")
            existing = root / "existing-file"
            existing.write_text("keep", encoding="utf-8")
            with self.assertRaisesRegex(ModelError, "empty directory"):
                restore(safe_archive, existing, "correct horse battery")
            self.assertEqual(existing.read_text(encoding="utf-8"), "keep")

            buffer = BytesIO()
            with ZipFile(buffer, "w", ZIP_DEFLATED) as zipped:
                zipped.writestr("../escape.txt", "unsafe")
            import base64
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
            from tracecascade.secure import _key
            salt, nonce = os.urandom(16), os.urandom(12)
            malicious = {"version": 1, "algorithm": "AES-256-GCM", "kdf": "scrypt-n16384-r8-p1",
                         "salt": base64.b64encode(salt).decode(), "nonce": base64.b64encode(nonce).decode(),
                         "ciphertext": base64.b64encode(AESGCM(_key("correct horse battery", salt)).encrypt(
                             nonce, buffer.getvalue(), b"tracecascade-backup-v1")).decode()}
            unsafe = root / "unsafe.enc"
            unsafe.write_text(json.dumps(malicious), encoding="utf-8")
            destination = root / "destination"
            with self.assertRaisesRegex(ModelError, "unsafe path"):
                restore(unsafe, destination, "correct horse battery")
            self.assertFalse(destination.exists())


if __name__ == "__main__":
    unittest.main()
