import json
import math
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from olga_companion import flowpath_details
from olga_companion.genkey_static import OlgaInputError, TOOL_OUTPUT_LIMIT_EXIT_CODE


def _geometry_result(pipes: list[dict[str, Any]]) -> dict[str, Any]:
    return {"ok": True, "result": pipes, "path": "/private/case.genkey", "command": {}}


def _pipe_child(
    label: str, lengths: list[float], end: tuple[float, float, float], *, length_unit: str = "m", diameter: float = 0.1, diameter_unit: str = "m"
) -> dict[str, Any]:
    return {
        "keyword": "PIPE",
        "params": {
            "LABEL": label,
            "NSEGMENT": len(lengths),
            "DIAMETER": {"value": diameter, "unit": diameter_unit},
            "LSEGMENT": {"value": lengths, "unit": length_unit},
            "XEND": {"value": end[0], "unit": length_unit},
            "YEND": {"value": end[1], "unit": length_unit},
            "ZEND": {"value": end[2], "unit": length_unit},
        },
    }


def _parser_payload(children: list[dict[str, Any]]) -> dict[str, Any]:
    return {"filepath": "/operator/private/case.genkey", "flowpaths": [
        {"type": "FLOWPATH", "tag": "FLOWPATH_A", "children": children}
    ]}


def _geometry_child(start: tuple[float, float, float] = (0, 0, 0), unit: str = "m") -> dict[str, Any]:
    return {"keyword": "GEOMETRY", "params": {
        axis: {"value": value, "unit": unit} for axis, value in zip(("XSTART", "YSTART", "ZSTART"), start, strict=True)
    }}


def _linear_payload(pipe_count: int, sections_per_pipe: int) -> dict[str, Any]:
    pipes = [_pipe_child(f"PIPE_{index}", [1.0] * sections_per_pipe, ((index + 1) * sections_per_pipe, 0.0, 0.0)) for index in range(pipe_count)]
    return _parser_payload([_geometry_child(), *pipes])


def _use_parser_result(
    monkeypatch: pytest.MonkeyPatch, payload: dict[str, Any] | None, *, exit_code: int = 0, stdout: str | None = None
) -> None:
    parser_stdout = json.dumps(payload) if stdout is None else stdout
    result = SimpleNamespace(exit_code=exit_code, stdout=parser_stdout, stderr="private stderr")
    monkeypatch.setattr(flowpath_details, "run_tool", lambda *_args, **_kwargs: result, raising=False)
    monkeypatch.setattr(
        flowpath_details,
        "pipe_geometry",
        lambda *_args: _geometry_result([{
            "label": "LEGACY_PIPE", "nsegment": 1, "diameter_m": 0.1,
            "total_length_m": 1.0, "volume_m3": 0.01, "section_range": [0, 0],
        }]),
    )


def _assert_geometry_unavailable(result: dict[str, Any], reason: str) -> None:
    assert result["schema_version"] == 2
    actual = (result["geometry"]["status"], result["geometry"]["reason"], result["sections"])
    assert actual == ("unavailable", reason, [])


def test_flowpath_details_are_bounded_aggregated_and_path_free(monkeypatch: pytest.MonkeyPatch) -> None:
    parser_result = SimpleNamespace(exit_code=0, stdout=json.dumps(_parser_payload([])), stderr="")
    monkeypatch.setattr(flowpath_details, "run_tool", lambda *_args, **_kwargs: parser_result, raising=False)
    monkeypatch.setattr(
        flowpath_details,
        "pipe_geometry",
        lambda path, flowpath, op: _geometry_result([
            {
                "label": "PIPE_A",
                "nsegment": 3,
                "diameter_m": 0.1,
                "total_length_m": 12.5,
                "volume_m3": 0.4,
                "section_range": [0, 2],
            },
            {
                "label": "PIPE_B",
                "nsegment": 2,
                "diameter_m": 0.2,
                "total_length_m": 7.5,
                "volume_m3": 0.3,
                "section_range": [3, 4],
            },
        ]),
    )

    result = flowpath_details.load_flowpath_details(Path("case.genkey"), "FLOWPATH_A")

    assert result["flowpath"] == "FLOWPATH_A"
    assert result["summary"] == {
        "pipe_count": 2,
        "segment_count": 5,
        "total_length_m": 20.0,
        "total_volume_m3": 0.7,
        "diameter_min_m": 0.1,
        "diameter_max_m": 0.2,
    }
    assert result["pipes"][0]["section_range"] == [0, 2]
    assert "path" not in result and "command" not in result


@pytest.mark.parametrize(
    "pipes",
    [
        [{"label": "PIPE_A", "nsegment": -1, "diameter_m": 0.1, "total_length_m": 1, "volume_m3": 1, "section_range": [0, 0]}],
        [{"label": "PIPE_A", "nsegment": 1, "diameter_m": float("nan"), "total_length_m": 1, "volume_m3": 1, "section_range": [0, 0]}],
        [{"label": "PIPE_A", "nsegment": 1, "diameter_m": 0.1, "total_length_m": 1, "volume_m3": 1, "section_range": [2, 1]}],
    ],
)
def test_flowpath_details_fail_closed_on_invalid_geometry(
    monkeypatch: pytest.MonkeyPatch,
    pipes: list[dict[str, Any]],
) -> None:
    monkeypatch.setattr(
        flowpath_details,
        "pipe_geometry",
        lambda path, flowpath, op: _geometry_result(pipes),
    )

    with pytest.raises(OlgaInputError):
        flowpath_details.load_flowpath_details(Path("case.genkey"), "FLOWPATH_A")


@pytest.mark.parametrize("field", ["total_length_m", "volume_m3"])
def test_flowpath_details_fail_closed_when_aggregate_overflows(
    monkeypatch: pytest.MonkeyPatch,
    field: str,
) -> None:
    pipe = {
        "label": "PIPE_A",
        "nsegment": 1,
        "diameter_m": 0.1,
        "total_length_m": 1.0,
        "volume_m3": 1.0,
        "section_range": [0, 0],
    }
    pipes = [{**pipe, field: 1e308}, {**pipe, "label": "PIPE_B", field: 1e308}]
    monkeypatch.setattr(
        flowpath_details,
        "pipe_geometry",
        lambda path, flowpath, op: _geometry_result(pipes),
    )

    with pytest.raises(OlgaInputError, match="aggregate"):
        flowpath_details.load_flowpath_details(Path("case.genkey"), "FLOWPATH_A")


def test_schema_v2_reconstructs_ordered_seven_pipe_geometry_when_parser_data_is_valid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    specs = [
        ("P1_suction", 4, 2.075, 0.0737, (7.81703, 0.0, 0.0)),
        ("P2_1_vert", 1, 2.65, 0.0737, (7.81703, 2.65, 0.0)),
        ("P2_2_horz", 7, 2.95714, 0.0737, (28.517, 2.65, 0.0)),
        ("P2_3_vert", 14, 3.05357, 0.0737, (28.517, 45.4, 0.0)),
        ("P3_1_1_wet", 3, 2.51333, 0.0493, (28.517, 52.94, 0.0)),
        ("P3_1_2_air", 1, 0.75, 0.0493, (28.517, 53.69, 0.0)),
        ("P3_2_air", 3, 2.46667, 0.0493, (35.917, 53.69, 0.0)),
    ]
    payload = _parser_payload([
        _geometry_child((0, -2.79, 0)),
        *[_pipe_child(label, [length] * count, end, diameter=diameter) for label, count, length, diameter, end in specs],
    ])
    _use_parser_result(monkeypatch, payload)

    result = flowpath_details.load_flowpath_details(Path("case.genkey"), "FLOWPATH_A")

    assert result["schema_version"] == 2
    assert result["geometry"] == {
        "status": "ready",
        "coordinate_unit": "m",
        "start": {"x_m": 0.0, "y_m": -2.79, "z_m": 0.0},
    }
    assert (
        result["summary"]["pipe_count"], result["summary"]["segment_count"], result["summary"]["total_length_m"], result["summary"]["total_volume_m3"]
    ) == (7, 33, pytest.approx(90.08996), pytest.approx(sum(math.pi * diameter**2 * count * length / 4 for _, count, length, diameter, _ in specs)))
    assert result["pipes"][0]["start"] == result["geometry"]["start"]
    assert result["pipes"][1]["start"] == result["pipes"][0]["end"]
    assert result["pipes"][-1]["section_range"] == [30, 32]
    assert (result["sections"][0]["section_index"], result["sections"][0]["pipe_section_index"]) == (0, 1)
    assert (result["sections"][-1]["section_index"], result["sections"][-1]["pipe_section_index"]) == (32, 3)
    assert result["sections"][0]["start"] == result["geometry"]["start"]
    assert result["sections"][-1]["end"] == result["pipes"][-1]["end"]
    encoded = json.dumps(result)
    assert "/operator/private" not in encoded
    for key in ("filepath", "path", "command", "stdout", "stderr"):
        assert f'"{key}"' not in encoded


def test_schema_v2_converts_parser_length_units_to_metres(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _parser_payload([
        _geometry_child(unit="ft"),
        _pipe_child("PIPE_FT", [4.0, 6.0], (10.0, 0.0, 0.0), length_unit="ft", diameter=100, diameter_unit="mm"),
    ])
    _use_parser_result(monkeypatch, payload)

    result = flowpath_details.load_flowpath_details(Path("case.genkey"), "FLOWPATH_A")

    assert result["pipes"][0]["end"] == {"x_m": pytest.approx(3.048), "y_m": 0.0, "z_m": 0.0}
    assert result["pipes"][0]["diameter_m"] == pytest.approx(0.1)
    assert [section["length_m"] for section in result["sections"]] == pytest.approx([1.2192, 1.8288])
    assert result["sections"][0]["center"]["x_m"] == pytest.approx(0.6096)


@pytest.mark.parametrize(
    ("child_index", "field", "attribute", "value", "reason"),
    [
        (0, "XSTART", "value", None, "missing_coordinates"),
        (1, "LSEGMENT", "unit", "furlong", "unknown_length_unit"),
        (1, "XEND", "value", float("inf"), "non_finite_coordinates"),
    ],
    ids=["missing_xyz", "unknown_unit", "non_finite"],
)
def test_schema_v2_marks_geometry_unavailable_when_parser_geometry_is_invalid(
    monkeypatch: pytest.MonkeyPatch,
    child_index: int,
    field: str,
    attribute: str,
    value: Any,
    reason: str,
) -> None:
    payload = _linear_payload(1, 2)
    payload["flowpaths"][0]["children"][child_index]["params"][field][attribute] = value
    _use_parser_result(monkeypatch, payload)

    result = flowpath_details.load_flowpath_details(Path("case.genkey"), "FLOWPATH_A")

    _assert_geometry_unavailable(result, reason)


def test_schema_v2_marks_geometry_unavailable_when_nsegment_mismatches_lsegment(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = _linear_payload(1, 2)
    payload["flowpaths"][0]["children"][1]["params"]["NSEGMENT"] = 3
    _use_parser_result(monkeypatch, payload)

    result = flowpath_details.load_flowpath_details(Path("case.genkey"), "FLOWPATH_A")

    _assert_geometry_unavailable(result, "section_count_mismatch")


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("XSTART", [], "invalid_coordinate_cardinality"),
        ("XSTART", [0.0, 1.0], "invalid_coordinate_cardinality"),
        ("DIAMETER", [], "invalid_diameter"),
        ("DIAMETER", [0.1, 0.2], "invalid_diameter"),
    ],
)
def test_schema_v2_rejects_non_scalar_coordinates_and_diameter(
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: list[float],
    reason: str,
) -> None:
    payload = _linear_payload(1, 2)
    child_index = 0 if field == "XSTART" else 1
    payload["flowpaths"][0]["children"][child_index]["params"][field]["value"] = value
    _use_parser_result(monkeypatch, payload)

    result = flowpath_details.load_flowpath_details(Path("case.genkey"), "FLOWPATH_A")

    _assert_geometry_unavailable(result, reason)


def test_schema_v2_rejects_zero_section_pipes_without_reversed_ranges(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = _parser_payload([_geometry_child(), _pipe_child("EMPTY", [], (0.0, 0.0, 0.0))])
    _use_parser_result(monkeypatch, payload)

    result = flowpath_details.load_flowpath_details(Path("case.genkey"), "FLOWPATH_A")

    _assert_geometry_unavailable(result, "section_count_mismatch")


def test_schema_v2_marks_geometry_unavailable_when_chord_and_section_lengths_disagree(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _linear_payload(1, 2)
    payload["flowpaths"][0]["children"][1]["params"]["XEND"]["value"] = 100.0
    _use_parser_result(monkeypatch, payload)

    result = flowpath_details.load_flowpath_details(Path("case.genkey"), "FLOWPATH_A")

    _assert_geometry_unavailable(result, "length_endpoint_mismatch")


def test_schema_v2_accepts_exact_pipe_and_section_bounds(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_parser_result(monkeypatch, _linear_payload(500, 10))

    result = flowpath_details.load_flowpath_details(Path("case.genkey"), "FLOWPATH_A")

    assert (result["summary"]["pipe_count"], result["summary"]["segment_count"], len(result["sections"])) == (
        500, 5_000, 5_000,
    )


@pytest.mark.parametrize(
    ("pipe_count", "sections_per_pipe", "message"),
    [(501, 1, "pipe limit"), (1, 5_001, "section limit")],
)
def test_schema_v2_rejects_geometry_when_response_bounds_are_exceeded(
    monkeypatch: pytest.MonkeyPatch,
    pipe_count: int,
    sections_per_pipe: int,
    message: str,
) -> None:
    _use_parser_result(monkeypatch, _linear_payload(pipe_count, sections_per_pipe))

    with pytest.raises(OlgaInputError, match=message):
        flowpath_details.load_flowpath_details(Path("case.genkey"), "FLOWPATH_A")


@pytest.mark.parametrize(
    ("exit_code", "stdout", "message"),
    [(1, "", "could not be read"), (0, "{", "parser output"), (TOOL_OUTPUT_LIMIT_EXIT_CODE, "", "output limit")],
)
def test_schema_v2_fails_closed_when_parser_output_is_unusable(
    monkeypatch: pytest.MonkeyPatch,
    exit_code: int,
    stdout: str,
    message: str,
) -> None:
    _use_parser_result(monkeypatch, None, exit_code=exit_code, stdout=stdout)

    with pytest.raises(OlgaInputError, match=message) as captured:
        flowpath_details.load_flowpath_details(Path("case.genkey"), "FLOWPATH_A")

    assert "/operator/private" not in str(captured.value)
