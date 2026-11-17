from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from olga_companion.opc import opc_capabilities, opc_gate_status
from olga_companion.sidecar import app

GATE_CONDITIONS = {
    "opc_dependencies",
    "windows_dcom",
    "olga_server_mode",
    "read_write_separation",
    "explicit_write_approval",
}


def test_gate_status_reports_all_documented_conditions() -> None:
    status = opc_gate_status()
    assert status["enabled"] is False
    assert set(status["conditions"].keys()) == GATE_CONDITIONS
    for condition in status["conditions"].values():
        assert condition["satisfied"] is False
        assert condition["reason"].strip()


def test_opc_capability_is_disabled() -> None:
    caps = opc_capabilities()
    assert caps["opc_live_control"]["enabled"] is False
    assert caps["opc_live_control"]["reason"].strip()


def test_status_route_is_always_available() -> None:
    client = TestClient(app)
    response = client.get("/api/opc/status")
    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is False
    assert len(body["conditions"]) == 5


def test_read_route_refuses_while_gate_closed() -> None:
    client = TestClient(app)
    response = client.post("/api/opc/read", json={"item": "OLGA.PT1.PRESSURE"})
    assert response.status_code == 403
    assert "gate" in response.json()["detail"].lower()


def test_write_refuses_even_with_approval_and_snapshot() -> None:
    client = TestClient(app)
    response = client.post(
        "/api/opc/write",
        json={"item": "OLGA.PT1.SETPOINT", "value": "100.0", "approved": True, "snapshot_id": "SNAP-1"},
    )
    assert response.status_code == 403


def test_open_gate_still_returns_501_not_live_control(monkeypatch: pytest.MonkeyPatch) -> None:
    # Even if every gate condition were satisfied, the control surface itself
    # is intentionally unimplemented until live Windows QA exists.
    import olga_companion.sidecar as sidecar_module

    monkeypatch.setattr(sidecar_module, "require_open_gate", lambda: {"enabled": True})
    client = TestClient(app)
    read = client.post("/api/opc/read", json={"item": "OLGA.PT1.PRESSURE"})
    assert read.status_code == 501
    write = client.post(
        "/api/opc/write",
        json={"item": "OLGA.PT1.SETPOINT", "value": "1", "approved": True, "snapshot_id": "S"},
    )
    assert write.status_code == 501


def test_write_precondition_contract_is_still_declared() -> None:
    # Even after the gate opens on a Windows host, a write must carry explicit
    # per-request approval plus a snapshot id — the contract is validated
    # before the gate check so it is enforceable and testable today.
    client = TestClient(app)
    no_approval = client.post("/api/opc/write", json={"item": "OLGA.X", "value": "1", "snapshot_id": "S"})
    assert no_approval.status_code == 400
    no_snapshot = client.post("/api/opc/write", json={"item": "OLGA.X", "value": "1", "approved": True})
    assert no_snapshot.status_code == 400
