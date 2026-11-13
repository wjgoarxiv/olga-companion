"""Deterministic, side-effect-free simulation setup preflight."""

from __future__ import annotations

import hashlib
import re
from typing import Protocol, assert_never

from .simulation_setup_models import (
    ActiveCaseBinding,
    CaseReviewEvidence,
    FluidEvidence,
    PreflightApproved,
    PreflightRefused,
    PreflightResult,
    PreviewEvidence,
    RuntimeEvidence,
    SimulationSetup,
    TransactionBinding,
)


class PreflightDependencies(Protocol):
    def context_generation(self) -> int: ...

    def review_case(self, setup: SimulationSetup) -> CaseReviewEvidence: ...

    def check_fluids(self, setup: SimulationSetup) -> FluidEvidence: ...

    def detect_runtime(self, setup: SimulationSetup) -> RuntimeEvidence: ...

    def preview_run(self, setup: SimulationSetup) -> PreviewEvidence: ...


def setup_hash(setup: SimulationSetup) -> str:
    canonical = setup.model_dump_json(exclude_none=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _refused(setup: SimulationSetup, reason: str, summary: str) -> PreflightRefused:
    return PreflightRefused(
        setup_hash=setup_hash(setup),
        reason=reason,
        receipt=f"Simulation preflight refused: {summary}.",
    )


def _expected_run_hash(setup: SimulationSetup) -> str:
    match setup.binding:
        case ActiveCaseBinding(source_sha256=source_hash):
            return source_hash
        case TransactionBinding(compiled_sha256=compiled_hash):
            return compiled_hash
        case unreachable:
            assert_never(unreachable)


def _review_refusal(
    setup: SimulationSetup,
    review: CaseReviewEvidence,
) -> PreflightRefused | None:
    if not review.certain:
        return _refused(setup, "uncertain_case_review", "case review is uncertain")
    if not review.valid:
        return _refused(setup, "invalid_case", "case validation has blocking errors")
    if review.source_sha256 != setup.binding.source_sha256:
        return _refused(setup, "stale_source", "case source changed after setup")
    if review.configured_end_time_s != float(setup.integration.end_time_s):
        return _refused(setup, "integration_mismatch", "run input ENDTIME differs from setup")
    if tuple(sorted(review.configured_outputs)) != tuple(sorted(setup.outputs)):
        return _refused(setup, "outputs_mismatch", "run input outputs differ from setup")
    match setup.binding:
        case ActiveCaseBinding():
            return None
        case TransactionBinding(compiled_sha256=compiled_hash):
            if review.compiled_sha256 != compiled_hash:
                return _refused(
                    setup,
                    "stale_compiled_case",
                    "compiled transaction changed after setup",
                )
            return None
        case unreachable:
            assert_never(unreachable)


def _fluid_refusal(
    setup: SimulationSetup,
    evidence: FluidEvidence,
) -> PreflightRefused | None:
    if not evidence.certain:
        return _refused(setup, "fluid_uncertain", "fluid companion evidence is uncertain")
    if evidence.run_input_sha256 != _expected_run_hash(setup):
        return _refused(setup, "fluid_hash_mismatch", "fluid review used another case revision")
    if not evidence.consistent:
        return _refused(setup, "fluid_mismatch", "fluid companion consistency failed")
    return None


def _runtime_refusal(
    setup: SimulationSetup,
    evidence: RuntimeEvidence,
) -> PreflightRefused | None:
    if evidence.certainty != "certain":
        return _refused(setup, "runtime_uncertain", "runtime detection is uncertain")
    if not evidence.available:
        return _refused(setup, "runtime_unavailable", "selected runtime is unavailable")
    if (
        evidence.candidate_id != setup.runtime.candidate_id
        or evidence.runtime_id != setup.runtime.runtime_id
    ):
        return _refused(setup, "runtime_binding_mismatch", "selected runtime changed")
    return None


def _preview_refusal(
    setup: SimulationSetup,
    evidence: PreviewEvidence,
) -> PreflightRefused | None:
    exact = (
        evidence.setup_hash == setup_hash(setup)
        and evidence.run_input_sha256 == _expected_run_hash(setup)
        and evidence.candidate_id == setup.runtime.candidate_id
        and evidence.runtime_id == setup.runtime.runtime_id
        and evidence.timeout_s == setup.timeout_s
        and evidence.context_generation == setup.context_generation
    )
    if not exact:
        return _refused(setup, "preview_binding_mismatch", "run preview is not exact")
    if not evidence.ready:
        return _refused(setup, "preview_rejected", "run preview reported blocking errors")
    return None


def _binding_label(setup: SimulationSetup) -> str:
    match setup.binding:
        case ActiveCaseBinding(source_sha256=source_hash):
            return f"active case revision {source_hash[:12]}"
        case TransactionBinding(transaction_id=transaction_id):
            return f"transaction {transaction_id[:12]}"
        case unreachable:
            assert_never(unreachable)


def _runtime_label(evidence: RuntimeEvidence) -> str:
    if re.fullmatch(r"[A-Za-z0-9 ._()+-]{1,80}", evidence.display_name):
        return evidence.display_name
    return f"selected OLGA runtime {evidence.runtime_id}"


def preflight_simulation(
    setup: SimulationSetup,
    dependencies: PreflightDependencies,
) -> PreflightResult:
    """Compose read-only evidence and return an exact approval-ready receipt."""
    if dependencies.context_generation() != setup.context_generation:
        return _refused(setup, "stale_context", "workspace context changed")
    review = dependencies.review_case(setup)
    if refused := _review_refusal(setup, review):
        return refused
    fluids = dependencies.check_fluids(setup)
    if refused := _fluid_refusal(setup, fluids):
        return refused
    runtime = dependencies.detect_runtime(setup)
    if refused := _runtime_refusal(setup, runtime):
        return refused
    preview = dependencies.preview_run(setup)
    if refused := _preview_refusal(setup, preview):
        return refused
    if dependencies.context_generation() != setup.context_generation:
        return _refused(setup, "stale_context", "workspace context changed during preflight")
    outputs = ", ".join(setup.outputs)
    receipt = (
        f"Ready to run {_binding_label(setup)} with {_runtime_label(runtime)}; "
        f"ENDTIME {setup.integration.end_time_s} s, outputs {outputs}, "
        f"timeout {setup.timeout_s} s, output target {setup.output_target.relative_dir}."
    )
    return PreflightApproved(
        setup_hash=setup_hash(setup),
        run_input_sha256=_expected_run_hash(setup),
        selection_id=preview.selection_id,
        context_generation=setup.context_generation,
        receipt=receipt,
    )
