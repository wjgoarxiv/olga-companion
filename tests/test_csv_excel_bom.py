"""L3: a CSV export can start with a UTF-8 BOM so Excel reads Korean and unit text right.

The BOM is opt-in. Without it the file bytes are exactly what they were before.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import olga_companion.sidecar as sidecar_module
from olga_companion import result_csv_exports
from olga_companion.genkey_static import CommandResult, file_sha256

BOM = b"\xef\xbb\xbf"


def _series(**_view: Any) -> dict[str, Any]:
    return {
        "variable": "PT", "position": "B", "unit": "bar", "time_unit": "s",
        "time": [0.0, 1.0], "values": [1.5, 2.5], "analysis": {}, "view": {},
    }


def _selected(tmp_path: Path, **options: Any) -> bytes:
    source = tmp_path / "case.tpl"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"source")
    exported = result_csv_exports.export_selected_series_csv(
        str(source), "PT", "B",
        value_unit=None, time_unit=None, quantity_kind="point", range_spec=None,
        resolve_result=Path, hash_file=file_sha256,
        exports_root=lambda: tmp_path / "exports",
        series_reader=lambda *_a, **view: _series(**view),
        **options,
    )
    assert exported["excel_bom"] is bool(options.get("excel_bom"))
    return Path(exported["csv"]).read_bytes()


def test_selected_csv_default_has_no_bom(tmp_path: Path) -> None:
    data = _selected(tmp_path)
    assert data == b"time_s,PT@B\r\n0.0,1.5\r\n1.0,2.5\r\n"


def test_selected_csv_with_excel_bom_only_adds_the_bom(tmp_path: Path) -> None:
    plain = _selected(tmp_path / "a")
    with_bom = _selected(tmp_path / "b", excel_bom=True)
    assert with_bom == BOM + plain


def _profile(tmp_path: Path, written: bytes, **options: Any) -> bytes:
    source = tmp_path / "case.ppl"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"source")

    def fake_tool(_key: str, args: list[str], **_kwargs: Any) -> CommandResult:
        Path(args[args.index("-o") + 1]).write_bytes(written)
        return CommandResult(script="data_exporter", args=args, exit_code=0, stdout="", stderr="", timed_out=False, elapsed_ms=1)

    exported = result_csv_exports.extract_csv(
        str(source), ["HOL"], "MAIN", None,
        resolve_result=Path, hash_file=file_sha256,
        exports_root=lambda: tmp_path / "exports",
        require_tokens=lambda values, _kind: values,
        run_tool=fake_tool, result_scripts={},
        **options,
    )
    assert exported["ok"] is True
    return Path(exported["csv"]).read_bytes()


def test_profile_csv_default_is_unchanged(tmp_path: Path) -> None:
    assert _profile(tmp_path, b"x,HOL\n0,0.1\n") == b"x,HOL\n0,0.1\n"


def test_profile_csv_with_excel_bom_gets_one_bom(tmp_path: Path) -> None:
    assert _profile(tmp_path / "a", b"x,HOL\n0,0.1\n", excel_bom=True) == BOM + b"x,HOL\n0,0.1\n"
    assert _profile(tmp_path / "b", BOM + b"x,HOL\n", excel_bom=True) == BOM + b"x,HOL\n"


def _capture(monkeypatch: pytest.MonkeyPatch, name: str) -> dict[str, Any]:
    seen: dict[str, Any] = {}

    def fake(*args: Any, **kwargs: Any) -> dict[str, Any]:
        seen["kwargs"] = kwargs
        return {"ok": True}

    monkeypatch.setattr(sidecar_module, name, fake)
    return seen


@pytest.mark.parametrize(
    ("body", "target"),
    [
        ({"path": "case.tpl", "variables": ["PT"], "position": "B"}, "export_selected_series_csv"),
        ({"path": "case.ppl", "variables": ["HOL"], "branch": "MAIN"}, "extract_csv"),
    ],
)
def test_route_forwards_the_excel_choice(monkeypatch: pytest.MonkeyPatch, body: dict, target: str) -> None:
    seen = _capture(monkeypatch, target)
    client = TestClient(sidecar_module.app)
    assert client.post("/api/results/extract-csv", json=body).status_code == 200
    assert seen["kwargs"]["excel_bom"] is False
    assert client.post("/api/results/extract-csv", json={**body, "excel_bom": True}).status_code == 200
    assert seen["kwargs"]["excel_bom"] is True
