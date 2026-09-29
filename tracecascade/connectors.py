"""Read-only source connectors for local Python and GitHub snapshots."""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
from pathlib import Path, PurePosixPath
from urllib.parse import quote
from urllib.request import Request, urlopen

from .model import ModelError
from .report import atomic_text


REPOSITORY = re.compile(r"[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}\Z")


def _node_id(relative: str) -> str:
    stem = relative.removesuffix(".py").replace("/__init__", "").strip("/") or "root"
    slug = re.sub(r"[^a-z0-9]+", "_", stem.lower()).strip("_") or "module"
    return f"py_{slug[:48]}_{hashlib.sha256(relative.encode()).hexdigest()[:8]}"


def scan_python(root: Path, output: Path, max_files: int = 10_000) -> dict:
    root, output = root.resolve(), output.resolve()
    if not root.is_dir() or output.parent != root or output.suffix.lower() != ".json":
        raise ModelError("Python graph output must be a .json file directly inside the scanned directory")
    paths = []
    for path in root.rglob("*.py"):
        if any(part in {".git", ".venv", "venv", "__pycache__"} for part in path.relative_to(root).parts):
            continue
        if path.is_symlink():
            raise ModelError(f"Python source is a symbolic link: {path}")
        paths.append(path)
        if len(paths) > max_files:
            raise ModelError(f"Python scan exceeds {max_files} files")
    modules = {}
    nodes = []
    for path in sorted(paths):
        relative = path.relative_to(root).as_posix()
        dotted = relative.removesuffix(".py").replace("/__init__", "").replace("/", ".")
        modules[dotted] = relative
        nodes.append({"id": _node_id(relative), "kind": "python-module", "title": relative,
                      "description": "Python module discovered by the read-only local connector."})
    edges = []
    seen = set()
    known_modules = sorted(modules, key=lambda module: (-len(module), module))
    for path in sorted(paths):
        relative = path.relative_to(root).as_posix()
        current_module = relative.removesuffix(".py").replace("/__init__", "").replace("/", ".")
        package_parts = current_module.split(".") if relative.endswith("/__init__.py") else current_module.split(".")[:-1]
        try:
            raw = path.read_bytes()
            text = raw.decode("utf-8")
            tree = ast.parse(text, filename=relative)
        except (OSError, UnicodeError, SyntaxError) as exc:
            raise ModelError(f"Cannot parse Python source {relative}: {exc}") from exc
        lines = text.splitlines()
        for item in ast.walk(tree):
            target_modules: list[str] = []
            if isinstance(item, ast.Import):
                for alias in item.names:
                    target = next((module for module in known_modules
                                   if alias.name == module or alias.name.startswith(module + ".")), None)
                    if target:
                        target_modules.append(target)
            elif isinstance(item, ast.ImportFrom):
                if item.level == 0 and item.module:
                    base = item.module
                elif item.level > 0 and item.level <= len(package_parts) + 1:
                    keep = len(package_parts) - item.level + 1
                    parts = package_parts[:keep]
                    if item.module:
                        parts.extend(item.module.split("."))
                    base = ".".join(parts)
                else:
                    base = ""
                if base:
                    for alias in item.names:
                        candidate = base if alias.name == "*" else f"{base}.{alias.name}"
                        target = next((module for module in known_modules
                                       if candidate == module or candidate.startswith(module + ".")), None)
                        if target is None:
                            target = next((module for module in known_modules
                                           if base == module or base.startswith(module + ".")), None)
                        if target:
                            target_modules.append(target)
            for target in target_modules:
                if target is None:
                    continue
                key = (relative, modules[target], item.lineno)
                if key in seen or relative == modules[target]:
                    continue
                seen.add(key)
                edge_id = f"import_{hashlib.sha256('|'.join(map(str, key)).encode()).hexdigest()[:16]}"
                edges.append({"id": edge_id, "from": _node_id(modules[target]), "to": _node_id(relative),
                              "relation": "imported-by", "status": "confirmed", "confidence": 1.0,
                              "evidence": {"source": relative, "quote": lines[item.lineno - 1].strip(),
                                           "line_start": item.lineno, "line_end": getattr(item, "end_lineno", item.lineno),
                                           "sha256": hashlib.sha256(raw).hexdigest()}})
    value = {"version": 1, "nodes": nodes, "edges": sorted(edges, key=lambda item: item["id"])}
    atomic_text(output, json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    return value


def github_snapshot(repository: str, output: Path, ref: str = "main", token: str | None = None,
                    max_files: int = 500, max_bytes: int = 20_000_000) -> dict:
    """Download a bounded text snapshot using GET-only GitHub API calls."""
    if (not REPOSITORY.fullmatch(repository) or not ref or len(ref) > 200
            or any(character.isspace() for character in ref) or max_files < 1 or max_bytes < 1):
        raise ModelError("GitHub repository or ref is invalid")
    output = output.resolve()
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ModelError("GitHub snapshot output must be an empty directory or not exist")
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "TraceCascade/0.2"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    tree_url = f"https://api.github.com/repos/{repository}/git/trees/{quote(ref, safe='')}?recursive=1"
    try:
        with urlopen(Request(tree_url, headers=headers, method="GET"), timeout=30) as response:
            tree = json.loads(response.read(max_bytes + 1))
    except Exception as exc:
        raise ModelError(f"Cannot read GitHub tree: {exc}") from exc
    if not isinstance(tree, dict) or tree.get("truncated") or not isinstance(tree.get("tree"), list):
        raise ModelError("GitHub tree is malformed or truncated")
    allowed = {".py", ".md", ".json", ".csv"}
    files = [item for item in tree["tree"] if isinstance(item, dict) and item.get("type") == "blob"
             and PurePosixPath(str(item.get("path", ""))).suffix.lower() in allowed]
    if len(files) > max_files:
        raise ModelError(f"GitHub snapshot exceeds {max_files} text files")
    total, manifest, downloads = 0, [], []
    for item in sorted(files, key=lambda value: value["path"]):
        relative = PurePosixPath(item["path"])
        if relative.is_absolute() or any(part in ("", ".", "..") for part in relative.parts):
            raise ModelError("GitHub tree contains an unsafe path")
        raw_url = f"https://raw.githubusercontent.com/{repository}/{quote(ref, safe='')}/{quote(relative.as_posix(), safe='/')}"
        raw_headers = {"User-Agent": headers["User-Agent"]}
        if token:
            raw_headers["Authorization"] = f"Bearer {token}"
        try:
            with urlopen(Request(raw_url, headers=raw_headers, method="GET"), timeout=30) as response:
                raw = response.read(max_bytes - total + 1)
        except Exception as exc:
            raise ModelError(f"Cannot read GitHub file {relative}: {exc}") from exc
        total += len(raw)
        if total > max_bytes:
            raise ModelError(f"GitHub snapshot exceeds {max_bytes} bytes")
        try:
            raw.decode("utf-8")
        except UnicodeError as exc:
            raise ModelError(f"GitHub file is not UTF-8: {relative}") from exc
        downloads.append((relative, raw))
        manifest.append({"path": relative.as_posix(), "bytes": len(raw),
                         "sha256": hashlib.sha256(raw).hexdigest(), "github_blob": item.get("sha")})
    output.mkdir(parents=True, exist_ok=True)
    for relative, raw in downloads:
        destination = output.joinpath(*relative.parts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.is_symlink():
            raise ModelError(f"Snapshot destination is a symbolic link: {relative}")
        temporary = destination.with_name(f".{destination.name}.tmp")
        temporary.write_bytes(raw)
        os.replace(temporary, destination)
    metadata = {"version": 1, "repository": repository, "ref": ref, "files": manifest,
                "total_bytes": total, "read_only_remote": True}
    atomic_text(output / "tracecascade-snapshot.json", json.dumps(metadata, indent=2) + "\n")
    return metadata
