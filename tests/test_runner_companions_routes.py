from __future__ import annotations

import shutil
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from olga_companion.runner import (
    execute_run,
    run_status,
)
from olga_companion.sidecar import app

FAKE_OLGA = Path(__file__).parent / "fixtures" / "fake_olga" / "fake_olga.py"
FLUID_TAB = Path(__file__).parent / "fixtures" / "fluids" / "fluid.tab"
SAMPLE_ROOT = Path(__file__).parent / "fixtures" / "cases"
SIMPLE = SAMPLE_ROOT / "simple_pipeline.genkey"
BROKEN = SAMPLE_ROOT / "intentionally_broken.genkey"

pytestmark = pytest.mark.skipif(not SIMPLE.exists(), reason="OLGA skill sample cases are unavailable")


def _resolvable_case(tmp_path: Path, name: str = "case.genkey") -> Path:
    """SIMPLE with its PVTFILE reference satisfied: refs ./fluid.tab, copied beside."""
    case = tmp_path / name
    text = SIMPLE.read_text()
    case.write_text(text.replace('"./dummy_fluid.tab"', '"./fluid.tab"'))
    shutil.copy2(FLUID_TAB, tmp_path / "fluid.tab")
    return case


def _wait_for_final_state(run_id: str, timeout_s: float = 15.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        status = run_status(run_id)
        if status["state"] != "running":
            return status
        time.sleep(0.2)
    raise AssertionError(f"run {run_id} did not reach a final state within {timeout_s}s")


def test_run_copies_relative_pvt_companion(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("OLGA_EXE_PATH", str(FAKE_OLGA))
    started = execute_run(str(_resolvable_case(tmp_path)), approved=True)
    run_dir = Path(started["run_dir"])
    assert (run_dir / "fluid.tab").exists(), "referenced PVT table must ride along into the sandbox"
    assert started["pvt_files"] == ["./fluid.tab"]
    assert started["pvt_missing"] == []
    _wait_for_final_state(started["run_id"])


def test_missing_pvt_ref_blocks_without_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from olga_companion.config import sandbox_root

    monkeypatch.setenv("OLGA_EXE_PATH", str(FAKE_OLGA))
    source = tmp_path / "case.genkey"
    shutil.copy2(SIMPLE, source)  # keeps the dangling ./dummy_fluid.tab reference
    runs_dir = sandbox_root() / "runs"
    before = set(p.name for p in runs_dir.iterdir()) if runs_dir.exists() else set()
    with pytest.raises(ValueError, match="PVTFILE"):
        execute_run(str(source), approved=True)
    after = set(p.name for p in runs_dir.iterdir()) if runs_dir.exists() else set()
    assert after == before, "refused preflight must not leave a run dir behind"


def test_missing_pvt_ref_allowed_with_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("OLGA_EXE_PATH", str(FAKE_OLGA))
    source = tmp_path / "case.genkey"
    shutil.copy2(SIMPLE, source)
    started = execute_run(str(source), approved=True, override=True)
    assert started["pvt_missing"] == ["./dummy_fluid.tab"]
    final = _wait_for_final_state(started["run_id"])
    assert final["ok"] is False, "override runs are never reported ok"


def test_traversal_pvt_ref_cannot_escape_sandbox(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """F1 regression: a PVTFILE ref with ../ must never write outside the run dir."""
    from olga_companion.config import sandbox_root

    monkeypatch.setenv("OLGA_EXE_PATH", str(FAKE_OLGA))
    # Case lives in work/; the traversal ref ../evil/fluid.tab resolves to a REAL
    # sibling file, so staging proceeds and would (pre-fix) write run_dir/../evil/.
    (tmp_path / "work").mkdir()
    (tmp_path / "evil").mkdir()
    shutil.copy2(FLUID_TAB, tmp_path / "evil" / "fluid.tab")
    case = tmp_path / "work" / "case.genkey"
    case.write_text(SIMPLE.read_text().replace('"./dummy_fluid.tab"', '"../evil/fluid.tab"'))

    runs_dir = sandbox_root() / "runs"
    escaped_before = (runs_dir / "evil").exists()
    started = execute_run(str(case), approved=True)
    run_dir = Path(started["run_dir"])
    # The tab was staged by basename INSIDE the run dir, and nothing was written to a sibling.
    assert (run_dir / "fluid.tab").exists()
    assert not (runs_dir / "evil").exists() or escaped_before, "traversal ref escaped run_dir"
    rewritten = (run_dir / "case.genkey").read_text()
    assert "../evil" not in rewritten, "escaping ref must be rewritten sandbox-relative"
    assert '"./fluid.tab"' in rewritten
    _wait_for_final_state(started["run_id"])


def test_absolute_pvt_ref_rewritten_sandbox_relative(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("OLGA_EXE_PATH", str(FAKE_OLGA))
    tab = tmp_path / "tables" / "fluid.tab"
    tab.parent.mkdir()
    shutil.copy2(FLUID_TAB, tab)
    case = tmp_path / "case.genkey"
    case.write_text(SIMPLE.read_text().replace('"./dummy_fluid.tab"', f'"{tab}"'))

    started = execute_run(str(case), approved=True)
    run_dir = Path(started["run_dir"])
    assert (run_dir / "fluid.tab").exists()
    rewritten = (run_dir / "case.genkey").read_text()
    assert str(tab) not in rewritten, "absolute host path must not survive into the executing copy"
    assert '"./fluid.tab"' in rewritten
    _wait_for_final_state(started["run_id"])


def test_run_routes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(tmp_path))
    case = tmp_path / SIMPLE.name
    shutil.copy2(SIMPLE, case)
    client = TestClient(app)

    monkeypatch.delenv("OLGA_EXE_PATH", raising=False)
    monkeypatch.setattr("olga_companion.runner.OLGA_EXE_GLOBS", [])
    detect = client.get("/api/run/detect")
    assert detect.status_code == 200
    assert detect.json()["detected"] is False

    monkeypatch.setenv("OLGA_EXE_PATH", str(FAKE_OLGA))
    preview = client.post("/api/run/preview", json={"source": str(case)})
    assert preview.status_code == 200
    body = preview.json()
    assert body["command"]
    assert body["display_command"]
    assert all(str(FAKE_OLGA) not in part for part in body["display_command"])
    assert body["selection_id"]
    assert body["candidate_id"]
    assert body["validation"]["valid"] is True

    from olga_companion.agent import session_token

    token = session_token.boot_token()
    # run/execute is now session-token guarded (T3 review consistency fix).
    execute_body = {"source": str(case), "approved": False, "selection_id": body["selection_id"]}
    no_token = client.post("/api/run/execute", json=execute_body)
    assert no_token.status_code == 401
    refused = client.post(
        "/api/run/execute", json=execute_body, headers={"X-Session-Token": token}
    )
    assert refused.status_code == 400

    missing = client.get("/api/run/status/nonexistent-run-id")
    assert missing.status_code == 404


def test_run_detect_route_contains_and_forwards_optional_source(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = TestClient(app)
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(tmp_path))
    case = tmp_path / "case.genkey"
    case.write_text("CASE LABEL=case\nENDCASE\n")
    seen: list[str | None] = []
    monkeypatch.setattr(
        "olga_companion.sidecar.detect_olga",
        lambda source=None: seen.append(source) or {"detected": False, "source": source},
    )

    response = client.get("/api/run/detect", params={"source": "case.genkey"})

    assert response.status_code == 200
    assert seen == [str(case.resolve())]

    escaped = client.get("/api/run/detect", params={"source": str(tmp_path.parent / "outside.genkey")})
    assert escaped.status_code == 400
