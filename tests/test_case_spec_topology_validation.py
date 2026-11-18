"""Verified v2 topology grammar constraints."""

from __future__ import annotations

import pytest

from olga_companion.agent.json_schema_validation import (
    SchemaValidationError,
    validate_json_schema,
)
from olga_companion.case_spec import validate_case_spec
from olga_companion import case_spec

from case_spec_v2_support import with_v2_inputs
from test_case_spec_validation import _error_codes, _supported_spec


def test_inline_schema_reaches_nested_dispatch_validation_without_ref_support() -> None:
    # Given: the current dispatch validator does not resolve Pydantic $refs/$defs.
    raw = _supported_spec()
    raw["flowpaths"][0]["pipes"][0]["rogue"] = "ignored-with-a-ref"
    inline_schema = case_spec.case_spec_inline_schema()

    # When / Then: the dispatch-compatible schema rejects the nested unknown field.
    assert "$defs" not in inline_schema
    with pytest.raises(SchemaValidationError, match="rogue"):
        validate_json_schema(inline_schema, raw)


def test_inline_schema_routes_bounded_equipment_to_capability_guidance() -> None:
    # Given: a bounded unsupported equipment proposal that needs precise guidance.
    raw = _supported_spec()
    raw["equipment"] = [{"kind": "controller", "label": "CTRL_A"}]

    # When: the dispatch-compatible schema validates the request envelope.
    validate_json_schema(case_spec.case_spec_inline_schema(), raw)

    # Then: semantic validation, not a generic unknown-field error, owns the refusal.
    result = validate_case_spec(with_v2_inputs(raw))
    assert result["errors"][0]["code"] == "unsupported_equipment"


def test_pipe_is_one_verified_straight_leg_with_exactly_two_endpoints() -> None:
    # Given: a PIPE trying to encode a polyline instead of ordered PIPE legs.
    raw = _supported_spec()
    raw["flowpaths"][0]["pipes"][0]["centerline_m"] = [
        [0, 0, 0],
        [50, 0, 2.5],
        [100, 0, 5],
    ]

    # When: the v1 grammar is validated.
    result = validate_case_spec(with_v2_inputs(raw))

    # Then: the unverified representation is rejected before compilation.
    assert result["valid"] is False
    assert "invalid_geometry" in _error_codes(result)


def test_two_arm_junction_is_not_misrepresented_as_verified_star() -> None:
    # Given: a connected one-in/one-out node labelled as a JUNCTIONNODE.
    raw = _supported_spec()
    raw["nodes"] = [node for node in raw["nodes"] if node["label"] != "SINK_B"]
    raw["flowpaths"] = [flow for flow in raw["flowpaths"] if flow["to"] != "SINK_B"]

    # When: topology semantics are validated.
    result = validate_case_spec(with_v2_inputs(raw))

    # Then: v1 requires a 1-to-N split or N-to-1 merge with at least three arms.
    assert result["valid"] is False
    assert "invalid_topology" in _error_codes(result)


def test_many_to_many_junction_is_rejected_as_unsupported_topology() -> None:
    # Given: a junction with two incoming and two outgoing flowpaths.
    raw = _supported_spec()
    raw["nodes"].append(
        {"label": "SOURCE_B", "kind": "source", "pressure_pa": 2_100_000.0}
    )
    raw["flowpaths"].append(
        {
            "label": "INLET_B",
            "from": "SOURCE_B",
            "to": "TEE_A",
            "pipes": [
                {
                    "label": "PIPE_D",
                    "centerline_m": [[0, 50, 0], [100, 0, 5]],
                    "diameter_m": 0.1,
                    "sections": 4,
                }
            ],
        }
    )

    # When: the verified star grammar is applied.
    result = validate_case_spec(with_v2_inputs(raw))

    # Then: ambiguous MIXTERM/FLOWTERM assignment fails closed.
    assert result["valid"] is False
    assert "invalid_topology" in _error_codes(result)


def test_junction_arm_count_is_capped_by_verified_vendor_evidence() -> None:
    # Given: a star with seven arms where evidence supports at most six.
    raw = _supported_spec()
    for index in range(5):
        raw["nodes"].append(
            {
                "label": f"EXTRA_SINK_{index}",
                "kind": "sink",
                "pressure_pa": 800_000.0,
            }
        )
        raw["flowpaths"].append(
            {
                "label": f"EXTRA_BRANCH_{index}",
                "from": "TEE_A",
                "to": f"EXTRA_SINK_{index}",
                "pipes": [
                    {
                        "label": f"EXTRA_PIPE_{index}",
                        "centerline_m": [[100, 0, 5], [170, index * 10, index]],
                        "diameter_m": 0.05,
                        "sections": 2,
                    }
                ],
            }
        )

    # When: v1 topology is validated.
    result = validate_case_spec(with_v2_inputs(raw))

    # Then: the unsupported arm count is rejected explicitly.
    assert result["valid"] is False
    assert "invalid_topology" in _error_codes(result)


def test_boundary_nodes_have_exactly_one_flowpath_arm() -> None:
    # Given: one source fans out directly to a second sink.
    raw = _supported_spec()
    raw["nodes"].append({"label": "SINK_C", "kind": "sink", "pressure_pa": 700_000.0})
    raw["flowpaths"].append(
        {
            "label": "SOURCE_FANOUT",
            "from": "SOURCE_A",
            "to": "SINK_C",
            "pipes": [
                {
                    "label": "PIPE_D",
                    "centerline_m": [[0, 0, 0], [50, 50, 0]],
                    "diameter_m": 0.05,
                    "sections": 2,
                }
            ],
        }
    )

    # When: boundary cardinality is checked.
    result = validate_case_spec(with_v2_inputs(raw))

    # Then: fan-out must be represented by a verified junction, not a source.
    assert result["valid"] is False
    assert "invalid_topology" in _error_codes(result)


def test_directed_cycles_are_outside_the_verified_v1_matrix() -> None:
    # Given: valid star degrees arranged around a directed junction cycle.
    def pipe(label: str, start: list[float], end: list[float]) -> list[dict]:
        return [
            {
                "label": label,
                "centerline_m": [start, end],
                "diameter_m": 0.1,
                "sections": 2,
            }
        ]

    raw = {
        "version": "1",
        "nodes": [
            {"label": "SRC", "kind": "source", "pressure_pa": 2_000_000.0},
            {"label": "J1", "kind": "junction"},
            {"label": "J2", "kind": "junction"},
            {"label": "J3", "kind": "junction"},
            {"label": "S1", "kind": "sink", "pressure_pa": 1_000_000.0},
            {"label": "S2", "kind": "sink", "pressure_pa": 900_000.0},
        ],
        "flowpaths": [
            {
                "label": "F0",
                "from": "SRC",
                "to": "J1",
                "pipes": pipe("P0", [-1, 0, 0], [0, 0, 0]),
            },
            {
                "label": "F1",
                "from": "J1",
                "to": "J2",
                "pipes": pipe("P1", [0, 0, 0], [1, 0, 0]),
            },
            {
                "label": "F2",
                "from": "J2",
                "to": "J3",
                "pipes": pipe("P2", [1, 0, 0], [0.5, 1, 0]),
            },
            {
                "label": "F3",
                "from": "J3",
                "to": "J1",
                "pipes": pipe("P3", [0.5, 1, 0], [0, 0, 0]),
            },
            {
                "label": "F4",
                "from": "J2",
                "to": "S1",
                "pipes": pipe("P4", [1, 0, 0], [2, 0, 0]),
            },
            {
                "label": "F5",
                "from": "J3",
                "to": "S2",
                "pipes": pipe("P5", [0.5, 1, 0], [1, 2, 0]),
            },
        ],
        "pvt_reference": "fluid.tab",
        "integration": {"end_time_s": 3600},
        "outputs": ["PT"],
    }

    # When: the verified topology subset is checked.
    result = validate_case_spec(with_v2_inputs(raw))

    # Then: compilation is disabled instead of claiming unverified cyclic grammar.
    assert result["valid"] is False
    assert "invalid_topology" in _error_codes(result)
