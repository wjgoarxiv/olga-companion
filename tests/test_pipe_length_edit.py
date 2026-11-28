"""set_pipe_length changes one pipe's length and keeps the rest of the flowpath where it was."""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from olga_companion import genkey_static, workspace
from olga_companion.agent.case_transaction_schemas import _OPERATION
from olga_companion.case_spec import CaseSpec
from olga_companion.case_transaction_apply import UnsupportedEditError, apply_operation
from olga_companion.case_transaction_models import TransactionFailure, parse_operation
from olga_companion.case_transactions import plan_case_edits_from_source
from case_spec_v2_support import with_v2_inputs

_FIXTURE = Path(__file__).parent / "fixtures" / "cases" / "simple_pipeline.genkey"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _owner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, text: str | None = None) -> tuple[Path, Path]:
    root = tmp_path / "workspace"
    root.mkdir()
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(root))
    monkeypatch.setenv("OLGA_CASE_TRANSACTION_DIR", str(tmp_path / "transactions"))
    source = root / "owner.genkey"
    source.write_text(text or _FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    (root / "dummy_fluid.tab").write_text('PVTTABLE LABEL="FLUID-A"\n', encoding="utf-8")
    return root, source


def _plan(root: Path, source: Path, operation: dict):
    return plan_case_edits_from_source(
        source, [operation], expected_hash=_sha256(source), workspace_root=root,
        context_generation=workspace.context_generation(),
    )


def _report(text: str, tmp_path: Path) -> str:
    case = tmp_path / "check.genkey"
    case.write_text(text, encoding="utf-8")
    return genkey_static.run_tool("validator", [str(case)]).stdout


def test_the_closed_grammar_and_the_tool_schema_know_set_pipe_length() -> None:
    operation = parse_operation({"op": "set_pipe_length", "flowpath": "F", "pipe": "P", "length_m": 120.0})
    assert operation.model_dump()["length_m"] == 120.0
    assert "set_pipe_length" in _OPERATION["properties"]["op"]["enum"]
    with pytest.raises(ValueError):
        parse_operation({"op": "set_pipe_length", "flowpath": "F", "pipe": "P", "length_m": 0})


@pytest.mark.parametrize("flowpath", ["Pipeline", "FLOWPATH_1"])
def test_owner_pipe_length_scales_segments_and_moves_later_end_points(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, flowpath: str
) -> None:
    root, source = _owner(tmp_path, monkeypatch)
    before = source.read_bytes()

    plan = _plan(root, source, {"op": "set_pipe_length", "flowpath": flowpath, "pipe": "Pipe_1", "length_m": 120.0})

    assert not isinstance(plan, TransactionFailure), plan
    assert plan.publishable is True
    assert source.read_bytes() == before
    text = plan.compiled_bytes.decode("utf-8")
    assert "LSEGMENT=(24, 24, 24, 24, 24) m, XEND=120 m" in text
    assert "LSEGMENT=(20, 20, 20, 20, 20) m, XEND=220 m" in text
    assert "LSEGMENT=(20, 20, 20, 20, 20) m, XEND=320 m" in text
    assert text.count("\n") == before.decode("utf-8").count("\n")
    report = _report(text, tmp_path)
    assert "X014" not in report and "ERRORS:   0" in report


def test_owner_sloped_pipe_keeps_its_direction(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    text = _FIXTURE.read_text(encoding="utf-8").replace(
        "LSEGMENT=(20, 20, 20, 20, 20) m, XEND=100 m, YEND=0 m",
        "LSEGMENT=(10, 10, 10, 10, 10) m, XEND=30 m, YEND=40 m",
    ).replace("XEND=200 m, YEND=0 m", "XEND=130 m, YEND=40 m").replace("XEND=300 m, YEND=0 m", "XEND=230 m, YEND=40 m")
    root, source = _owner(tmp_path, monkeypatch, text)

    plan = _plan(root, source, {"op": "set_pipe_length", "flowpath": "Pipeline", "pipe": "Pipe_1", "length_m": 100.0})

    assert not isinstance(plan, TransactionFailure), plan
    out = plan.compiled_bytes.decode("utf-8")
    assert "LSEGMENT=(20, 20, 20, 20, 20) m, XEND=60 m, YEND=80 m" in out
    assert "XEND=160 m, YEND=80 m" in out and "XEND=260 m, YEND=80 m" in out


def test_owner_length_style_pipe_rewrites_length_and_segments(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    text = _FIXTURE.read_text(encoding="utf-8").replace(
        "LSEGMENT=(20, 20, 20, 20, 20) m, XEND=100 m, YEND=0 m, ZEND=0 m",
        "LSEGMENT=(0.02, 0.02, 0.02, 0.02, 0.02) km, LENGTH=100 m, ELEVATION=0 m",
    )
    # Later pipes keep their own coordinates; their start follows the first pipe only by coordinates,
    # so the fixture's later pipes are written by length too.
    text = text.replace(", XEND=200 m, YEND=0 m, ZEND=0 m", ", LENGTH=100 m, ELEVATION=0 m")
    text = text.replace(", XEND=300 m, YEND=0 m, ZEND=0 m", ", LENGTH=100 m, ELEVATION=0 m")
    root, source = _owner(tmp_path, monkeypatch, text)

    plan = _plan(root, source, {"op": "set_pipe_length", "flowpath": "Pipeline", "pipe": "Pipe_1", "length_m": 150.0})

    assert not isinstance(plan, TransactionFailure), plan
    out = plan.compiled_bytes.decode("utf-8")
    assert "LSEGMENT=(0.03, 0.03, 0.03, 0.03, 0.03) km, LENGTH=150 m, ELEVATION=0 m" in out
    assert out.count("LENGTH=100 m") == 2


def test_owner_uneven_segments_keep_their_proportions_and_exact_sum(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    text = _FIXTURE.read_text(encoding="utf-8").replace(
        "NSEGMENT=5, \\\n        LSEGMENT=(20, 20, 20, 20, 20) m, XEND=100 m",
        "NSEGMENT=3, \\\n        LSEGMENT=(10, 30, 60) m, XEND=100 m",
    )
    root, source = _owner(tmp_path, monkeypatch, text)

    plan = _plan(root, source, {"op": "set_pipe_length", "flowpath": "Pipeline", "pipe": "Pipe_1", "length_m": 70.0})

    assert not isinstance(plan, TransactionFailure), plan
    assert "LSEGMENT=(7, 21, 42) m, XEND=70 m" in plan.compiled_bytes.decode("utf-8")


@pytest.mark.parametrize(
    ("operation", "reason"),
    [
        ({"op": "set_pipe_length", "flowpath": "Pipeline", "pipe": "Pipe_9", "length_m": 120.0}, "unknown_target"),
        ({"op": "set_pipe_length", "flowpath": "Elsewhere", "pipe": "Pipe_1", "length_m": 120.0}, "unknown_target"),
    ],
)
def test_owner_unknown_targets_write_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: dict, reason: str
) -> None:
    root, source = _owner(tmp_path, monkeypatch)
    before = source.read_bytes()

    plan = _plan(root, source, operation)

    assert isinstance(plan, TransactionFailure)
    assert plan.errors[0].code == reason
    assert source.read_bytes() == before


def test_owner_pipe_cannot_get_shorter_than_its_rise(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    text = _FIXTURE.read_text(encoding="utf-8").replace(
        "LSEGMENT=(20, 20, 20, 20, 20) m, XEND=100 m, YEND=0 m, ZEND=0 m",
        "LSEGMENT=(20, 20, 20, 20, 20) m, LENGTH=100 m, ELEVATION=50 m",
    )
    text = text.replace(", XEND=200 m, YEND=0 m, ZEND=0 m", ", LENGTH=100 m, ELEVATION=0 m")
    text = text.replace(", XEND=300 m, YEND=0 m, ZEND=0 m", ", LENGTH=100 m, ELEVATION=0 m")
    root, source = _owner(tmp_path, monkeypatch, text)

    plan = _plan(root, source, {"op": "set_pipe_length", "flowpath": "Pipeline", "pipe": "Pipe_1", "length_m": 40.0})

    assert isinstance(plan, TransactionFailure)
    assert plan.errors[0].code == "unsupported_operation"


def _spec(pipes: list[dict]) -> CaseSpec:
    raw = with_v2_inputs({
        "version": "1",
        "nodes": [
            {"label": "SOURCE", "kind": "source", "pressure_pa": 2_000_000.0},
            {"label": "SINK", "kind": "sink", "pressure_pa": 1_000_000.0},
        ],
        "flowpaths": [{"label": "MAIN", "from": "SOURCE", "to": "SINK", "pipes": pipes}],
        "pvt_reference": "fluid.tab",
        "integration": {"end_time_s": 3600.0},
        "outputs": ["PT"],
    })
    raw["version"] = "3"
    return CaseSpec.model_validate(raw)


def test_casespec_centerline_pipe_moves_the_pipes_after_it() -> None:
    spec = _spec([
        {"label": "A", "centerline_m": [[0, 0, 0], [30, 40, 0]], "diameter_m": 0.1, "sections": 2,
         "segment_lengths_m": [20.0, 30.0]},
        {"label": "B", "centerline_m": [[30, 40, 0], [130, 40, 0]], "diameter_m": 0.1, "sections": 4},
    ])

    updated, diff = apply_operation(spec, parse_operation(
        {"op": "set_pipe_length", "flowpath": "MAIN", "pipe": "A", "length_m": 100.0}
    ))

    a, b = updated.flowpaths[0].pipes
    assert a.centerline_m == ((0, 0, 0), (60.0, 80.0, 0.0))
    assert a.segment_lengths_m == (40.0, 60.0)
    assert b.centerline_m == ((60.0, 80.0, 0.0), (160.0, 80.0, 0.0))
    assert diff.path == "flowpaths.MAIN.pipes.A.length_m"
    assert (diff.before, diff.after) == (50.0, 100.0)


def test_casespec_length_pipe_sets_its_length_and_refuses_a_too_short_one() -> None:
    spec = _spec([
        {"label": "A", "length_m": 100.0, "elevation_m": 10.0, "diameter_m": 0.1, "sections": 2},
    ])
    updated, _ = apply_operation(spec, parse_operation(
        {"op": "set_pipe_length", "flowpath": "MAIN", "pipe": "A", "length_m": 250.0}
    ))
    assert updated.flowpaths[0].pipes[0].length_m == 250.0
    with pytest.raises(UnsupportedEditError):
        apply_operation(spec, parse_operation(
            {"op": "set_pipe_length", "flowpath": "MAIN", "pipe": "A", "length_m": 5.0}
        ))
