"""OLGA's vertical axis is Y: an elevation edit moves Y, and pipe_mapper reads Y as elevation."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from case_spec_v2_support import with_v2_inputs
from olga_companion.agent.case_transaction_schemas import CASE_TRANSACTION_PARAMETER_SCHEMAS
from olga_companion.agent.tool_validation import ToolError, validate_tool_arguments
from olga_companion.case_spec import normalize_case_spec
from olga_companion.case_transaction_apply import apply_operation
from olga_companion.case_transaction_models import parse_operation

TOOLKIT = Path(__file__).resolve().parents[1] / "resources" / "olga-toolkit" / "scripts"


def _spec():
    return normalize_case_spec(with_v2_inputs({
        "version": "1",
        "nodes": [
            {"label": "SOURCE", "kind": "source", "pressure_pa": 2_000_000.0},
            {"label": "SINK", "kind": "sink", "pressure_pa": 1_000_000.0},
        ],
        "flowpaths": [{
            "label": "MAIN", "from": "SOURCE", "to": "SINK",
            "pipes": [{
                "label": "PIPE_A",
                "centerline_m": [[0.0, 2.0, 3.0], [100.0, 4.0, 5.0]],
                "diameter_m": 0.1,
                "sections": 10,
            }],
        }],
        "pvt_reference": "fluid.tab",
        "integration": {"end_time_s": 3600.0},
        "outputs": ["PT"],
    }))


def test_elevation_offset_raises_every_y_and_leaves_z_unchanged() -> None:
    operation = parse_operation(
        {"op": "set_pipe_geometry", "flowpath": "MAIN", "pipe": "PIPE_A", "elevation_offset_m": 1.0}
    )

    updated, _diff = apply_operation(_spec(), operation)

    points = updated.flowpaths[0].pipes[0].centerline_m
    assert points == ((0.0, 3.0, 3.0), (100.0, 5.0, 5.0))


def test_z_offset_is_refused_by_the_model_and_the_tool_schema() -> None:
    with pytest.raises(ValidationError):
        parse_operation(
            {"op": "set_pipe_geometry", "flowpath": "MAIN", "pipe": "PIPE_A", "z_offset_m": 1.0}
        )
    schema = CASE_TRANSACTION_PARAMETER_SCHEMAS["case_edit_plan"]
    args = {
        "spec": {}, "spec_hash": "0" * 64,
        "operations": [{"op": "set_pipe_geometry", "flowpath": "MAIN", "pipe": "PIPE_A", "z_offset_m": 1.0}],
    }
    with pytest.raises(ToolError):
        validate_tool_arguments("case_edit_plan", args, schema)


def test_a_geometry_edit_with_neither_field_is_refused() -> None:
    with pytest.raises(ValidationError):
        parse_operation({"op": "set_pipe_geometry", "flowpath": "MAIN", "pipe": "PIPE_A"})
    with pytest.raises(ToolError):
        validate_tool_arguments(
            "case_edit_plan",
            {"spec": {}, "spec_hash": "0" * 64,
             "operations": [{"op": "set_pipe_geometry", "flowpath": "MAIN", "pipe": "PIPE_A"}]},
            CASE_TRANSACTION_PARAMETER_SCHEMAS["case_edit_plan"],
        )


_COORDINATE_GENKEY = """\
CASE AUTHOR="X", PROJECT="Y"
NETWORKCOMPONENT TYPE=FLOWPATH, TAG=FP
 PARAMETERS LABEL="FP"
 GEOMETRY LABEL="G-FP", XSTART=0 m, YSTART=0 m, ZSTART=0 m
 PIPE LABEL=FLAT, NSEGMENT=2, LSEGMENT=(5,5) m, XEND=10 m, YEND=0 m, ZEND=0 m, DIAMETER=0.1 m
 PIPE LABEL=RISER, NSEGMENT=2, LSEGMENT=(5,5) m, XEND=10 m, YEND=10 m, ZEND=0 m, DIAMETER=0.1 m
ENDNETWORKCOMPONENT
"""


@pytest.fixture
def _mapper(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    sys.path.insert(0, str(TOOLKIT))
    try:
        from pipe_mapper import PipeMapper

        path = tmp_path / "coord.genkey"
        path.write_text(_COORDINATE_GENKEY, encoding="utf-8")
        yield PipeMapper(str(path), "FP")
    finally:
        sys.path.remove(str(TOOLKIT))


def test_coordinate_genkey_elevation_profile_reads_yend(_mapper) -> None:
    profile = _mapper.get_elevation_profile()

    assert [(p["pipe_label"], p["start_elev"], p["end_elev"]) for p in profile] == [
        ("FLAT", 0.0, 0.0),
        ("RISER", 0.0, 10.0),
    ]


def test_coordinate_genkey_lowest_point_is_the_bottom(_mapper) -> None:
    _description, elevation = _mapper.get_lowest_point()

    assert elevation == 0.0
    assert _mapper.get_elevation_profile()[-1]["end_elev"] == 10.0
