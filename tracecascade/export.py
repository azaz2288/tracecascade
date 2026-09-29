"""Export affected nodes as an explicit ReproForge execution plan."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .model import IDENTIFIER, ModelError, _relative_path
from .report import atomic_text


def export_reproforge(report_path: Path, mapping_path: Path, output: Path) -> dict[str, Any]:
    try:
        report = json.loads(report_path.read_bytes())
        mapping = json.loads(mapping_path.read_bytes())
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ModelError(f"Cannot read export input: {exc}") from exc
    if not isinstance(report, dict) or report.get("version") != 1 or not isinstance(report.get("impacts"), list):
        raise ModelError("Input is not a TraceCascade impact report")
    if (not isinstance(mapping, dict) or set(mapping) != {"version", "tasks"} or mapping.get("version") != 1
            or not isinstance(mapping["tasks"], dict)):
        raise ModelError("ReproForge mapping must contain version=1 and tasks")
    impacted: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(report["impacts"]):
        if (not isinstance(item, dict) or not isinstance(item.get("node"), dict)
                or not isinstance(item["node"].get("id"), str)
                or not IDENTIFIER.fullmatch(item["node"]["id"])
                or type(item.get("depth")) is not int or item["depth"] < 1
                or not isinstance(item.get("path"), list)):
            raise ModelError(f"Impact report item {index} is malformed")
        node_id = item["node"]["id"]
        if node_id in impacted:
            raise ModelError(f"Impact report repeats node {node_id}")
        impacted[node_id] = item
    missing = sorted(set(impacted) - set(mapping["tasks"]))
    if missing:
        raise ModelError(f"Missing ReproForge task mappings: {', '.join(missing)}")
    tasks = []
    for node_id in sorted(impacted, key=lambda key: (impacted[key]["depth"], key)):
        template = mapping["tasks"][node_id]
        if not isinstance(template, dict):
            raise ModelError(f"Task mapping for {node_id} is not an object")
        allowed = {"command", "inputs", "outputs", "timeout_seconds", "cache"}
        command = template.get("command")
        inputs = template.get("inputs", [])
        outputs = template.get("outputs", [])
        timeout = template.get("timeout_seconds", 300)
        cache = template.get("cache", False)
        if (set(template) - allowed or not isinstance(command, list) or not command
                or any(not isinstance(word, str) or not word for word in command)
                or not isinstance(inputs, list) or not isinstance(outputs, list)
                or type(timeout) is not int or not 1 <= timeout <= 3600 or type(cache) is not bool):
            raise ModelError(f"Task mapping for {node_id} has invalid fields")
        destinations: set[str] = set()
        input_dependencies: set[str] = set()
        for index, item in enumerate(inputs):
            if not isinstance(item, dict) or "as" not in item:
                raise ModelError(f"Task mapping for {node_id} has invalid input {index}")
            destination = _relative_path(item["as"], f"{node_id}.inputs[{index}].as")
            if destination in destinations:
                raise ModelError(f"Task mapping for {node_id} repeats input destination {destination}")
            destinations.add(destination)
            if set(item) == {"project", "as"}:
                _relative_path(item["project"], f"{node_id}.inputs[{index}].project")
            elif set(item) == {"task", "artifact", "as"}:
                dependency = item["task"]
                if not isinstance(dependency, str) or not IDENTIFIER.fullmatch(dependency):
                    raise ModelError(f"Task mapping for {node_id} has an invalid task input")
                _relative_path(item["artifact"], f"{node_id}.inputs[{index}].artifact")
                input_dependencies.add(dependency)
            else:
                raise ModelError(f"Task mapping for {node_id} has invalid input {index}")
        output_paths = [_relative_path(item, f"{node_id}.outputs") for item in outputs]
        if len(set(output_paths)) != len(output_paths):
            raise ModelError(f"Task mapping for {node_id} repeats an output")
        dependencies = []
        path = impacted[node_id].get("path", [])
        if path:
            final_step = path[-1]
            if not isinstance(final_step, dict) or not isinstance(final_step.get("from"), str):
                raise ModelError(f"Impact path for {node_id} is malformed")
            predecessor = final_step["from"]
            if predecessor in impacted:
                dependencies.append(predecessor)
        unknown_inputs = input_dependencies - set(impacted)
        if unknown_inputs:
            raise ModelError(f"Task mapping for {node_id} references tasks that are not exported: {', '.join(sorted(unknown_inputs))}")
        tasks.append({"id": node_id, **template, "depends_on": dependencies})
    dependencies = {task["id"]: set(task["depends_on"]) |
                    {item["task"] for item in task.get("inputs", []) if "task" in item}
                    for task in tasks}
    remaining = set(dependencies)
    while remaining:
        ready = {task_id for task_id in remaining if not (dependencies[task_id] & remaining)}
        if not ready:
            raise ModelError("Exported ReproForge tasks contain a dependency cycle")
        remaining -= ready
    value = {"version": 1, "tasks": tasks}
    if output.resolve() in {report_path.resolve(), mapping_path.resolve()}:
        raise ModelError("Export output cannot overwrite its inputs")
    atomic_text(output.resolve(), json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    return value
