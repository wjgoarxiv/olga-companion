from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any


def require_timeout_seconds(ctx: Any, value: int) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or not 1 <= value <= ctx.MAX_RUN_TIMEOUT_SECONDS
    ):
        raise ctx.OlgaInputError(
            f"timeout_s must be an integer between 1 and {ctx.MAX_RUN_TIMEOUT_SECONDS}."
        )
    return value


def detect_olga(ctx: Any, source_value: str | Path | None = None) -> dict[str, Any]:
    return ctx.detect_runtime(ctx.OLGA_EXE_GLOBS, source=source_value)


def build_command(ctx: Any, exe: str, case_name: str) -> list[str]:
    return ctx.build_command(
        exe,
        case_name,
        wsl_init_path=ctx.WSL_INIT_PATH,
        wsl_interop_path=ctx.WSL_INTEROP_PATH,
    )


def require_detected(ctx: Any, source_value: str | Path | None = None) -> dict[str, Any]:
    detection = ctx.detect_olga(source_value)
    if not detection["detected"]:
        detail = detection.get("rationale") or (
            "Set OLGA_EXE_PATH or install OLGA before requesting a run."
        )
        raise ctx.OlgaInputError(f"No suitable OLGA executable detected. {detail}")
    return detection


def require_candidate(ctx: Any, source: Path, candidate_id: str) -> dict[str, Any]:
    detection = ctx.detect_olga(source)
    selected = next(
        (
            item
            for item in detection.get("candidates", [])
            if isinstance(item, dict) and item.get("candidate_id") == candidate_id
        ),
        None,
    )
    if selected is None:
        raise ctx.OlgaInputError(
            "Requested OLGA runtime candidate is not available in the fresh installed inventory."
        )
    required_version = detection.get("required_version")
    if required_version is not None and selected.get("version") != required_version:
        raise ctx.OlgaInputError(
            f"Engine-authored case evidence requires OLGA {required_version}; "
            "the requested runtime candidate does not match."
        )
    exe = str(selected.get("exe") or "")
    if not exe or not Path(exe).is_file():
        raise ctx.OlgaInputError("Requested OLGA runtime candidate is no longer available.")
    resolved = copy.deepcopy(detection)
    resolved.update(
        {
            "detected": True,
            "source": selected.get("source"),
            "exe": exe,
            "kind": selected.get("kind"),
            "version": selected.get("version"),
            "sha256": selected.get("sha256"),
            "candidate_id": selected.get("candidate_id"),
            "runtime_id": selected.get("runtime_id"),
            "selection_status": "selected_candidate",
            "rationale": (
                "Selected the requested server-issued runtime candidate "
                "from a fresh installed inventory."
            ),
            "alternatives": [
                item
                for item in detection.get("candidates", [])
                if item.get("candidate_id") != candidate_id
            ],
        }
    )
    return resolved


def revalidate_pinned_detection(
    ctx: Any,
    source: Path,
    pinned_detection: dict[str, Any],
) -> dict[str, Any]:
    candidate_id = str(pinned_detection.get("candidate_id") or "")
    if not pinned_detection.get("detected") or not candidate_id:
        raise ctx.OlgaInputError("Pinned OLGA runtime selection is not executable.")
    fresh = ctx._require_candidate(source, candidate_id)
    for field in ("sha256", "version", "kind"):
        if fresh.get(field) != pinned_detection.get(field):
            raise ctx.OlgaInputError(
                "Pinned OLGA runtime candidate/content changed after preview; request a fresh preview."
            )
    return fresh


def selection_id(
    ctx: Any,
    source: Path,
    detection: dict[str, Any],
    timeout_s: int,
    command: list[str],
    *,
    source_sha256: str | None = None,
    companions: list[dict[str, Any]] | None = None,
    launch_strategy: str = "direct",
    broker: dict[str, Any] | None = None,
    staged_case_name: str | None = None,
) -> str:
    workspace_root, workspace_generation = ctx.workspace.context_identity()
    evidence = [
        {
            key: item.get(key)
            for key in (
                "source_type",
                "path",
                "version",
                "strength",
                "input_file",
                "normal_stop",
            )
            if key in item
        }
        for item in detection.get("evidence", [])
        if isinstance(item, dict)
    ]
    payload = {
        "selection_boot_nonce": ctx._SELECTION_BOOT_NONCE,
        "workspace_context_root": str(workspace_root),
        "workspace_context_generation": workspace_generation,
        "source_path": str(source.resolve()),
        "source_sha256": source_sha256 if source_sha256 is not None else ctx.file_sha256(source),
        "companions": companions if companions is not None else ctx.companion_manifest(source),
        "exe": detection.get("exe"),
        "version": detection.get("version"),
        "kind": detection.get("kind"),
        "candidate_id": detection.get("candidate_id"),
        "exe_sha256": detection.get("sha256"),
        "timeout_s": timeout_s,
        "command": command,
        "launch_strategy": launch_strategy,
        # Framework csc.exe cannot build deterministically, so a rebuild from the same
        # sources has new bytes. Approve what the broker is built from; dispatch still
        # checks the per-run copy against the exact build it uses.
        "broker": None if broker is None else {k: v for k, v in broker.items() if k != "sha256"},
        "staged_case_name": staged_case_name or source.name,
        "evidence": evidence,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def selection_id_for(
    ctx: Any,
    source: Path,
    detection: dict[str, Any],
    timeout_s: int,
) -> str:
    expected_root, expected_generation = ctx.workspace.context_identity()
    with ctx.workspace.expected_context(expected_generation) as identity:
        if identity[0] != expected_root:
            raise ctx.workspace.StaleWorkspaceContextError(
                "Workspace context changed; refresh the preview and approve again."
            )
        launch_strategy, artifact, staged_case_name = ctx._launch_binding(detection)
        staged_case_name = staged_case_name or source.name
        command = ctx._build_command(str(detection["exe"]), staged_case_name)
        selected = ctx._selection_id(
            source,
            detection,
            timeout_s,
            command,
            launch_strategy=launch_strategy,
            broker=None if artifact is None else artifact.to_dict(),
            staged_case_name=staged_case_name,
        )
        with ctx._REGISTRY_LOCK:
            ctx._SELECTION_CONTEXTS[selected] = identity
        return selected


def launch_binding(ctx: Any, detection: dict[str, Any]) -> tuple[str, Any | None, str]:
    if detection.get("kind") == "engine":
        artifact = ctx.ensure_broker()
        return "explorer_one_shot_broker", artifact, ctx.FIXED_CASE_NAME
    if detection.get("kind") != "script" and str(detection.get("exe") or "").lower().endswith(
        ".exe"
    ):
        raise ctx.OlgaInputError(
            "This native OLGA candidate is unsupported by the approved Explorer broker path; "
            "select a direct OLGA engine executable and request a fresh preview."
        )
    return "direct", None, ""


def preview_run(
    ctx: Any,
    source_value: str,
    timeout_s: int = 3600,
    candidate_id: str | None = None,
) -> dict[str, Any]:
    timeout_s = ctx.require_timeout_seconds(timeout_s)
    expected_root, expected_generation = ctx.workspace.context_identity()
    with ctx.workspace.expected_context(expected_generation) as identity:
        if identity[0] != expected_root:
            raise ctx.workspace.StaleWorkspaceContextError(
                "Workspace context changed; refresh the preview and approve again."
            )
        source = ctx.require_genkey_path(source_value)
        detection = (
            ctx._require_candidate(source, candidate_id)
            if candidate_id
            else ctx._require_detected(source)
        )
        launch_strategy, artifact, staged_case_name = ctx._launch_binding(detection)
        staged_case_name = staged_case_name or source.name
        command = ctx._build_command(detection["exe"], staged_case_name)
        display_command = ctx.build_display_command(command, str(detection["exe"]))
        broker = None if artifact is None else artifact.to_dict()
        selected = ctx._selection_id(
            source,
            detection,
            timeout_s,
            command,
            launch_strategy=launch_strategy,
            broker=broker,
            staged_case_name=staged_case_name,
        )
        validation = ctx._validate_case(source)
        with ctx._REGISTRY_LOCK:
            ctx._SELECTION_CONTEXTS[selected] = identity
        return {
            "source": str(source),
            "detection": detection,
            "command": command,
            "display_command": display_command,
            "selection_id": selected,
            "candidate_id": detection.get("candidate_id"),
            "runtime_id": detection.get("runtime_id"),
            "cwd_template": str(ctx.sandbox_root() / "runs" / "<run_id>"),
            "timeout_s": timeout_s,
            "validation": validation,
            "launch_strategy": launch_strategy,
            "broker": broker,
            "staged_case_name": staged_case_name,
            "context_generation": identity[1],
        }
