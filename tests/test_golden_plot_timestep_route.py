"""R9: the profile timestep the screen sends reaches plot_result through the real route."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

import olga_companion.sidecar as sidecar_module
from olga_companion.result_plot_exports import _profile_at


def _capture(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    seen: dict[str, Any] = {}

    def fake(*args: Any, **kwargs: Any) -> dict[str, Any]:
        seen["args"] = args
        seen["kwargs"] = kwargs
        return {"plots": [], "selected_plot": None}

    monkeypatch.setattr(sidecar_module, "plot_result", fake)
    return seen


def test_route_forwards_the_timestep(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _capture(monkeypatch)
    response = TestClient(sidecar_module.app).post(
        "/api/results/plot",
        json={"path": "case.ppl", "variables": ["HOL"], "branch": "PIPE", "timestep": 60},
    )
    assert response.status_code == 200, response.text
    assert seen["kwargs"]["timestep"] == 60


def test_route_without_timestep_sends_none(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _capture(monkeypatch)
    TestClient(sidecar_module.app).post(
        "/api/results/plot", json={"path": "case.ppl", "variables": ["HOL"], "branch": "PIPE"}
    )
    assert seen["kwargs"]["timestep"] is None


@pytest.mark.parametrize("bad", [-1, "nan"])
def test_route_refuses_a_bad_timestep(monkeypatch: pytest.MonkeyPatch, bad: Any) -> None:
    _capture(monkeypatch)
    response = TestClient(sidecar_module.app).post(
        "/api/results/plot",
        json={"path": "case.ppl", "variables": ["HOL"], "branch": "PIPE", "timestep": bad},
    )
    assert response.status_code == 422


def test_profile_at_picks_the_nearest_timestep() -> None:
    plots = [f"/x/PIPE_HOL_t{t:08.1f}.png" for t in (0.0, 30.0, 60.0, 90.0)]
    assert _profile_at(plots, 58.0).endswith("t000060.0.png")
    assert _profile_at(plots, None).endswith("t000090.0.png")
