"""Gallery cards draw each example from its own case and state its size and difficulty by a fixed rule."""

from __future__ import annotations

from olga_companion import example_diagram as d, examples


def _spec(**over):
    spec = {
        "nodes": [{"label": "IN", "kind": "source"}, {"label": "OUT", "kind": "sink"}],
        "flowpaths": [{"label": "P", "from": "IN", "to": "OUT", "pipes": [{"label": "A", "length_m": 100.0, "elevation_m": 20.0}]}],
        "thermal": {"model": "adiabatic"},
    }
    spec.update(over)
    return spec


def test_a_spec_gives_nodes_profile_and_valves() -> None:
    spec = _spec(equipment=[{"kind": "valve", "label": "V", "flowpath": "P", "pipe": "A", "position": 1.0, "schedule": [{"time_s": 0.0, "opening": 1.0}]}])
    model = d.diagram_from_spec(spec)
    assert [n["kind"] for n in model["nodes"]] == ["source", "sink"]
    assert model["edges"][0]["segments"] == [{"id": "A", "length_m": 100.0, "rise_m": 20.0}]
    assert model["edges"][0]["valves"][0]["scheduled"] is True
    assert model["scheduled_valves"] is True and model["thermal"] is False


def test_a_v2_centerline_becomes_length_and_rise() -> None:
    spec = _spec(flowpaths=[{"label": "P", "from": "IN", "to": "OUT", "pipes": [{"label": "A", "centerline_m": [[0, 0, 0], [30, 0, 40]]}]}])
    assert d.diagram_from_spec(spec)["edges"][0]["segments"][0] == {"id": "A", "length_m": 50.0, "rise_m": 40.0}


def test_difficulty_rule() -> None:
    assert d.card_facts(d.diagram_from_spec(_spec())) == {"components": 3, "difficulty": "beginner"}
    cooled = d.diagram_from_spec(_spec(thermal={"model": "ambient_h_given"}))
    assert d.card_facts(cooled)["difficulty"] == "intermediate"
    hard = _spec(
        nodes=[{"label": n, "kind": k} for n, k in [("A", "source"), ("B", "source"), ("M1", "junction"), ("M2", "junction"), ("S", "sink")]],
        flowpaths=[
            {"label": "1", "from": "A", "to": "M1", "pipes": [{"label": "a", "length_m": 1.0, "elevation_m": 0.0}]},
            {"label": "2", "from": "B", "to": "M1", "pipes": [{"label": "b", "length_m": 1.0, "elevation_m": 0.0}]},
            {"label": "3", "from": "M1", "to": "M2", "pipes": [{"label": "c", "length_m": 1.0, "elevation_m": 0.0}]},
            {"label": "4", "from": "M2", "to": "S", "pipes": [{"label": "d", "length_m": 1.0, "elevation_m": 0.0}]},
        ],
    )
    assert d.card_facts(d.diagram_from_spec(hard))["difficulty"] == "advanced"


def test_a_network_is_drawn_by_flow_direction() -> None:
    model = d.diagram_from_network(
        {"nodes": [{"id": "N1", "kind": "TERMINAL"}, {"id": "N2", "kind": "TERMINAL"}], "edges": [{"source": "N1", "target": "N2", "label": "FP"}]}
    )
    assert [n["kind"] for n in model["nodes"]] == ["source", "sink"]
    assert model["edges"][0]["id"] == "FP"


def test_every_gallery_example_carries_a_drawing_and_facts() -> None:
    for row in examples.list_examples():
        assert row["diagram"] and row["diagram"]["nodes"] and row["diagram"]["edges"], row["id"]
        assert row["components"] >= 3 and row["difficulty"] in {"beginner", "intermediate", "advanced"}
        names = {n["id"] for n in row["diagram"]["nodes"]}
        assert all(e["from"] in names and e["to"] in names for e in row["diagram"]["edges"]), row["id"]


def test_every_example_has_a_run_time_measured_on_the_reference_pc() -> None:
    for row in examples.list_examples():
        assert isinstance(row["measured_run_s"], (int, float)) and row["measured_run_s"] > 0, row["id"]


def test_the_sidecar_checks_the_examples_in_the_background_at_start(monkeypatch) -> None:
    from olga_companion import sidecar_local_api

    calls = []
    monkeypatch.setattr(examples, "list_examples", lambda: calls.append(1) or [])
    sidecar_local_api._warm_examples()
    assert calls == [1]
    monkeypatch.setattr(examples, "list_examples", lambda: (_ for _ in ()).throw(OSError("busy")))
    sidecar_local_api._warm_examples()
