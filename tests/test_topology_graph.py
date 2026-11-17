"""F3 — the network is exposed as a {nodes, edges} graph for the topology map."""
import shutil
from pathlib import Path

import pytest

from olga_companion import genkey_static
from olga_companion.agent import tools

SAMPLES = Path(__file__).parent / "fixtures" / "cases"


def test_simple_pipeline_yields_two_nodes_one_edge():
    if not (SAMPLES / "simple_pipeline.genkey").exists():
        pytest.skip("sample unavailable")
    g = genkey_static.parse_network(str(SAMPLES / "simple_pipeline.genkey"))
    ids = {n["id"] for n in g["nodes"]}
    assert {"NODE_INLET", "NODE_OUTLET"} <= ids
    assert g["counts"]["nodes"] == 2
    # FLOWPATH_1 connects inlet → outlet as one edge
    e = next(e for e in g["edges"] if e["label"] == "FLOWPATH_1")
    assert e["source"] == "NODE_INLET" and e["target"] == "NODE_OUTLET"
    assert g["truncated"] is False


def test_network_from_parsed_is_pure_and_handles_dangling():
    parsed = {
        "flowpaths": [{"tag": "FP1"}, {"tag": "FP_DANGLE"}],
        "nodes": [{"tag": "N1", "type": "NODE"}, {"tag": "N2", "type": "JUNCTIONNODE"}],
        "connections": [
            {"TERMINALS": [{"component": "FP1", "terminal": "INLET"}, {"component": "N1", "terminal": "FLOWTERM_1"}]},
            {"TERMINALS": [{"component": "FP1", "terminal": "OUTLET"}, {"component": "N2", "terminal": "FLOWTERM_1"}]},
            {"TERMINALS": [{"component": "FP_DANGLE", "terminal": "INLET"}, {"component": "N1", "terminal": "FLOWTERM_2"}]},
        ],
    }
    g = genkey_static._network_from_parsed(parsed, "x.genkey")
    fp1 = next(e for e in g["edges"] if e["label"] == "FP1")
    assert (fp1["source"], fp1["target"]) == ("N1", "N2")
    # a flowpath with only one endpoint becomes its own vertex, still linked
    assert any(n["id"] == "FP_DANGLE" and n["kind"] == "FLOWPATH" for n in g["nodes"])
    assert any(e["source"] == "FP_DANGLE" and e["target"] == "N1" for e in g["edges"])


def test_dense_network_is_edge_bounded():
    # A few junctions carrying thousands of flowpaths must be bounded by edge count,
    # not just node count — otherwise a huge edge list floods the transcript/paint.
    n = genkey_static._MAX_GRAPH_EDGES + 2000
    parsed = {
        "flowpaths": [{"tag": f"FP{i}"} for i in range(n)],
        "nodes": [{"tag": "A", "type": "NODE"}, {"tag": "B", "type": "NODE"}],
        "connections": [
            c for i in range(n) for c in (
                {"TERMINALS": [{"component": f"FP{i}", "terminal": "INLET"}, {"component": "A", "terminal": "T"}]},
                {"TERMINALS": [{"component": f"FP{i}", "terminal": "OUTLET"}, {"component": "B", "terminal": "T"}]},
            )
        ],
    }
    g = genkey_static._network_from_parsed(parsed, "dense.genkey")
    assert len(g["edges"]) <= genkey_static._MAX_GRAPH_EDGES
    assert g["truncated"] is True
    assert g["counts"]["flowpaths"] == n  # true total still reported


def test_cap_does_not_truncate_a_network_graph():
    # The generic list-cap would drop the graph to 50 items and corrupt it; a
    # topology result must pass through whole (it's bounded in the backend).
    graph = {
        "path": "big.genkey",
        "nodes": [{"id": f"N{i}", "label": f"N{i}", "kind": "NODE"} for i in range(127)],
        "edges": [{"source": f"N{i}", "target": f"N{i+1}", "label": f"FP{i}", "kind": "FLOWPATH"} for i in range(126)],
        "counts": {"nodes": 127, "flowpaths": 126, "edges": 126},
        "truncated": False,
    }
    capped = tools._cap(graph)
    assert len(capped["nodes"]) == 127, "all nodes survive the cap"
    assert len(capped["edges"]) == 126, "all edges survive the cap"


def test_genkey_topology_tool_defaults_to_active(monkeypatch, tmp_path: Path):
    from olga_companion import workspace
    if not (SAMPLES / "simple_pipeline.genkey").exists():
        pytest.skip("sample unavailable")
    case = tmp_path / "simple_pipeline.genkey"
    shutil.copy2(SAMPLES / case.name, case)
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setattr(workspace, "active_path", lambda: str(case))
    out = tools._t_genkey_topology({})  # no path → active case
    assert out["counts"]["nodes"] == 2
    assert "genkey_topology" in tools.TOOLS
    assert "path" not in tools.TOOLS["genkey_topology"].parameters["required"]
