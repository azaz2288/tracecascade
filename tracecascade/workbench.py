"""Loopback-only human review workbench."""

from __future__ import annotations

import html
import hashlib
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .model import Graph, ModelError
from .review import append_decision, load_policy, read_events


def _esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def _page(graph: Graph, actor: str, policy_path: Path, log_path: Path,
          token: str, secret: str | None, message: str = "") -> str:
    policy = load_policy(policy_path)
    events = read_events(log_path, secret, policy["require_hmac"])
    graph_digest = hashlib.sha256(graph.raw_bytes).hexdigest()
    latest = {event["edge"]: event for event in events
              if event.get("graph_sha256") == graph_digest and event.get("edge")}
    cards = []
    for edge in graph.edges:
        decision = latest.get(edge.id)
        state = decision["decision"] if decision else "unreviewed"
        actions = "".join(
            f'<button name="decision" value="{action}">{action.title()}</button>'
            for action in ("confirm", "reject", "expire"))
        cards.append(
            f'<section><h2>{_esc(edge.source)} → {_esc(edge.target)}</h2>'
            f'<p><strong>{_esc(edge.relation)}</strong> · declared {_esc(edge.status)} · '
            f'confidence {_esc(edge.confidence)} · review <mark>{_esc(state)}</mark></p>'
            f'<blockquote>{_esc(edge.evidence.quote)}</blockquote>'
            f'<p><code>{_esc(edge.evidence.source)}:{edge.evidence.line_start}</code></p>'
            f'<form method="post" action="/review"><input type="hidden" name="token" value="{token}">'
            f'<input type="hidden" name="edge" value="{_esc(edge.id)}">'
            '<label>Reason <input name="note" required maxlength="1000"></label>'
            f'<div>{actions}</div></form></section>')
    return ("<!doctype html><html lang=\"en\"><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            "<title>TraceCascade Review</title><style>body{font:16px system-ui;max-width:1000px;margin:2rem auto;"
            "padding:0 1rem;background:#f4f6f8;color:#17202a}section{background:white;padding:1rem 1.3rem;"
            "margin:1rem 0;border-radius:.7rem;box-shadow:0 1px 5px #ccd}blockquote{border-left:4px solid #6b8afd;"
            "padding:.5rem 1rem;margin-left:0}input{width:min(34rem,90%);padding:.45rem;margin:.5rem}button{padding:.45rem .8rem;"
            "margin:.4rem}.message{background:#e8f5e9;padding:.7rem}code{overflow-wrap:anywhere}</style>"
            f'<h1>TraceCascade review</h1><p>Actor: <strong>{_esc(actor)}</strong>. Decisions append to a tamper-evident audit log.</p>'
            f'<p class="message">{_esc(message)}</p>{"".join(cards)}</html>')


def make_server(graph: Graph, actor: str, policy_path: Path, log_path: Path,
                secret: str | None = None, port: int = 8766) -> tuple[ThreadingHTTPServer, str]:
    policy = load_policy(policy_path)
    if actor not in policy["users"]:
        raise ModelError(f"Actor {actor} is not in the review policy")
    token = secrets.token_urlsafe(32)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            """Keep the local workbench quiet; callers can add their own process logging."""

        def _send(self, status: int, body: str) -> None:
            raw = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'")
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self) -> None:
            if urlsplit(self.path).path != "/":
                self.send_error(404)
                return
            self._send(200, _page(graph, actor, policy_path, log_path, token, secret))

        def do_POST(self) -> None:
            if urlsplit(self.path).path != "/review":
                self.send_error(404)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                self.send_error(400)
                return
            if not 0 < length <= 4096 or self.headers.get_content_type() != "application/x-www-form-urlencoded":
                self.send_error(400)
                return
            values = parse_qs(self.rfile.read(length).decode("utf-8"), strict_parsing=True)
            submitted = values.get("token", [""])[0]
            if not secrets.compare_digest(submitted, token):
                self.send_error(403)
                return
            origin = self.headers.get("Origin")
            if origin and origin not in {f"http://127.0.0.1:{self.server.server_port}", f"http://localhost:{self.server.server_port}"}:
                self.send_error(403)
                return
            try:
                event = append_decision(graph, values.get("edge", [""])[0], values.get("decision", [""])[0],
                                        actor, values.get("note", [""])[0], policy_path, log_path, secret)
                body = _page(graph, actor, policy_path, log_path, token, secret,
                             f"Recorded {event['decision']} for {event['edge']}.")
                self._send(200, body)
            except (ModelError, UnicodeError, ValueError) as exc:
                self._send(400, _page(graph, actor, policy_path, log_path, token, secret, f"Rejected: {exc}"))

    return ThreadingHTTPServer(("127.0.0.1", port), Handler), token
