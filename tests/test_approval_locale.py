"""Todo 2 (plans/remaining-closeout.md): approval rows and save errors follow the chat locale.

ko output must stay byte-identical; en labels/values contain no Hangul;
case-file labels, OLGA keywords and units are never translated; the
"code:" prefix on save errors stays English.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import anyio

from olga_companion import case_spec
from olga_companion.agent import (
    approval_display,
    approval_event_persistence,
    approval_execution,
    chat,
    history,
    pending_approvals,
    runtime,
    tools,
)

FIXTURES = Path(__file__).parent / "fixtures"
SOURCE = FIXTURES / "casespec_source_massflow.json"
HANGUL = re.compile(r"[가-힣]")


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
        "steady_state": True,
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
    raw["equipment"] = [
        {
            "kind": "valve",
            "label": "VALVE_1",
            "flowpath": "MAIN",
            "pipe": "PIPE_A",
            "position": 0.5,
            "diameter_m": 0.1,
            "opening": 0.8,
        }
    ]
    return raw


def _spec():
    return case_spec.normalize_case_spec(_rich_spec())


def _boundary_kinds_spec():
    """Closed + junction boundary rows without running topology validation."""
    from olga_companion.case_spec import CaseSpec
    from olga_companion.case_spec_types import ClosedNode, IntegrationSpec, JunctionNode

    return CaseSpec.model_construct(
        nodes=(
            ClosedNode(label="BLK", kind="closed"),
            JunctionNode(label="TEE", kind="junction"),
        ),
        massflow_sources=(),
        flowpaths=(),
        equipment=(),
        integration=IntegrationSpec.model_construct(end_time_s=3600.0),
        outputs=("PT",),
        trend_positions=None,
    )


# ---------------------------------------------------------------- ko snapshot


def test_ko_rows_are_byte_identical() -> None:
    rows = approval_display.reviewed_inputs(_spec())
    assert rows == [
        {"group": "경계", "name": "SINK 압력", "value": "1000000", "unit": "Pa"},
        {"group": "경계", "name": "SINK 온도", "value": "30", "unit": "°C"},
        {"group": "경계", "name": "SINK 기체분율", "value": "0.2", "unit": "-"},
        {"group": "경계", "name": "SINK 총수분율", "value": "0.1", "unit": "-"},
        {"group": "경계", "name": "SOURCE 압력", "value": "2000000", "unit": "Pa"},
        {"group": "경계", "name": "SOURCE 온도", "value": "40", "unit": "°C"},
        {"group": "경계", "name": "SOURCE 기체분율", "value": "0.2", "unit": "-"},
        {"group": "경계", "name": "SOURCE 총수분율", "value": "0.4", "unit": "-"},
        {"group": "유입", "name": "FEED 관로", "value": "MAIN", "unit": ""},
        {"group": "유입", "name": "FEED 배관", "value": "PIPE_A", "unit": ""},
        {"group": "유입", "name": "FEED 구간", "value": "1", "unit": ""},
        {"group": "유입", "name": "FEED 시계열 1 시간", "value": "0", "unit": "s"},
        {"group": "유입", "name": "FEED 시계열 1 질량유량", "value": "0", "unit": "kg/s"},
        {"group": "유입", "name": "FEED 시계열 1 온도", "value": "15", "unit": "°C"},
        {"group": "유입", "name": "FEED 시계열 1 기체분율", "value": "0.1", "unit": "-"},
        {"group": "유입", "name": "FEED 시계열 1 총수분율", "value": "0.4", "unit": "-"},
        {"group": "유입", "name": "FEED 시계열 2 시간", "value": "5", "unit": "s"},
        {"group": "유입", "name": "FEED 시계열 2 질량유량", "value": "2", "unit": "kg/s"},
        {"group": "유입", "name": "FEED 시계열 2 온도", "value": "15", "unit": "°C"},
        {"group": "유입", "name": "FEED 시계열 2 기체분율", "value": "0.1", "unit": "-"},
        {"group": "유입", "name": "FEED 시계열 2 총수분율", "value": "0.4", "unit": "-"},
        {"group": "배관", "name": "PIPE_A 지름", "value": "0.1", "unit": "m"},
        {"group": "배관", "name": "PIPE_A 거칠기", "value": "5e-05", "unit": "m"},
        {"group": "배관", "name": "PIPE_A 구간 수", "value": "10", "unit": "개"},
        {"group": "배관", "name": "PIPE_A 시작", "value": "0, 0, 0", "unit": "m"},
        {"group": "배관", "name": "PIPE_A 끝", "value": "100, 0, 0", "unit": "m"},
        {"group": "배관", "name": "VALVE_1 지름", "value": "0.1", "unit": "m"},
        {"group": "배관", "name": "VALVE_1 개도", "value": "0.8", "unit": "-"},
        {"group": "배관", "name": "VALVE_1 위치", "value": "0.5", "unit": "-"},
        {"group": "해석", "name": "끝 시간", "value": "3600", "unit": "s"},
        {"group": "해석", "name": "트렌드 간격", "value": "60", "unit": "s"},
        {"group": "해석", "name": "프로파일 간격", "value": "900", "unit": "s"},
        {"group": "해석", "name": "출력 간격", "value": "3600", "unit": "s"},
        {"group": "해석", "name": "최대 시간 간격", "value": "10", "unit": "s"},
        {"group": "해석", "name": "정상상태 전처리", "value": "true", "unit": ""},
        {"group": "해석", "name": "시작 시간 간격", "value": "1e-06", "unit": "s"},
        {"group": "해석", "name": "최소 시간 간격", "value": "1e-07", "unit": "s"},
        {"group": "출력", "name": "출력 변수", "value": "GT", "unit": ""},
        {"group": "출력", "name": "출력 변수", "value": "PT", "unit": ""},
        {"group": "출력", "name": "POS_MID 트렌드", "value": "PIPE_A 구간 4", "unit": ""},
    ]


def test_ko_is_the_default_locale() -> None:
    spec = _spec()
    assert approval_display.reviewed_inputs(spec) == approval_display.reviewed_inputs(
        spec, locale="ko"
    )


def test_unknown_locale_falls_back_to_korean() -> None:
    spec = _spec()
    assert approval_display.reviewed_inputs(
        spec, locale="xx"
    ) == approval_display.reviewed_inputs(spec, locale="ko")
    assert approval_execution._publish_refusal(
        "destination_collision: .", locale="xx"
    ) == approval_execution._publish_refusal(
        "destination_collision: .", locale="ko"
    )


# ---------------------------------------------------------------- en rows


def test_en_rows_have_no_hangul_and_keep_units_and_case_labels() -> None:
    ko = approval_display.reviewed_inputs(_spec(), locale="ko")
    en = approval_display.reviewed_inputs(_spec(), locale="en")
    assert len(en) == len(ko)
    assert {row["group"] for row in en} == {
        "Boundary",
        "Inflow",
        "Piping",
        "Simulation",
        "Output",
    }
    for row in en:
        assert set(row) == {"group", "name", "value", "unit"}
        assert HANGUL.search(row["group"]) is None
        assert HANGUL.search(row["name"]) is None
        assert HANGUL.search(row["value"]) is None
    assert {row["unit"] for row in en} <= {"Pa", "°C", "-", "s", "kg/s", "m", ""}
    for ko_row, en_row in zip(ko, en):
        assert en_row["value"] in {ko_row["value"], "PIPE_A Section 4"}
        assert ko_row["unit"] == en_row["unit"] or (
            ko_row["unit"] == "개" and en_row["unit"] == ""
        )
    names = [row["name"] for row in en]
    for label in ("SOURCE", "SINK", "FEED", "PIPE_A", "VALVE_1", "POS_MID"):
        assert any(name.startswith(label) for name in names), label


def test_en_field_labels_spot_check() -> None:
    en = {
        (row["group"], row["name"], row["unit"])
        for row in approval_display.reviewed_inputs(_spec(), locale="en")
    }
    for expected in [
        ("Boundary", "SOURCE Pressure", "Pa"),
        ("Boundary", "SINK Temperature", "°C"),
        ("Boundary", "SOURCE Gas fraction", "-"),
        ("Boundary", "SOURCE Total water fraction", "-"),
        ("Inflow", "FEED Flowpath", ""),
        ("Inflow", "FEED Pipe", ""),
        ("Inflow", "FEED Section", ""),
        ("Inflow", "FEED Time series 1 Time", "s"),
        ("Inflow", "FEED Time series 1 Mass flow", "kg/s"),
        ("Inflow", "FEED Time series 2 Temperature", "°C"),
        ("Piping", "PIPE_A Diameter", "m"),
        ("Piping", "PIPE_A Roughness", "m"),
        ("Piping", "PIPE_A Section count", ""),
        ("Piping", "PIPE_A Start", "m"),
        ("Piping", "PIPE_A End", "m"),
        ("Piping", "VALVE_1 Diameter", "m"),
        ("Piping", "VALVE_1 Opening", "-"),
        ("Piping", "VALVE_1 Position", "-"),
        ("Simulation", "End time", "s"),
        ("Simulation", "Trend interval", "s"),
        ("Simulation", "Profile interval", "s"),
        ("Simulation", "Output interval", "s"),
        ("Simulation", "Max time step", "s"),
        ("Simulation", "Steady-state preprocessing", ""),
        ("Simulation", "Initial time step", "s"),
        ("Simulation", "Min time step", "s"),
        ("Output", "Output variable", ""),
        ("Output", "POS_MID Trend", ""),
    ]:
        assert expected in en, expected
    values = {
        row["name"]: row["value"]
        for row in approval_display.reviewed_inputs(_spec(), locale="en")
    }
    assert values["POS_MID Trend"] == "PIPE_A Section 4"


def test_closed_and_branch_values_are_localized() -> None:
    spec = _boundary_kinds_spec()
    ko = {
        row["name"]: row["value"]
        for row in approval_display.reviewed_inputs(spec)
        if row["group"] == "경계"
    }
    assert ko == {"BLK 경계": "닫힘", "TEE 경계": "분기"}
    en = {
        row["name"]: row["value"]
        for row in approval_display.reviewed_inputs(spec, locale="en")
        if row["group"] == "Boundary"
    }
    assert en == {"BLK Boundary": "Closed", "TEE Boundary": "Branch"}
    for name, value in en.items():
        assert HANGUL.search(name) is None
        assert HANGUL.search(value) is None


# ---------------------------------------------------------------- save errors


def test_every_save_error_code_has_ko_and_en_text() -> None:
    ko_codes = set(approval_execution._PUBLISH_RECOVERY)
    en_codes = set(approval_execution._PUBLISH_RECOVERY_EN)
    assert en_codes == ko_codes
    for code in ko_codes:
        ko_sentence = approval_execution._PUBLISH_RECOVERY[code]
        en_sentence = approval_execution._PUBLISH_RECOVERY_EN[code]
        assert HANGUL.search(ko_sentence) is not None, code
        assert HANGUL.search(en_sentence) is None, code
        assert "OLGA" not in en_sentence or code == "pvt_companion"


def test_publish_refusal_keeps_an_english_code_prefix() -> None:
    for code in approval_execution._PUBLISH_RECOVERY:
        for locale in ("ko", "en"):
            refused = approval_execution._publish_refusal(
                f"{code}: detail", locale=locale
            )
            assert refused is not None
            assert refused["state"] == "failed"
            error = refused["result"]["error"]
            assert error.startswith(f"{code}: ")
            sentence = error[len(code) + 2 :]
            if locale == "en":
                assert HANGUL.search(sentence) is None
    assert approval_execution._publish_refusal("no-such-code: x") is None
    assert approval_execution._publish_refusal("no separator here") is None


def test_old_pending_envelope_without_locale_defaults_to_ko() -> None:
    assert "locale" in approval_execution._APPROVAL_ENVELOPE_KEYS
    session_id = history.new_session("locale envelope")
    history.append(
        session_id,
        {
            "record": "approval",
            "state": "pending",
            "pending_id": "p-en",
            "turn_id": "t",
            "request_id": "r",
            "locale": "en",
        },
    )
    history.append(
        session_id,
        {
            "record": "approval",
            "state": "pending",
            "pending_id": "p-old",
            "turn_id": "t",
            "request_id": "r",
        },
    )
    assert (
        approval_execution._pending_approval_envelope(session_id, "p-en")["locale"]
        == "en"
    )
    old_envelope = approval_execution._pending_approval_envelope(session_id, "p-old")
    assert "locale" not in old_envelope
    assert approval_execution._refusal_locale(old_envelope) == "ko"
    assert approval_execution._refusal_locale({"locale": "en"}) == "en"
    assert approval_execution._refusal_locale({"locale": "xx"}) == "ko"


# ---------------------------------------------------------------- threading


def test_tools_wrapper_forwards_locale(monkeypatch) -> None:
    seen: dict = {}

    def spy(*args, **kwargs):
        seen["args"] = args
        seen["kwargs"] = kwargs
        return {"ok": True}

    monkeypatch.setattr(tools._approval_display, "build", spy)
    tools.approval_display("run_execute", {"source": "case.genkey"}, locale="en")
    assert seen["kwargs"].get("locale") == "en"


def test_case_publish_build_respects_locale(
    tmp_path: Path, monkeypatch
) -> None:
    from olga_companion import case_compiler
    from olga_companion.case_publish_types import PublishTransactionSnapshot

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
        locale="en",
    )
    rows = display["inputs"]
    assert rows
    for row in rows:
        assert HANGUL.search(row["group"]) is None
        assert HANGUL.search(row["name"]) is None
        assert HANGUL.search(row["value"]) is None
    assert any(
        row["group"] == "Simulation" and row["name"] == "Min time step"
        for row in rows
    )


def test_chat_thread_passes_en_locale_to_display(
    monkeypatch, tmp_path: Path
) -> None:
    from fastapi.testclient import TestClient

    from olga_companion.agent import session_token as _tokens
    from olga_companion.llm.protocol import StreamResult, ToolCall
    from olga_companion.sidecar import app as _app

    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(tmp_path))
    case = tmp_path / "case.genkey"
    case.write_text("CASE LABEL=case\nENDCASE\n", encoding="utf-8")
    seen: dict = {}

    def spy(name, args, locale="ko"):
        seen["locale"] = locale
        return {"case": "case.genkey"}

    monkeypatch.setattr("olga_companion.agent.tools.approval_display", spy)

    class _Conversation:
        def add_user_message(self, text, images=None): ...
        def add_assistant_response(self, text, tool_calls=None, thought_signature=None): ...
        def add_tool_result(self, call_id, name, result): ...

    class _Client:
        def create_conversation(self, model=""):
            return _Conversation()

        async def stream_generate(self, **kwargs):
            return StreamResult(
                tool_calls=[
                    ToolCall(
                        name="run_execute",
                        args={
                            "source": str(case),
                            "timeout_s": 3600,
                            "selection_id": "selection-1",
                        },
                        call_id="call-1",
                    )
                ]
            )

    chat.set_client_builder(lambda p, m, v: _Client())
    try:
        boot = _tokens.boot_token()
        local = TestClient(_app)
        sid = local.post(
            "/api/chat/session", json={"title": ""}, headers={"X-Session-Token": boot}
        ).json()["session_id"]
        response = local.post(
            "/api/chat",
            json={"session_id": sid, "message": "run it", "locale": "en"},
            headers={"X-Session-Token": boot},
        )
        assert response.status_code == 200
    finally:
        chat.set_client_builder(None)
        pending_approvals.revoke_all()
    assert seen.get("locale") == "en"


def test_en_rows_are_byte_identical() -> None:
    assert approval_display.reviewed_inputs(_spec(), locale="en") == [
        {"group": "Boundary", "name": "SINK Pressure", "value": "1000000", "unit": "Pa"},
        {"group": "Boundary", "name": "SINK Temperature", "value": "30", "unit": "°C"},
        {"group": "Boundary", "name": "SINK Gas fraction", "value": "0.2", "unit": "-"},
        {"group": "Boundary", "name": "SINK Total water fraction", "value": "0.1", "unit": "-"},
        {"group": "Boundary", "name": "SOURCE Pressure", "value": "2000000", "unit": "Pa"},
        {"group": "Boundary", "name": "SOURCE Temperature", "value": "40", "unit": "°C"},
        {"group": "Boundary", "name": "SOURCE Gas fraction", "value": "0.2", "unit": "-"},
        {"group": "Boundary", "name": "SOURCE Total water fraction", "value": "0.4", "unit": "-"},
        {"group": "Inflow", "name": "FEED Flowpath", "value": "MAIN", "unit": ""},
        {"group": "Inflow", "name": "FEED Pipe", "value": "PIPE_A", "unit": ""},
        {"group": "Inflow", "name": "FEED Section", "value": "1", "unit": ""},
        {"group": "Inflow", "name": "FEED Time series 1 Time", "value": "0", "unit": "s"},
        {"group": "Inflow", "name": "FEED Time series 1 Mass flow", "value": "0", "unit": "kg/s"},
        {"group": "Inflow", "name": "FEED Time series 1 Temperature", "value": "15", "unit": "°C"},
        {"group": "Inflow", "name": "FEED Time series 1 Gas fraction", "value": "0.1", "unit": "-"},
        {"group": "Inflow", "name": "FEED Time series 1 Total water fraction", "value": "0.4", "unit": "-"},
        {"group": "Inflow", "name": "FEED Time series 2 Time", "value": "5", "unit": "s"},
        {"group": "Inflow", "name": "FEED Time series 2 Mass flow", "value": "2", "unit": "kg/s"},
        {"group": "Inflow", "name": "FEED Time series 2 Temperature", "value": "15", "unit": "°C"},
        {"group": "Inflow", "name": "FEED Time series 2 Gas fraction", "value": "0.1", "unit": "-"},
        {"group": "Inflow", "name": "FEED Time series 2 Total water fraction", "value": "0.4", "unit": "-"},
        {"group": "Piping", "name": "PIPE_A Diameter", "value": "0.1", "unit": "m"},
        {"group": "Piping", "name": "PIPE_A Roughness", "value": "5e-05", "unit": "m"},
        {"group": "Piping", "name": "PIPE_A Section count", "value": "10", "unit": ""},
        {"group": "Piping", "name": "PIPE_A Start", "value": "0, 0, 0", "unit": "m"},
        {"group": "Piping", "name": "PIPE_A End", "value": "100, 0, 0", "unit": "m"},
        {"group": "Piping", "name": "VALVE_1 Diameter", "value": "0.1", "unit": "m"},
        {"group": "Piping", "name": "VALVE_1 Opening", "value": "0.8", "unit": "-"},
        {"group": "Piping", "name": "VALVE_1 Position", "value": "0.5", "unit": "-"},
        {"group": "Simulation", "name": "End time", "value": "3600", "unit": "s"},
        {"group": "Simulation", "name": "Trend interval", "value": "60", "unit": "s"},
        {"group": "Simulation", "name": "Profile interval", "value": "900", "unit": "s"},
        {"group": "Simulation", "name": "Output interval", "value": "3600", "unit": "s"},
        {"group": "Simulation", "name": "Max time step", "value": "10", "unit": "s"},
        {"group": "Simulation", "name": "Steady-state preprocessing", "value": "true", "unit": ""},
        {"group": "Simulation", "name": "Initial time step", "value": "1e-06", "unit": "s"},
        {"group": "Simulation", "name": "Min time step", "value": "1e-07", "unit": "s"},
        {"group": "Output", "name": "Output variable", "value": "GT", "unit": ""},
        {"group": "Output", "name": "Output variable", "value": "PT", "unit": ""},
        {"group": "Output", "name": "POS_MID Trend", "value": "PIPE_A Section 4", "unit": ""},
    ]


def test_label_lookup_has_no_korean_keyed_tables() -> None:
    """Per-row (ko, en) pairs replaced the Korean-word lookup dicts."""
    for name in ("_locale_of", "_GROUPS_EN", "_FIELDS_EN", "_VALUES_EN"):
        assert not hasattr(approval_display, name), name


def test_persistence_normalizes_unknown_locale_to_korean_once(
    monkeypatch,
) -> None:
    seen: dict = {}

    def spy(name, args, locale="ko"):
        seen["display_locale"] = locale
        return {"inputs": []}

    monkeypatch.setattr(approval_event_persistence.tools, "approval_display", spy)

    async def provider_events(*_args, **kwargs):
        seen["turn_locale"] = kwargs.get("locale")
        yield runtime.AgentEvent(
            "approval_required",
            {
                "name": "case_publish",
                "args": {},
                "call_id": "call-fallback",
                "context_generation": 0,
            },
        )

    monkeypatch.setattr(approval_event_persistence.runtime, "run_turn", provider_events)
    session_id = history.new_session("persistence fallback")
    try:
        anyio.run(
            approval_event_persistence.persist_runtime_events,
            object(),
            "model",
            object(),
            session_id,
            {"turn_id": "turn-1", "request_id": "request-1", "locale": "xx"},
            None,
        )
    finally:
        pending_approvals.revoke_all()
    assert seen.get("display_locale") == "ko"
    assert seen.get("turn_locale") == "ko"


def test_persistence_builds_display_in_turn_locale(monkeypatch) -> None:
    seen: dict = {}

    def spy(name, args, locale="ko"):
        seen["locale"] = locale
        return {"inputs": []}

    monkeypatch.setattr(approval_event_persistence.tools, "approval_display", spy)

    async def provider_events(*_args, **_kwargs):
        yield runtime.AgentEvent(
            "approval_required",
            {
                "name": "case_publish",
                "args": {},
                "call_id": "call-locale",
                "context_generation": 0,
            },
        )

    monkeypatch.setattr(approval_event_persistence.runtime, "run_turn", provider_events)
    session_id = history.new_session("persistence locale")
    try:
        anyio.run(
            approval_event_persistence.persist_runtime_events,
            object(),
            "model",
            object(),
            session_id,
            {"turn_id": "turn-1", "request_id": "request-1", "locale": "en"},
            None,
        )
    finally:
        pending_approvals.revoke_all()
    assert seen.get("locale") == "en"
