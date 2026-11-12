"""Atomic, source-bound planning for ordered CaseSpec edit transactions."""

from __future__ import annotations

import difflib
import hashlib
import json
import re
import secrets
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing_extensions import override
from pydantic import ValidationError

from .case_companion import CompanionVerificationError, verify_pvt_companion
from .case_compiler import CaseCompileError, compile_case_spec, render_case_spec
from .case_spec import CaseSpec, normalize_case_spec
from .case_spec_recovery import UnsupportedSourceError, recover_case_spec
from .case_spec_validation import JsonValue
from .case_transaction_apply import UnknownTargetError, UnsupportedEditError, apply_operation
from .case_transaction_models import (
    SetIntegration,
    BackupReceipt,
    RollbackReceipt,
    SemanticDiff,
    Snapshot,
    TransactionFailure,
    TransactionIssue,
    TransactionPlan,
    TransactionResult,
    ValidationReceipt,
    parse_operation,
)
from .case_transaction_store import PublishTransaction, load_transaction, persist_transaction

_HASH = re.compile(r"[0-9a-f]{64}")
_SECOND_UNITS = frozenset({"s", "sec", "secs", "second", "seconds"})
_ENDTIME = re.compile(
    r"(?i:(?<![A-Za-z0-9_])ENDTIME\s*=\s*)"
    r"(?P<number>[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)"
    r"(?P<gap>\s*)"
    r"(?P<unit>[A-Za-z][A-Za-z0-9_./+-]*)?"
)


@dataclass(frozen=True, slots=True)
class StaleSourceError(RuntimeError):
    expected: str
    actual: str

    @override
    def __str__(self) -> str:
        return "The source hash is stale; refresh the case before editing."


@dataclass(frozen=True, slots=True)
class UnsafeSourceError(RuntimeError):
    reason: str

    @override
    def __str__(self) -> str:
        return self.reason


def _canonical_bytes(spec: CaseSpec) -> bytes:
    # An absent initial_conditions stays out so specs written before the field keep their hash.
    exclude = {"initial_conditions"} if spec.initial_conditions is None else None
    return spec.model_dump_json(by_alias=True, exclude=exclude).encode("utf-8")


def case_spec_hash(raw: Mapping[str, JsonValue] | CaseSpec) -> str:
    """Return the canonical content identity used for source-free builds."""
    spec = raw if isinstance(raw, CaseSpec) else normalize_case_spec(raw)
    return hashlib.sha256(_canonical_bytes(spec)).hexdigest()


def _safe_source(source: Path, workspace_root: Path) -> Path:
    root_input = workspace_root.expanduser()
    source_input = source.expanduser()
    if root_input.is_symlink() or source_input.is_symlink():
        raise UnsafeSourceError("Transaction source paths cannot be symlinks.")
    root = root_input.resolve()
    candidate = source_input.resolve()
    try:
        _ = candidate.relative_to(root)
    except ValueError as exc:
        raise UnsafeSourceError("Transaction source leaves the workspace.") from exc
    if candidate.suffix.casefold() != ".genkey" or not candidate.is_file():
        raise UnsafeSourceError("Transaction source must be a contained regular GENKEY.")
    return candidate


def _snapshot(spec: CaseSpec, index: int, previous: str | None) -> Snapshot:
    return Snapshot(index=index, spec_hash=case_spec_hash(spec), previous_hash=previous)


def _failure(
    transaction_id: str, source_hash: str, snapshots: list[Snapshot], step: int,
    code: str, message: str, evidence: str,
) -> TransactionFailure:
    return TransactionFailure(
        transaction_id, source_hash, tuple(snapshots), step,
        (TransactionIssue(code, message, evidence[:160]),),
    )


def plan_case_edits(
    base_spec: Mapping[str, JsonValue] | CaseSpec,
    operations: Sequence[Mapping[str, JsonValue]],
    *,
    expected_hash: str,
    owner_source: Path | None = None,
    workspace_root: Path | None = None,
    context_generation: int = 0,
    pending_companion: str | None = None,
) -> TransactionResult:
    """Apply ordered typed edits, validate once at the end, and persist success.

    ``pending_companion`` names the .tab that an approved plan step will create; see
    ``verify_pvt_companion``. Publishing checks the table again.
    """
    if len(operations) > 20:
        raise UnsafeSourceError("A transaction accepts at most 20 operations.")
    base = base_spec if isinstance(base_spec, CaseSpec) else normalize_case_spec(base_spec)
    source = None
    owner_probe: Path | None = None
    backup_bytes = _canonical_bytes(base)
    actual_hash = case_spec_hash(base)
    if owner_source is not None:
        if workspace_root is None:
            raise UnsafeSourceError("Owner-backed transactions require a workspace root.")
        source = _safe_source(owner_source, workspace_root)
        backup_bytes = source.read_bytes()
        actual_hash = hashlib.sha256(backup_bytes).hexdigest()
    else:
        if workspace_root is None or workspace_root.is_symlink():
            raise UnsafeSourceError(
                "Source-free transactions require a non-symlink workspace root."
            )
        root = workspace_root.expanduser().resolve()
        if not root.is_dir():
            raise UnsafeSourceError("Transaction workspace root does not exist.")
        owner_probe = root / ".casespec-owner.genkey"
        try:
            # Existence and containment only; the fluid label is checked against the
            # final spec below, because edits may change it.
            _ = verify_pvt_companion(owner_probe, base.pvt_reference, pending=pending_companion)
        except CompanionVerificationError as exc:
            raise UnsafeSourceError(str(exc)) from exc
    if _HASH.fullmatch(expected_hash) is None or expected_hash != actual_hash:
        raise StaleSourceError(expected_hash, actual_hash)
    transaction_id = secrets.token_hex(16)
    snapshots = [
        Snapshot(0, actual_hash, None)
        if source is not None
        else _snapshot(base, 0, None)
    ]
    semantic_diff: list[SemanticDiff] = []
    working = base
    for index, raw in enumerate(operations):
        try:
            operation = parse_operation(dict(raw))
        except ValidationError:
            evidence = json.dumps(raw, ensure_ascii=False, sort_keys=True)
            return _failure(transaction_id, actual_hash, snapshots, index, "unsupported_operation", "Operation is outside the closed edit grammar.", evidence)
        try:
            working, change = apply_operation(working, operation)
        except UnknownTargetError as exc:
            return _failure(transaction_id, actual_hash, snapshots, index, "unknown_target", str(exc), operation.model_dump_json())
        except UnsupportedEditError as exc:
            return _failure(transaction_id, actual_hash, snapshots, index, "unsupported_operation", str(exc), operation.model_dump_json())
        semantic_diff.append(change)
        snapshots.append(_snapshot(working, index + 1, snapshots[-1].spec_hash))
    try:
        final = normalize_case_spec(working.model_dump(mode="json", by_alias=True))
        if owner_probe is not None:
            _ = verify_pvt_companion(
                owner_probe, final.pvt_reference, final.fluid_label, pending=pending_companion
            )
        compiled = compile_case_spec(final, owner_source=source, pending_companion=pending_companion)
    except ValidationError as exc:
        details = exc.errors()
        kind = str(details[0].get("type", "")) if details else ""
        evidence = f"{kind}: {exc}" if kind else str(exc)
        return _failure(transaction_id, actual_hash, snapshots, len(operations), "final_validation_failed", "The complete edit set is not a valid CaseSpec.", evidence)
    except (CaseCompileError, CompanionVerificationError) as exc:
        return _failure(transaction_id, actual_hash, snapshots, len(operations), "compile_validation_failed", str(exc), type(exc).__name__)
    if source is not None and hashlib.sha256(source.read_bytes()).hexdigest() != actual_hash:
        raise StaleSourceError(actual_hash, hashlib.sha256(source.read_bytes()).hexdigest())
    before_text = render_case_spec(base).decode("utf-8").splitlines()
    after_text = compiled.text.splitlines()
    text_diff = tuple(difflib.unified_diff(before_text, after_text, fromfile="source", tofile="working", lineterm=""))
    working_hash = case_spec_hash(final)
    transaction_payload = json.dumps({
        "source_hash": actual_hash,
        "working_hash": working_hash,
        "compiled_hash": compiled.sha256,
        "operations": [dict(operation) for operation in operations],
    }, sort_keys=True, separators=(",", ":")).encode("utf-8")
    validation = ValidationReceipt(
        compiled.validation.clean, compiled.validation.parser_clean,
        compiled.validation.validator_clean, compiled.validation.diagnostics,
    )
    backup_hash = hashlib.sha256(backup_bytes).hexdigest()
    plan = TransactionPlan(
        transaction_id, hashlib.sha256(transaction_payload).hexdigest(), actual_hash,
        working_hash, compiled.sha256, compiled.compiled_bytes, tuple(snapshots),
        tuple(semantic_diff), text_diff, BackupReceipt(True, backup_hash), validation,
        RollbackReceipt(True, backup_hash, True),
    )
    _ = persist_transaction(
        plan, source=source, backup_bytes=backup_bytes,
        context_generation=context_generation,
    )
    return plan


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _integration_regions(text: str) -> list[tuple[int, int]]:
    regions: list[tuple[int, int]] = []
    offset = 0
    lines = text.splitlines(keepends=True)
    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        token = ""
        if stripped and not stripped.startswith("!"):
            token = stripped.split(None, 1)[0].rstrip(",").upper()
        if token != "INTEGRATION":
            offset += len(line)
            index += 1
            continue
        start = offset
        raw = line
        offset += len(line)
        index += 1
        while raw.rstrip("\r\n").endswith("\\") and index < len(lines):
            raw = lines[index]
            offset += len(raw)
            index += 1
        regions.append((start, offset))
    return regions


def _endtime_matches(text: str) -> list[re.Match[str]]:
    matches: list[re.Match[str]] = []
    for start, end in _integration_regions(text):
        matches.extend(_ENDTIME.finditer(text, start, end))
    return matches


def _render_end_time(original: str, value: float) -> str | None:
    """Rewrite only the numeric token, keeping a plain integer or fixed-decimal shape."""
    body = original.lstrip("+-")
    if re.fullmatch(r"\d+", body):
        if not value.is_integer():
            return None
        return str(int(value))
    matched = re.fullmatch(r"\d+\.(\d+)", body)
    if matched is None:
        return None
    return f"{value:.{len(matched.group(1))}f}"


def _apply_owner_operation(text: str, operation: SetIntegration) -> tuple[str, SemanticDiff] | str:
    matches = _endtime_matches(text)
    if len(matches) != 1:
        return "unknown_target"
    match = matches[0]
    unit = match.group("unit")
    if unit is not None and unit.casefold() not in _SECOND_UNITS:
        return "unit_unchanged"
    rendered = _render_end_time(match.group("number"), operation.end_time_s)
    if rendered is None:
        return "unknown_target"
    number = match.group("number")
    revised = text[: match.start("number")] + rendered + text[match.end("number") :]
    return revised, SemanticDiff("integration.end_time_s", number, rendered)


def _validate_owner_bytes(content: bytes) -> tuple[bool, tuple[str, ...]]:
    from . import genkey_static

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "reviewed.genkey"
        path.write_bytes(content)
        result = genkey_static.run_tool("validator", [str(path)])
    lines = [line.strip()[:128] for line in result.stdout.splitlines() if line.strip()]
    return result.exit_code == 0, tuple(lines[:8])


def plan_owner_byte_edits(
    source: Path,
    operations: Sequence[Mapping[str, JsonValue]],
    *,
    expected_hash: str,
    workspace_root: Path,
    context_generation: int = 0,
) -> TransactionResult:
    """Apply closed edits to one owner GENKEY copy without recovering CaseSpec."""
    if len(operations) > 20:
        raise UnsafeSourceError("A transaction accepts at most 20 operations.")
    if not operations:
        contained = _safe_source(source, workspace_root)
        before_hash = _sha256_file(contained)
        if expected_hash != before_hash:
            raise StaleSourceError(expected_hash, before_hash)
        return _failure(
            secrets.token_hex(16), before_hash, [Snapshot(0, before_hash, None)], 0,
            "unsupported_operation", "A reviewed copy needs one closed edit.", "[]",
        )
    contained = _safe_source(source, workspace_root)
    before_hash = _sha256_file(contained)
    original = contained.read_bytes()
    if _sha256_file(contained) != before_hash or _HASH.fullmatch(expected_hash) is None:
        raise StaleSourceError(expected_hash, before_hash)
    if expected_hash != before_hash:
        raise StaleSourceError(expected_hash, before_hash)
    try:
        text = original.decode("utf-8")
    except UnicodeError as exc:
        raise UnsafeSourceError("Transaction source must be UTF-8.") from exc
    transaction_id = secrets.token_hex(16)
    snapshots = [Snapshot(0, before_hash, None)]
    semantic_diff: list[SemanticDiff] = []
    for index, raw in enumerate(operations):
        try:
            operation = parse_operation(dict(raw))
        except ValidationError:
            evidence = json.dumps(raw, ensure_ascii=False, sort_keys=True)
            return _failure(
                transaction_id, before_hash, snapshots, index, "unsupported_operation",
                "Operation is outside the closed edit grammar.", evidence,
            )
        if not isinstance(operation, SetIntegration):
            return _failure(
                transaction_id, before_hash, snapshots, index, "unknown_target",
                "Edit target does not exist on this owner GENKEY.", operation.model_dump_json(),
            )
        applied = _apply_owner_operation(text, operation)
        if isinstance(applied, str):
            message = (
                "ENDTIME unit is not seconds; the number was not converted."
                if applied == "unit_unchanged"
                else "Edit target does not exist: INTEGRATION.ENDTIME"
            )
            return _failure(
                transaction_id, before_hash, snapshots, index, applied, message, operation.model_dump_json(),
            )
        text, change = applied
        semantic_diff.append(change)
        revised_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        snapshots.append(Snapshot(index + 1, revised_hash, snapshots[-1].spec_hash))
    if _sha256_file(contained) != before_hash:
        raise StaleSourceError(before_hash, _sha256_file(contained))
    reviewed = text.encode("utf-8")
    clean, diagnostics = _validate_owner_bytes(reviewed)
    if not clean:
        return _failure(
            transaction_id, before_hash, snapshots, len(operations), "compile_validation_failed",
            "The reviewed GENKEY copy did not validate cleanly.", " ".join(diagnostics),
        )
    compiled_hash = hashlib.sha256(reviewed).hexdigest()
    text_diff = tuple(difflib.unified_diff(
        original.decode("utf-8").splitlines(), text.splitlines(),
        fromfile="source", tofile="working", lineterm="",
    ))
    transaction_payload = json.dumps({
        "source_hash": before_hash,
        "working_hash": compiled_hash,
        "compiled_hash": compiled_hash,
        "operations": [dict(operation) for operation in operations],
    }, sort_keys=True, separators=(",", ":")).encode("utf-8")
    validation = ValidationReceipt(True, True, True, ())
    plan = TransactionPlan(
        transaction_id, hashlib.sha256(transaction_payload).hexdigest(), before_hash,
        compiled_hash, compiled_hash, reviewed, tuple(snapshots), tuple(semantic_diff),
        text_diff, BackupReceipt(True, before_hash), validation,
        RollbackReceipt(True, before_hash, True),
    )
    try:
        _ = contained.relative_to(workspace_root.expanduser().resolve())
    except ValueError as exc:
        raise UnsafeSourceError("Transaction source leaves the workspace.") from exc
    _ = persist_transaction(
        plan, source=contained, backup_bytes=original, context_generation=context_generation,
    )
    return plan


def plan_case_edits_from_source(
    source: Path,
    operations: Sequence[Mapping[str, JsonValue]],
    *,
    expected_hash: str,
    workspace_root: Path,
    context_generation: int = 0,
) -> TransactionResult:
    """Recover a trusted compiler artifact, then plan without model-resupplied state."""
    contained = _safe_source(source, workspace_root)
    try:
        base_spec = recover_case_spec(contained)
    except UnsupportedSourceError as exc:
        if exc.reason != "provenance marker is absent":
            raise
        return plan_owner_byte_edits(
            contained,
            operations,
            expected_hash=expected_hash,
            workspace_root=workspace_root,
            context_generation=context_generation,
        )
    return plan_case_edits(
        base_spec,
        operations,
        expected_hash=expected_hash,
        owner_source=contained,
        workspace_root=workspace_root,
        context_generation=context_generation,
    )


__all__ = [
    "PublishTransaction", "StaleSourceError", "TransactionResult",
    "UnsupportedSourceError", "UnsafeSourceError", "case_spec_hash",
    "load_transaction", "plan_case_edits", "plan_case_edits_from_source",
]
