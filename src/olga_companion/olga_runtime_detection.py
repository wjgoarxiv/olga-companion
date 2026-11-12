from __future__ import annotations

import glob
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

from .olga_runtime_paths import executable_kind, path_key
from .olga_runtime_versions import case_evidence, path_version


def executable_sha256(path: Path) -> str:
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


def detect_olga(
    exe_globs: Sequence[str],
    environ: Mapping[str, str] | None = None,
    source: str | Path | None = None,
) -> dict[str, Any]:
    environment = os.environ if environ is None else environ
    searched: list[str] = []
    candidates_by_path: dict[str, dict[str, Any]] = {}
    env_value = environment.get("OLGA_EXE_PATH", "").strip()
    env_requested = bool(env_value)
    env_key: str | None = None
    if env_value:
        override = Path(env_value).expanduser()
        searched.append(f"env:OLGA_EXE_PATH={env_value}")
        if override.is_file():
            env_key = path_key(str(override))
            candidates_by_path[env_key] = candidate(str(override), "env:OLGA_EXE_PATH")
    for pattern in exe_globs:
        searched.append(pattern)
        matches = sorted(glob.glob(pattern))
        for exe in matches:
            key = path_key(exe)
            if key not in candidates_by_path:
                candidates_by_path[key] = candidate(exe, "install-glob")

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

    if env_requested and env_key is None:
        base["selection_status"] = "override_not_found"
        base["rationale"] = (
            "OLGA_EXE_PATH was set, but it does not name an existing executable file."
        )
        base["reason_code"] = "override_not_found"
        base["reason_params"] = {}
        return base

    if env_key is not None:
        selected = candidates_by_path[env_key]
        if required_version is not None and selected["version"] != required_version:
            base["selection_status"] = "override_version_mismatch"
            override_version = selected["version"] or "unknown"
            base["rationale"] = (
                f"OLGA_EXE_PATH identifies OLGA {override_version}, but strong case evidence requires "
                f"OLGA {required_version}."
            )
            base["reason_code"] = "override_version_mismatch"
            base["reason_params"] = {
                "override_version": override_version,
                "required_version": required_version,
            }
            return base
        status = "selected_override"
        rationale = "Selected the explicit OLGA_EXE_PATH override."
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
