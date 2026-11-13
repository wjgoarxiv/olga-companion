"""Guided new-case intake reads its required-field list from the CaseSpec schema."""

from __future__ import annotations

from fastapi.testclient import TestClient

from olga_companion import sidecar


def _requirements() -> dict:
    response = TestClient(sidecar.app).get("/api/case-spec/requirements")
    assert response.status_code == 200
    return response.json()


def test_requirements_cover_every_intake_group() -> None:
    payload = _requirements()
    groups = {group["id"]: group for group in payload["groups"]}
    assert {
        "fluid",
        "boundary",
        "geometry",
        "thermal",
        "equipment",
        "outputs",
        "time",
    } <= set(groups)
    for group in payload["groups"]:
        assert group["title"]
        assert group["items"]
        for item in group["items"]:
            assert item["key"]
            assert item["label"]
            assert item["unit"]
            assert isinstance(item["required"], bool)


def test_fluid_and_time_fields_come_from_the_schema() -> None:
    payload = _requirements()
    by_key = {
        item["key"]: item
        for group in payload["groups"]
        for item in group["items"]
    }
    assert by_key["fluid.pvt_reference"]["required"] is True
    assert by_key["fluid.fluid_label"]["required"] is True
    assert by_key["time.end_time_s"]["required"] is True
    assert by_key["time.end_time_s"]["unit"] == "s"


def test_optional_equipment_stays_optional_and_outputs_stay_closed() -> None:
    payload = _requirements()
    by_key = {
        item["key"]: item
        for group in payload["groups"]
        for item in group["items"]
    }
    assert by_key["equipment.valve"]["required"] is False
    outputs = by_key["outputs.outputs"]
    assert outputs["required"] is True
    assert {"PT", "TM", "HOL"} <= set(outputs["values"])


def test_boundary_covers_pressure_or_massflow_intake() -> None:
    payload = _requirements()
    by_key = {
        item["key"]: item
        for group in payload["groups"]
        for item in group["items"]
    }
    assert by_key["boundary.source_pressure"]["unit"] == "Pa"
    assert by_key["boundary.massflow_rate"]["required"] is False
    assert by_key["boundary.inlet_choice"]["label"] == (
        "입구: 압력 경계 또는 막힌 끝 + 질량유량 입구"
    )
    assert by_key["boundary.inlet_choice"]["required"] is False
