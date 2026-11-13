from __future__ import annotations

import glob
import hashlib
import json
import os
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any, Mapping, Sequence

from .olga_runtime_paths import executable_kind, path_key
from .olga_runtime_versions import case_evidence, path_version


def executable_sha256(path: Path) -> str:
    """SHA-256 of the real file content. Never cached: the approval-pinned identity must detect replacement."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def candidate(exe: str, source: str) -> dict[str, Any]:
    release, version_key = path_version(exe)
    path = Path(exe)
    stat = path.stat()
    sha256 = executable_sha256(path)
    identity = json.dumps(
        {
            "exe": path_key(str(Path(exe).resolve())),
            "kind": executable_kind(exe),
            "version": release,
            "size": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
            "sha256": sha256,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    candidate_id = (
        "runtime_" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32]
    )
    return {
        "exe": exe,
        "kind": executable_kind(exe),
        "version": release,
        "source": source,
        "candidate_id": candidate_id,
        "runtime_id": candidate_id,
        "sha256": sha256,
        "_version_key": version_key,
    }


def candidate_sort_key(item: Mapping[str, Any]) -> tuple[Any, ...]:
    release = item["_version_key"]
    kind_priority = {"engine": 0, "opi": 1, "script": 2, "executable": 3}
    if release is None:
        return (
            1,
            0,
            0,
            0,
            kind_priority.get(str(item["kind"]), 9),
            path_key(str(item["exe"])),
        )
    return (
        0,
        -release[0],
        -release[1],
        -release[2],
        kind_priority.get(str(item["kind"]), 9),
        path_key(str(item["exe"])),
    )


def public_candidate(item: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in item.items() if not key.startswith("_")}


_EXCLUDED_INSTALL_DIRS = frozenset({"olga-s", "excel tool", "namespace explorer"})
_DISPLAY_VERSION = re.compile(r"(?i)\bOLGA\s*((?:20\d{2})|7)(?:\.\d+)*")


def _is_excluded_install(exe: str) -> bool:
    """True for companion/tool folders that are never OLGA engines."""
    return any(
        part.casefold() in _EXCLUDED_INSTALL_DIRS
        for part in exe.replace("\\", "/").split("/")
    )


def _is_olga_display_name(value: str) -> bool:
    """True for an engine release entry, never for companion/tool entries."""
    return _DISPLAY_VERSION.search(value or "") is not None


def _read_uninstall_registry() -> list[tuple[str, str]]:
    """Enumerate (DisplayName, InstallLocation) from the Uninstall keys.

    HKLM/HKCU × 64/32-bit views on Windows only; [] anywhere else.
    """
    try:
        import winreg
    except ImportError:
        return []
    found: list[tuple[str, str]] = []
    roots = [
        (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_64KEY),
        (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_32KEY),
        (winreg.HKEY_CURRENT_USER, winreg.KEY_WOW64_64KEY),
        (winreg.HKEY_CURRENT_USER, winreg.KEY_WOW64_32KEY),
    ]
    for hive, view in roots:
        try:
            key = winreg.OpenKey(
                hive,
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
                0,
                winreg.KEY_READ | view,
            )
        except OSError:
            continue
        with key:
            index = 0
            while True:
                try:
                    subkey_name = winreg.EnumKey(key, index)
                except OSError:
                    break
                index += 1
                try:
                    with winreg.OpenKey(key, subkey_name) as subkey:
                        name, _ = winreg.QueryValueEx(subkey, "DisplayName")
                        try:
                            location, _ = winreg.QueryValueEx(subkey, "InstallLocation")
                        except OSError:
                            location = ""
                except OSError:
                    continue
                if isinstance(name, str) and isinstance(location, str):
                    found.append((name, location))
    return found


def registry_install_locations(
    *,
    reader: Callable[[], list[tuple[str, str]]] | None = None,
) -> list[str]:
    """Install locations whose DisplayName names an OLGA engine release."""
    read = reader if reader is not None else _read_uninstall_registry
    try:
        pairs = read()
    except Exception:  # noqa: BLE001  # noqa: BROAD_EXCEPT_OK — registry is best-effort
        return []
    locations: list[str] = []
    for name, location in pairs:
        if not _is_olga_display_name(name) or not location.strip():
            continue
        if location not in locations:
            locations.append(location)
    return locations


def _detect_olga_inner(
    exe_globs: Sequence[str],
    environ: Mapping[str, str] | None = None,
    source: str | Path | None = None,
    registry_reader: Callable[[], list[tuple[str, str]]] | None = None,
    _ignore_manual: bool = False,
) -> dict[str, Any]:
    from . import config as _config

    environment = os.environ if environ is None else environ
    searched: list[str] = []
    candidates_by_path: dict[str, dict[str, Any]] = {}
    env_value = environment.get("OLGA_EXE_PATH", "").strip()
    manual_value = "" if (env_value or _ignore_manual) else _config.load_olga_exe_override().strip()
    override_value = env_value or manual_value
    override_source = (
        "env:OLGA_EXE_PATH"
        if env_value
        else ("manual:settings" if manual_value else "")
    )
    override_requested = bool(override_value)
    override_key: str | None = None
    if override_value:
        override = Path(override_value).expanduser()
        searched.append(f"{override_source}={override_value}")
        if override.is_file():
            try:
                override_key = path_key(str(override))
                candidates_by_path[override_key] = candidate(str(override), override_source)
            except OSError:
                override_key = None
    registry_patterns = [
        os.path.join(glob.escape(location), suffix)
        for location in registry_install_locations(reader=registry_reader)
        for suffix in ("opi.exe", os.path.join("bin", "opi.exe"), os.path.join("OlgaExecutables", "OLGA-*.exe"))
    ]
    registry_pattern_set = set(registry_patterns)
    for pattern in list(exe_globs) + registry_patterns:
        searched.append(pattern)
        matches = sorted(glob.glob(pattern))
        for exe in matches:
            if _is_excluded_install(exe):
                continue
            key = path_key(exe)
            if key not in candidates_by_path:
                origin = "registry" if pattern in registry_pattern_set else "install-glob"
                try:
                    candidates_by_path[key] = candidate(exe, origin)
                except OSError:
                    continue

    candidates_internal = sorted(candidates_by_path.values(), key=candidate_sort_key)
    candidates = [public_candidate(item) for item in candidates_internal]
    case_source, evidence = case_evidence(source)
    strong_versions = sorted(
        {item["version"] for item in evidence if item["strength"] == "strong"},
        key=lambda value: tuple(map(int, value.split("."))),
    )
    required_version = strong_versions[0] if len(strong_versions) == 1 else None

    base: dict[str, Any] = {
        "detected": False,
        "source": None,
        "exe": None,
        "kind": None,
        "searched": searched,
        "version": None,
        "sha256": None,
        "candidate_id": None,
        "runtime_id": None,
        "selection_status": "not_found",
        "required_version": required_version,
        "rationale": "No OLGA executable candidate was found.",
        "reason_code": "no_candidate_found",
        "reason_params": {},
        "candidates": candidates,
        "alternatives": candidates,
        "evidence": evidence,
        "case_source": case_source,
    }
    if len(strong_versions) > 1:
        base["selection_status"] = "conflicting_evidence"
        base["rationale"] = (
            "Conflicting engine-authored case versions were found: "
            + ", ".join(strong_versions)
            + "."
        )
        base["reason_code"] = "conflicting_evidence"
        base["reason_params"] = {"versions": list(strong_versions)}
        return base

    if override_requested and override_key is None:
        base["selection_status"] = "override_not_found"
        base["rationale"] = (
            "OLGA_EXE_PATH was set, but it does not name an existing executable file."
            if env_value
            else "The manually chosen OLGA executable was not found; pick it again in Settings."
        )
        base["reason_code"] = "override_not_found"
        base["reason_params"] = {}
        return base

    if override_key is not None:
        selected = candidates_by_path[override_key]
        if required_version is not None and selected["version"] != required_version:
            base["selection_status"] = "override_version_mismatch"
            override_version = selected["version"] or "unknown"
            base["rationale"] = (
                f"OLGA_EXE_PATH identifies OLGA {override_version}, but strong case evidence requires "
                f"OLGA {required_version}."
                if env_value
                else f"The manually chosen OLGA {override_version} does not match the OLGA {required_version} "
                f"this case evidence requires; pick the matching release in Settings."
            )
            base["reason_code"] = "override_version_mismatch"
            base["reason_params"] = {
                "override_version": override_version,
                "required_version": required_version,
            }
            return base
        status = "selected_override"
        rationale = (
            "Selected the explicit OLGA_EXE_PATH override."
            if env_value
            else "Selected the manually chosen OLGA executable from Settings."
        )
        reason_code = "selected_override"
        reason_params: dict[str, Any] = {}
    elif required_version is not None:
        selected = next(
            (
                item
                for item in candidates_internal
                if item["version"] == required_version
            ),
            None,
        )
        if selected is None:
            base["selection_status"] = "missing_required_version"
            base["rationale"] = (
                f"Engine-authored case evidence requires OLGA {required_version}, but that release is not installed."
            )
            base["reason_code"] = "missing_required_version"
            base["reason_params"] = {"required_version": required_version}
            return base
        status = "selected"
        rationale = f"Selected installed OLGA {required_version} to match strong engine-authored case evidence."
        reason_code = "selected_required_version"
        reason_params = {"version": required_version}
    elif candidates_internal:
        selected = next(
            (item for item in candidates_internal if item["kind"] == "engine"),
            candidates_internal[0],
        )
        status = "selected_fallback"
        if selected["version"] is None:
            rationale = (
                "No run record exists for this case; selected the available OLGA executable."
            )
            reason_code = "no_run_record_available"
            reason_params = {}
        elif selected["kind"] == "engine":
            rationale = (
                "No run record exists for this case; selected the newest installed "
                f"direct OLGA engine ({selected['version']})."
            )
            reason_code = "no_run_record_newest_direct"
            reason_params = {"version": selected["version"]}
        else:
            rationale = (
                "No run record exists for this case; selected the newest installed "
                f"OLGA ({selected['version']})."
            )
            reason_code = "no_run_record_newest_available"
            reason_params = {"version": selected["version"]}
    else:
        return base

    selected_public = public_candidate(selected)
    base.update(
        {
            "detected": True,
            "source": selected["source"],
            "exe": selected["exe"],
            "kind": selected["kind"],
            "version": selected["version"],
            "sha256": selected["sha256"],
            "candidate_id": selected["candidate_id"],
            "runtime_id": selected["runtime_id"],
            "selection_status": status,
            "rationale": rationale,
            "reason_code": reason_code,
            "reason_params": reason_params,
            "alternatives": [
                item for item in candidates if item["exe"] != selected_public["exe"]
            ],
        }
    )
    return base


def detect_olga(
    exe_globs: Sequence[str],
    environ: Mapping[str, str] | None = None,
    source: str | Path | None = None,
    registry_reader: Callable[[], list[tuple[str, str]]] | None = None,
) -> dict[str, Any]:
    """Detect the OLGA executable, falling through a stale manual choice to autodetect.

    A manually chosen executable that no longer exists is reported in the
    rationale instead of failing the run, so a new install is picked up
    automatically. A set OLGA_EXE_PATH still fails closed when it is missing.
    """
    from . import config as _config

    environment = os.environ if environ is None else environ
    manual_value = (
        ""
        if environment.get("OLGA_EXE_PATH", "").strip()
        else _config.load_olga_exe_override().strip()
    )
    stale_manual = bool(manual_value) and not Path(manual_value).expanduser().is_file()
    result = _detect_olga_inner(
        exe_globs, environ, source, registry_reader, _ignore_manual=stale_manual
    )
    if stale_manual:
        note = " The manually chosen OLGA executable was not found; using automatic detection instead."
        result["rationale"] = f"{result.get('rationale') or ''}{note}".strip()
        params = result.get("reason_params")
        if isinstance(params, dict):
            params["stale_manual_override"] = True
    return result
