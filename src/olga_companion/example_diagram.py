"""What an example builds, as a small drawing model and a few facts for its gallery card.

Everything here is read from the example itself (its CaseSpec, or the network of the
toolkit case it installs), so the card cannot disagree with the case.
"""

from __future__ import annotations

import math
from typing import Any

_NODE_KINDS = {"source", "sink", "junction", "closed"}


def _pipe_length_rise(pipe: dict[str, Any]) -> tuple[float, float]:
    if "length_m" in pipe:
        return float(pipe["length_m"]), float(pipe.get("elevation_m") or 0.0)
    points = pipe.get("centerline_m") or []
    length = sum(math.dist(a, b) for a, b in zip(points, points[1:]))
    rise = float(points[-1][2]) - float(points[0][2]) if len(points) >= 2 else 0.0
    return length, rise


def diagram_from_spec(spec: dict[str, Any]) -> dict[str, Any]:
    """Drawing model for a CaseSpec: nodes, flowpaths with their pipe profile, valves, thermal."""
    nodes = [
        {"id": str(node["label"]), "kind": str(node.get("kind")) if node.get("kind") in _NODE_KINDS else "junction"}
        for node in spec.get("nodes", [])
    ]
    valves: dict[str, list[dict[str, Any]]] = {}
    scheduled = False
    for item in spec.get("equipment", []) or []:
        if item.get("kind") != "valve":
            continue
        has_schedule = bool(item.get("schedule"))
        scheduled = scheduled or has_schedule
        valves.setdefault(str(item.get("flowpath")), []).append(
            {"pipe": str(item.get("pipe")), "position": float(item.get("position") or 0.0), "scheduled": has_schedule}
        )
    edges = []
    for path in spec.get("flowpaths", []):
        pipes = path.get("pipes", [])
        segments = []
        for pipe in pipes:
            length, rise = _pipe_length_rise(pipe)
            segments.append({"id": str(pipe.get("label")), "length_m": round(length, 3), "rise_m": round(rise, 3)})
        edges.append(
            {
                "id": str(path["label"]),
                "from": str(path["from"]),
                "to": str(path["to"]),
                "segments": segments,
                "valves": valves.get(str(path["label"]), []),
            }
        )
    thermal = (spec.get("thermal") or {}).get("model") not in (None, "adiabatic")
    return {"nodes": nodes, "edges": edges, "thermal": thermal, "scheduled_valves": scheduled}


def diagram_from_network(network: dict[str, Any]) -> dict[str, Any]:
    """Drawing model for a toolkit case read through the genkey network parser (no profile)."""
    edges = [
        {
            "id": str(edge.get("id") or edge.get("label")),
            "from": str(edge.get("source")),
            "to": str(edge.get("target")),
            "segments": [],
            "valves": [],
        }
        for edge in network.get("edges", [])
        if edge.get("source") and edge.get("target")
    ]
    targets = {edge["to"] for edge in edges}
    origins = {edge["from"] for edge in edges}
    nodes = []
    for node in network.get("nodes", []):
        node_id = str(node.get("id"))
        if str(node.get("kind")).upper() == "FLOWPATH":
            continue
        if str(node.get("kind")).upper() == "CLOSED":
            kind = "closed"
        elif node_id in origins and node_id not in targets:
            kind = "source"
        elif node_id in targets and node_id not in origins:
            kind = "sink"
        else:
            kind = "junction"
        nodes.append({"id": node_id, "kind": kind})
    return {"nodes": nodes, "edges": edges, "thermal": False, "scheduled_valves": False}


def card_facts(diagram: dict[str, Any]) -> dict[str, Any]:
    """Component count and difficulty, by the rule shown in the gallery legend.

    Components are nodes, pipes and valves. Beginner: one flowpath, at most two pipes, no
    valve, no heat loss. Advanced: twelve or more components, two or more junctions, or a
    valve schedule together with heat loss. Everything else is Intermediate.
    """
    pipes = sum(max(1, len(edge["segments"])) for edge in diagram["edges"])
    valves = sum(len(edge["valves"]) for edge in diagram["edges"])
    components = len(diagram["nodes"]) + pipes + valves
    junctions = sum(1 for node in diagram["nodes"] if node["kind"] == "junction")
    if components >= 12 or junctions >= 2 or (diagram["scheduled_valves"] and diagram["thermal"]):
        level = "advanced"
    elif len(diagram["edges"]) == 1 and pipes <= 2 and valves == 0 and not diagram["thermal"]:
        level = "beginner"
    else:
        level = "intermediate"
    return {"components": components, "difficulty": level}
