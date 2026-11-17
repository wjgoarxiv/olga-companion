"""Live, path-private adapter for typed simulation setup preflight."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .. import case_compiler_toolkit, case_transactions, fluids, genkey_static, runner, workspace
from ..case_transaction_store import TransactionStoreError
from ..simulation_setup import preflight_simulation, setup_hash
from ..simulation_setup_models import (
    ActiveCaseBinding,
    CaseReviewEvidence,
    FluidEvidence,
    PreviewEvidence,
    RuntimeEvidence,
    SimulationSetup,
    TransactionBinding,
)
from .tool_validation import ToolError


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class _LivePreflight:
    def __init__(self, setup: SimulationSetup) -> None:
        self.setup = setup
        self.transaction = None
        match setup.binding:
            case ActiveCaseBinding(source_sha256=expected):
                active = workspace.active_path()
                if not active:
                    raise ToolError("Select an active workspace case before simulation setup.")
                self.source = workspace.resolve_input_file(active, {".genkey"})
                if _sha256(self.source) != expected:
                    raise ToolError("The active case hash is stale; refresh setup evidence.")
            case TransactionBinding(transaction_id=transaction_id):
                self.transaction = case_transactions.load_transaction(transaction_id)
                if self.transaction.context_generation != setup.context_generation:
                    raise ToolError("The reviewed transaction context is stale; create a new plan.")
                self.source = self.transaction.compiled

    def context_generation(self) -> int:
        return workspace.context_generation()

    def review_case(self, setup: SimulationSetup) -> CaseReviewEvidence:
        reviewed = genkey_static.review_file(str(self.source))
        verified = case_compiler_toolkit.verify_with_toolkit(self.source.read_text(encoding="utf-8"))
        current = _sha256(self.source)
        if self.transaction is None:
            source_hash, compiled_hash = current, None
        else:
            source_hash = self.transaction.source_hash
            compiled_hash = current
        return CaseReviewEvidence(
            valid=bool(reviewed.get("valid")) and verified.clean,
            certain=True,
            source_sha256=source_hash,
            compiled_sha256=compiled_hash,
            configured_end_time_s=verified.end_time_s,
            configured_outputs=verified.outputs,
            errors=() if reviewed.get("valid") and verified.clean else ("GENKEY validation failed",),
        )

    def check_fluids(self, setup: SimulationSetup) -> FluidEvidence:
        if self.transaction is not None:
            return FluidEvidence(
                consistent=False,
                certain=True,
                run_input_sha256=_sha256(self.source),
                issues=("Publish the reviewed transaction beside its PVT companion first.",),
            )
        checked = fluids.consistency(str(self.source))
        before = str(checked.get("source_sha256_before") or "")
        after = str(checked.get("source_sha256_after") or "")
        certain = len(before) == 64 and before == after and not checked.get("source_mutated")
        references = checked.get("references")
        validated = isinstance(references, list) and bool(references) and all(
            isinstance(reference, dict)
            and reference.get("exists") is True
            and isinstance(reference.get("cross_check"), dict)
            and reference["cross_check"].get("valid") is True
            for reference in references
        )
        consistent = certain and checked.get("missing") == 0 and validated
        return FluidEvidence(
            consistent=consistent,
            certain=certain,
            run_input_sha256=after,
            issues=() if consistent else (
                "PVT companion is missing" if checked.get("missing")
                else "PVT validation failed or could not be confirmed.",
            ),
        )

    def detect_runtime(self, setup: SimulationSetup) -> RuntimeEvidence:
        detected = runner.detect_olga(self.source)
        selected = next(
            (
                item
                for item in detected.get("candidates", [])
                if isinstance(item, dict)
                and item.get("candidate_id") == setup.runtime.candidate_id
                and item.get("runtime_id") == setup.runtime.runtime_id
            ),
            None,
        )
        display = (
            f"OLGA {selected.get('version') or 'runtime'} · {selected.get('kind') or 'engine'}"
            if selected is not None
            else setup.runtime.runtime_id
        )
        return RuntimeEvidence(
            available=selected is not None,
            certainty="certain" if isinstance(detected.get("candidates"), list) else "uncertain",
            candidate_id=setup.runtime.candidate_id,
            runtime_id=setup.runtime.runtime_id,
            display_name=display,
        )

    def preview_run(self, setup: SimulationSetup) -> PreviewEvidence:
        preview = runner.preview_run(
            str(self.source), setup.timeout_s, candidate_id=setup.runtime.candidate_id
        )
        validation = preview.get("validation")
        return PreviewEvidence(
            ready=isinstance(validation, dict) and bool(validation.get("valid")),
            setup_hash=setup_hash(setup),
            run_input_sha256=_sha256(self.source),
            candidate_id=str(preview.get("candidate_id") or ""),
            runtime_id=str(preview.get("runtime_id") or ""),
            timeout_s=int(preview.get("timeout_s") or 0),
            context_generation=workspace.context_generation(),
            selection_id=str(preview.get("selection_id") or ""),
            command_label="Selected OLGA runtime",
            errors=() if isinstance(validation, dict) and validation.get("valid") else ("Run preview validation failed",),
        )


def execute(args: dict[str, Any]) -> dict[str, Any]:
    """Validate a closed setup and run the read-only live preflight chain."""
    try:
        setup = SimulationSetup.model_validate(args)
        result = preflight_simulation(setup, _LivePreflight(setup))
    except ValidationError as exc:
        raise ToolError(f"Invalid simulation setup: {exc}") from exc
    except (OSError, UnicodeError, TransactionStoreError, workspace.WorkspaceError) as exc:
        raise ToolError("Simulation setup could not be verified safely.") from exc
    return result.model_dump(mode="json")
