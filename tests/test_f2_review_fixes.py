"""F2 review fixes for the approval/heal lifecycle (M1-M4, m1-m6, m8).

Offline: every provider is scripted, every approval is seeded straight into history.
"""
from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from olga_companion import genkey_static, workspace
from olga_companion.agent import (
    approval_continuation,
    approval_execution,
    chat,
    chat_replay,
    history,
    pending_approvals,
    runtime,
    session_token,
    tools,
)
from olga_companion.agent.chat_singleflight import (
    session_busy,
    session_single_flight,
    session_single_flight_sync,
)
from olga_companion.llm.openai_chat_adapter import OpenAIChatConversationBuilder
from olga_companion.llm.protocol import StreamResult, ToolCall
from olga_companion.sidecar import app

ARGS: dict[str, Any] = {
    "fluid_label": "SYN1",
    "components": [{"name": "METHANE", "mole_fraction": 1.0}],
    "model": "SRK",
    "temperatures": [-10.0, 50.0],
    "temperature_unit": "degC",
    "pressures": [0.0, 5.0],
    "pressure_unit": "barg",
    "mfl_rel": "synthetic.mfl",
}
PENDING_ID = "p" * 32


@pytest.fixture(autouse=True)
def _isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(tmp_path))
    session_token.boot_token()
    pending_approvals.revoke_all()
    yield
    pending_approvals.revoke_all()
    chat.set_client_builder(None)


def _common(generation: int, locale: str = "en") -> dict[str, Any]:
    return {
        "workspace_generation": generation,
        "provider": "openai",
        "model": "m",
        "locale": locale,
    }


def _seed(
    *,
    calls: tuple[str, ...] = ("orphan-1",),
    approval_call: str | None = "orphan-1",
    state: str = "pending",
    pending_id: str = PENDING_ID,
    locale: str = "en",
    result: dict[str, Any] | None = None,
    generation: int | None = None,
) -> tuple[str, int]:
    session_id = history.new_session("f2")
    gen = workspace.context_generation() if generation is None else generation
    common = _common(gen, locale)
    history.append(session_id, {"record": "user", "text": "draft it", **common})
    history.append(
        session_id,
        {
            "record": "assistant",
            "text": "",
            "tool_calls": [
                {"name": "fluids_draft_mfl", "args": ARGS, "call_id": cid, "raw_arguments": "{}", "item_id": ""}
                for cid in calls
            ],
            **common,
        },
    )
    for cid in calls[:1]:
        history.append(
            session_id,
            {
                "record": "event", "type": "tool_call", "name": "fluids_draft_mfl",
                "call_id": cid, "args": ARGS, "raw_arguments": "{}", "item_id": "", **common,
            },
        )
    if approval_call is not None:
        record: dict[str, Any] = {
            "record": "approval", "pending_id": pending_id, "call_id": approval_call,
            "name": "fluids_draft_mfl", "args": ARGS, "state": state, **common,
        }
        if result is not None:
            record["result"] = result
        history.append(session_id, record)
    return session_id, gen


def _results(session_id: str, call_id: str) -> list[dict[str, Any]]:
    return [
        r for r in history.read(session_id)
        if r.get("record") == "event" and r.get("type") == "tool_result" and r.get("call_id") == call_id
    ]


class _Client:
    """Real OpenAI chat builder; captures the payload each generation sees."""

    def __init__(self, script: list[StreamResult] | None = None) -> None:
        self.script = list(script or [StreamResult(text="ok")])
        self.payloads: list[list[dict]] = []

    def create_conversation(self, model: str = ""):
        return OpenAIChatConversationBuilder()

    async def stream_generate(self, *, conversation, **kwargs) -> StreamResult:
        self.payloads.append(conversation.get_request_payload())
        return self.script.pop(0)


def _run_turn(session_id: str, message: str, locale: str = "en") -> list[runtime.AgentEvent]:
    async def go():
        return [
            e async for e in chat.run_chat_turn(
                session_id, message, provider="openai", model="m", variant="", locale=locale
            )
        ]

    return asyncio.run(go())


# ---------------------------------------------------------------- M1


def test_m1_heal_runs_before_the_user_message_so_it_is_seeded_once() -> None:
    session_id, _ = _seed()
    client = _Client()
    chat.set_client_builder(lambda _p, _m, _v: client)

    _run_turn(session_id, "second message")

    users = [r for r in history.read(session_id) if r.get("record") == "user" and r["text"] == "second message"]
    assert len(users) == 1
    payload = client.payloads[0]
    seeded = [i for i, m in enumerate(payload) if m.get("role") == "user" and m.get("content") == "second message"]
    assert len(seeded) == 1, payload
    tool_at = [i for i, m in enumerate(payload) if m.get("role") == "tool" and m.get("tool_call_id") == "orphan-1"]
    assert len(tool_at) == 1 and tool_at[0] < seeded[0], payload


# ---------------------------------------------------------------- M2


def test_m2a_workspace_switch_makes_a_pending_approval_dead(monkeypatch: pytest.MonkeyPatch) -> None:
    session_id, gen = _seed()
    pending_id = pending_approvals.register(
        action_kind="fluids_draft_mfl", args=dict(ARGS), call_id="orphan-1",
        context_generation=gen, session_id=session_id,
    )
    history.append(
        session_id,
        {"record": "approval", "pending_id": pending_id, "call_id": "orphan-1",
         "name": "fluids_draft_mfl", "args": ARGS, "state": "pending", **_common(gen)},
    )
    assert pending_approvals.is_actionable(
        pending_id, session_id=session_id, call_id="orphan-1", context_generation=gen
    )
    monkeypatch.setattr(workspace, "context_generation", lambda: gen + 1)

    assert chat._heal_orphan_tool_calls(session_id, history.read(session_id), "en") is True
    assert len(_results(session_id, "orphan-1")) == 1


def test_m2a_read_session_does_not_offer_a_card_from_another_workspace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id, gen = _seed()
    pending_id = pending_approvals.register(
        action_kind="fluids_draft_mfl", args=dict(ARGS), call_id="orphan-1",
        context_generation=gen, session_id=session_id,
    )
    history.append(
        session_id,
        {"record": "approval", "pending_id": pending_id, "call_id": "orphan-1",
         "name": "fluids_draft_mfl", "args": ARGS, "state": "pending", **_common(gen)},
    )
    api = TestClient(app)

    live = api.get(f"/api/chat/session/{session_id}").json()["records"]
    assert [r.get("actionable") for r in live if r.get("record") == "approval"][-1] is True

    monkeypatch.setattr(workspace, "context_generation", lambda: gen + 1)
    switched = api.get(f"/api/chat/session/{session_id}").json()["records"]
    assert not [r for r in switched if r.get("actionable")]


def test_m2b_resume_pending_without_a_terminal_record_is_answered_with_the_stored_result() -> None:
    stored = {"ok": True, "path": "synthetic.mfl"}
    session_id, _ = _seed(state="resume_pending", result=stored)

    assert chat._heal_orphan_tool_calls(session_id, history.read(session_id), "en") is True

    rows = _results(session_id, "orphan-1")
    assert len(rows) == 1 and rows[0]["result"] == stored


def test_m2c_uncertain_identity_error_with_no_tool_result_is_answered() -> None:
    stored = {"ok": True, "path": "synthetic.mfl"}
    session_id, _ = _seed(state="uncertain", result=stored)

    assert chat._heal_orphan_tool_calls(session_id, history.read(session_id), "en") is True

    rows = _results(session_id, "orphan-1")
    assert len(rows) == 1 and rows[0]["result"] == stored


# ---------------------------------------------------------------- M3


def _execute_with_failed_audit(
    monkeypatch: pytest.MonkeyPatch, session_id: str, gen: int
) -> str:
    pending_id = pending_approvals.register(
        action_kind="fluids_draft_mfl", args=dict(ARGS), call_id="orphan-1",
        context_generation=gen, session_id=session_id,
    )
    history.append(
        session_id,
        {"record": "approval", "pending_id": pending_id, "call_id": "orphan-1",
         "name": "fluids_draft_mfl", "args": ARGS, "state": "pending", **_common(gen)},
    )
    real_append = history.append

    def flaky(session: str, record: dict) -> None:
        if record.get("record") == "approval" and record.get("state") == "resume_pending":
            raise OSError("audit storage unavailable")
        real_append(session, record)

    with monkeypatch.context() as patch:
        patch.setattr(tools, "approval_payload", lambda _n, _a: {})
        patch.setattr(tools, "dispatch", lambda _n, _a: {"ok": True, "real": 1})
        patch.setattr(approval_execution.approvals, "mint", lambda *a, **k: {"token": "t"})
        patch.setattr(history, "append", flaky)
        body = approval_execution.execute(
            pending_id=pending_id, session_id=session_id, call_id="orphan-1", context_generation=gen
        )
    assert body["state"] == "resume_pending"
    return pending_id


def test_m3_failed_audit_then_heal_then_resume_leaves_one_real_tool_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id, gen = _seed()
    pending_id = _execute_with_failed_audit(monkeypatch, session_id, gen)

    # The action completed; the live terminal record owns the answer, so the heal stands down.
    assert chat._heal_orphan_tool_calls(session_id, history.read(session_id), "en") is False
    assert _results(session_id, "orphan-1") == []

    client = _Client()
    chat.set_client_builder(lambda _p, _m, _v: client)
    asyncio.run(
        approval_continuation.resume(
            pending_id=pending_id, session_id=session_id, call_id="orphan-1", context_generation=gen
        )
    )

    rows = _results(session_id, "orphan-1")
    assert len(rows) == 1
    assert rows[0]["result"]["real"] == 1


def test_m3_answer_rows_share_one_deterministic_record_id() -> None:
    session_id, _ = _seed(state="rejected")
    chat._heal_orphan_tool_calls(session_id, history.read(session_id), "en")
    approval_execution._answer_failed_call(
        session_id=session_id, pending_id=PENDING_ID, call_id="orphan-1",
        action_kind="fluids_draft_mfl", message="x",
    )
    rows = _results(session_id, "orphan-1")
    assert len(rows) == 1
    assert rows[0]["record_id"] == "tool_result:orphan-1"


def test_m3_resume_dedupes_by_call_id_not_only_by_pending_id(monkeypatch: pytest.MonkeyPatch) -> None:
    session_id, gen = _seed()
    pending_id = _execute_with_failed_audit(monkeypatch, session_id, gen)
    # A tool_result for the call already exists without any approval_pending_id on it.
    history.append(
        session_id,
        {"record": "event", "type": "tool_result", "name": "fluids_draft_mfl",
         "call_id": "orphan-1", "result": {"error": "legacy"}, **_common(gen)},
    )
    chat.set_client_builder(lambda _p, _m, _v: _Client())
    asyncio.run(
        approval_continuation.resume(
            pending_id=pending_id, session_id=session_id, call_id="orphan-1", context_generation=gen
        )
    )
    assert len(_results(session_id, "orphan-1")) == 1


# ---------------------------------------------------------------- M4


def _two_call_batch(tmp_path: Path) -> StreamResult:
    case = tmp_path / "case.genkey"
    case.write_text("CASE LABEL=c\nENDCASE\n", encoding="utf-8")
    return StreamResult(
        tool_calls=[
            ToolCall(name="run_execute", args={"source": str(case), "selection_id": "selection-1"}, call_id="first"),
            ToolCall(name="run_detect", args={}, call_id="sibling"),
        ]
    )


@pytest.mark.parametrize(
    ("locale", "needle"), [("en", "had to be approved first"), ("ko", "승인을 먼저")]
)
def test_m4_runtime_answers_calls_behind_the_approval_stop(
    tmp_path: Path, locale: str, needle: str
) -> None:
    client = _Client([_two_call_batch(tmp_path)])
    events = asyncio.run(_collect(runtime.run_turn(client, "go", locale=locale)))

    kinds = [e.type for e in events]
    assert kinds[-1] == "approval_required"
    answered = [e for e in events if e.type == "tool_result"]
    assert [e.data["call_id"] for e in answered] == ["sibling"]
    assert needle in json.dumps(answered[0].data["result"], ensure_ascii=False)


def test_m4_reject_after_a_batch_leaves_no_orphan_in_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(chat.tools, "approval_display", lambda _n, _a, locale="ko": {})
    session_id = history.new_session("batch")
    chat.set_client_builder(lambda _p, _m, _v: _Client([_two_call_batch(tmp_path)]))
    events = _run_turn(session_id, "go")
    approval = next(e for e in events if e.type == "approval_required")

    approval_execution.reject(
        pending_id=approval.data["pending_id"], session_id=session_id,
        call_id="first", context_generation=approval.data["context_generation"],
    )

    class _B:
        def create_conversation(self, model: str = ""):
            return OpenAIChatConversationBuilder()

    payload = chat_replay.rebuild_conversation(_B(), "m", history.read(session_id)).get_request_payload()
    calls = {c["id"] for m in payload if m.get("role") == "assistant" for c in m.get("tool_calls", [])}
    answered = {m["tool_call_id"] for m in payload if m.get("role") == "tool"}
    assert calls == {"first", "sibling"}
    assert calls <= answered


async def _collect(stream):
    return [event async for event in stream]


# ---------------------------------------------------------------- m1 / m8


def test_m1_minor_answer_requires_a_matching_dead_approval() -> None:
    session_id, gen = _seed()
    # Unknown pending id for this call: nothing is written.
    approval_execution.answer_unactionable_call(
        session_id=session_id, pending_id="q" * 32, call_id="orphan-1", message="x"
    )
    assert _results(session_id, "orphan-1") == []
    # A live (actionable) approval is never answered by this path.
    live = pending_approvals.register(
        action_kind="fluids_draft_mfl", args=dict(ARGS), call_id="orphan-1",
        context_generation=gen, session_id=session_id,
    )
    history.append(
        session_id,
        {"record": "approval", "pending_id": live, "call_id": "orphan-1",
         "name": "fluids_draft_mfl", "args": ARGS, "state": "pending", **_common(gen)},
    )
    approval_execution.answer_unactionable_call(
        session_id=session_id, pending_id=live, call_id="orphan-1", message="x"
    )
    assert _results(session_id, "orphan-1") == []
    # A matching pending id whose approval is gone is answered, once, with the stable id.
    pending_approvals.revoke_all()
    for _ in range(2):
        approval_execution.answer_unactionable_call(
            session_id=session_id, pending_id=live, call_id="orphan-1", message="x"
        )
    rows = _results(session_id, "orphan-1")
    assert len(rows) == 1 and rows[0]["record_id"] == "tool_result:orphan-1"


def test_m1_minor_answer_waits_for_the_session_lock() -> None:
    session_id, _ = _seed()
    entered = threading.Event()
    finished = threading.Event()

    def answer() -> None:
        entered.set()
        approval_execution.answer_unactionable_call(
            session_id=session_id, pending_id=PENDING_ID, call_id="orphan-1", message="x"
        )
        finished.set()

    with session_single_flight_sync(session_id):
        worker = threading.Thread(target=answer)
        worker.start()
        assert entered.wait(2)
        assert not finished.wait(0.3), "answered while another job held the session"
    worker.join(5)
    assert finished.is_set()


def test_m8_expiry_sentence_in_the_tool_result_follows_the_session_locale() -> None:
    korean = "승인 시간이 지났습니다. 다시 요청하세요."
    for locale in ("en", "ko"):
        session_id, _ = _seed(locale=locale)
        approval_execution.answer_unactionable_call(
            session_id=session_id, pending_id=PENDING_ID, call_id="orphan-1", message=korean
        )
        text = json.dumps(_results(session_id, "orphan-1")[0]["result"], ensure_ascii=False)
        if locale == "en":
            assert "expired" in text and korean not in text
        else:
            assert korean in text


# ---------------------------------------------------------------- m2


@pytest.mark.parametrize(
    ("raised", "expected"),
    [
        (workspace.WorkspaceError("path is outside the workspace"), "path is outside the workspace"),
        (genkey_static.OlgaInputError("bad olga input"), "bad olga input"),
        (workspace.StaleWorkspaceContextError("x"), runtime.STALE_CONTEXT_MESSAGE_EN),
    ],
)
def test_m2_precheck_maps_workspace_errors_like_the_click_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, raised: Exception, expected: str
) -> None:
    def boom(_name: str, _args: dict) -> dict:
        raise raised

    monkeypatch.setattr(runtime.tools, "approval_payload", boom)
    client = _Client([_two_call_batch(tmp_path), StreamResult(text="done")])
    events = asyncio.run(_collect(runtime.run_turn(client, "go", locale="en")))
    first = next(e for e in events if e.type == "tool_result" and e.data["call_id"] == "first")
    assert first.data["result"]["error"] == expected


def test_m2_precheck_payload_io_runs_off_the_event_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[bool] = []
    real = runtime.tools.approval_payload

    def probe(name: str, args: dict) -> dict:
        try:
            asyncio.get_running_loop()
            seen.append(True)
        except RuntimeError:
            seen.append(False)
        return real(name, args)

    monkeypatch.setattr(runtime.tools, "approval_payload", probe)
    client = _Client([_two_call_batch(tmp_path)])
    asyncio.run(_collect(runtime.run_turn(client, "go")))
    assert seen == [False], "approval_payload ran on the event loop thread"


# ---------------------------------------------------------------- m3


def test_m3_publish_precheck_oserror_never_leaks_a_path(monkeypatch: pytest.MonkeyPatch) -> None:
    from olga_companion.agent import case_publish_adapter as adapter

    secret_path = "C:/Users/someone/secret-folder/out.genkey"

    def explode(*_a: Any, **_k: Any) -> None:
        raise OSError(13, "Permission denied", secret_path)

    monkeypatch.setattr(adapter.case_publish, "assert_publishable_destination", explode)
    monkeypatch.setattr(adapter, "_reviewed", lambda args, loader: (_Binding(), object()))
    with pytest.raises(tools.ToolError) as caught:
        adapter.approval_payload({})
    assert secret_path not in str(caught.value)
    assert "secret-folder" not in str(caught.value)


class _Binding:
    context_generation = 0
    destination_rel = "out.genkey"


# ---------------------------------------------------------------- m6


def test_m6_cancelled_queued_acquire_does_not_hold_the_lock_forever() -> None:
    session_id = "c" * 16
    release = threading.Event()
    held = threading.Event()

    def hold() -> None:
        with session_single_flight_sync(session_id):
            held.set()
            release.wait(5)

    holder = threading.Thread(target=hold)
    holder.start()
    assert held.wait(2)

    async def go() -> bool:
        async def queued() -> None:
            async with session_single_flight(session_id):
                pass

        task = asyncio.create_task(queued())
        await asyncio.sleep(0.1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        release.set()
        holder.join(5)
        await asyncio.sleep(0.3)
        return session_busy(session_id)

    try:
        still_held = asyncio.run(go())
    finally:
        release.set()
        holder.join(5)
    assert not still_held, "a cancelled queued turn left the lock held"

    async def fresh() -> None:
        async with session_single_flight(session_id):
            pass

    asyncio.run(asyncio.wait_for(fresh(), 2))


# ---------------------------------------------------------------- m4 / m5


def test_m4_redactor_holds_back_a_bounded_tail_on_a_long_token_run() -> None:
    from olga_companion.agent.draft_stream import DraftRedactor

    redactor = DraftRedactor(runtime._SECRET_TEXT)
    for _ in range(3000):
        redactor.feed("a" * 10)
    assert len(redactor._carry) <= 256


def test_m5_cancelled_provider_unwinds_before_the_generator_closes() -> None:
    from olga_companion.agent.draft_stream import drafting_generation

    unwound = threading.Event()
    problems: list[dict] = []

    class Slow:
        async def stream_generate(self, *, on_token, **kwargs):
            await on_token("hello ")
            try:
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                await asyncio.sleep(0.05)
                unwound.set()
                raise RuntimeError("closing the stream failed")

    async def go() -> None:
        asyncio.get_running_loop().set_exception_handler(lambda _l, ctx: problems.append(ctx))
        stream = drafting_generation(Slow(), {}, runtime._SECRET_TEXT)
        assert await stream.__anext__() == "hello "
        await stream.aclose()
        assert unwound.is_set(), "aclose returned before the provider task unwound"
        import gc

        gc.collect()
        await asyncio.sleep(0)

    asyncio.run(go())
    assert not problems, problems


# ------------------------------------------- a message typed while an approval waits


def _provider_order_ok(messages: list[dict]) -> bool:
    """OpenAI Chat rule: assistant tool_calls are answered right away, each id once."""
    index = 0
    while index < len(messages):
        message = messages[index]
        if message["role"] == "tool":
            return False
        index += 1
        if message["role"] == "assistant" and message.get("tool_calls"):
            ids = [call["id"] for call in message["tool_calls"]]
            answered = []
            while index < len(messages) and messages[index]["role"] == "tool":
                answered.append(messages[index]["tool_call_id"])
                index += 1
            if answered != ids:
                return False
    return True


def test_typing_while_an_approval_waits_then_approving_keeps_the_provider_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id, gen = _seed(approval_call=None)
    pending_id = pending_approvals.register(
        action_kind="fluids_draft_mfl", args=dict(ARGS), call_id="orphan-1",
        context_generation=gen, session_id=session_id,
    )
    history.append(
        session_id,
        {"record": "approval", "pending_id": pending_id, "call_id": "orphan-1",
         "name": "fluids_draft_mfl", "args": ARGS, "state": "pending", **_common(gen)},
    )
    client = _Client([StreamResult(text="It is waiting for your approval."), StreamResult(text="Done.")])
    chat.set_client_builder(lambda _p, _m, _v: client)

    _run_turn(session_id, "Run it now please.")

    assert client.payloads and _provider_order_ok(client.payloads[0]), client.payloads[0]
    waiting = json.loads(next(m for m in client.payloads[0] if m["role"] == "tool")["content"])
    assert waiting["state"] == "awaiting_approval"

    monkeypatch.setattr(tools, "approval_payload", lambda _n, _a: {})
    monkeypatch.setattr(tools, "dispatch", lambda _n, _a: {"ok": True, "real": 1})
    monkeypatch.setattr(approval_execution.approvals, "mint", lambda *a, **k: {"token": "t"})
    approval_execution.execute(
        pending_id=pending_id, session_id=session_id, call_id="orphan-1", context_generation=gen
    )
    asyncio.run(
        approval_continuation.resume(
            pending_id=pending_id, session_id=session_id, call_id="orphan-1", context_generation=gen
        )
    )

    last = client.payloads[-1]
    assert len(client.payloads) == 2 and _provider_order_ok(last), last
    tool_rows = [m for m in last if m["role"] == "tool"]
    assert [json.loads(m["content"]).get("real") for m in tool_rows] == [1]
    assert len(_results(session_id, "orphan-1")) == 1
    # The typed question was answered in between, so the continuation must not end on that
    # assistant reply: providers without prefill refuse it ("must end with a user message").
    assert last[-1]["role"] == "user" and "approved" in last[-1]["content"], last[-1]
