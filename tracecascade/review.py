"""Role-gated, hash-chained review decisions and graph application."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import tempfile
import time
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .model import Graph, ModelError, load_graph
from .report import atomic_text


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


@contextmanager
def _lock(path: Path, timeout: float = 5.0) -> Iterator[None]:
    lock_path = path.with_suffix(path.suffix + ".lock")
    if lock_path.is_symlink():
        raise ModelError("Review lock path is a symbolic link")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with lock_path.open("a+b") as stream:
            if stream.tell() == 0:
                stream.write(b"\0")
                stream.flush()
            deadline = time.monotonic() + timeout
            while True:
                try:
                    if os.name == "nt":
                        import msvcrt
                        stream.seek(0)
                        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError as exc:
                    if time.monotonic() >= deadline:
                        raise ModelError(f"Timed out waiting for review lock: {exc}") from exc
                    time.sleep(0.05)
            try:
                yield
            finally:
                if os.name == "nt":
                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
    except OSError as exc:
        raise ModelError(f"Cannot use review lock: {exc}") from exc


def load_policy(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_bytes())
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ModelError(f"Cannot read review policy: {exc}") from exc
    if (not isinstance(value, dict) or set(value) != {"version", "users", "roles", "require_hmac"}
            or value.get("version") != 1 or not isinstance(value["users"], dict)
            or not isinstance(value["roles"], dict) or type(value["require_hmac"]) is not bool):
        raise ModelError("Review policy is malformed")
    allowed = {"confirm", "reject", "expire"}
    for role, actions in value["roles"].items():
        if not isinstance(role, str) or not isinstance(actions, list) or not set(actions) <= allowed:
            raise ModelError("Review policy roles are malformed")
    if any(not isinstance(user, str) or role not in value["roles"] for user, role in value["users"].items()):
        raise ModelError("Review policy users are malformed")
    return value


def read_events(path: Path, secret: str | None = None, require_hmac: bool = False) -> list[dict[str, Any]]:
    if path.is_symlink():
        raise ModelError("Review log is a symbolic link")
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise ModelError(f"Cannot read review log: {exc}") from exc
    result, previous = [], "0" * 64
    for number, line in enumerate(lines, 1):
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ModelError(f"Review log line {number} is invalid JSON: {exc}") from exc
        if not isinstance(event, dict) or event.get("prev_hash") != previous:
            raise ModelError(f"Review log chain is broken at line {number}")
        required = {"version", "timestamp", "graph_sha256", "edge", "decision", "actor", "role",
                    "note", "prev_hash", "event_hash", "signature"}
        if (set(event) != required or event.get("version") != 1
                or not isinstance(event.get("timestamp"), str)
                or not isinstance(event.get("graph_sha256"), str) or len(event["graph_sha256"]) != 64
                or not isinstance(event.get("edge"), str) or not event["edge"]
                or event.get("decision") not in ("confirm", "reject", "expire")
                or not isinstance(event.get("actor"), str) or not event["actor"]
                or not isinstance(event.get("role"), str) or not event["role"]
                or not isinstance(event.get("note"), str) or not event["note"]
                or not isinstance(event.get("event_hash"), str)):
            raise ModelError(f"Review log event schema is invalid at line {number}")
        stored_hash = event.get("event_hash")
        stored_signature = event.get("signature")
        payload = {key: value for key, value in event.items() if key not in ("event_hash", "signature")}
        actual = hashlib.sha256(_canonical(payload)).hexdigest()
        if stored_hash != actual:
            raise ModelError(f"Review log event hash mismatch at line {number}")
        if require_hmac and not secret:
            raise ModelError("Review policy requires TRACECASCADE_AUDIT_KEY")
        if secret:
            signature = hmac.new(secret.encode("utf-8"), actual.encode("ascii"), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(str(stored_signature), signature):
                raise ModelError(f"Review log signature mismatch at line {number}")
        elif require_hmac or stored_signature is not None:
            raise ModelError(f"Cannot verify signed review event at line {number} without a key")
        result.append(event)
        previous = actual
    return result


def append_decision(graph: Graph, edge_id: str, decision: str, actor: str, note: str,
                    policy_path: Path, log_path: Path, secret: str | None = None) -> dict[str, Any]:
    policy = load_policy(policy_path)
    role = policy["users"].get(actor)
    if role is None or decision not in policy["roles"][role]:
        raise ModelError(f"Actor {actor} is not allowed to {decision}")
    if edge_id not in {edge.id for edge in graph.edges}:
        raise ModelError(f"Unknown edge {edge_id}")
    if decision not in ("confirm", "reject", "expire") or not note.strip() or len(note) > 1000:
        raise ModelError("Review decision or note is invalid")
    if policy["require_hmac"] and not secret:
        raise ModelError("Review policy requires TRACECASCADE_AUDIT_KEY")
    with _lock(log_path):
        events = read_events(log_path, secret, policy["require_hmac"])
        previous = events[-1]["event_hash"] if events else "0" * 64
        payload = {"version": 1, "timestamp": _now(), "graph_sha256": hashlib.sha256(graph.raw_bytes).hexdigest(),
                   "edge": edge_id, "decision": decision, "actor": actor, "role": role,
                   "note": note.strip(), "prev_hash": previous}
        event_hash = hashlib.sha256(_canonical(payload)).hexdigest()
        event = {**payload, "event_hash": event_hash,
                 "signature": hmac.new(secret.encode("utf-8"), event_hash.encode("ascii"), hashlib.sha256).hexdigest()
                 if secret else None}
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with log_path.open("a", encoding="utf-8", newline="") as stream:
                stream.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
        except OSError as exc:
            raise ModelError(f"Cannot append review event: {exc}") from exc
    return event


def apply_reviews(graph_path: Path, log_path: Path, policy_path: Path, output: Path,
                  secret: str | None = None) -> dict[str, Any]:
    graph = load_graph(graph_path)
    policy = load_policy(policy_path)
    events = read_events(log_path, secret, policy["require_hmac"])
    latest: dict[str, dict[str, Any]] = {}
    graph_digest = hashlib.sha256(graph.raw_bytes).hexdigest()
    for event in events:
        if event.get("graph_sha256") == graph_digest:
            latest[event["edge"]] = event
    edges = []
    for edge in graph.edges:
        event = latest.get(edge.id)
        if event and event["decision"] == "reject":
            continue
        status, confidence = edge.status, edge.confidence
        if event and event["decision"] == "confirm":
            status = "confirmed"
        elif event and event["decision"] == "expire":
            status, confidence = "inferred", min(confidence, 0.49)
        edges.append({"id": edge.id, "from": edge.source, "to": edge.target, "relation": edge.relation,
                      "status": status, "confidence": confidence, "evidence": asdict(edge.evidence)})
    value = {"version": 1, "nodes": [asdict(node) for node in graph.nodes], "edges": edges}
    if output.resolve() in {graph.path, log_path.resolve(), policy_path.resolve()}:
        raise ModelError("Reviewed graph output cannot overwrite its sources")
    atomic_text(output.resolve(), json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    load_graph(output)
    return value
