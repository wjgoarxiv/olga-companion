from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from olga_companion import config, sweep_execution, workspace
from olga_companion.agent import session_token
from olga_companion.sidecar import app
from olga_companion.sweep_execution import (
    approval_payload,
    execute_sweep,
    preview_sweep,
)
from sweep_test_support import FAKE_OLGA, SIMPLE, _resolvable_case

pytestmark = pytest.mark.skipif(
    not SIMPLE.exists(), reason="OLGA skill sample cases are unavailable"
)


def test_sweep_preview_persists_generated_cases(tmp_path: Path) -> None:
    """Given a resolvable base case, When a sweep is previewed, Then it gets a stable approval id and case list."""
    preview = preview_sweep(
        str(_resolvable_case(tmp_path)),
        ["INTEGRATION.ENDTIME=3600,7200"],
        "oat",
        5,
        30,
    )

    assert preview["sweep_id"]
    assert preview["dry_run"] is True
    assert preview["state"] == "planned"
    assert len(preview["cases"]) == 2
    assert approval_payload(preview["sweep_id"], preview["plan_id"]) == {
        "sweep_id": preview["sweep_id"],
        "plan_id": preview["plan_id"],
    }
    assert all(Path(case["path"]).exists() for case in preview["cases"])


@pytest.mark.parametrize("max_cases", [21, 1_000_000_000])
def test_sweep_preview_route_rejects_case_limits_above_twenty(max_cases: int) -> None:
    response = TestClient(app).post(
        "/api/sweep/preview",
        json={"base": "case.genkey", "sweeps": ["A=1,2"], "max_cases": max_cases},
    )

    assert response.status_code == 422


def test_sweep_registry_rejects_more_than_twenty_cases_before_materialization(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    base = tmp_path / "case.genkey"
    base.write_text("CASE LABEL=case\nENDCASE\n", encoding="utf-8")
    monkeypatch.setattr(
        sweep_execution.genkey_static, "require_genkey_path", lambda value: base
    )
    monkeypatch.setattr(
        sweep_execution.runner,
        "detect_olga",
        lambda source=None: {"detected": True, "candidate_id": "c"},
    )
    monkeypatch.setattr(
        sweep_execution.genkey_static,
        "sweep_preview",
        lambda *args: {
            "ok": True,
            "base": str(base),
            "strategy": "oat",
            "sweeps": ["A=1,2"],
            "output_dir": str(tmp_path),
            "command": {},
            "plan": [
                {"index": index, "path": str(tmp_path / f"case-{index}.genkey")}
                for index in range(21)
            ],
        },
    )

    with pytest.raises(ValueError, match="20"):
        preview_sweep(str(base), ["A=1,2"], max_cases=20)


def test_sweep_preview_rejects_more_than_twenty_values_before_tool_invocation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tool = Mock()
    monkeypatch.setattr(sweep_execution.genkey_static, "sweep_preview", tool)
    values = ",".join(str(value) for value in range(21))

    with pytest.raises(ValueError, match="20"):
        preview_sweep("case.genkey", [f"A={values}"], max_cases=20)

    tool.assert_not_called()


def test_sweep_execution_rejects_workspace_generation_changed_after_preview(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("OLGA_EXE_PATH", str(FAKE_OLGA))
    old = tmp_path / "old-workspace"
    new = tmp_path / "new-workspace"
    old.mkdir()
    new.mkdir()
    base = _resolvable_case(old)
    config.set_workspace_root(str(old))
    preview = preview_sweep(str(base), ["INTEGRATION.ENDTIME=3600,7200"], "oat", 5, 30)
    child_calls: list[str] = []
    monkeypatch.setattr(
        "olga_companion.sweep_execution.runner.execute_run",
        lambda source, **kwargs: child_calls.append(source) or {"run_id": "unexpected"},
    )

    workspace.switch_root(new)

    with pytest.raises(ValueError, match="Workspace context changed"):
        execute_sweep(preview["sweep_id"], approved=True, plan_id=preview["plan_id"])
    assert preview["context_generation"] == 0
    assert child_calls == []


def test_direct_sweep_execute_api_returns_conflict_for_stale_preview(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("OLGA_EXE_PATH", str(FAKE_OLGA))
    old = tmp_path / "api-old"
    new = tmp_path / "api-new"
    old.mkdir()
    new.mkdir()
    config.set_workspace_root(str(old))
    preview = preview_sweep(
        str(_resolvable_case(old)),
        ["INTEGRATION.ENDTIME=3600,7200"],
        "oat",
        5,
        30,
    )
    workspace.switch_root(new)

    response = TestClient(app).post(
        "/api/sweep/execute",
        json={
            "sweep_id": preview["sweep_id"],
            "plan_id": preview["plan_id"],
            "approved": True,
        },
        headers={"X-Session-Token": session_token.boot_token()},
    )

    assert response.status_code == 409
    assert "Workspace context changed" in response.json()["detail"]
