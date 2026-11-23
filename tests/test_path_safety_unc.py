"""Network (UNC) paths are refused before any filesystem call (security review B1, B2, C1).

On Windows, merely resolving or stat-ing ``\\\\host\\share\\x`` opens an SMB
connection and sends the user's NTLM challenge response to that host. A case
file or a tool argument must never cause that.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from olga_companion import path_safety, run_companions, workspace_paths
from olga_companion import result_export_paths

NETWORK = [
    "\\\\evil\\share\\x.genkey",
    "//evil/share/x.genkey",
    "\\\\?\\UNC\\evil\\share\\x.genkey",
    "\\\\.\\pipe\\x.genkey",
    "\\/evil/share/x.genkey",
    "  \\\\evil\\share\\x.genkey",
    "\" \\\\evil\\share\\x.genkey\"",
]


class _Workspace(ValueError):
    pass


@pytest.fixture
def no_fs(monkeypatch: pytest.MonkeyPatch):
    """Fail if the code touches the filesystem with the given path."""

    def boom(self, *args, **kwargs):  # noqa: ANN001
        raise AssertionError(f"filesystem call on {self!s}")

    for name in ("resolve", "stat", "is_file", "exists", "open"):
        monkeypatch.setattr(Path, name, boom)


@pytest.mark.parametrize("value", NETWORK)
def test_is_network_path_recognises_unc_forms(value: str) -> None:
    assert path_safety.is_network_path(value)


@pytest.mark.parametrize(
    "value",
    ["case.genkey", "sub/case.genkey", "C:\\work\\case.genkey", "/home/u/case.genkey", "..\\up\\x.tab", "",
     # Windows hands installed apps their own folders in the local extended-length form.
     "\\\\?\\C:\\Program Files\\OLGA Companion\\resources\\fluids\\air_water.tab",
     "//?/d:/work/case.genkey"],
)
def test_ordinary_paths_are_not_network(value: str) -> None:
    assert not path_safety.is_network_path(value)


@pytest.mark.parametrize("value", NETWORK)
def test_contained_at_refuses_network_before_resolving(value: str, tmp_path: Path, no_fs) -> None:
    with pytest.raises(_Workspace) as caught:
        workspace_paths.contained_at(tmp_path, value, _Workspace)
    assert caught.value.error_code == "path_outside_workspace"


@pytest.mark.parametrize("value", NETWORK)
def test_resolve_input_file_refuses_network_before_resolving(value: str, tmp_path: Path, no_fs) -> None:
    with pytest.raises(_Workspace) as caught:
        workspace_paths.resolve_input_file_at(value, {".genkey"}, tmp_path, tmp_path, _Workspace)
    assert caught.value.error_code == "path_outside_workspace"


@pytest.mark.parametrize("value", NETWORK)
def test_resolve_result_refuses_network_before_resolving(value: str, no_fs) -> None:
    with pytest.raises(_Workspace) as caught:
        workspace_paths.resolve_result(value, (".tpl",), _Workspace)
    assert caught.value.error_code == "path_outside_workspace"


@pytest.mark.parametrize("value", NETWORK)
def test_export_path_refuses_network_before_resolving(value: str, tmp_path: Path, no_fs) -> None:
    with pytest.raises(result_export_paths.OlgaInputError):
        result_export_paths.require_export_path(value, exports_root=lambda: tmp_path)


def _case(tmp_path: Path, reference: str) -> Path:
    case = tmp_path / "case.genkey"
    case.write_text(f'CASE PROJECT="p"\nFILES PVTFILE="{reference}"\n', encoding="utf-8")
    return case


def _guard_network_touch(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    touched: list[str] = []
    real_is_file, real_resolve = Path.is_file, Path.resolve

    def is_file(self):  # noqa: ANN001
        if "evil" in str(self):
            touched.append(str(self))
            raise AssertionError("network path touched")
        return real_is_file(self)

    def resolve(self, *args, **kwargs):  # noqa: ANN001
        if "evil" in str(self):
            touched.append(str(self))
            raise AssertionError("network path touched")
        return real_resolve(self, *args, **kwargs)

    monkeypatch.setattr(Path, "is_file", is_file)
    monkeypatch.setattr(Path, "resolve", resolve)
    monkeypatch.setattr(
        run_companions,
        "_file_sha256",
        lambda path: (_ for _ in ()).throw(AssertionError("hashed")) if "evil" in str(path) else None,
    )
    return touched


def test_network_companion_is_listed_unfound_and_never_touched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = _case(tmp_path, "\\\\evil\\share\\fluid.tab")
    touched = _guard_network_touch(monkeypatch)
    manifest = run_companions.effective_companion_manifest(case)
    assert manifest == [
        {"kind": "pvt", "reference": "\\\\evil\\share\\fluid.tab", "resolved_path": None, "sha256": None}
    ]
    assert touched == []


def test_network_companion_is_not_staged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    case = _case(tmp_path, "//evil/share/fluid.tab")
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    working = run_dir / "case.genkey"
    working.write_bytes(case.read_bytes())
    touched = _guard_network_touch(monkeypatch)
    evidence = run_companions.stage_companions(case, working, run_dir)
    assert evidence["pvt_missing"] == ["//evil/share/fluid.tab"]
    assert evidence["pvt_files"] == []
    assert touched == []
    assert sorted(p.name for p in run_dir.iterdir()) == ["case.genkey"]


@pytest.mark.parametrize("value", NETWORK)
def test_genkey_and_fluid_routes_refuse_network_before_resolving(value: str, no_fs) -> None:
    from olga_companion import fluids, genkey_static

    with pytest.raises(genkey_static.OlgaInputError, match="network"):
        genkey_static.require_genkey_path(value)
    with pytest.raises(fluids.OlgaInputError, match="network"):
        fluids.require_fluid_path(value.replace(".genkey", ".tab"), {".tab"})


@pytest.mark.parametrize("value", NETWORK)
def test_workspace_root_and_case_dialog_refuse_network_before_resolving(value: str, no_fs) -> None:
    from olga_companion import workspace_root

    with pytest.raises(_Workspace, match="network"):
        workspace_root.plan_root_transition(
            value.replace("x.genkey", ""), context_identity=lambda: (Path("/w"), 0),
            env_workspace_root=None, workspace_error=_Workspace,
        )
    with pytest.raises(_Workspace, match="network"):
        workspace_root.selected_case_path(value, (".genkey",), _Workspace)


def test_fluid_consistency_lists_a_network_pvtfile_without_touching_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from olga_companion import fluids

    case = _case(tmp_path, "\\\\evil\\share\\fluid.tab")
    touched = _guard_network_touch(monkeypatch)
    monkeypatch.setattr(fluids, "_validate_tab", lambda *a, **k: (_ for _ in ()).throw(AssertionError("validated")))
    report = fluids.consistency(str(case))
    assert report["references"] == [
        {"raw": "\\\\evil\\share\\fluid.tab", "resolved": None, "exists": False, "network": True, "cross_check": None}
    ]
    assert report["missing"] == 1
    assert touched == []


def test_local_companion_still_works(tmp_path: Path) -> None:
    (tmp_path / "fluid.tab").write_text("tab", encoding="utf-8")
    case = _case(tmp_path, "fluid.tab")
    manifest = run_companions.effective_companion_manifest(case)
    assert manifest[0]["sha256"] is not None
