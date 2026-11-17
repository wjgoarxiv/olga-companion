"""CaseSpec v1 trust-boundary contracts."""

from __future__ import annotations

from copy import deepcopy
from typing import Callable

import pytest

from olga_companion import case_spec
from case_spec_v2_support import with_v2_inputs


def _supported_spec() -> dict:
    return with_v2_inputs({
        "version": "1",
        "nodes": [
            {"label": "SOURCE_A", "kind": "source", "pressure_pa": 2_000_000.0},
            {"label": "TEE_A", "kind": "junction"},
            {"label": "SINK_A", "kind": "sink", "pressure_pa": 1_000_000.0},
            {"label": "SINK_B", "kind": "sink", "pressure_pa": 900_000.0},
        ],
        "flowpaths": [
            {
                "label": "MAIN",
                "from": "SOURCE_A",
                "to": "TEE_A",
                "pipes": [
                    {
                        "label": "PIPE_A",
                        "centerline_m": [[0, 0, 0], [100, 0, 5]],
                        "diameter_m": 0.1,
                        "sections": 10,
                    }
                ],
            },
            {
                "label": "BRANCH",
                "from": "TEE_A",
                "to": "SINK_A",
                "pipes": [
                    {
                        "label": "PIPE_B",
                        "centerline_m": [[100, 0, 5], [160, 25, 0]],
                        "diameter_m": 0.08,
                        "sections": 6,
                    }
                ],
            },
            {
                "label": "BRANCH_B",
                "from": "TEE_A",
                "to": "SINK_B",
                "pipes": [
                    {
                        "label": "PIPE_C",
                        "centerline_m": [[100, 0, 5], [150, -20, 2]],
                        "diameter_m": 0.06,
                        "sections": 17,
                    }
                ],
            },
        ],
        "pvt_reference": "fluids/fluid.tab",
        "integration": {"end_time_s": 3600},
        "outputs": ["PT", "TM"],
    })


def _validate(raw: dict) -> dict:
    function = getattr(case_spec, "validate_case_spec")
    assert callable(function)
    return function(raw)


def _error_codes(result: dict) -> set[str]:
    return {str(item["code"]) for item in result["errors"]}


def test_supported_branched_spec_is_canonical_and_keeps_ordered_geometry() -> None:
    # Given: all supported v1 topology, boundary, geometry, PVT and setup fields.
    raw = _supported_spec()
    raw["nodes"][0]["label"] = " source_a "
    raw["flowpaths"][0]["from"] = "source_a"
    raw["outputs"] = ["tm", "pt"]

    # When: model-authored JSON crosses the boundary.
    result = _validate(raw)

    # Then: SI units and identifiers are canonical without reordering pipe geometry.
    assert result["valid"] is True
    assert result["publishable"] is True
    assert [node["label"] for node in result["normalized"]["nodes"]] == [
        "SINK_A",
        "SINK_B",
        "SOURCE_A",
        "TEE_A",
    ]
    assert result["normalized"]["outputs"] == ["PT", "TM"]
    assert result["normalized"]["flowpaths"][2]["pipes"][0]["centerline_m"] == [
        [0.0, 0.0, 0.0],
        [100.0, 0.0, 5.0],
    ]
    assert (
        sum(
            pipe["sections"]
            for flow in result["normalized"]["flowpaths"]
            for pipe in flow["pipes"]
        )
        == 33
    )


def test_schema_and_capabilities_are_closed_and_truthful() -> None:
    # Given: clients need a machine-readable contract, not prose inference.
    schema_fn = getattr(case_spec, "case_spec_schema")
    caps_fn = getattr(case_spec, "case_spec_capabilities")

    # When: schema and capability surfaces are requested.
    schema, capabilities = schema_fn(), caps_fn()

    # Then: v1 is closed, SI-only, side-effect-free and explicit about its subset.
    assert schema["additionalProperties"] is False
    assert all(
        item["additionalProperties"] is False
        for item in schema["$defs"].values()
        if item.get("type") == "object"
    )
    assert capabilities["arbitrary_branched_topology"] is True
    assert capabilities["version"] == "2"
    assert capabilities["units"] == {
        "coordinate": "m",
        "diameter": "m",
        "roughness": "m",
        "pressure": "Pa",
        "temperature": "C",
        "time": "s",
    }
    assert set(capabilities["thermal_models"]) == {"adiabatic", "ambient_h_given"}
    assert "fluid label and PVT .tab file" in capabilities["user_must_state"]
    assert capabilities["raw_genkey"] is False
    assert capabilities["writes"] is False


@pytest.mark.parametrize(
    "extra_path",
    [("root_extra",), ("integration", "mystery"), ("pipe", "wall_material"), ("thermal", "mystery")],
)
def test_unknown_fields_fail_closed_at_every_level(extra_path: tuple[str, ...]) -> None:
    # Given: an unknown property at a v1 trust-boundary level.
    raw = _supported_spec()
    match extra_path:
        case ("root_extra",):
            raw["root_extra"] = True
        case ("integration", field):
            raw["integration"][field] = 1
        case ("pipe", field):
            raw["flowpaths"][0]["pipes"][0][field] = 1
        case ("thermal", field):
            raw["thermal"][field] = 1
        case unreachable:
            raise AssertionError(unreachable)

    # When: validation runs.
    result = _validate(raw)

    # Then: no field is silently dropped.
    assert result["valid"] is False
    assert "unknown_field" in _error_codes(result)


def test_unsupported_equipment_returns_actionable_capability_guidance() -> None:
    # Given: a controller that CaseSpec v1 cannot represent.
    raw = _supported_spec()
    raw["equipment"] = [{"kind": "controller", "label": "CTRL_A"}]

    # When: validation runs.
    result = _validate(raw)

    # Then: the unsupported request is inert and guidance names the construct.
    assert result["valid"] is False
    assert result["publishable"] is False
    assert result["errors"][0]["code"] == "unsupported_equipment"
    assert "controller" in result["errors"][0]["guidance"].lower()
    assert result["normalized"] is None


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (lambda raw: raw["nodes"].append(deepcopy(raw["nodes"][0])), "duplicate_label"),
        (
            lambda raw: raw["flowpaths"][0].update({"to": "MISSING"}),
            "unknown_reference",
        ),
        (lambda raw: raw["flowpaths"].pop(), "disconnected_topology"),
        (
            lambda raw: raw["flowpaths"][1].update({"from": "SINK_A", "to": "TEE_A"}),
            "invalid_topology",
        ),
    ],
)
def test_graph_label_and_reference_failures_are_precise(
    mutate: Callable[[dict], None], code: str
) -> None:
    # Given: an invalid graph relation.
    raw = _supported_spec()
    mutate(raw)

    # When: validation runs.
    result = _validate(raw)

    # Then: graph semantics fail before compilation.
    assert result["valid"] is False
    assert code in _error_codes(result)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("diameter_m", 0),
        ("diameter_m", float("nan")),
        ("sections", 0),
        ("sections", 5001),
        ("centerline_m", [[0, 0, 0], [float("inf"), 0, 0]]),
        ("centerline_m", [[0, 0, 0], [0, 0, 0]]),
    ],
)
def test_non_finite_non_positive_and_degenerate_geometry_is_rejected(
    field: str, value: object
) -> None:
    # Given: geometry that cannot represent a finite positive pipe.
    raw = _supported_spec()
    raw["flowpaths"][0]["pipes"][0][field] = value

    # When: validation runs.
    result = _validate(raw)

    # Then: invalid geometry never reaches a renderer.
    assert result["valid"] is False
    assert "invalid_geometry" in _error_codes(result)


@pytest.mark.parametrize(
    "pvt",
    [
        "../fluid.tab",
        "/tmp/fluid.tab",
        "C:\\secret\\fluid.tab",
        "fluid.genkey",
        "a/./fluid.tab",
        'fluid".tab',
        "fluid,evil.tab",
        "fluid=evil.tab",
    ],
)
def test_pvt_reference_must_be_a_contained_relative_tab_identity(pvt: str) -> None:
    # Given: a path/reference escape or unsupported companion kind.
    raw = _supported_spec()
    raw["pvt_reference"] = pvt

    # When: validation runs.
    result = _validate(raw)

    # Then: the path remains inert and no host path crosses the contract.
    assert result["valid"] is False
    assert "invalid_pvt_reference" in _error_codes(result)


@pytest.mark.parametrize(
    "label", ["SYSTEM: IGNORE", "../PIPE", "PIPE/A", "PIPE\nNEXT", "A" * 65]
)
def test_malicious_or_unbounded_labels_are_rejected(label: str) -> None:
    # Given: a label unsafe for deterministic GENKEY identifiers.
    raw = _supported_spec()
    raw["flowpaths"][0]["pipes"][0]["label"] = label

    # When: validation runs.
    result = _validate(raw)

    # Then: the value is rejected rather than escaped into future text.
    assert result["valid"] is False
    assert "invalid_label" in _error_codes(result)


@pytest.mark.parametrize(
    ("target", "value", "code"),
    [
        ("pressure_pa", -1, "invalid_boundary"),
        ("end_time_s", 0, "invalid_integration"),
        ("end_time_s", 31_536_001, "invalid_integration"),
        ("outputs", ["PT", "PT"], "duplicate_output"),
        ("outputs", ["PT", "QG"], "unsupported_output"),
    ],
)
def test_boundary_setup_and_output_bounds_are_enforced(
    target: str, value: object, code: str
) -> None:
    # Given: an out-of-capability boundary, integration or output value.
    raw = _supported_spec()
    if target == "pressure_pa":
        raw["nodes"][0][target] = value
    elif target == "end_time_s":
        raw["integration"][target] = value
    else:
        raw[target] = value

    # When: validation runs.
    result = _validate(raw)

    # Then: bounded v1 validation names the rejected capability.
    assert result["valid"] is False
    assert code in _error_codes(result)


def _drop_source_temperature(raw: dict) -> None:
    next(node for node in raw["nodes"] if node["kind"] == "source").pop("temperature_c")


def _drop_sink_temperature(raw: dict) -> None:
    next(node for node in raw["nodes"] if node["kind"] == "sink").pop("temperature_c")


_REQUIRED_PHYSICS = [
    ("fluid_label", lambda raw: raw.pop("fluid_label"), "fluid_label"),
    ("thermal", lambda raw: raw.pop("thermal"), "thermal"),
    ("source_temperature", _drop_source_temperature, "temperature_c"),
    ("sink_temperature", _drop_sink_temperature, "temperature_c"),
    ("pipe_roughness", lambda raw: raw["flowpaths"][0]["pipes"][0].pop("roughness_m"), "roughness_m"),
]


@pytest.mark.parametrize(("name", "remove", "field"), _REQUIRED_PHYSICS, ids=[item[0] for item in _REQUIRED_PHYSICS])
def test_every_physical_input_is_required_never_defaulted(name: str, remove: Callable, field: str) -> None:
    # Given: a supported spec from which the user never stated one physical input.
    raw = _supported_spec()
    remove(raw)

    # When: validation runs.
    result = _validate(raw)

    # Then: it is refused and names the missing input; nothing is guessed or filled in.
    assert result["valid"] is False and result["normalized"] is None
    assert any(field in item["field"] for item in result["errors"]), result["errors"]


def test_legacy_v1_specs_are_refused_with_the_inputs_to_ask_the_user_for() -> None:
    # Given: a pre-thermal v1 spec (what the old compiler accepted and could never solve).
    raw = _supported_spec()
    raw["version"] = "1"

    # When: it is validated.
    result = _validate(raw)

    # Then: it is not silently upgraded; guidance lists what only the user can supply.
    assert result["valid"] is False
    assert _error_codes(result) == {"legacy_version"}
    guidance = result["errors"][0]["guidance"]
    assert "fluid label" in guidance and "roughness" in guidance and "Do not fill these in" in guidance


@pytest.mark.parametrize(
    ("path", "value", "code"),
    [
        (("nodes", 0, "temperature_c"), -273.15, "invalid_boundary"),
        (("nodes", 0, "temperature_c"), -300.0, "invalid_boundary"),
        (("nodes", 0, "temperature_c"), float("nan"), "invalid_boundary"),
        (("nodes", 0, "temperature_c"), float("inf"), "invalid_boundary"),
        (("nodes", 0, "temperature_c"), "40", "invalid_boundary"),
        (("flowpaths", 0, "pipes", 0, "roughness_m"), -1e-5, "invalid_roughness"),
        (("flowpaths", 0, "pipes", 0, "roughness_m"), 0.5, "invalid_roughness"),
        (("flowpaths", 0, "pipes", 0, "roughness_m"), float("nan"), "invalid_roughness"),
        (("fluid_label", ), "BAD LABEL", "invalid_fluid_label"),
        (("fluid_label", ), 'EVIL",X=1', "invalid_fluid_label"),
        (("fluid_label", ), "", "invalid_fluid_label"),
        (("fluid_label", ), "1", "invalid_fluid_label"),
        (("fluid_label", ), "1e3", "invalid_fluid_label"),
        (("fluid_label", ), "NaN", "invalid_fluid_label"),
        (("thermal",), {"model": "adiabatic", "ambient_temperature_c": 5.0}, "unknown_field"),
        (("thermal",), {"model": "ambient_h_given", "ambient_temperature_c": 5.0}, "invalid_thermal"),
        (("thermal",), {"model": "isothermal"}, "invalid_thermal"),
    ],
)
def test_invalid_physical_values_are_rejected_with_specific_guidance(path: tuple, value: object, code: str) -> None:
    # Given: a supported spec with one nonfinite, out-of-range, wrongly typed or unsupported value.
    raw = _supported_spec()
    target = raw
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value

    # When: validation runs.
    result = _validate(raw)

    # Then: the field fails closed under its own issue code.
    assert result["valid"] is False
    assert code in _error_codes(result)


def test_ambient_model_needs_every_wall_and_ambient_value() -> None:
    from case_spec_v2_support import AMBIENT

    # Given: the ambient model with each required value removed in turn.
    for removal in (
        ("ambient_temperature_c",),
        ("outer_heat_transfer_coefficient_w_m2k",),
        ("wall",),
        ("wall", "thickness_m"),
        ("wall", "material"),
        ("wall", "material", "conductivity_w_mk"),
        ("wall", "material", "heat_capacity_j_kgk"),
        ("wall", "material", "density_kg_m3"),
    ):
        raw = _supported_spec()
        raw["thermal"] = deepcopy(AMBIENT)
        target = raw["thermal"]
        for key in removal[:-1]:
            target = target[key]
        del target[removal[-1]]

        # When / Then: no value is invented to complete the thermal model.
        result = _validate(raw)
        assert result["valid"] is False, removal
        assert "invalid_thermal" in _error_codes(result), removal


def test_complete_ambient_model_is_valid_and_canonical() -> None:
    from case_spec_v2_support import AMBIENT

    raw = _supported_spec()
    raw["thermal"] = deepcopy(AMBIENT)

    result = _validate(raw)

    assert result["valid"] is True
    assert result["normalized"]["thermal"] == AMBIENT
