"""Agent tools default their case path from the active workspace case, set it on
touch, and still enforce the run_execute approval gate."""
import pytest

from olga_companion import workspace
from olga_companion.agent import tools


@pytest.fixture
def active(tmp_path, monkeypatch):
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setattr(workspace, "_active_state_path", lambda: tmp_path / "active.json")
    case = tmp_path / "case.genkey"
    case.write_text("x")
    workspace.set_active_rel("case.genkey")
    return str(case.resolve())


@pytest.fixture
def empty_ws(tmp_path, monkeypatch):
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setattr(workspace, "_active_state_path", lambda: tmp_path / "active.json")
    return tmp_path


def test_apply_active_default_fills_omitted_case_arg(active):
    assert tools.apply_active_default("genkey_review", {})["path"] == active
    assert tools.apply_active_default("genkey_modify", {"keyword": "k", "key": "x", "value": "1"})["path"] == active
    assert tools.apply_active_default("run_preview", {})["source"] == active
    assert tools.apply_active_default("run_detect", {})["source"] == active
    # run_execute's source is filled BEFORE the approval digest is computed.
    assert tools.apply_active_default("run_execute", {"approval_token": "t"})["source"] == active


def test_apply_active_default_respects_explicit_path(active):
    assert tools.apply_active_default("genkey_review", {"path": "other.genkey"})["path"] == "other.genkey"
    assert tools.apply_active_default("run_detect", {"source": "other.genkey"})["source"] == "other.genkey"


def test_case_edit_plan_spec_mode_does_not_inject_active_source(active):
    args = {
        "spec": {},
        "spec_hash": "b" * 64,
        "operations": [{"op": "set_outputs", "outputs": ["PT", "TM"]}],
    }

    normalized = tools.apply_active_default("case_edit_plan", args)

    assert normalized == args
    assert "source" not in normalized


def test_apply_active_default_ignores_non_case_tools(active):
    assert tools.apply_active_default("run_status", {"run_id": "x"}) == {"run_id": "x"}
    assert "path" not in tools.apply_active_default("results_load", {})  # output path, not the case


def test_set_active_case_updates_state(empty_ws):
    c = empty_ws / "c.genkey"
    c.write_text("x")
    tools._set_active_case(str(c))
    assert workspace.active()["name"] == "c.genkey"


def test_case_tool_errors_without_path_or_active(empty_ws):
    with pytest.raises(tools.ToolError):
        tools._t_run_preview({})
    with pytest.raises(tools.ToolError):
        tools._t_genkey_review({})


def test_run_execute_still_requires_token_even_with_active(active):
    with pytest.raises(tools.ToolError):
        tools._t_run_execute({})  # no approval_token → refused before touching the runner


def test_cap_keeps_decision_fields_when_over_budget():
    # A real 800 KB genkey_review must not be withheld wholesale: `valid`/`path`
    # survive and the big report fields are truncated-but-present, so the model
    # can still tell the user the case is invalid (matches what a direct toolkit
    # call exposes — the core capability-parity requirement).
    big = {
        "path": "case.genkey",
        "valid": False,
        "validation": {"exit_code": 1, "stdout": "ERRORS: 643\n" + ("[T003] undefined node\n" * 40000)},
        "summary": "S" * 300000,
        "topology": "T" * 400000,
    }
    capped = tools._cap(big)
    assert capped.get("valid") is False, "the decision field must survive the cap"
    assert capped.get("path") == "case.genkey"
    assert "validation" in capped, "the report is truncated, not withheld wholesale"
    assert "ERRORS: 643" in str(capped), "the head of the validation report survives"
    import json as _json
    assert len(_json.dumps(capped, default=str)) <= tools.MAX_RESULT_BYTES


def test_cap_keeps_producer_capped_ends_while_cutting_long_lists():
    # An import result carries 100 ends (capped by the producer at _MAX_ENDS);
    # the generic cap must keep all 100 while still cutting an uncapped list.
    import json as _json

    ends = [{"x_m": float(index), "y_m": 0.0, "z_m": 0.0} for index in range(100)]
    payload = {
        "ends": ends,
        "junk": ["y" * 100 for _ in range(500)],
        "note": "水" * 9000,
    }
    assert len(_json.dumps(payload, default=str)) > tools.MAX_RESULT_BYTES

    capped = tools._cap(payload)

    assert len(capped["ends"]) == 100
    assert len(capped["junk"]) < 500
    assert len(_json.dumps(capped, default=str)) <= tools.MAX_RESULT_BYTES


def test_genkey_modify_points_active_at_modified_copy(active, tmp_path, monkeypatch):
    # After a modify, "run/validate my case" must use the MODIFIED copy, not the
    # untouched source — so the active case follows modified_copy.
    from olga_companion import genkey_static
    modified = tmp_path / "case-abc123.genkey"
    modified.write_text("modified")
    monkeypatch.setattr(genkey_static, "modify_copy",
                        lambda *a, **k: {"source": a[0], "modified_copy": str(modified), "valid": True})
    out = tools._t_genkey_modify({"path": active, "keyword": "INTEGRATION", "key": "ENDTIME", "value": "7200 s"})
    assert out["modified_copy"] == str(modified)
    assert workspace.active_path() == str(modified)


def test_fluids_consistency_defaults_to_active_case(active):
    assert tools.apply_active_default("fluids_consistency", {})["path"] == active
    assert "path" not in tools.TOOLS["fluids_consistency"].parameters["required"]


def test_case_tool_schemas_no_longer_require_path(active):
    # The model may omit path/source now (defaulted from the active case).
    assert "path" not in tools.TOOLS["genkey_review"].parameters["required"]
    assert "source" not in tools.TOOLS["run_preview"].parameters["required"]
    assert "source" not in tools.TOOLS["run_execute"].parameters["required"]
    assert "approval_token" in tools.TOOLS["run_execute"].parameters["required"]  # gate intact
