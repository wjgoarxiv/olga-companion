from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import pytest
from pydantic import ValidationError

from olga_companion.simulation_setup import preflight_simulation, setup_hash
from olga_companion.simulation_setup_models import (
    ActiveCaseBinding,
    CaseReviewEvidence,
    FluidEvidence,
    IntegrationSettings,
    OutputTarget,
    PreflightApproved,
    PreflightRefused,
    PreviewEvidence,
    RuntimeEvidence,
    RuntimeSelection,
    SimulationSetup,
    TransactionBinding,
)

SOURCE_HASH = "a" * 64
COMPILED_HASH = "b" * 64


def _active_setup() -> SimulationSetup:
    return SimulationSetup(
        binding=ActiveCaseBinding(
            kind="active_case",
            source_sha256=SOURCE_HASH,
        ),
        integration=IntegrationSettings(end_time_s=10_800),
        outputs=("PT", "TM"),
        runtime=RuntimeSelection(candidate_id="candidate-01", runtime_id="runtime-01"),
        timeout_s=3_600,
        output_target=OutputTarget(relative_dir="results/case-01"),
        context_generation=7,
    )


def _transaction_setup() -> SimulationSetup:
    return _active_setup().model_copy(
        update={
            "binding": TransactionBinding(
                kind="transaction",
                transaction_id="1" * 32,
                source_sha256=SOURCE_HASH,
                compiled_sha256=COMPILED_HASH,
            )
        }
    )


@dataclass(frozen=True, slots=True)
class FakePreflight:
    """Call-recording fake used to prove preflight ordering."""
    current_context: int = 7
    review_valid: bool = True
    review_certain: bool = True
    fluid_consistent: bool = True
    runtime_available: bool = True
    runtime_certainty: Literal["certain", "uncertain"] = "certain"
    preview_ready: bool = True
    review_source_hash: str = SOURCE_HASH
    review_compiled_hash: str | None = None
    review_end_time_s: float = 10_800
    review_outputs: tuple[str, ...] = ("PT", "TM")
    run_input_hash: str = SOURCE_HASH
    preview_candidate_id: str = "candidate-01"
    preview_runtime_id: str = "runtime-01"
    preview_context: int = 7
    preview_setup_hash: str | None = None
    preview_run_input_hash: str | None = None
    runtime_display_name: str = "OLGA 2022.1 direct engine"
    calls: list[str] = field(default_factory=list)

    def review_case(self, setup: SimulationSetup) -> CaseReviewEvidence:
        self.calls.append("review")
        return CaseReviewEvidence(
            valid=self.review_valid,
            certain=self.review_certain,
            source_sha256=self.review_source_hash,
            compiled_sha256=self.review_compiled_hash,
            configured_end_time_s=self.review_end_time_s,
            configured_outputs=self.review_outputs,
            errors=() if self.review_valid else ("validator rejected case",),
        )

    def check_fluids(self, setup: SimulationSetup) -> FluidEvidence:
        self.calls.append("fluids")
        return FluidEvidence(
            consistent=self.fluid_consistent,
            certain=True,
            run_input_sha256=self.run_input_hash,
            issues=() if self.fluid_consistent else ("PVT companion mismatch",),
        )

    def detect_runtime(self, setup: SimulationSetup) -> RuntimeEvidence:
        self.calls.append("runtime")
        return RuntimeEvidence(
            available=self.runtime_available,
            certainty=self.runtime_certainty,
            candidate_id="candidate-01",
            runtime_id="runtime-01",
            display_name=self.runtime_display_name,
        )

    def preview_run(self, setup: SimulationSetup) -> PreviewEvidence:
        self.calls.append("preview")
        return PreviewEvidence(
            ready=self.preview_ready,
            setup_hash=self.preview_setup_hash or setup_hash(setup),
            run_input_sha256=self.preview_run_input_hash or self.run_input_hash,
            candidate_id=self.preview_candidate_id,
            runtime_id=self.preview_runtime_id,
            timeout_s=setup.timeout_s,
            context_generation=self.preview_context,
            selection_id="selection-01",
            command_label="OLGA 2022.1 · direct engine",
            errors=() if self.preview_ready else ("preview rejected",),
        )

    def context_generation(self) -> int:
        return self.current_context


def test_setup_rejects_unknown_and_malformed_fields() -> None:
    payload = _active_setup().model_dump()
    payload["unexpected"] = True
    payload["output_target"] = {"relative_dir": "../escape"}

    with pytest.raises(ValidationError):
        SimulationSetup.model_validate(payload)


def test_setup_parses_json_arrays_but_rejects_coerced_numbers() -> None:
    payload = _active_setup().model_dump(mode="json")

    parsed = SimulationSetup.model_validate(payload)
    payload["timeout_s"] = "3600"

    assert parsed.outputs == ("PT", "TM")
    with pytest.raises(ValidationError):
        SimulationSetup.model_validate(payload)


def test_preflight_approves_exact_active_case_without_mutation() -> None:
    setup = _active_setup()
    deps = FakePreflight()

    result = preflight_simulation(setup, deps)

    assert isinstance(result, PreflightApproved)
    assert result.selection_id == "selection-01"
    assert result.receipt == (
        "Ready to run active case revision aaaaaaaaaaaa with OLGA 2022.1 direct engine; "
        "ENDTIME 10800 s, outputs PT, TM, timeout 3600 s, "
        "output target results/case-01."
    )
    assert "/mnt/" not in result.receipt
    assert deps.calls == ["review", "fluids", "runtime", "preview"]


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"current_context": 8}, "stale_context"),
        ({"review_source_hash": "c" * 64}, "stale_source"),
        ({"review_valid": False}, "invalid_case"),
        ({"review_certain": False}, "uncertain_case_review"),
        ({"review_end_time_s": 7200}, "integration_mismatch"),
        ({"review_outputs": ("PT",)}, "outputs_mismatch"),
        ({"fluid_consistent": False}, "fluid_mismatch"),
        ({"runtime_available": False}, "runtime_unavailable"),
        ({"runtime_certainty": "uncertain"}, "runtime_uncertain"),
        ({"preview_candidate_id": "candidate-02"}, "preview_binding_mismatch"),
        ({"preview_setup_hash": "d" * 64}, "preview_binding_mismatch"),
        ({"preview_run_input_hash": "e" * 64}, "preview_binding_mismatch"),
        ({"preview_ready": False}, "preview_rejected"),
    ],
)
def test_preflight_fails_closed_for_stale_invalid_or_uncertain_evidence(
    change: dict[str, int | str | bool],
    reason: str,
) -> None:
    deps = FakePreflight(**change)

    result = preflight_simulation(_active_setup(), deps)

    assert isinstance(result, PreflightRefused)
    assert result.reason == reason
    assert result.ready is False


def test_transaction_requires_exact_compiled_hash_through_preview() -> None:
    deps = FakePreflight(
        review_compiled_hash=COMPILED_HASH,
        run_input_hash=COMPILED_HASH,
    )

    approved = preflight_simulation(_transaction_setup(), deps)
    refused = preflight_simulation(
        _transaction_setup(),
        FakePreflight(
            review_compiled_hash=COMPILED_HASH,
            run_input_hash="c" * 64,
        ),
    )

    assert isinstance(approved, PreflightApproved)
    assert isinstance(refused, PreflightRefused)
    assert refused.reason == "fluid_hash_mismatch"


def test_transaction_refuses_stale_compiled_review() -> None:
    result = preflight_simulation(
        _transaction_setup(),
        FakePreflight(review_compiled_hash="c" * 64, run_input_hash=COMPILED_HASH),
    )

    assert isinstance(result, PreflightRefused)
    assert result.reason == "stale_compiled_case"


def test_receipt_does_not_echo_private_runtime_path() -> None:
    result = preflight_simulation(
        _active_setup(),
        FakePreflight(runtime_display_name="C:\\Program Files\\OLGA\\olga.exe"),
    )

    assert isinstance(result, PreflightApproved)
    assert "Program Files" not in result.receipt
    assert "runtime-01" in result.receipt


def test_preflight_short_circuits_without_preview_or_side_effect_on_invalid_review() -> None:
    deps = FakePreflight(review_valid=False)

    result = preflight_simulation(_active_setup(), deps)

    assert isinstance(result, PreflightRefused)
    assert deps.calls == ["review"]


@pytest.fixture
def live_fluid_preflight(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from olga_companion.agent.simulation_setup_adapter import _LivePreflight
    from olga_companion import genkey_static, workspace

    fixtures = Path(__file__).parent / "fixtures" / "fluids"
    source = tmp_path / "case.genkey"
    shutil.copyfile(fixtures / "case_ok.genkey", source)
    shutil.copyfile(fixtures / "fluid.tab", tmp_path / "fluid.tab")
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setattr(workspace, "active_path", lambda: str(source))
    setup = _active_setup().model_copy(update={
        "binding": ActiveCaseBinding(kind="active_case", source_sha256=genkey_static.file_sha256(source)),
    })
    return _LivePreflight(setup), setup


@pytest.mark.parametrize(
    "references",
    [
        [],
        [{"exists": True, "cross_check": {"valid": False}}],
        [{"exists": True, "cross_check": None}],
        [{"exists": True}],
        [{"exists": True, "cross_check": {"valid": "true"}}],
        [
            {"exists": True, "cross_check": {"valid": True}},
            {"exists": True, "cross_check": {"valid": False}},
        ],
    ],
)
def test_live_preflight_does_not_confuse_present_pvt_with_valid_pvt(
    live_fluid_preflight, monkeypatch: pytest.MonkeyPatch, references: list[dict]
) -> None:
    from olga_companion import fluids

    live, setup = live_fluid_preflight
    monkeypatch.setattr(fluids, "consistency", lambda _source: {
        "missing": 0,
        "references": references,
        "source_sha256_before": SOURCE_HASH,
        "source_sha256_after": SOURCE_HASH,
        "source_mutated": False,
    })

    evidence = live.check_fluids(setup)

    assert evidence.certain is True
    assert evidence.consistent is False
    assert evidence.issues


def test_live_preflight_checks_the_actual_pvt_validator(live_fluid_preflight) -> None:
    live, setup = live_fluid_preflight
    source_before = live.source.read_bytes()

    assert live.check_fluids(setup).consistent is True
    shutil.copyfile(
        Path(__file__).parent / "fixtures" / "fluids" / "broken.tab",
        live.source.parent / "fluid.tab",
    )

    refused = live.check_fluids(setup)

    assert refused.consistent is False
    assert refused.issues
    assert live.source.read_bytes() == source_before
