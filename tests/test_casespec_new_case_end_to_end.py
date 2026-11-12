"""From-scratch CaseSpec through the agent tools, without starting OLGA."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest

from case_spec_v2_support import AMBIENT
from olga_companion import windows_broker, workspace
from olga_companion.agent import approvals, tools
from olga_companion.agent import case_publish_adapter

_FIXTURES = Path(__file__).parent / "fixtures"
_TAB = _FIXTURES / "fluids" / "fluid.tab"
# simple_pipeline.genkey: ENDTIME=24 h, 50/30 bara, 20/15 C, 0.3 m, 2.5e-05 m, 5 sections.
_END_TIME_S = 24 * 3600
_BARA_TO_PA = 100_000


def _spec() -> dict:
    material = AMBIENT["wall"]["material"]
    return {
        "version": "2",
        "nodes": [
            {
                "label": "Inlet_Node",
                "kind": "source",
                "pressure_pa": 50 * _BARA_TO_PA,
                "temperature_c": 20,
                "gas_fraction": 0.2,
                "total_water_fraction": 0.4,
            },
            {
                "label": "Outlet_Node",
                "kind": "sink",
                "pressure_pa": 30 * _BARA_TO_PA,
                "temperature_c": 15,
                "gas_fraction": 0.15,
                "total_water_fraction": 0.35,
            },
        ],
        "flowpaths": [{
            "label": "Pipeline",
            "from": "Inlet_Node",
            "to": "Outlet_Node",
            "pipes": [
                {
                    "label": "Pipe_1",
                    "centerline_m": [[0, 0, 0], [100, 0, 0]],
                    "diameter_m": 0.3,
                    "roughness_m": 2.5e-05,
                    "sections": 5,
                },
                {
                    "label": "Pipe_2",
                    "centerline_m": [[100, 0, 0], [200, 0, 0]],
                    "diameter_m": 0.3,
                    "roughness_m": 2.5e-05,
                    "sections": 5,
                },
                {
                    "label": "Pipe_3",
                    "centerline_m": [[200, 0, 0], [300, 0, 0]],
                    "diameter_m": 0.3,
                    "roughness_m": 2.5e-05,
                    "sections": 5,
                },
            ],
        }],
        "pvt_reference": "fluid.tab",
        "fluid_label": "FLUID-A",
        "thermal": {
            "model": "ambient_h_given",
            "ambient_temperature_c": 10,
            "outer_heat_transfer_coefficient_w_m2k": 10,
            "wall": {
                "thickness_m": 0.01,
                "material": {
                    "conductivity_w_mk": material["conductivity_w_mk"],
                    "heat_capacity_j_kgk": material["heat_capacity_j_kgk"],
                    "density_kg_m3": material["density_kg_m3"],
                },
            },
        },
        "integration": {"end_time_s": _END_TIME_S},
        "outputs": ["PT", "TM"],
    }


@pytest.fixture(autouse=True)
def _clear_approvals() -> None:
    approvals.revoke_all()
    yield
    approvals.revoke_all()


def _workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "workspace"
    root.mkdir()
    shutil.copyfile(_TAB, root / "fluid.tab")
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(root))
    monkeypatch.setenv("OLGA_CASE_TRANSACTION_DIR", str(tmp_path / "transactions"))
    monkeypatch.setenv("OLGA_CASE_PUBLISH_JOURNAL_DIR", str(tmp_path / "journal"))
    return root


def _windows_broker_cache(monkeypatch: pytest.MonkeyPatch) -> Path:
    """Engine preview builds the Explorer broker beside a Windows-visible cache.

    The pytest sandbox is under /tmp, which the broker refuses. This cache is
    only the compile output; preview does not start OLGA.
    """
    parent = Path("/mnt/c/Users/Woojin/AppData/Local/Temp")
    parent.mkdir(parents=True, exist_ok=True)
    hold = tempfile.TemporaryDirectory(prefix="olga-e2e-broker-", dir=parent)
    cache = Path(hold.name)
    monkeypatch.setattr(windows_broker, "sandbox_root", lambda: cache)
    monkeypatch.setattr(windows_broker, "_e2e_cache_hold", hold, raising=False)
    return cache


def _closed_inlet_spec() -> dict:
    spec = _spec()
    inlet = spec["nodes"][0]
    inlet["kind"] = "closed"
    del inlet["pressure_pa"]
    del inlet["temperature_c"]
    del inlet["gas_fraction"]
    del inlet["total_water_fraction"]
    spec["massflow_sources"] = [{
        "label": "FEED",
        "flowpath": "Pipeline",
        "pipe": "Pipe_1",
        "section": 1,
        "time_s": 0.0,
        "mass_flow_kg_s": 1.0,
        "temperature_c": 20.0,
        "gas_fraction": 0.0,
        "total_water_fraction": 0.0,
    }]
    return spec


def _plan(root: Path, destination_rel: str, spec: dict | None = None) -> tuple[dict, dict]:
    assert root.is_dir()
    spec = _spec() if spec is None else spec
    validated = tools.dispatch("case_spec_validate", {"spec": spec})
    assert validated["valid"] is True
    compiled = tools.dispatch("case_spec_compile", {"spec": spec})
    assert compiled["valid"] is True
    assert compiled["compiled_hash"]
    plan = tools.dispatch(
        "case_edit_plan",
        {
            "spec": spec,
            "spec_hash": validated["spec_hash"],
            "destination_rel": destination_rel,
            "operations": [],
        },
    )
    assert plan["publishable"] is True
    assert plan["compiled_hash"]
    return spec, plan


def test_new_casespec_publishes_and_preflights(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _workspace(tmp_path, monkeypatch)
    destination = "pipeline.genkey"
    _spec_body, plan = _plan(root, destination)
    args = {
        "transaction_id": plan["transaction_id"],
        "source_hash": plan["source_hash"],
        "compiled_hash": plan["compiled_hash"],
        "destination_rel": destination,
        "context_generation": plan["context_generation"],
    }
    payload = case_publish_adapter.approval_payload(args)
    token = approvals.mint(
        "case_publish", payload, context_generation=plan["context_generation"]
    )["token"]
    receipt = tools.dispatch(
        "case_publish",
        {**args, "approval_token": token, "idempotency_key": "n" * 32},
    )

    published = root / destination
    assert receipt["state"] == "completed"
    assert receipt["published_hash"] == plan["compiled_hash"]
    assert published.is_file()
    assert Path(workspace.active_path() or "").resolve() == published.resolve()
    assert (root / "fluid.tab").is_file()
    assert b'FILES PVTFILE="fluid.tab"' in published.read_bytes()
    assert b'FLUID="FLUID-A"' in published.read_bytes()

    review = tools.dispatch("genkey_review", {"path": str(published)})
    _windows_broker_cache(monkeypatch)
    detected = tools.dispatch("run_detect", {"source": str(published)})
    candidates = [
        item for item in detected.get("candidates", []) if isinstance(item, dict) and item.get("candidate_id")
    ]
    assert candidates, detected
    runtime = candidates[0]
    preflight = tools.dispatch(
        "simulation_setup",
        {
            "binding": {"kind": "active_case", "source_sha256": review["source_sha256"]},
            "integration": {"end_time_s": _END_TIME_S},
            "outputs": ["PT", "TM"],
            "runtime": {
                "candidate_id": runtime["candidate_id"],
                "runtime_id": runtime["runtime_id"],
            },
            "timeout_s": 120,
            "output_target": {"relative_dir": "managed-run-sandbox"},
            "context_generation": plan["context_generation"],
        },
    )
    assert preflight["ready"] is True, preflight


def test_closed_inlet_publishes_and_preflights(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _workspace(tmp_path, monkeypatch)
    destination = "closed-inlet.genkey"
    _spec_body, plan = _plan(root, destination, _closed_inlet_spec())
    args = {
        "transaction_id": plan["transaction_id"],
        "source_hash": plan["source_hash"],
        "compiled_hash": plan["compiled_hash"],
        "destination_rel": destination,
        "context_generation": plan["context_generation"],
    }
    payload = case_publish_adapter.approval_payload(args)
    token = approvals.mint(
        "case_publish", payload, context_generation=plan["context_generation"]
    )["token"]
    receipt = tools.dispatch(
        "case_publish",
        {**args, "approval_token": token, "idempotency_key": "c" * 32},
    )

    published = root / destination
    text = published.read_text(encoding="utf-8")
    inlet = text.split("TAG=INLET_NODE", 1)[1].split("ENDNETWORKCOMPONENT", 1)[0]
    assert receipt["state"] == "completed"
    assert "TYPE=CLOSED" in inlet
    assert "PRESSURE=" not in inlet
    assert 'SOURCE LABEL="FEED"' in text
    assert Path(workspace.active_path() or "").resolve() == published.resolve()

    review = tools.dispatch("genkey_review", {"path": str(published)})
    _windows_broker_cache(monkeypatch)
    detected = tools.dispatch("run_detect", {"source": str(published)})
    candidates = [
        item for item in detected.get("candidates", []) if isinstance(item, dict) and item.get("candidate_id")
    ]
    assert candidates, detected
    runtime = candidates[0]
    preflight = tools.dispatch(
        "simulation_setup",
        {
            "binding": {"kind": "active_case", "source_sha256": review["source_sha256"]},
            "integration": {"end_time_s": _END_TIME_S},
            "outputs": ["PT", "TM"],
            "runtime": {
                "candidate_id": runtime["candidate_id"],
                "runtime_id": runtime["runtime_id"],
            },
            "timeout_s": 120,
            "output_target": {"relative_dir": "managed-run-sandbox"},
            "context_generation": plan["context_generation"],
        },
    )
    assert preflight["ready"] is True, preflight


def test_publish_refuses_a_destination_without_its_tab(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _workspace(tmp_path, monkeypatch)
    (root / "sub").mkdir()
    _spec_body, plan = _plan(root, "sub/pipeline.genkey")
    args = {
        "transaction_id": plan["transaction_id"],
        "source_hash": plan["source_hash"],
        "compiled_hash": plan["compiled_hash"],
        "destination_rel": "sub/pipeline.genkey",
        "context_generation": plan["context_generation"],
    }

    with pytest.raises(tools.ToolError, match="PVT|companion|beside|missing"):
        case_publish_adapter.approval_payload(args)

    assert not (root / "sub" / "pipeline.genkey").exists()
    assert list(root.glob("*.genkey")) == []
