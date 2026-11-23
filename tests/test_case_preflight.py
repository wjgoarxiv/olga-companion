"""0.1.22 row 8: a read-only file checklist before a run, built only from checks the app already has.
It never writes a file and never starts OLGA."""

from __future__ import annotations

from pathlib import Path

import pytest

from test_case_edit_routes import _headers, _install, client, ws  # noqa: F401

from olga_companion import genkey_static, pvt_range, runner
from olga_companion.genkey_tool_runner import CommandResult


def _preflight(case: Path, headers: dict[str, str] | None = None) -> object:
    return client.get("/api/case-preflight", params={"rel": case.name}, headers=_headers() if headers is None else headers)


def _items(case: Path) -> dict[str, dict]:
    response = _preflight(case)
    assert response.status_code == 200, response.text
    return {item["id"]: item for item in response.json()["items"]}


def _owner_case(root: Path, integration: str) -> Path:
    case = root / "owner.genkey"
    case.write_text(f"CASE LABEL=owner\nINTEGRATION {integration}\nENDCASE\n", encoding="utf-8")
    return case


def test_a_clean_compiled_case_passes_the_file_check(ws: Path) -> None:  # noqa: F811
    items = _items(_install(ws, "valve-shut-in"))
    assert items["validation"] == {"id": "validation", "state": "ok", "message_code": "validation_clean"}


@pytest.mark.parametrize(("exit_code", "timed_out", "stdout"), [(124, True, ""), (125, False, ""), (1, False, "Traceback: boom")])
def test_review_r6_a_validator_that_did_not_finish_is_not_called_an_input_error(
    ws: Path, monkeypatch: pytest.MonkeyPatch, exit_code: int, timed_out: bool, stdout: str,  # noqa: F811
) -> None:
    case = _install(ws, "valve-shut-in")
    result = CommandResult("validator", [], exit_code, stdout, "stderr text", timed_out, 30_000)
    monkeypatch.setattr(genkey_static, "run_tool", lambda *args, **kwargs: result)
    assert _items(case)["validation"] == {"id": "validation", "state": "warn", "message_code": "validation_unavailable"}


def test_a_validator_error_line_is_an_input_error(ws: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    case = _install(ws, "valve-shut-in")
    result = CommandResult("validator", [], 1, "header\n[X] PIPE P1: LENGTH missing\n", "", False, 10)
    monkeypatch.setattr(genkey_static, "run_tool", lambda *args, **kwargs: result)
    assert _items(case)["validation"] == {
        "id": "validation", "state": "warn", "message_code": "validation_failed", "detail": "[X] PIPE P1: LENGTH missing",
    }


def test_a_value_the_file_leaves_out_is_listed_as_not_set_on_its_row(ws: Path) -> None:  # noqa: F811
    items = _items(_install(ws, "valve-shut-in"))
    assert items["row:integration.max_dt_s"] == {
        "id": "row:integration.max_dt_s", "state": "missing", "row_id": "integration.max_dt_s", "message_code": "value_unset",
        "target": "MAXDT", "field": "max_dt_s",
    }


def test_a_missing_end_time_is_listed_as_missing(ws: Path) -> None:  # noqa: F811
    items = _items(_owner_case(ws, "DTSTART=0.1 s"))
    assert items["rule:endtime_missing"]["state"] == "missing"
    assert items["rule:endtime_missing"]["message_code"] == "endtime_missing"


def test_a_timing_rule_the_app_enforces_is_a_warning(ws: Path) -> None:  # noqa: F811
    items = _items(_owner_case(ws, "ENDTIME=600 s, MINDT=10 s, MAXDT=1 s"))
    item = items["rule:mindt_above_maxdt"]
    assert item["state"] == "warn"
    assert item["message_code"] == "mindt_above_maxdt"
    assert item["values"] == {"keyword": "INTEGRATION", "value": 10.0, "limit": 1.0, "unit": "s"}
    assert "row_id" not in item, "a case the app did not compile has no MINDT row to open"


def test_a_stated_end_time_raises_no_missing_item(ws: Path) -> None:  # noqa: F811
    items = _items(_owner_case(ws, "ENDTIME=600 s"))
    assert "rule:endtime_missing" not in items
    assert not [item for item in items.values() if item["state"] == "missing"]


def test_a_fluid_table_flag_is_a_warning_on_its_row(ws: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    case = _install(ws, "valve-shut-in")
    flag = {"origin": "OUTLET", "kind": "node", "quantity": "pressure", "value": "1 bar", "status": "outside", "relation": "below"}
    monkeypatch.setattr(pvt_range, "range_flags", lambda source, tab_dir=None: [flag])
    items = _items(case)
    assert items["pvt:OUTLET:pressure"] == {
        "id": "pvt:OUTLET:pressure", "state": "warn", "row_id": "nodes.OUTLET.pressure_pa", "message_code": "pvt_outside",
        "target": "OUTLET", "values": flag,
    }


def test_the_check_writes_nothing_and_never_starts_olga(ws: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    case = _install(ws, "valve-shut-in")

    def refuse(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("the file check started the OLGA runner")

    for name in ("detect_olga", "preview_run", "execute_run"):
        monkeypatch.setattr(runner, name, refuse)
    before = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    _items(case)
    after = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    assert after == before


def test_the_check_needs_the_session_token(ws: Path) -> None:  # noqa: F811
    response = _preflight(_install(ws, "valve-shut-in"), headers={})
    assert response.status_code == 401


def test_a_case_outside_the_workspace_is_refused(ws: Path, tmp_path: Path) -> None:  # noqa: F811
    outside = tmp_path / "outside.genkey"
    outside.write_text("CASE\n", encoding="utf-8")
    response = client.get("/api/case-preflight", params={"rel": str(outside)}, headers=_headers())
    assert response.status_code == 400
