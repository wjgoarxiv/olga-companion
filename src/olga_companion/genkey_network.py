from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .genkey_tool_runner import CommandResult

MAX_GRAPH_NODES = 600
MAX_GRAPH_EDGES = 600


def parse_network(
    path_value: str,
    *,
    require_path: Callable[[str], Path],
    run_tool: Callable[..., CommandResult],
    input_error: type[ValueError],
) -> dict[str, Any]:
    path = require_path(path_value)
    result = run_tool("parser", [str(path), "--json", "--compact"])
    if result.exit_code != 0 or not result.stdout.strip():
        raise input_error(f"Could not parse the network from {path.name}.")
    try:
        parsed = json.loads(result.stdout)
    except (json.JSONDecodeError, RecursionError):
        raise input_error(f"Unexpected parser output for {path.name}.") from None
    if not isinstance(parsed, dict):
        raise input_error(f"Unexpected parser output for {path.name}.")
    return network_from_parsed(parsed, str(path))


def network_from_parsed(parsed: dict[str, Any], path: str) -> dict[str, Any]:
    flowpaths = [item for item in parsed.get("flowpaths", []) if item.get("tag")]
    node_list = [item for item in parsed.get("nodes", []) if item.get("tag")]
    flowpath_tags = {item["tag"] for item in flowpaths}
    node_tags = {item["tag"] for item in node_list}
    nodes: list[dict[str, Any]] = [
        {
            "id": node["tag"],
            "label": node["tag"],
            "kind": (node.get("type") or "NODE").upper(),
        }
        for node in node_list
    ]
    flowpath_ends: dict[str, dict[str, str]] = {}
    for connection in parsed.get("connections", []):
        terminals = connection.get("TERMINALS", [])
        flowpath_side = next(
            (
                terminal
                for terminal in terminals
                if terminal.get("component") in flowpath_tags
            ),
            None,
        )
        node_side = next(
            (
                terminal
                for terminal in terminals
                if terminal.get("component") in node_tags
            ),
            None,
        )
        if flowpath_side and node_side:
            terminal = (flowpath_side.get("terminal") or "").upper()
            flowpath_ends.setdefault(flowpath_side["component"], {})[terminal] = (
                node_side["component"]
            )
    edges: list[dict[str, Any]] = []
    for flowpath in flowpaths:
        tag = flowpath["tag"]
        ends = flowpath_ends.get(tag, {})
        source, target = ends.get("INLET"), ends.get("OUTLET")
        if not (source and target):
            values = list(ends.values())
            source = source or (values[0] if values else None)
            target = target or (values[1] if len(values) > 1 else None)
        if source and target:
            edges.append(
                {
                    "source": source,
                    "target": target,
                    "label": tag,
                    "kind": "FLOWPATH",
                }
            )
        else:
            nodes.append({"id": tag, "label": tag, "kind": "FLOWPATH"})
            for node in ends.values():
                edges.append(
                    {
                        "source": tag,
                        "target": node,
                        "label": "",
                        "kind": "FLOWPATH",
                    }
                )
    counts = {
        "nodes": len(node_list),
        "flowpaths": len(flowpaths),
        "edges": len(edges),
    }
    truncated = False
    if len(nodes) > MAX_GRAPH_NODES:
        kept = {node["id"] for node in nodes[:MAX_GRAPH_NODES]}
        nodes = [node for node in nodes if node["id"] in kept]
        edges = [
            edge
            for edge in edges
            if edge["source"] in kept and edge["target"] in kept
        ]
        truncated = True
    if len(edges) > MAX_GRAPH_EDGES:
        edges = edges[:MAX_GRAPH_EDGES]
        truncated = True
    return {
        "path": path,
        "nodes": nodes,
        "edges": edges,
        "counts": counts,
        "truncated": truncated,
    }
