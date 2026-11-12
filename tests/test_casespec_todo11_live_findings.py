"""Todo 11: refuse STEADYSTATE=OFF without initial conditions, show reviewed numbers, keep workspace reads off the chat turn."""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import anyio
import pytest

from olga_companion import case_compiler, case_spec, workspace
from olga_companion.agent import approval_display, approval_execution
from olga_companion.agent.runtime import SYSTEM_PROMPT
from olga_companion.case_publish_types import PublishTransactionSnapshot

FIXTURES = Path(__file__).parent / "fixtures"
SOURCE = FIXTURES / "casespec_source_massflow.json"


def _rich_spec() -> dict:
    raw = json.loads(SOURCE.read_text(encoding="utf-8"))
    raw["integration"] = {
        "end_time_s": 3600.0,
        "trend_interval_s": 60.0,
        "profile_interval_s": 900.0,
        "output_interval_s": 3600.0,
        "max_dt_s": 10.0,
        "dt_start_s": 1e-6,
        "min_dt_s": 1e-7,
    }
    raw["nodes"][1]["gas_fraction"] = 0.2
    raw["nodes"][1]["total_water_fraction"] = 0.1
    raw["massflow_sources"][0]["series"] = [
        {
            "time_s": 0.0,
            "mass_flow_kg_s": 0.0,
            "temperature_c": 15.0,
            "gas_fraction": 0.1,
            "total_water_fraction": 0.4,
        },
        {
            "time_s": 5.0,
            "mass_flow_kg_s": 2.0,
            "temperature_c": 15.0,
            "gas_fraction": 0.1,
            "total_water_fraction": 0.4,
        },
    ]
    raw["trend_positions"] = [{"label": "POS_MID", "pipe": "PIPE_A", "section": 4}]
    raw["outputs"] = ["PT", "GT"]
    return raw


def _by_group(rows: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        grouped.setdefault(row["group"], []).append(row)
    return grouped


def test_steady_state_off_without_initial_conditions_is_refused() -> None:
    raw = json.loads(SOURCE.read_text(encoding="utf-8"))
    raw["integration"]["steady_state"] = False

    result = case_spec.validate_case_spec(raw)

    assert result["valid"] is False
    assert result["publishable"] is False
    assert result["errors"][0]["code"] == "steady_state_off_requires_initial_conditions"
    assert "INITIALCONDITIONS" not in case_compiler.render_case_spec(
        json.loads(SOURCE.read_text(encoding="utf-8"))
    ).decode()


def _closed_inlet() -> dict:
    raw = json.loads(SOURCE.read_text(encoding="utf-8"))
    inlet = raw["nodes"][0]
    assert inlet["label"] == "SOURCE"
    inlet["kind"] = "closed"
    del inlet["pressure_pa"]
    del inlet["temperature_c"]
    del inlet["gas_fraction"]
    del inlet["total_water_fraction"]
    return raw


def _zero_then_one_series() -> list[dict]:
    return [
        {
            "time_s": 0.0,
            "mass_flow_kg_s": 0.0,
            "temperature_c": 15.0,
            "gas_fraction": 0.0,
            "total_water_fraction": 1.0,
        },
        {
            "time_s": 10.0,
            "mass_flow_kg_s": 1.0,
            "temperature_c": 15.0,
            "gas_fraction": 0.0,
            "total_water_fraction": 1.0,
        },
    ]


def test_closed_inlet_steady_state_refuses_a_zero_first_source_value() -> None:
    raw = _closed_inlet()
    raw["massflow_sources"][0]["series"] = _zero_then_one_series()

    result = case_spec.validate_case_spec(raw)

    assert result["valid"] is False
    assert result["publishable"] is False
    assert result["errors"][0]["code"] == "closed_inlet_requires_nonzero_initial_source"


def test_closed_inlet_scalar_zero_at_the_first_section_is_refused() -> None:
    raw = _closed_inlet()
    raw["massflow_sources"][0]["mass_flow_kg_s"] = 0.0

    result = case_spec.validate_case_spec(raw)

    assert result["errors"][0]["code"] == "closed_inlet_requires_nonzero_initial_source"


def test_closed_inlet_with_a_nonzero_first_value_stays_valid() -> None:
    raw = _closed_inlet()
    raw["massflow_sources"][0]["series"] = _zero_then_one_series()
    raw["massflow_sources"][0]["series"][0]["mass_flow_kg_s"] = 1.0

    result = case_spec.validate_case_spec(raw)

    assert result["valid"] is True


def test_pressure_inlet_may_start_a_series_at_zero() -> None:
    raw = json.loads(SOURCE.read_text(encoding="utf-8"))
    raw["massflow_sources"][0]["series"] = _zero_then_one_series()

    result = case_spec.validate_case_spec(raw)

    assert result["valid"] is True


def test_steady_state_off_still_reports_the_initial_conditions_issue() -> None:
    raw = _closed_inlet()
    raw["integration"]["steady_state"] = False
    raw["massflow_sources"][0]["series"] = _zero_then_one_series()

    result = case_spec.validate_case_spec(raw)

    assert result["errors"][0]["code"] == "steady_state_off_requires_initial_conditions"


def test_steady_state_left_unset_stays_valid() -> None:
    result = case_spec.validate_case_spec(json.loads(SOURCE.read_text(encoding="utf-8")))

    assert result["valid"] is True
    assert result["normalized"]["integration"].get("steady_state") is None


def test_prompt_echoes_user_numerics_verbatim_before_validate() -> None:
    prompt = SYSTEM_PROMPT
    lowered = prompt.lower()

    assert "before case_spec_validate" in lowered
    assert "1e-7" in prompt
    assert "character for character" in lowered
    assert "0.0001" in prompt


def test_case_publish_reviewed_inputs_list_normalized_numbers() -> None:
    spec = case_spec.normalize_case_spec(_rich_spec())
    rows = approval_display.reviewed_inputs(spec)
    grouped = _by_group(rows)

    assert list(grouped) == ["경계", "유입", "배관", "해석", "출력"]
    assert all(set(row) == {"group", "name", "value", "unit"} for row in rows)
    assert all(isinstance(row["value"], str) for row in rows)
    pressures = [row for row in grouped["경계"] if row["name"].endswith("압력")]
    assert {row["value"] for row in pressures} >= {"2000000", "1000000"}
    assert all(row["unit"] == "Pa" for row in pressures)
    series = [row for row in grouped["유입"] if "시계열" in row["name"]]
    assert any(row["value"] == "5" and row["unit"] == "s" for row in series)
    assert any(row["value"] == "2" and row["unit"] == "kg/s" for row in series)
    pipes = grouped["배관"]
    assert any(row["name"].endswith("지름") and row["value"] == "0.1" and row["unit"] == "m" for row in pipes)
    assert any(row["name"].endswith("거칠기") and row["value"] == "5e-05" for row in pipes)
    integration = {row["name"]: row for row in grouped["해석"]}
    assert integration["최소 시간 간격"]["value"] in {"1e-07", "1e-7"}
    assert integration["최소 시간 간격"]["value"] != "0.0001"
    assert integration["최소 시간 간격"]["unit"] == "s"
    assert integration["시작 시간 간격"]["value"] in {"1e-06", "1e-6"}
    assert integration["끝 시간"]["value"] == "3600"
    assert integration["최대 시간 간격"]["value"] == "10"
    assert [row["value"] for row in grouped["출력"] if row["name"] == "출력 변수"] == ["GT", "PT"]
    assert any(row["value"] == "PIPE_A 구간 4" for row in grouped["출력"])


def test_case_publish_display_carries_recovered_inputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    compiled = tmp_path / "compiled.genkey"
    compiled.write_bytes(case_compiler.render_case_spec(_rich_spec()))
    snapshot = PublishTransactionSnapshot(
        transaction_id="a" * 32,
        source=None,
        source_hash="b" * 64,
        compiled=compiled,
        compiled_hash="c" * 64,
        backup=tmp_path / "backup.genkey",
        backup_hash="d" * 64,
        validation_clean=True,
        publishable=True,
        context_generation=4,
    )

    def load(transaction_id: str) -> PublishTransactionSnapshot:
        assert transaction_id == snapshot.transaction_id
        return snapshot

    monkeypatch.setattr(approval_display.case_transactions, "load_transaction", load)
    display = approval_display.build(
        "case_publish",
        {
            "transaction_id": snapshot.transaction_id,
            "source_hash": snapshot.source_hash,
            "compiled_hash": snapshot.compiled_hash,
            "destination_rel": "published.genkey",
            "context_generation": 4,
        },
    )

    rows = display["inputs"]
    assert any(
        row["group"] == "해석" and row["name"] == "최소 시간 간격" and row["value"] in {"1e-07", "1e-7"}
        for row in rows
    )
    assert any(row["group"] == "유입" and "시계열" in row["name"] and row["value"] == "2" for row in rows)


def test_workspace_reads_return_while_resume_turn_is_blocked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(root))
    entered = threading.Event()

    async def blocked_turn(**_kwargs: object) -> dict[str, object]:
        entered.set()
        await anyio.sleep(1.0)
        return {"state": "resume_pending", "result": {}, "resume_allowed": True}

    monkeypatch.setattr(approval_execution.approval_continuation, "resume", blocked_turn)

    def hold_resume() -> None:
        anyio.run(
            lambda: approval_execution.resume(
                pending_id="pending",
                session_id="session",
                call_id="call",
                context_generation=workspace.context_generation(),
            )
        )

    holder = threading.Thread(target=hold_resume)
    holder.start()
    assert entered.wait(2)
    started = time.perf_counter()
    active = workspace.active_workspace()
    context = workspace.context_snapshot()
    elapsed = time.perf_counter() - started
    holder.join(timeout=3)

    assert active["path"] is None
    assert context["generation"] == workspace.context_generation()
    assert elapsed < 0.3, (
        f"workspace.active_workspace and context_snapshot waited {elapsed:.3f}s "
        "while approval_execution.resume held workspace.expected_context "
        "across approval_continuation.resume"
    )


def test_resume_still_rejects_a_stale_generation_before_the_turn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(root))
    called = False

    async def blocked_turn(**_kwargs: object) -> dict[str, object]:
        nonlocal called
        called = True
        return {"state": "resume_pending", "result": {}, "resume_allowed": True}

    monkeypatch.setattr(approval_execution.approval_continuation, "resume", blocked_turn)

    with pytest.raises(workspace.StaleWorkspaceContextError):
        anyio.run(
            lambda: approval_execution.resume(
                pending_id="pending",
                session_id="session",
                call_id="call",
                context_generation=9,
            )
        )

    assert called is False
