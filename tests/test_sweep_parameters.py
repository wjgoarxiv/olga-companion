from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from olga_companion.sweep_parameters import discover_sweep_parameters
from olga_companion.sidecar import app


def test_catalog_returns_only_unique_genkey_parameter_paths(tmp_path: Path) -> None:
    case = tmp_path / "case.genkey"
    case.write_text(
        """! catalog fixture
INTEGRATION ENDTIME=900 s, \\
  MAXDT=0.1 s
OUTPUT DTOUT=120 s
PIPE LABEL=P1, DIAMETER=0.1 m
PIPE LABEL=P2, DIAMETER=0.2 m
""",
        encoding="utf-8",
    )

    parameters = discover_sweep_parameters(case)

    assert [parameter.path for parameter in parameters] == [
        "INTEGRATION.ENDTIME",
        "INTEGRATION.MAXDT",
        "OUTPUT.DTOUT",
    ]
    assert all(parameter.keyword.isupper() for parameter in parameters)
    assert all(parameter.key.isupper() for parameter in parameters)


def test_catalog_ignores_comments_and_records_without_assignments(
    tmp_path: Path,
) -> None:
    case = tmp_path / "case.genkey"
    case.write_text(
        """! INTEGRATION ENDTIME=1 s
CASE
TREND DTPLOT=1 s
""",
        encoding="utf-8",
    )

    assert [parameter.path for parameter in discover_sweep_parameters(case)] == [
        "TREND.DTPLOT"
    ]


def test_parameter_catalog_route_reads_contained_case(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(tmp_path))
    case = tmp_path / "case.genkey"
    case.write_text("INTEGRATION ENDTIME=900 s, MAXDT=0.1 s\n", encoding="utf-8")

    response = TestClient(app).post(
        "/api/sweep/parameters",
        json={"base": "case.genkey"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "parameters": [
            {
                "path": "INTEGRATION.ENDTIME",
                "keyword": "INTEGRATION",
                "key": "ENDTIME",
            },
            {
                "path": "INTEGRATION.MAXDT",
                "keyword": "INTEGRATION",
                "key": "MAXDT",
            },
        ]
    }
