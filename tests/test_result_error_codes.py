"""0.1.22 row 5: a result read refusal carries a stable code next to the original message, so the
app can show a headline in its own language and keep the raw text below it."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from olga_companion import results as R
from olga_companion.result_series_view import ResultSeriesDataError
from olga_companion.sidecar import app

FIX = Path(__file__).parent / "fixtures" / "results"

pytestmark = pytest.mark.skipif(not (FIX / "fixture.tpl").exists(), reason="result fixtures unavailable")


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(FIX))
    R._LOAD_CACHE.clear()
    return TestClient(app)


def _detail(response) -> dict:
    assert response.status_code == 400, response.text
    detail = response.json()["detail"]
    assert isinstance(detail, dict), detail
    assert detail["message"], "the original message is never empty"
    return detail


def test_an_invalid_variable_name_has_its_code(client: TestClient) -> None:
    detail = _detail(client.post("/api/results/series", json={"rel": "fixture.tpl", "variable": "-bad"}))
    assert detail["code"] == "variable_invalid"
    assert "-bad" in detail["message"]


def test_an_invalid_position_has_its_code(client: TestClient) -> None:
    detail = _detail(client.post("/api/results/series", json={"rel": "fixture.tpl", "variable": "HOL", "position": "-x"}))
    assert detail["code"] == "position_invalid"


def test_an_unreadable_series_has_its_code(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(R, "run_tool", lambda *_a, **_k: SimpleNamespace(stdout="not json"))
    detail = _detail(client.post("/api/results/series", json={"rel": "fixture.tpl", "variable": "HOL"}))
    assert detail["code"] == "series_unreadable"
    assert "fixture.tpl" in detail["message"]


@pytest.mark.parametrize("message", ["The selected result series has no finite samples.", "Result time samples must be non-decreasing."])
def test_review_r7_a_problem_in_the_series_data_is_not_blamed_on_the_unit_or_range(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, message: str,
) -> None:
    def broken(*_a, **_k):
        raise ResultSeriesDataError(message)

    monkeypatch.setattr(R, "apply_series_view", broken)
    detail = _detail(client.post("/api/results/series", json={"rel": "fixture.tpl", "variable": "HOL"}))
    assert detail == {"code": "series_data_invalid", "message": message}


def test_a_range_the_series_cannot_take_keeps_the_view_code(client: TestClient) -> None:
    body = {"rel": "fixture.tpl", "variable": "HOL", "range": {"mode": "bounds", "start": 10, "end": 1}}
    assert _detail(client.post("/api/results/series", json=body))["code"] == "view_invalid"


def test_an_invalid_profile_branch_has_its_code(client: TestClient) -> None:
    detail = _detail(client.post("/api/results/profile", json={"rel": "fixture.tpl", "variable": "HOL", "branch": "-b"}))
    assert detail["code"] == "branch_invalid"


def test_an_unreadable_profile_has_its_code(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(R, "run_tool", lambda *_a, **_k: SimpleNamespace(stdout="{}"))
    detail = _detail(client.post("/api/results/profile", json={"rel": "fixture.tpl", "variable": "HOL", "branch": "PIPE"}))
    assert detail["code"] == "profile_unreadable"


def test_an_uncoded_refusal_keeps_its_plain_text_detail(client: TestClient) -> None:
    response = client.post("/api/results/series", json={"rel": "../../../etc/passwd", "variable": "HOL"})
    assert response.status_code >= 400
    assert isinstance(response.json()["detail"], str)
