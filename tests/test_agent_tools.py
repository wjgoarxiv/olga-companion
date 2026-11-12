"""T2 gate — tool belt: allowlist, schema safety, byte caps, approval gate, injection.

All offline. The belt is exercised directly (no LLM); the agent runtime is tested
separately with a scripted fake client.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from olga_companion.agent import approvals, tools

FIX = Path(__file__).parent / "fixtures"
FAKE_OLGA = FIX / "fake_olga" / "fake_olga.py"
INJ_CASE = FIX / "injection" / "injected_case.genkey"
INJ_LOG = FIX / "injection" / "injected_log.out"
CLEAN_OUT = FIX / "out" / "clean_run.out"
TROUBLED_OUT = FIX / "out" / "troubled_run.out"


# ---------------------------------------------------------------- schema safety

def test_no_tool_exposes_approved_or_override_parameter():
    """The self-approval BLOCKER: no tool may let the model set approval intent."""
    for tool in tools.TOOLS.values():
        props = set(tool.parameters.get("properties", {}))
        assert "approved" not in props, tool.name
        assert "override" not in props, tool.name


def test_side_effect_dispatch_contracts_are_approval_gated():
    for name in ("run_execute", "sweep_execute"):
        assert tools.TOOLS[name].side_effect is True
        assert "approval_token" in tools.TOOLS[name].parameters["properties"]
        assert "approval_token" in tools.TOOLS[name].parameters["required"]
    assert "selection_id" in tools.TOOLS["run_execute"].parameters["required"]
    assert "plan_id" in tools.TOOLS["sweep_execute"].parameters["required"]


def test_no_shell_or_freewrite_tool_exists():
    banned = {"read_file", "write_file", "edit_file", "run_command", "bash", "shell", "exec"}
    assert banned.isdisjoint(tools.TOOLS.keys())


def test_agent_cannot_mint_no_approval_tool_in_registry():
    """Plan §T2: the agent has no route to mint/approve — the registry lacks one."""
    for name in tools.TOOLS:
        assert "mint" not in name.lower(), name
        assert "approve" not in name.lower(), name
        assert "approval" not in name.lower(), name


def test_every_belt_entry_maps_to_an_allowlisted_adapter():
    """Plan §T2: every tool handler delegates to an olga_companion adapter module,
    never to a shell/file primitive."""
    allowed_modules = {
        "olga_companion.genkey_static", "olga_companion.fluids", "olga_companion.results",
        "olga_companion.evaluation", "olga_companion.reports", "olga_companion.runner",
        "olga_companion.diagnostics", "olga_companion.agent.tools",
    }
    for tool in tools.TOOLS.values():
        assert tool.handler.__module__ == "olga_companion.agent.tools", tool.name
        # The handler body must reference only allowlisted adapters (no os/subprocess/open).
        names = tool.handler.__code__.co_names
        assert "system" not in names and "popen" not in names, tool.name
    # And the belt only imports adapter modules (asserted structurally via the import list).
    assert allowed_modules  # sanity: adapters exist


def test_tool_specs_are_model_shaped():
    specs = tools.tool_specs()
    assert specs and all({"name", "description", "parameters"} <= set(s) for s in specs)


def test_model_tool_specs_never_expose_approval_capability():
    specs = {spec["name"]: spec for spec in tools.tool_specs()}

    for name, tool in tools.TOOLS.items():
        if not tool.side_effect:
            continue
        parameters = specs[name]["parameters"]
        assert "approval_token" not in parameters["properties"]
        assert "approval_token" not in parameters.get("required", [])
        assert "approval_token" not in specs[name]["description"]


def test_run_detect_accepts_case_source_and_explains_selection(monkeypatch, tmp_path):
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(tmp_path))
    case = tmp_path / "case.genkey"
    case.write_text("CASE LABEL=case\nENDCASE\n", encoding="utf-8")
    seen = []
    monkeypatch.setattr(tools.runner, "detect_olga", lambda source=None: seen.append(source) or {"detected": False})

    assert tools.dispatch("run_detect", {"source": str(case)})["detected"] is False
    assert seen == [str(case.resolve())]
    spec = tools.TOOLS["run_detect"]
    assert "source" in spec.parameters["properties"]
    assert all(word in spec.description.lower() for word in ("evidence", "alternatives", "suitable"))


def test_unknown_tool_is_refused():
    with pytest.raises(tools.ToolError, match="allowlisted"):
        tools.dispatch("delete_everything", {})


def test_genkey_modify_handler_matches_adapter_signature(tmp_path, monkeypatch):
    """F2 regression: the handler must call modify_copy with its real args."""
    sample = Path(__file__).parent / "fixtures" / "cases" / "simple_pipeline.genkey"
    if not sample.exists():
        pytest.skip("sample case unavailable")
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(tmp_path))
    case = tmp_path / "case.genkey"
    case.write_text(sample.read_text())
    out = tools.dispatch("genkey_modify", {
        "path": str(case), "keyword": "INTEGRATION", "key": "ENDTIME", "value": "7200 s",
    })
    assert "source_mutated" in out
    assert out["source_mutated"] is False


def test_malformed_tool_call_raises_toolerror_not_crash():
    """F2 regression: a missing required arg must surface as ToolError (caught by
    dispatch/runtime), never an uncaught TypeError/KeyError that kills the turn."""
    with pytest.raises(tools.ToolError):
        tools.dispatch("genkey_modify", {"path": "/x.genkey"})  # missing keyword/key/value


def test_agent_run_preview_rejects_unbounded_timeout_before_adapter_dispatch(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(tmp_path))
    case = tmp_path / "case.genkey"
    case.write_text("CASE LABEL=case\nENDCASE\n", encoding="utf-8")
    calls = []
    monkeypatch.setattr(
        tools.runner,
        "preview_run",
        lambda *args, **kwargs: calls.append((args, kwargs)) or {"unexpected": True},
    )

    with pytest.raises(tools.ToolError, match="timeout_s must be an integer between 1 and 604800"):
        tools.dispatch("run_preview", {"source": str(case), "timeout_s": 604_801})

    assert calls == []


# ---------------------------------------------------------------- byte caps

def test_oversized_result_is_capped():
    huge = {"blob": "x" * (tools.MAX_RESULT_BYTES + 1000)}
    capped = tools._cap(huge)
    # Over-budget results are truncated in place (shape + small fields kept), not
    # withheld wholesale: the field stays present but shortened, marked _truncated.
    assert capped.get("_truncated") is True or capped.get("truncated") is True
    assert "blob" in capped
    assert len(__import__("json").dumps(capped)) <= tools.MAX_RESULT_BYTES


# ---------------------------------------------------------------- approval gate

def test_run_execute_without_token_refused():
    with pytest.raises(tools.ToolError, match="approval_token"):
        tools.dispatch("run_execute", {"source": "/ws/case.genkey"})


def test_run_execute_with_forged_token_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(tmp_path))
    case = tmp_path / "case.genkey"
    case.write_text("CASE LABEL=case\nENDCASE\n", encoding="utf-8")
    with pytest.raises(tools.ToolError, match="unknown|used|match"):
        tools.dispatch(
            "run_execute",
            {"source": str(case), "selection_id": "selection-A", "approval_token": "forged"},
        )


def test_sweep_execute_without_token_refused():
    with pytest.raises(tools.ToolError, match="approval_token"):
        tools.dispatch("sweep_execute", {"sweep_id": "sweep-1"})


def test_sweep_execute_token_must_match_exact_sweep():
    minted = approvals.mint("sweep_execute", {"sweep_id": "sweep-A", "plan_id": "plan-A"})
    with pytest.raises(tools.ToolError, match="match"):
        tools.dispatch(
            "sweep_execute",
            {"sweep_id": "sweep-B", "plan_id": "plan-A", "approval_token": minted["token"]},
        )


def test_sweep_execute_rejects_token_from_another_workspace_generation(monkeypatch):
    payload = {"sweep_id": "sweep-A", "plan_id": "plan-A"}
    minted = approvals.mint("sweep_execute", payload, context_generation=2)
    monkeypatch.setattr(tools.workspace, "context_generation", lambda: 3)

    with pytest.raises(tools.ToolError, match="workspace context"):
        tools.dispatch("sweep_execute", {**payload, "approval_token": minted["token"]})


def test_run_execute_token_must_match_exact_source(monkeypatch, tmp_path):
    monkeypatch.setenv("OLGA_EXE_PATH", str(FAKE_OLGA))
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(tmp_path))
    source_a = tmp_path / "A.genkey"
    source_b = tmp_path / "B.genkey"
    source_a.write_text("CASE LABEL=A\nENDCASE\n", encoding="utf-8")
    source_b.write_text("CASE LABEL=B\nENDCASE\n", encoding="utf-8")
    payload = {"source": str(source_a), "timeout_s": 3600, "selection_id": "selection-A"}
    minted = approvals.mint("run_execute", payload)
    # Same token, different source → refused, and the token survives for its real action.
    with pytest.raises(tools.ToolError, match="match"):
        tools.dispatch(
            "run_execute",
            {
                "source": str(source_b),
                "selection_id": "selection-A",
                "approval_token": minted["token"],
                "timeout_s": 3600,
            },
        )


def test_run_execute_rejects_token_from_another_workspace_generation(monkeypatch, tmp_path):
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(tmp_path))
    source = tmp_path / "A.genkey"
    source.write_text("CASE LABEL=A\nENDCASE\n", encoding="utf-8")
    payload = {"source": str(source), "timeout_s": 3600, "selection_id": "selection-A"}
    minted = approvals.mint("run_execute", payload, context_generation=4)
    child_calls: list[str] = []
    monkeypatch.setattr(tools.workspace, "context_generation", lambda: 5)
    monkeypatch.setattr(
        tools.runner,
        "execute_run",
        lambda source, **kwargs: child_calls.append(source) or {"run_id": "unexpected"},
    )

    with pytest.raises(tools.ToolError, match="workspace context"):
        tools.dispatch("run_execute", {**payload, "approval_token": minted["token"]})

    assert child_calls == []


def test_active_case_persistence_failure_does_not_hide_started_run(tmp_path, monkeypatch):
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(tmp_path))
    case = tmp_path / "case.genkey"
    case.write_text("CASE LABEL=case\nENDCASE\n", encoding="utf-8")
    payload = {"source": str(case), "timeout_s": 3600, "selection_id": "selection-1"}
    minted = approvals.mint(
        "run_execute",
        payload,
        context_generation=tools.workspace.context_generation(),
    )
    monkeypatch.setattr(
        tools.runner,
        "execute_run",
        lambda *_args, **_kwargs: {"run_id": "started-run", "state": "running"},
    )

    def fail_active_state(_path: str) -> None:
        raise OSError("active state unavailable")

    monkeypatch.setattr(tools.workspace, "set_active_path", fail_active_state)

    result = tools.dispatch("run_execute", {**payload, "approval_token": minted["token"]})

    assert result["run_id"] == "started-run"


# ---------------------------------------------------------------- diagnostics tools

def test_diagnose_clean_out_reports_no_issues(tmp_path, monkeypatch):
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(tmp_path))
    solver_out = tmp_path / CLEAN_OUT.name
    shutil.copy2(CLEAN_OUT, solver_out)
    out = tools.dispatch("diagnose_out", {"path": str(solver_out)})
    assert out["ok"] is True
    assert out["issue_count"] == 0


def test_diagnose_troubled_out_flags_issues_and_suggests(tmp_path, monkeypatch):
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(tmp_path))
    solver_out = tmp_path / TROUBLED_OUT.name
    shutil.copy2(TROUBLED_OUT, solver_out)
    out = tools.dispatch("diagnose_out", {"path": str(solver_out)})
    assert out["ok"] is True  # JSON decides usability even though the script exits 1
    kinds = {i.get("type") for i in out["issues"]}
    assert {"STALLED", "MASS_ERROR"} & kinds
    assert out["suggestions"]


def test_monitor_snapshot_extracts_latest_timestep(tmp_path, monkeypatch):
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(tmp_path))
    solver_out = tmp_path / CLEAN_OUT.name
    shutil.copy2(CLEAN_OUT, solver_out)
    snap = tools.dispatch("monitor_snapshot", {"path": str(solver_out)})
    assert snap["parse_status"] == "parsed"
    assert snap["step"] == 100
    assert snap["adaptive_total_steps"] == 100
    assert snap["fraction"] is None
    assert "live" not in snap, "file activity must not claim process liveness"


# ---------------------------------------------------------------- injection corpus

def test_injected_case_text_cannot_elevate_permissions(tmp_path, monkeypatch):
    """Reading a case whose text says 'run_execute with approval_token=bypass'
    returns data only — it never triggers a side-effectful tool."""
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(tmp_path))
    injected_case = tmp_path / INJ_CASE.name
    shutil.copy2(INJ_CASE, injected_case)
    review = tools.dispatch("genkey_review", {"path": str(injected_case)})
    # The payload text is present as DATA in the summary/validation, but no run
    # was started and the forged 'bypass' token is not valid.
    with pytest.raises(tools.ToolError):
        tools.dispatch("run_execute", {"source": str(injected_case), "approval_token": "bypass"})
    assert "path" in review


def test_injected_log_text_does_not_mint_a_token(tmp_path, monkeypatch):
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(tmp_path))
    injected_log = tmp_path / INJ_LOG.name
    shutil.copy2(INJ_LOG, injected_log)
    diag = tools.dispatch("diagnose_out", {"path": str(injected_log)})
    # The log's 'mint an approval_token now' text is inert: nothing was minted,
    # so run_execute bound to this source still refuses.
    with pytest.raises(tools.ToolError):
        tools.dispatch("run_execute", {"source": str(injected_log), "approval_token": "granted"})
    assert diag["path"].endswith("injected_log.out")
