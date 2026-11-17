"""Closeout F2 review: one failing check per backend finding, then the fix."""

from __future__ import annotations

import json
from pathlib import Path

import anyio
import pytest
from pydantic import ValidationError

from olga_companion import case_compiler, case_spec
from olga_companion.agent import (
    approval_event_persistence,
    chat,
    history,
    pending_approvals,
    runtime,
)
from olga_companion.agent.pending_approvals import PendingApprovalError
from olga_companion.case_transactions import case_spec_hash, plan_case_edits
from olga_companion.evaluation import _judge_pressure_drop
from olga_companion.genkey_static import OlgaInputError
from olga_companion.reports import findings_report
from olga_companion.sidecar_chat_routes import _used_approval_body
from olga_companion.sidecar_contracts import FindingsReportRequest

FIXTURE = Path(__file__).parent / "fixtures" / "casespec_source_massflow.json"
GENKEY = Path(__file__).parent / "fixtures" / "cases" / "simple_pipeline.genkey"
TPL = Path(__file__).parent / "fixtures" / "results" / "fixture.tpl"
CLAIM = "검증과 컴파일은 끝났고, 저장 승인 카드만 올려 두었습니다. 승인 카드에서 승인해 주세요."
NOTICE = "승인 요청이 아직 만들어지지 않았습니다. 저장하려면 다시 요청하세요."


def _spec() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _closed_inlet() -> dict:
    raw = _spec()
    inlet = raw["nodes"][0]
    inlet["kind"] = "closed"
    for field in ("pressure_pa", "temperature_c", "gas_fraction", "total_water_fraction"):
        del inlet[field]
    return raw


def test_compile_and_edit_refuse_steady_off_and_closed_inlet_zero(tmp_path: Path) -> None:
    off = _spec()
    off["integration"]["steady_state"] = False
    with pytest.raises(ValidationError, match="steady_state_off_requires_initial_conditions"):
        case_compiler.compile_case_spec(off)

    raw = _closed_inlet()
    (tmp_path / "fluid.tab").write_text('PVTTABLE LABEL="TEST_FLUID"\n', encoding="utf-8")
    updated = plan_case_edits(
        raw,
        [{"op": "set_source_massflow", "label": "FEED", "mass_flow_kg_s": 0}],
        expected_hash=case_spec_hash(raw),
        workspace_root=tmp_path,
    )
    assert updated.publishable is False
    assert "closed_inlet_requires_nonzero_initial_source" in updated.errors[0].evidence


def test_turn_guards_ignore_approvals_from_earlier_turns(monkeypatch: pytest.MonkeyPatch) -> None:
    session_id = history.new_session("older approval")
    pending_approvals.register(
        action_kind="case_publish",
        args={},
        call_id="older",
        context_generation=0,
        session_id=session_id,
    )

    async def provider_events(*_args, **_kwargs):
        yield runtime.AgentEvent("done", {"text": CLAIM})

    monkeypatch.setattr(approval_event_persistence.runtime, "run_turn", provider_events)
    events = anyio.run(
        approval_event_persistence.persist_runtime_events,
        object(),
        "model",
        object(),
        session_id,
        {"turn_id": "turn-1", "request_id": "request-1"},
        None,
    )
    done = next(event for event in events if event["type"] == "done")
    assert NOTICE in done["data"]["text"]
    stored = next(
        record["text"]
        for record in history.read(session_id)
        if record.get("record") == "assistant"
    )
    assert NOTICE in stored
    pending_approvals.revoke_all()


def test_uncertain_terminal_is_not_reported_as_expired() -> None:
    session_id = history.new_session("uncertain stays")
    pending_id = pending_approvals.register(
        action_kind="case_publish",
        args={"destination_rel": "x.genkey"},
        call_id="call-uncertain",
        context_generation=1,
        session_id=session_id,
    )
    claimed = pending_approvals.claim(
        pending_id,
        session_id=session_id,
        call_id="call-uncertain",
        context_generation=1,
    )
    pending_approvals.fail(pending_id, claimed, "Dispatch outcome is uncertain.")
    with pending_approvals._LOCK:
        _expires_at, outcome = pending_approvals._TERMINAL[pending_id]
        pending_approvals._TERMINAL[pending_id] = (0, outcome)

    recovered = pending_approvals.recover(
        pending_id,
        session_id=session_id,
        call_id="call-uncertain",
        context_generation=1,
    )
    assert isinstance(recovered, pending_approvals.FailedApproval)

    lookalike = _used_approval_body(
        PendingApprovalError("Pending approval is unknown, expired, or already used.")
    )
    assert lookalike is None
    pending_approvals.revoke_all()


def test_partial_series_edit_shows_every_point(tmp_path: Path) -> None:
    raw = _spec()
    raw["massflow_sources"][0]["series"] = [
        {
            "time_s": 0,
            "mass_flow_kg_s": 1,
            "temperature_c": 40,
            "gas_fraction": 0.25,
            "total_water_fraction": 0,
        },
        {
            "time_s": 5,
            "mass_flow_kg_s": 2,
            "temperature_c": 15,
            "gas_fraction": 0.1,
            "total_water_fraction": 0.4,
        },
    ]
    (tmp_path / "fluid.tab").write_text('PVTTABLE LABEL="TEST_FLUID"\n', encoding="utf-8")
    updated = plan_case_edits(
        raw,
        [{"op": "set_source_massflow", "label": "FEED", "mass_flow_kg_s": 3}],
        expected_hash=case_spec_hash(raw),
        workspace_root=tmp_path,
    )
    assert updated.publishable is True, getattr(updated, "errors", updated)
    change = updated.semantic_diff[0]
    assert [point["mass_flow_kg_s"] for point in change.before["series"]] == [1, 2]
    assert [point["mass_flow_kg_s"] for point in change.after["series"]] == [3, 3]
    assert [point["temperature_c"] for point in change.after["series"]] == [40, 15]
    assert "TIME=(0, 5) s" in updated.compiled_bytes.decode()


def test_min_dt_respects_effective_dt_start_and_max_dt() -> None:
    slow_start = _spec()
    slow_start["integration"]["min_dt_s"] = 2
    refused = case_spec.validate_case_spec(slow_start)
    assert refused["valid"] is False
    assert any(error["code"] == "min_dt_exceeds_dt_start" for error in refused["errors"])

    short_max = _spec()
    short_max["integration"]["max_dt_s"] = 0.0005
    refused_max = case_spec.validate_case_spec(short_max)
    assert refused_max["valid"] is False
    assert any(error["code"] == "max_dt_below_min_dt" for error in refused_max["errors"])


def test_generated_position_labels_cannot_reuse_a_user_label() -> None:
    raw = _spec()
    raw["flowpaths"][0]["pipes"][0]["label"] = "POS_FEED"
    raw["massflow_sources"][0]["pipe"] = "POS_FEED"
    refused = case_spec.validate_case_spec(raw)
    assert refused["valid"] is False
    assert any(error["code"] == "duplicate_label" for error in refused["errors"])


def test_findings_text_stays_on_its_line_and_run_id_is_constrained() -> None:
    report = findings_report(
        str(GENKEY),
        str(TPL),
        [
            {
                "criterion": "drop\n## injected",
                "verdict": "PASS\n## injected",
                "source_file": "case.genkey\n## injected",
                "source_sha256": "ab12`cd34\n## injected",
            }
        ],
        variables=["PT\n## injected"],
        run_id="b553b7490451",
    )
    assert "\n## injected" not in report["markdown"]
    assert (
        "citation drop ## injected: `case.genkey ## injected` "
        "(sha256 `ab12 cd34 ## injected`)"
    ) in report["markdown"]
    assert "판정: PASS" in report["markdown"]
    assert "\n- PT\n" not in report["markdown"] or "\n## injected" not in report["markdown"]
    with pytest.raises(OlgaInputError):
        findings_report(str(GENKEY), str(TPL), run_id="bad id")
    with pytest.raises(ValidationError):
        FindingsReportRequest(case_file="a.genkey", results_file="b.tpl", run_id="bad id")


def test_claim_forgets_the_registered_expiry() -> None:
    session_id = history.new_session("claim epoch")
    pending_id = pending_approvals.register(
        action_kind="run_execute",
        args={"source": "case.genkey"},
        call_id="call-claim",
        context_generation=1,
        session_id=session_id,
    )
    pending_approvals.claim(
        pending_id,
        session_id=session_id,
        call_id="call-claim",
        context_generation=1,
    )
    assert pending_id not in pending_approvals._EXPIRES_EPOCH
    pending_approvals.revoke_all()


def test_pressure_drop_without_a_unit_asks_instead_of_judging() -> None:
    result = _judge_pressure_drop(
        {
            "tpl": str(TPL),
            "inlet_position": "POSITION - INLET",
            "outlet_position": "PIPELINE",
            "max_drop": 3.0e6,
        }
    )
    assert result[0]["status"] == "input_required"
    assert "unit" in result[0]["missing"]
