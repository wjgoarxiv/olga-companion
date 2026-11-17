from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from olga_companion.agent import simulation_setup_adapter
from olga_companion.agent.tool_validation import ToolError


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize("fluid_valid", [True, False, None])
def test_live_adapter_returns_path_private_exact_preview(
    tmp_path: Path,
    monkeypatch,
    fluid_valid: bool | None,
) -> None:
    case = tmp_path / "case.genkey"
    case.write_text("INTEGRATION ENDTIME=3600\n", encoding="utf-8")
    source_hash = _sha256(case)
    candidate_id = "candidate_01"
    runtime_id = "runtime_2022"
    context_generation = 17

    monkeypatch.setattr(simulation_setup_adapter.workspace, "active_path", lambda: str(case))
    monkeypatch.setattr(
        simulation_setup_adapter.workspace,
        "resolve_input_file",
        lambda _path, _suffixes: case,
    )
    monkeypatch.setattr(
        simulation_setup_adapter.workspace,
        "context_generation",
        lambda: context_generation,
    )
    monkeypatch.setattr(
        simulation_setup_adapter.genkey_static,
        "review_file",
        lambda _path: {"valid": True},
    )
    monkeypatch.setattr(
        simulation_setup_adapter.case_compiler_toolkit,
        "verify_with_toolkit",
        lambda _text: SimpleNamespace(
            clean=True,
            end_time_s=3600.0,
            outputs=("PT", "TM"),
        ),
    )
    monkeypatch.setattr(
        simulation_setup_adapter.fluids,
        "consistency",
        lambda _path: {
            "source_sha256_before": source_hash,
            "source_sha256_after": source_hash,
            "source_mutated": False,
            "missing": 0,
            "references": [{"exists": True, "cross_check": {"valid": fluid_valid}}],
        },
    )
    monkeypatch.setattr(
        simulation_setup_adapter.runner,
        "detect_olga",
        lambda _path: {
            "candidates": [
                {
                    "candidate_id": candidate_id,
                    "runtime_id": runtime_id,
                    "version": "2022.1.0",
                    "kind": "direct engine",
                }
            ]
        },
    )

    preview_calls = []

    def preview(_path: str, timeout_s: int, *, candidate_id: str) -> dict:
        preview_calls.append(_path)
        return {
            "validation": {"valid": True},
            "candidate_id": candidate_id,
            "runtime_id": runtime_id,
            "timeout_s": timeout_s,
            "selection_id": "selection_01",
        }

    monkeypatch.setattr(simulation_setup_adapter.runner, "preview_run", preview)
    payload = {
        "binding": {
            "kind": "active_case",
            "source_sha256": source_hash,
        },
        "integration": {"end_time_s": 3600},
        "outputs": ["PT", "TM"],
        "runtime": {"candidate_id": candidate_id, "runtime_id": runtime_id},
        "timeout_s": 120,
        "output_target": {"relative_dir": "managed-run-sandbox"},
        "context_generation": context_generation,
    }
    result = simulation_setup_adapter.execute(payload)

    if fluid_valid is not True:
        assert result["ready"] is False
        assert result["reason"] == "fluid_mismatch"
        assert preview_calls == []
        return

    assert result["ready"] is True
    assert result["run_input_sha256"] == source_hash
    assert result["selection_id"] == "selection_01"
    assert str(tmp_path) not in repr(result)

    payload["integration"] = {"end_time_s": 7200}
    mismatched = simulation_setup_adapter.execute(payload)
    assert mismatched["ready"] is False
    assert mismatched["reason"] == "integration_mismatch"


def test_transaction_binding_refuses_transaction_context_drift(
    tmp_path: Path,
    monkeypatch,
) -> None:
    compiled = tmp_path / "compiled.genkey"
    compiled.write_text("INTEGRATION ENDTIME=3600 s\n", encoding="utf-8")
    compiled_hash = _sha256(compiled)
    monkeypatch.setattr(
        simulation_setup_adapter.case_transactions,
        "load_transaction",
        lambda _transaction_id: SimpleNamespace(
            compiled=compiled,
            source_hash="a" * 64,
            compiled_hash=compiled_hash,
            context_generation=4,
        ),
    )

    with pytest.raises(ToolError, match="context|stale"):
        simulation_setup_adapter.execute(
            {
                "binding": {
                    "kind": "transaction",
                    "transaction_id": "1" * 32,
                    "source_sha256": "a" * 64,
                    "compiled_sha256": compiled_hash,
                },
                "integration": {"end_time_s": 3600},
                "outputs": ["PT"],
                "runtime": {"candidate_id": "candidate_01", "runtime_id": "runtime_2022"},
                "timeout_s": 120,
                "output_target": {"relative_dir": "managed-run-sandbox"},
                "context_generation": 5,
            }
        )
