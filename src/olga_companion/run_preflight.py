from __future__ import annotations

from pathlib import Path
from typing import Any

from .run_model import PreparedRun


def _mint_workspace_root(ctx: Any) -> str | None:
    """Workspace root frozen onto the receipt at mint time.

    Fail-closed tagging: any lookup problem yields None (unknown → other
    workspace) and must never break preflight, so the chain is defensive.
    """
    workspace = getattr(ctx, "workspace", None)
    identity = getattr(workspace, "context_identity", None)
    if identity is None:
        return None
    try:
        root, _generation = identity()
    except Exception:
        return None
    return str(root)


def prepare_run(
    ctx: Any,
    source_value: str,
    *,
    approved: bool,
    override: bool,
    timeout_s: int,
    selection_id: str | None,
    pinned_detection: dict[str, Any] | None,
    candidate_id: str | None,
) -> PreparedRun:
    timeout_s = ctx.require_timeout_seconds(timeout_s)
    source = ctx.require_genkey_path(source_value)
    if pinned_detection is not None:
        detection = ctx.revalidate_pinned_detection(source, pinned_detection)
    elif candidate_id:
        detection = ctx._require_candidate(source, candidate_id)
    else:
        detection = ctx._require_detected(source)
    if not approved:
        raise ctx.OlgaInputError(
            "Run requires explicit approval (approved=true) after reviewing the command preview."
        )
    launch_strategy, artifact, staged_case_name = ctx._launch_binding(detection)
    staged_case_name = staged_case_name or source.name
    approved_command = ctx._build_command(detection["exe"], staged_case_name)
    approved_source_hash = ctx.file_sha256(source)
    approved_companions = ctx.companion_manifest(source)
    current_selection_id = ctx._selection_id(
        source,
        detection,
        timeout_s,
        approved_command,
        source_sha256=approved_source_hash,
        companions=approved_companions,
        launch_strategy=launch_strategy,
        broker=None if artifact is None else artifact.to_dict(),
        staged_case_name=staged_case_name,
    )
    if selection_id is not None and selection_id != current_selection_id:
        raise ctx.OlgaInputError(
            "OLGA runtime selection changed after preview; review and approve a fresh run preview."
        )

    run_id = ctx.uuid.uuid4().hex[:12]
    run_dir = ctx.sandbox_root() / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    contained_runtime: Path | None = None
    execution_artifact: dict[str, str] | None = None
    command = approved_command
    if launch_strategy == "direct":
        try:
            contained_runtime, execution_artifact = ctx._prepare_contained_runtime(
                run_dir,
                detection,
            )
        except (OSError, ctx.OlgaInputError) as exc:
            ctx.shutil.rmtree(run_dir, ignore_errors=True)
            if isinstance(exc, ctx.OlgaInputError):
                raise
            raise ctx.OlgaInputError(
                f"Approved OLGA runtime could not be contained safely: {exc}"
            ) from exc
        command = ctx._build_command(str(contained_runtime), staged_case_name)

    working_copy = run_dir / staged_case_name
    ctx.shutil.copy2(source, working_copy)
    if ctx.file_sha256(working_copy) != approved_source_hash:
        ctx.shutil.rmtree(run_dir, ignore_errors=True)
        raise ctx.OlgaInputError(
            "Staged run source changed from the approved manifest; run was not launched."
        )
    expected_staged_source_hash = ctx.expected_staged_source_sha256(
        working_copy,
        approved_companions,
        run_dir,
    )
    companions = ctx.stage_companions(source, working_copy, run_dir)
    if (
        ctx.file_sha256(working_copy) != expected_staged_source_hash
        or not ctx.staged_companions_match(approved_companions, run_dir)
    ):
        ctx.shutil.rmtree(run_dir, ignore_errors=True)
        raise ctx.OlgaInputError(
            "Staged run source or companion files changed from the approved manifest."
        )
    staged_source_hash = ctx.file_sha256(working_copy)
    staged_companions = ctx.companion_manifest(working_copy)
    validation = ctx._validate_case(working_copy)
    if not validation["valid"] and not override:
        ctx.shutil.rmtree(run_dir, ignore_errors=True)
        raise ctx.OlgaInputError(
            "Validation reported blocking errors. Fix the case or set override=true to run anyway."
        )
    if companions["pvt_missing"] and not override:
        ctx.shutil.rmtree(run_dir, ignore_errors=True)
        raise ctx.OlgaInputError(
            "PVTFILE reference(s) not found next to the case: "
            + ", ".join(companions["pvt_missing"])
            + ". Fix the reference or set override=true to run anyway."
        )
    if companions["restart_missing"] and not override:
        ctx.shutil.rmtree(run_dir, ignore_errors=True)
        raise ctx.OlgaInputError(
            "RESTART READFILE=ON reference(s) not found next to the case: "
            + ", ".join(companions["restart_missing"])
            + ". Fix the reference or set override=true to run anyway."
        )
    try:
        source_unchanged = (
            ctx._selection_id(
                source,
                detection,
                timeout_s,
                approved_command,
                launch_strategy=launch_strategy,
                broker=None if artifact is None else artifact.to_dict(),
                staged_case_name=staged_case_name,
            )
            == current_selection_id
        )
        staged_unchanged = (
            ctx.file_sha256(working_copy) == staged_source_hash
            and ctx.companion_manifest(working_copy) == staged_companions
        )
    except OSError:
        source_unchanged = staged_unchanged = False
    if not source_unchanged:
        ctx.shutil.rmtree(run_dir, ignore_errors=True)
        raise ctx.OlgaInputError(
            "Run source or companion files changed after preview; review and approve a fresh preview."
        )
    if not staged_unchanged:
        ctx.shutil.rmtree(run_dir, ignore_errors=True)
        raise ctx.OlgaInputError(
            "Staged run source or companion files changed during preflight; run was not launched."
        )

    validation_valid = (
        validation["valid"]
        and not companions["pvt_missing"]
        and not companions["restart_missing"]
    )
    receipt: dict[str, Any] = {
        "schema_version": 1,
        "run_id": run_id,
        "phase": "prepared",
        "state": "prepared",
        "source": {
            "name": source.name,
            "resolved_path": str(source.resolve()),
            "sha256": approved_source_hash,
            "staged_sha256": staged_source_hash,
        },
        "companions": approved_companions,
        "runtime": {
            "candidate_id": detection.get("candidate_id"),
            "runtime_id": detection.get("runtime_id"),
            "version": detection.get("version"),
            "kind": detection.get("kind"),
            "exe": detection.get("exe"),
            "sha256": detection.get("sha256"),
            "approved_path": detection.get("exe"),
            "approved_sha256": detection.get("sha256"),
        },
        "selection_id": current_selection_id,
        "validation": validation,
        "timestamps": {"prepared_at": ctx._utc_now(), "started_at": None, "finished_at": None},
        "command": command,
        "approved_command": approved_command,
        "exit_code": None,
        "failure": None,
        "outputs": [],
        "timed_out": False,
        "cancelled": False,
        "ok": False,
        "engine_failed": False,
        "validation_valid": validation_valid,
        "elapsed_ms": 0,
        "log_tail": "",
        "detection": detection,
        "launch_strategy": launch_strategy,
        "broker": None if artifact is None else artifact.to_dict(),
        "staged_case_name": staged_case_name,
        "workspace_root": _mint_workspace_root(ctx),
    }
    if execution_artifact is not None:
        receipt["execution_artifact"] = execution_artifact
    try:
        ctx.write_run_record(run_dir, receipt)
    except (OSError, ctx.RunRecordError):
        ctx.shutil.rmtree(run_dir, ignore_errors=True)
        raise

    return PreparedRun(
        run_id=run_id,
        run_dir=run_dir,
        source=source,
        detection=detection,
        launch_strategy=launch_strategy,
        artifact=artifact,
        staged_case_name=staged_case_name,
        approved_command=approved_command,
        command=command,
        approved_source_hash=approved_source_hash,
        staged_source_hash=staged_source_hash,
        source_hash=staged_source_hash,
        validation=validation,
        companions=companions,
        receipt=receipt,
        contained_runtime=contained_runtime,
        execution_artifact=execution_artifact,
        selection_id=current_selection_id,
        timeout_s=timeout_s,
        approved=approved,
        override=override,
        working_copy=working_copy,
    )
