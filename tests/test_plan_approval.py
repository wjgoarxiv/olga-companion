"""One approval card for a bounded, re-validated sequence of steps (plan todo 6).

Offline: every provider is scripted; case publication and the run are faked at the
tool seam, while the fluid draft writes a real new file in a temp workspace.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from olga_companion import fluid_table, workspace
from olga_companion.agent import (
    approval_continuation,
    approval_display,
    approval_execution,
    approvals,
    case_publish_adapter,
    chat,
    history,
    pending_approvals,
    plan_execution,
    plan_model,
    plan_progress,
    runtime,
    session_token,
    tools,
)
from olga_companion.agent.tool_validation import ToolError
from olga_companion.llm.protocol import StreamResult, ToolCall

DRAFT: dict[str, Any] = {
    "fluid_label": "SYN1",
    "components": [{"name": "METHANE", "mole_fraction": 1.0}],
    "model": "SRK",
    "temperatures": [-10.0, 50.0],
    "temperature_unit": "degC",
    "pressures": [0.0, 5.0],
    "pressure_unit": "barg",
    "mfl_rel": "synthetic.mfl",
}
PUBLISH: dict[str, Any] = {
    "transaction_id": "t" * 24,
    "source_hash": "a" * 64,
    "compiled_hash": "b" * 64,
    "destination_rel": "cases/new.genkey",
    "context_generation": 0,
}
PLAN_STEPS: list[dict[str, Any]] = [
    {"kind": "fluids_draft_mfl", "args": DRAFT},
    {"kind": "case_publish", "args": PUBLISH},
    {"kind": "run_execute", "args": {"timeout_s": 600}, "source_from_step": 2},
]


@pytest.fixture(autouse=True)
def _plan_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setattr(
        fluid_table, "databank_names", lambda *a, **k: {"METHANE": "METHANE"}
    )
    session_token.boot_token()
    pending_approvals.revoke_all()
    yield
    pending_approvals.revoke_all()
    chat.set_client_builder(None)


@pytest.fixture
def gen() -> int:
    return workspace.context_generation()


def _steps(*overrides: dict[str, Any]) -> list[dict[str, Any]]:
    return json.loads(json.dumps(list(overrides) or PLAN_STEPS))


def _publish(gen: int) -> dict[str, Any]:
    return {**PUBLISH, "context_generation": gen}


class Seam:
    """Fakes publish/run/preview; the fluid draft stays real and writes a new file."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, root: Path) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.hooks: dict[str, Any] = {}
        self.validation_valid = True
        self.root = root
        self.real_dispatch = tools.dispatch
        self.real_payload = tools.approval_payload
        self.inputs = [
            {"group": "Boundary", "name": "SOURCE Pressure", "value": "2000000", "unit": "Pa"}
        ]
        self.display_locales: list[str] = []
        monkeypatch.setattr(approval_display, "_case_publish_display", self._publish_display)
        monkeypatch.setattr(
            case_publish_adapter,
            "approval_payload",
            lambda args, **_k: {
                key: args[key]
                for key in (
                    "transaction_id", "source_hash", "compiled_hash",
                    "destination_rel", "context_generation",
                )
            },
        )
        monkeypatch.setattr(tools, "dispatch", self.dispatch)

    def _publish_display(self, _args: dict[str, Any], locale: str = "ko") -> dict[str, Any]:
        self.display_locales.append(locale)
        return {"inputs": self.inputs}

    def dispatch(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((name, dict(args)))
        hook = self.hooks.get(name)
        if hook is not None:
            return hook(args)
        if name == "run_preview":
            return {
                "source": str(self.root / args["source"]),
                "selection_id": "sel-1",
                "validation": {"valid": self.validation_valid},
                "timeout_s": args.get("timeout_s", 3600),
            }
        if name in {"case_publish", "run_execute"}:
            approvals.consume(
                args["approval_token"], name, self.real_payload(name, args),
                context_generation=workspace.context_generation(),
            )
            if name == "case_publish":
                target = self.root / args["destination_rel"]
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("CASE LABEL=demo\nENDCASE\n", encoding="utf-8")
                return {
                    "state": "published",
                    "destination_rel": args["destination_rel"],
                    "published_hash": hashlib.sha256(target.read_bytes()).hexdigest(),
                }
            return {"run_id": "run0001", "state": "running"}
        return self.real_dispatch(name, args)

    def names(self) -> list[str]:
        return [name for name, _ in self.calls]


@pytest.fixture
def seam(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Seam:
    return Seam(monkeypatch, tmp_path)


def _register(steps: list[dict[str, Any]], gen: int, *, call_id: str = "plan-1") -> tuple[str, str]:
    session_id = history.new_session("plan")
    pending_id = pending_approvals.register(
        action_kind="action_plan",
        args={"steps": steps},
        call_id=call_id,
        context_generation=gen,
        session_id=session_id,
    )
    return session_id, pending_id


def _plan_steps(gen: int) -> list[dict[str, Any]]:
    steps = _steps()
    steps[1]["args"] = _publish(gen)
    return steps


def _execute(session_id: str, pending_id: str, gen: int, call_id: str = "plan-1") -> dict[str, Any]:
    return approval_execution.execute(
        pending_id=pending_id, session_id=session_id, call_id=call_id, context_generation=gen
    )


def _states(body: dict[str, Any]) -> list[str]:
    return [step["state"] for step in body["result"]["steps"]]


# ------------------------------------------------------------------ precheck


def test_plan_is_a_side_effect_tool_with_a_bounded_closed_schema() -> None:
    tool = tools.TOOLS["action_plan"]
    assert tool.side_effect is True
    steps = tool.parameters["properties"]["steps"]
    assert steps["maxItems"] == plan_model.MAX_STEPS
    assert steps["minItems"] == 1
    assert tool.parameters["additionalProperties"] is False
    names = {spec["name"] for spec in tools.tool_specs()}
    assert "action_plan" in names


@pytest.mark.parametrize(
    "kind", ["run_cancel", "sweep_cancel", "sweep_execute", "genkey_save", "multiflash_open"]
)
def test_plan_refuses_actions_that_never_join_a_plan(kind: str, gen: int) -> None:
    steps = _plan_steps(gen) + [{"kind": kind, "args": {"run_id": "r1"}}]
    with pytest.raises(ToolError, match=kind):
        tools.approval_payload("action_plan", {"steps": steps})


def test_plan_refuses_empty_and_oversized_lists(gen: int) -> None:
    with pytest.raises(ToolError):
        tools.approval_payload("action_plan", {"steps": []})
    too_many = [{"kind": "fluids_draft_mfl", "args": DRAFT}] * (plan_model.MAX_STEPS + 1)
    with pytest.raises(ToolError, match="at most"):
        tools.approval_payload("action_plan", {"steps": too_many})


def test_plan_refuses_a_capability_inside_a_step(gen: int) -> None:
    steps = _steps({"kind": "fluids_draft_mfl", "args": {**DRAFT, "approval_token": "x"}})
    with pytest.raises(ToolError, match="capability"):
        tools.approval_payload("action_plan", {"steps": steps})


@pytest.mark.parametrize(
    "bad",
    [
        {"kind": "run_execute", "args": {"timeout_s": 60}, "source_from_step": 3},
        {"kind": "run_execute", "args": {"timeout_s": 60}, "source_from_step": 1},
        {"kind": "run_execute", "args": {"timeout_s": 60, "selection_id": "s"}, "source_from_step": 2},
        {"kind": "case_publish", "args": {}, "source_from_step": 1},
    ],
)
def test_plan_rule_binding_must_point_at_an_earlier_publish(bad: dict[str, Any], gen: int) -> None:
    steps = [
        {"kind": "fluids_draft_mfl", "args": DRAFT},
        {"kind": "case_publish", "args": _publish(gen)},
        bad,
    ]
    if bad.get("source_from_step") == 3:
        steps = steps[:2] + [bad]
    with pytest.raises(ToolError):
        tools.approval_payload("action_plan", {"steps": steps})


def test_plan_precheck_pins_exact_steps_and_leaves_bound_steps_open(
    seam: Seam, gen: int
) -> None:
    payload = tools.approval_payload("action_plan", {"steps": _plan_steps(gen)})
    kinds = [step["kind"] for step in payload["steps"]]
    assert kinds == ["fluids_draft_mfl", "case_publish", "run_execute"]
    assert payload["steps"][0]["payload"]["mfl_rel"] == "synthetic.mfl"
    assert payload["steps"][2]["payload"] is None
    assert payload["steps"][2]["bind"] == {"source_from_step": 2}


def test_plan_placeholder_for_the_future_table_tool_is_refused_until_it_exists(gen: int) -> None:
    steps = [{"kind": "fluids_generate_tab", "args": {}}]
    with pytest.raises(ToolError, match="not available"):
        tools.approval_payload("action_plan", {"steps": steps})


# -------------------------------------------------------------------- digest


def test_plan_digest_binds_ordered_steps_session_generation_and_call(gen: int) -> None:
    steps = _plan_steps(gen)
    base = plan_model.digest({"steps": steps}, "s1", gen, "c1")
    assert base == plan_model.digest({"steps": json.loads(json.dumps(steps))}, "s1", gen, "c1")
    assert base != plan_model.digest({"steps": steps[:2]}, "s1", gen, "c1"), "dropped step"
    assert base != plan_model.digest({"steps": steps[::-1]}, "s1", gen, "c1"), "reordered"
    extra = steps + [{"kind": "fluids_draft_mfl", "args": DRAFT}]
    assert base != plan_model.digest({"steps": extra}, "s1", gen, "c1"), "appended"
    changed = _plan_steps(gen)
    changed[0]["args"]["fluid_label"] = "OTHER"
    assert base != plan_model.digest({"steps": changed}, "s1", gen, "c1"), "changed field"
    assert base != plan_model.digest({"steps": steps}, "s2", gen, "c1"), "session"
    assert base != plan_model.digest({"steps": steps}, "s1", gen + 1, "c1"), "generation"
    assert base != plan_model.digest({"steps": steps}, "s1", gen, "c2"), "call id"


def test_plan_digest_mismatch_runs_nothing(seam: Seam, gen: int) -> None:
    session_id, pending_id = _register(_plan_steps(gen), gen)
    stored = pending_approvals._PENDING[pending_id][1]
    stored.args["steps"].append({"kind": "fluids_draft_mfl", "args": DRAFT})

    body = _execute(session_id, pending_id, gen)

    assert _states(body) == ["not_run"] * 4
    assert body["result"]["ok"] is False
    assert "changed" in body["result"]["error"]
    assert seam.calls == [], "no step was prepared or dispatched"


# ---------------------------------------------------------------- happy path


def test_plan_runs_each_step_once_with_its_own_token_and_key(seam: Seam, gen: int, tmp_path: Path) -> None:
    session_id, pending_id = _register(_plan_steps(gen), gen)

    body = _execute(session_id, pending_id, gen)

    assert body["state"] == "resume_pending"
    assert _states(body) == ["done", "done", "done"]
    assert body["result"]["ok"] is True
    assert (tmp_path / "synthetic.mfl").exists()
    dispatched = [(n, a) for n, a in seam.calls if n != "run_preview"]
    assert [n for n, _ in dispatched] == ["fluids_draft_mfl", "case_publish", "run_execute"]
    tokens = [a["approval_token"] for _, a in dispatched]
    keys = [a["idempotency_key"] for _, a in dispatched]
    assert len(set(tokens)) == 3 and len(set(keys)) == 3
    assert all(len(key) == 32 for key in keys)
    with pytest.raises(approvals.ApprovalError):
        approvals.consume(tokens[0], "fluids_draft_mfl", seam.real_payload("fluids_draft_mfl", DRAFT))


def test_plan_replays_its_terminal_result_without_running_again(seam: Seam, gen: int) -> None:
    session_id, pending_id = _register(_plan_steps(gen), gen)
    first = _execute(session_id, pending_id, gen)
    count = len(seam.calls)

    second = _execute(session_id, pending_id, gen)

    assert second["result"] == first["result"]
    assert len(seam.calls) == count


def test_each_step_is_revalidated_at_its_own_turn(
    seam: Seam, gen: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    session_id, pending_id = _register(_plan_steps(gen), gen)
    original = seam.real_payload

    def drifting(kind: str, args: dict[str, Any]) -> dict[str, Any]:
        if kind == "case_publish":
            raise ToolError("stale_source: the source changed after review")
        return original(kind, args)

    monkeypatch.setattr(tools, "approval_payload", drifting)
    body = _execute(session_id, pending_id, gen)

    assert _states(body) == ["done", "failed", "not_run"]
    assert body["result"]["stopped_at"] == 2
    assert "case_publish" not in seam.names()


def test_plan_stops_on_the_first_failure_and_marks_the_rest_not_run(seam: Seam, gen: int) -> None:
    def refuse(_args: dict[str, Any]) -> dict[str, Any]:
        raise tools.ToolPreDispatchError("The destination is not available.")

    seam.hooks["case_publish"] = refuse
    session_id, pending_id = _register(_plan_steps(gen), gen)

    body = _execute(session_id, pending_id, gen)

    assert body["state"] == "resume_pending"
    assert _states(body) == ["done", "failed", "not_run"]
    steps = body["result"]["steps"]
    assert steps[1]["error"] == "The destination is not available."
    assert "run_execute" not in seam.names()


def test_a_draft_destination_that_appears_mid_plan_fails_the_step(
    seam: Seam, gen: int, tmp_path: Path
) -> None:
    session_id, pending_id = _register(_plan_steps(gen), gen)
    target = tmp_path / "synthetic.mfl"
    target.write_text("owner file\n", encoding="utf-8")

    body = _execute(session_id, pending_id, gen)

    assert _states(body) == ["failed", "not_run", "not_run"]
    assert target.read_text(encoding="utf-8") == "owner file\n", "no overwrite"
    assert "already exists" in body["result"]["steps"][0]["error"]


def test_a_publish_destination_collision_stops_the_chain(seam: Seam, gen: int) -> None:
    def collide(_args: dict[str, Any]) -> dict[str, Any]:
        raise tools.ToolError("destination_collision: exists")

    seam.hooks["case_publish"] = collide
    session_id, pending_id = _register(_plan_steps(gen), gen)

    body = _execute(session_id, pending_id, gen)

    assert body["state"] == "resume_pending", "a known refusal never ran, so it is not uncertain"
    assert _states(body) == ["done", "failed", "not_run"]


# ------------------------------------------------------------------- run step


def test_the_run_step_reruns_preview_on_the_published_case(seam: Seam, gen: int) -> None:
    session_id, pending_id = _register(_plan_steps(gen), gen)

    _execute(session_id, pending_id, gen)

    preview = [a for n, a in seam.calls if n == "run_preview"]
    assert preview == [{"source": "cases/new.genkey", "timeout_s": 600}]
    run = [a for n, a in seam.calls if n == "run_execute"][0]
    assert run["source"] == "cases/new.genkey"
    assert run["selection_id"] == "sel-1"
    assert seam.names().index("run_preview") > seam.names().index("case_publish")


def test_the_run_step_refuses_a_case_that_does_not_validate_cleanly(seam: Seam, gen: int) -> None:
    seam.validation_valid = False
    session_id, pending_id = _register(_plan_steps(gen), gen)

    body = _execute(session_id, pending_id, gen)

    assert _states(body) == ["done", "done", "failed"]
    assert "validate" in body["result"]["steps"][2]["error"]
    assert "run_execute" not in seam.names(), "nothing was started"
    assert body["state"] == "resume_pending"


def test_the_run_step_refuses_when_the_selection_changed(seam: Seam, gen: int) -> None:
    def changed(_args: dict[str, Any]) -> dict[str, Any]:
        # The real run_execute raises this typed refusal for a pre-launch OlgaInputError.
        raise tools.ToolRefusedError("OLGA runtime selection changed after preview; review again.")

    seam.hooks["run_execute"] = changed
    session_id, pending_id = _register(_plan_steps(gen), gen)

    body = _execute(session_id, pending_id, gen)

    assert _states(body) == ["done", "done", "failed"]
    assert body["state"] == "resume_pending"


def test_a_plan_with_an_exact_run_step_keeps_its_own_selection(seam: Seam, gen: int, tmp_path: Path) -> None:
    case = tmp_path / "old.genkey"
    case.write_text("CASE LABEL=old\nENDCASE\n", encoding="utf-8")
    steps = _steps({"kind": "run_execute", "args": {"source": "old.genkey", "selection_id": "sel-9", "timeout_s": 60}})
    session_id, pending_id = _register(steps, gen)

    body = _execute(session_id, pending_id, gen)

    assert _states(body) == ["done"]
    assert "run_preview" not in seam.names(), "an exact step is not re-previewed"


# --------------------------------------------------------------------- lifetime


def test_plan_ttl_is_separate_from_the_step_token_ttl(seam: Seam, gen: int) -> None:
    import time

    assert plan_model.PLAN_TTL_SECONDS > approvals.TTL_SECONDS
    session_id, pending_id = _register(_plan_steps(gen), gen)
    remaining = pending_approvals.registered_expires_epoch(pending_id) - time.time()
    assert remaining > approvals.TTL_SECONDS + 600
    other = pending_approvals.register(
        action_kind="fluids_draft_mfl", args=DRAFT, call_id="solo-1",
        context_generation=gen, session_id=session_id,
    )
    solo = pending_approvals.registered_expires_epoch(other) - time.time()
    assert solo <= approvals.TTL_SECONDS + 5

    _execute(session_id, pending_id, gen)
    minted = [a["approval_token"] for n, a in seam.calls if n == "fluids_draft_mfl"]
    assert len(minted) == 1


def test_plan_expiry_denies_remaining_steps_without_renewal(
    seam: Seam, gen: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    import time

    session_id, pending_id = _register(_plan_steps(gen), gen)
    start = time.time()
    clock = {"now": start}
    monkeypatch.setattr(plan_execution, "_now", lambda: clock["now"])
    after_first = seam.hooks.setdefault("case_publish", None)
    assert after_first is None

    def late(_args: dict[str, Any]) -> dict[str, Any]:
        clock["now"] = start + plan_model.PLAN_TTL_SECONDS + 5
        return {"state": "published", "destination_rel": "cases/new.genkey"}

    seam.hooks["fluids_draft_mfl"] = lambda _a: late(_a) and {"ok": True}

    body = _execute(session_id, pending_id, gen)

    assert _states(body) == ["done", "not_run", "not_run"]
    assert "expired" in body["result"]["error"]
    assert "case_publish" not in seam.names()


# ---------------------------------------------------------------- after approval


def test_a_continuation_turn_gets_its_own_card_instead_of_a_plan_step(
    seam: Seam, gen: int
) -> None:
    session_id, pending_id = _register(_plan_steps(gen), gen)
    _execute(session_id, pending_id, gen)
    before = plan_progress.load(pending_id)

    class Client:
        def create_conversation(self, model: str = ""):
            class Conversation:
                def add_user_message(self, *a, **k): ...
                def add_assistant_response(self, *a, **k): ...
                def add_tool_result(self, *a, **k): ...

            return Conversation()

        async def stream_generate(self, **_kwargs):
            return StreamResult(
                tool_calls=[ToolCall(name="case_publish", args=_publish(gen), call_id="extra-1")]
            )

    async def collect():
        return [
            event
            async for event in runtime.run_turn(
                Client(), "", model="m", conversation=Client().create_conversation(),
                seed_user=False, context_generation=gen, fill_active_case=False,
            )
        ]

    events = asyncio.run(collect())
    approval = [e for e in events if e.type == "approval_required"]
    assert [e.data["name"] for e in approval] == ["case_publish"]
    assert plan_progress.load(pending_id) == before, "the closed plan gained nothing"
    assert [n for n, _ in seam.calls].count("case_publish") == 1


def test_runtime_stops_at_a_plan_and_answers_calls_batched_behind_it(gen: int) -> None:
    class Client:
        def create_conversation(self, model: str = ""):
            class Conversation:
                def __init__(self) -> None:
                    self.results: list[str] = []

                def add_user_message(self, *a, **k): ...
                def add_assistant_response(self, *a, **k): ...
                def add_tool_result(self, call_id, name, result):
                    self.results.append(call_id)

            return Conversation()

        async def stream_generate(self, **_kwargs):
            return StreamResult(
                tool_calls=[
                    ToolCall(name="action_plan", args={"steps": _steps({"kind": "fluids_draft_mfl", "args": DRAFT})}, call_id="plan-1"),
                    ToolCall(name="run_status", args={"run_id": "r1"}, call_id="after-1"),
                ]
            )

    client = Client()
    conversation = client.create_conversation()

    async def collect():
        return [
            event
            async for event in runtime.run_turn(
                client, "go", model="m", conversation=conversation,
                context_generation=gen,
            )
        ]

    events = asyncio.run(collect())

    assert events[-1].type == "approval_required"
    assert events[-1].data["name"] == "action_plan"
    answered = [e.data["call_id"] for e in events if e.type == "tool_result"]
    assert answered == ["after-1"]
    assert conversation.results == ["after-1"]


def test_an_invalid_plan_is_answered_without_a_card(gen: int) -> None:
    class Client:
        def create_conversation(self, model: str = ""):
            class Conversation:
                def add_user_message(self, *a, **k): ...
                def add_assistant_response(self, *a, **k): ...
                def add_tool_result(self, *a, **k): ...

            return Conversation()

        async def stream_generate(self, **_kwargs):
            return StreamResult(
                tool_calls=[ToolCall(name="action_plan", args={"steps": [{"kind": "run_cancel", "args": {"run_id": "r"}}]}, call_id="plan-1")]
            ) if not getattr(self, "done", False) else StreamResult(text="ok")

    client = Client()
    conversation = client.create_conversation()

    async def collect():
        out = []
        async for event in runtime.run_turn(
            client, "go", model="m", conversation=conversation, context_generation=gen,
            max_iterations=1,
        ):
            out.append(event)
        return out

    events = asyncio.run(collect())

    assert not [e for e in events if e.type == "approval_required"]
    result = [e for e in events if e.type == "tool_result"]
    assert result and "run_cancel" in result[0].data["result"]["error"]


# ------------------------------------------------------------------------ crash


class Crash(BaseException):
    """A process death: nothing in the app may catch it."""


def _simulate_restart() -> None:
    with pending_approvals._LOCK:
        pending_approvals._PENDING.clear()
        pending_approvals._IN_FLIGHT.clear()
        pending_approvals._TERMINAL.clear()
        pending_approvals._EXPIRES_EPOCH.clear()
    pending_approvals._restore()


def test_crash_after_step_k_restores_uncertain_k_and_unrun_rest(seam: Seam, gen: int) -> None:
    def die(_args: dict[str, Any]) -> dict[str, Any]:
        raise Crash

    seam.hooks["case_publish"] = die
    session_id, pending_id = _register(_plan_steps(gen), gen)
    with pytest.raises(Crash):
        _execute(session_id, pending_id, gen)

    _simulate_restart()

    report = plan_progress.report(pending_id)
    assert [step["state"] for step in report] == ["done", "uncertain", "not_run"]
    with pytest.raises(approval_execution.ApprovalDispatchUncertainError) as raised:
        _execute(session_id, pending_id, gen)
    assert [s["state"] for s in raised.value.response()["steps"]] == ["done", "uncertain", "not_run"]
    answers = [
        r for r in history.read(session_id)
        if r.get("type") == "tool_result" and r.get("call_id") == "plan-1"
    ]
    assert len(answers) == 1
    assert answers[0]["record_id"] == "tool_result:plan-1"
    assert [s["state"] for s in answers[0]["result"]["steps"]] == ["done", "uncertain", "not_run"]
    assert seam.names().count("case_publish") == 1, "never dispatched again after restart"


def test_an_uncertain_step_seals_the_plan_and_is_not_resumed(seam: Seam, gen: int) -> None:
    def broken(_args: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("socket closed after the write started")

    seam.hooks["case_publish"] = broken
    session_id, pending_id = _register(_plan_steps(gen), gen)

    with pytest.raises(approval_execution.ApprovalDispatchUncertainError) as raised:
        _execute(session_id, pending_id, gen)

    response = raised.value.response()
    assert response["resume_allowed"] is False
    assert [s["state"] for s in response["steps"]] == ["done", "uncertain", "not_run"]
    assert "run_execute" not in seam.names()


# --------------------------------------------------------------------- replay


def _seed_plan_history(state: str, *, result: dict[str, Any] | None = None) -> tuple[str, str]:
    session_id = history.new_session("plan")
    generation = workspace.context_generation()
    common = {"workspace_generation": generation, "provider": "openai", "model": "m", "locale": "en"}
    steps = _steps({"kind": "fluids_draft_mfl", "args": DRAFT})
    pending_id = pending_approvals.register(
        action_kind="action_plan", args={"steps": steps}, call_id="plan-1",
        context_generation=generation, session_id=session_id,
    )
    history.append(session_id, {"record": "user", "text": "go", **common})
    history.append(
        session_id,
        {"record": "assistant", "text": "", "tool_calls": [
            {"name": "action_plan", "args": {"steps": steps}, "call_id": "plan-1", "raw_arguments": "{}", "item_id": ""}
        ], **common},
    )
    record = {"record": "approval", "pending_id": pending_id, "call_id": "plan-1",
              "name": "action_plan", "args": {"steps": steps}, "state": state, **common}
    if result is not None:
        record["result"] = result
    history.append(session_id, record)
    return session_id, pending_id


def _answers(session_id: str) -> list[dict[str, Any]]:
    return [
        r for r in history.read(session_id)
        if r.get("record") == "event" and r.get("type") == "tool_result" and r.get("call_id") == "plan-1"
    ]


@pytest.mark.parametrize("state", ["rejected", "uncertain", "failed"])
def test_the_heal_answers_a_plan_call_once_in_every_dead_state(state: str) -> None:
    session_id, _ = _seed_plan_history(state, result={"error": "stopped"})

    assert chat._heal_orphan_tool_calls(session_id, history.read(session_id), "en") is True
    assert chat._heal_orphan_tool_calls(session_id, history.read(session_id), "en") is False

    rows = _answers(session_id)
    assert len(rows) == 1 and rows[0]["record_id"] == "tool_result:plan-1"


def test_the_heal_answers_an_expired_plan_and_leaves_a_live_one(gen: int) -> None:
    live, _ = _seed_plan_history("pending")
    assert chat._heal_orphan_tool_calls(live, history.read(live), "en", generation=gen) is False

    expired, pending_id = _seed_plan_history("pending")
    pending_approvals.revoke_all()
    assert chat._heal_orphan_tool_calls(expired, history.read(expired), "en", generation=gen) is True
    assert len(_answers(expired)) == 1


def test_a_stopped_plan_result_carries_every_step_to_the_model(seam: Seam, gen: int) -> None:
    def refuse(_args: dict[str, Any]) -> dict[str, Any]:
        raise tools.ToolPreDispatchError("The destination is not available.")

    seam.hooks["case_publish"] = refuse
    session_id, pending_id = _register(_plan_steps(gen), gen)

    body = _execute(session_id, pending_id, gen)

    rows = body["result"]["steps"]
    assert [row["index"] for row in rows] == [1, 2, 3]
    assert [row["kind"] for row in rows] == ["fluids_draft_mfl", "case_publish", "run_execute"]
    assert rows[2]["state"] == "not_run"


# ---------------------------------------------------------------------- display


def test_plan_display_lists_one_row_per_step_with_what_is_not_known_yet(seam: Seam, gen: int) -> None:
    display = approval_display.build("action_plan", {"steps": _plan_steps(gen)})
    steps = display["plan"]["steps"]
    assert [s["index"] for s in steps] == [1, 2, 3]
    assert [s["kind"] for s in steps] == ["fluids_draft_mfl", "case_publish", "run_execute"]
    assert {"key": "file", "value": "synthetic.mfl"} in steps[0]["fields"]
    assert {"key": "file", "value": "cases/new.genkey"} in steps[1]["fields"]
    assert steps[2]["bound_to"] == 2
    assert steps[2]["unknown"] == ["run_case", "runtime", "executable", "output"]
    assert {"key": "timeout", "value": "600", "unit": "s"} in steps[2]["fields"]
    assert "approval_token" not in json.dumps(display)


# ------------------------------------------------------------------------ prompt


def test_the_prompt_explains_the_plan_tool_and_its_limits() -> None:
    prompt = runtime.SYSTEM_PROMPT
    assert "action_plan" in prompt
    assert "one card" in prompt
    for forbidden in ("run_cancel", "sweep_execute", "genkey_save"):
        assert forbidden in prompt.split("action_plan", 1)[1][:1200]


# ------------------------------------------------------------------- over HTTP


def _sse(text: str) -> list[tuple[str, dict[str, Any]]]:
    events: list[tuple[str, dict[str, Any]]] = []
    for block in text.strip().split("\n\n"):
        name, data = "", {}
        for line in block.splitlines():
            if line.startswith("event: "):
                name = line.removeprefix("event: ")
            elif line.startswith("data: "):
                data = json.loads(line.removeprefix("data: "))
        if name:
            events.append((name, data))
    return events


class _OneShotClient:
    def __init__(self, result: StreamResult) -> None:
        self._result = result

    def create_conversation(self, model: str = ""):
        class Conversation:
            def add_user_message(self, *a, **k): ...
            def add_assistant_response(self, *a, **k): ...
            def add_tool_result(self, *a, **k): ...

        return Conversation()

    async def stream_generate(self, **_kwargs):
        return self._result


def test_a_chat_turn_raises_one_plan_card_and_one_click_runs_the_sequence(
    seam: Seam, gen: int
) -> None:
    from fastapi.testclient import TestClient

    from olga_companion import sidecar

    headers = {"X-Session-Token": session_token.boot_token()}
    chat.set_client_builder(
        lambda *_a: _OneShotClient(
            StreamResult(
                tool_calls=[
                    ToolCall(name="action_plan", args={"steps": _plan_steps(gen)}, call_id="plan-http")
                ]
            )
        )
    )
    api = TestClient(sidecar.app)
    session_id = api.post("/api/chat/session", json={"title": ""}, headers=headers).json()["session_id"]

    streamed = api.post(
        "/api/chat", json={"session_id": session_id, "message": "set it all up"}, headers=headers
    )
    cards = [data for name, data in _sse(streamed.text) if name == "approval_required"]
    assert len(cards) == 1
    card = cards[0]
    assert card["name"] == "action_plan"
    assert [row["kind"] for row in card["display"]["plan"]["steps"]] == [
        "fluids_draft_mfl", "case_publish", "run_execute",
    ]
    assert "approval_token" not in json.dumps(card)
    expires = card["expires_at"]
    import time

    assert expires - time.time() > approvals.TTL_SECONDS + 600

    clicked = api.post(
        "/api/approvals/execute",
        json={
            "pending_id": card["pending_id"], "session_id": session_id,
            "call_id": "plan-http", "context_generation": gen,
        },
        headers=headers,
    )

    assert clicked.status_code == 200, clicked.text
    assert [s["state"] for s in clicked.json()["result"]["steps"]] == ["done", "done", "done"]
    assert seam.names().count("run_execute") == 1


def test_an_uncertain_plan_answers_409_with_its_step_states(seam: Seam, gen: int) -> None:
    from fastapi.testclient import TestClient

    from olga_companion import sidecar

    def broken(_args: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("write started, then the connection dropped")

    seam.hooks["case_publish"] = broken
    session_id, pending_id = _register(_plan_steps(gen), gen)
    api = TestClient(sidecar.app)
    headers = {"X-Session-Token": session_token.boot_token()}
    body = {
        "pending_id": pending_id, "session_id": session_id,
        "call_id": "plan-1", "context_generation": gen,
    }

    first = api.post("/api/approvals/execute", json=body, headers=headers)
    second = api.post("/api/approvals/execute", json=body, headers=headers)

    for response in (first, second):
        assert response.status_code == 409
        assert response.json()["resume_allowed"] is False
        assert [s["state"] for s in response.json()["steps"]] == ["done", "uncertain", "not_run"]
    assert seam.names().count("case_publish") == 1


def test_a_pending_plan_survives_a_restart_with_its_full_lifetime(seam: Seam, gen: int) -> None:
    import time

    session_id, pending_id = _register(_plan_steps(gen), gen)
    _simulate_restart()

    assert pending_approvals.is_actionable(
        pending_id, session_id=session_id, call_id="plan-1", context_generation=gen
    )
    assert pending_approvals.registered_expires_epoch(pending_id) - time.time() > approvals.TTL_SECONDS + 600
    body = _execute(session_id, pending_id, gen)
    assert _states(body) == ["done", "done", "done"]


def test_the_continuation_answers_the_plan_call_once_with_every_step(seam: Seam, gen: int) -> None:
    session_id, pending_id = _seed_plan_history("pending")
    approval_execution.execute(
        pending_id=pending_id, session_id=session_id, call_id="plan-1", context_generation=gen
    )
    chat.set_client_builder(lambda *_a: _OneShotClient(StreamResult(text="All steps are done.")))

    asyncio.run(
        approval_continuation.resume(
            pending_id=pending_id, session_id=session_id, call_id="plan-1", context_generation=gen
        )
    )

    rows = _answers(session_id)
    assert len(rows) == 1
    assert [s["state"] for s in rows[0]["result"]["steps"]] == ["done"]
    assert rows[0]["record_id"] == "tool_result:plan-1"


# ============================================================ review findings (d7c95e9)

import re  # noqa: E402

from olga_companion import genkey_static, runner  # noqa: E402
from olga_companion.agent import approval_journal  # noqa: E402

SECRET_PATH = "C:\\Users\\secret\\work\\case.genkey"
OLD_CASE = {"source": "old.genkey", "selection_id": "sel-9", "timeout_s": 60}


def _row_json(body: dict[str, Any], pending_id: str) -> str:
    """Everything a person, the model or the journal could read about the plan."""
    return json.dumps([body, plan_progress.load(pending_id)], default=str)


# ---- M1: the plan card shows what a single card shows


def test_plan_display_publish_row_carries_the_reviewed_inputs(seam: Seam, gen: int) -> None:
    display = approval_display.build("action_plan", {"steps": _plan_steps(gen)}, locale="en")

    row = display["plan"]["steps"][1]
    assert row["inputs"] == seam.inputs
    assert seam.display_locales == ["en"], "inputs are localized like the single card"
    assert "inputs" not in display["plan"]["steps"][0]


def test_plan_display_exact_run_row_shows_runtime_executable_output_and_case(
    seam: Seam, gen: int, tmp_path: Path
) -> None:
    (tmp_path / "old.genkey").write_text("CASE LABEL=old\nENDCASE\n", encoding="utf-8")
    seen: list[tuple[str, int]] = []

    def previewer(source: str, timeout_s: int) -> dict[str, Any]:
        seen.append((Path(source).name, timeout_s))
        return {
            "selection_id": "sel-9",
            "runtime_id": "olga-2025",
            "detection": {"exe": "C:\\Program Files\\OLGA\\OLGA-2025.exe"},
            "timeout_s": timeout_s,
        }

    steps = _steps({"kind": "run_execute", "args": OLD_CASE})
    display = approval_display.build("action_plan", {"steps": steps}, previewer=previewer)

    fields = {field["key"]: field for field in display["plan"]["steps"][0]["fields"]}
    assert fields["run_case"]["value"] == "old.genkey"
    assert fields["runtime"]["value"] == "olga-2025"
    assert fields["executable"]["value"] == "OLGA-2025.exe"
    assert fields["output"]["value"]
    assert fields["timeout"] == {"key": "timeout", "value": "60", "unit": "s"}
    assert seen == [("old.genkey", 60)]
    assert "C:\\" not in json.dumps(display), "no host path on the card"


def test_plan_display_exact_run_row_refuses_a_selection_that_changed(
    seam: Seam, gen: int, tmp_path: Path
) -> None:
    (tmp_path / "old.genkey").write_text("CASE LABEL=old\nENDCASE\n", encoding="utf-8")
    steps = _steps({"kind": "run_execute", "args": OLD_CASE})

    with pytest.raises(ToolError):
        approval_display.build(
            "action_plan",
            {"steps": steps},
            previewer=lambda *_a: {"selection_id": "other", "detection": {}},
        )


def test_plan_display_bound_run_row_says_the_runtime_is_chosen_at_run_time(
    seam: Seam, gen: int
) -> None:
    row = approval_display.build("action_plan", {"steps": _plan_steps(gen)})["plan"]["steps"][2]

    assert row["unknown"] == ["run_case", "runtime", "executable", "output"]
    assert row["bound_to"] == 2


def test_plan_display_survives_an_unavailable_runtime_as_a_tool_error(
    seam: Seam, gen: int, tmp_path: Path
) -> None:
    (tmp_path / "old.genkey").write_text("CASE LABEL=old\nENDCASE\n", encoding="utf-8")

    def no_olga(*_a: Any) -> dict[str, Any]:
        raise genkey_static.OlgaInputError("No suitable OLGA executable detected.")

    steps = _steps({"kind": "run_execute", "args": OLD_CASE})
    with pytest.raises(ToolError):
        approval_display.build("action_plan", {"steps": steps}, previewer=no_olga)


# ---- M2: a plan with no reviewable display never becomes a card


def _chat_with_plan(gen: int, call_id: str) -> tuple[Any, str, dict[str, str]]:
    from fastapi.testclient import TestClient

    from olga_companion import sidecar

    headers = {"X-Session-Token": session_token.boot_token()}
    chat.set_client_builder(
        lambda *_a: _OneShotClient(
            StreamResult(
                tool_calls=[ToolCall(name="action_plan", args={"steps": _plan_steps(gen)}, call_id=call_id)]
            )
        )
    )
    api = TestClient(sidecar.app)
    session_id = api.post("/api/chat/session", json={"title": ""}, headers=headers).json()["session_id"]
    return api, session_id, headers


@pytest.mark.parametrize("failure", ["error", "empty", "no-rows"])
def test_a_plan_whose_display_fails_or_is_empty_is_answered_and_never_registered(
    seam: Seam, gen: int, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    def display(*_a: Any, **_k: Any) -> dict[str, Any]:
        if failure == "error":
            raise ToolError("The pending case publication no longer matches its reviewed transaction.")
        return {} if failure == "empty" else {"plan": {"steps": []}}

    monkeypatch.setattr(tools, "approval_display", display)
    api, session_id, headers = _chat_with_plan(gen, "plan-bad-display")

    streamed = api.post("/api/chat", json={"session_id": session_id, "message": "go"}, headers=headers)

    events = _sse(streamed.text)
    assert not [data for name, data in events if name == "approval_required"], "no card"
    answers = [data for name, data in events if name == "tool_result" and data["call_id"] == "plan-bad-display"]
    assert len(answers) == 1 and answers[0]["result"].get("error")
    assert approval_journal.load_all() == {}, "nothing was registered"
    stored = [
        r for r in history.read(session_id)
        if r.get("type") == "tool_result" and r.get("call_id") == "plan-bad-display"
    ]
    assert len(stored) == 1, "the call is answered once in history, so replay has no orphan"
    assert [r for r in history.read(session_id) if r.get("record") == "terminal"]


# ---- minor 1: a bound run is tied to the published bytes


@pytest.mark.parametrize("receipt_hash", ["0" * 64, None, "", 5])
def test_a_bound_run_refuses_when_the_saved_file_differs_from_the_receipt(
    seam: Seam, gen: int, receipt_hash: Any
) -> None:
    def publish(args: dict[str, Any]) -> dict[str, Any]:
        target = seam.root / args["destination_rel"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("CASE LABEL=edited\nENDCASE\n", encoding="utf-8")
        receipt: dict[str, Any] = {"state": "published", "destination_rel": args["destination_rel"]}
        if receipt_hash is not None:
            receipt["published_hash"] = receipt_hash
        return receipt

    seam.hooks["case_publish"] = publish
    session_id, pending_id = _register(_plan_steps(gen), gen)

    body = _execute(session_id, pending_id, gen)

    assert _states(body) == ["done", "done", "failed"]
    assert "run_preview" not in seam.names(), "nothing is previewed from unverified bytes"
    assert "run_execute" not in seam.names()
    assert body["state"] == "resume_pending"


# ---- minor 2: classification


def test_an_exception_while_binding_the_run_fails_the_step_instead_of_sealing_it(
    seam: Seam, gen: int
) -> None:
    def boom(_args: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError(f"cannot open {SECRET_PATH}")

    seam.hooks["run_preview"] = boom
    session_id, pending_id = _register(_plan_steps(gen), gen)

    body = _execute(session_id, pending_id, gen)

    assert _states(body) == ["done", "done", "failed"]
    assert body["state"] == "resume_pending", "nothing was started, so the plan is not uncertain"
    assert "run_execute" not in seam.names()
    assert "secret" not in _row_json(body, pending_id)


def test_run_execute_raises_a_typed_refusal_for_a_prelaunch_input_error(
    gen: int, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "old.genkey").write_text("CASE LABEL=old\nENDCASE\n", encoding="utf-8")

    def refuse(*_a: Any, **_k: Any) -> dict[str, Any]:
        raise genkey_static.OlgaInputError(
            "Validation reported blocking errors. Fix the case or set override=true to run anyway."
        )

    monkeypatch.setattr(runner, "execute_run", refuse)
    args = dict(OLD_CASE)
    token = approvals.mint(
        "run_execute", tools.approval_payload("run_execute", args), context_generation=gen
    )["token"]

    with pytest.raises(tools.ToolRefusedError, match="blocking errors"):
        tools.dispatch("run_execute", {**args, "approval_token": token, "idempotency_key": "k" * 32})


def test_a_prelaunch_refusal_fails_the_step_with_its_reason(seam: Seam, gen: int) -> None:
    def refuse(_args: dict[str, Any]) -> dict[str, Any]:
        raise tools.ToolRefusedError(
            "Validation reported blocking errors. Fix the case or set override=true to run anyway."
        )

    seam.hooks["run_execute"] = refuse
    session_id, pending_id = _register(_plan_steps(gen), gen)

    body = _execute(session_id, pending_id, gen)

    assert _states(body) == ["done", "done", "failed"]
    assert "Validation reported blocking errors" in body["result"]["steps"][2]["error"]
    assert body["state"] == "resume_pending"


def test_an_untyped_tool_error_from_an_entered_step_is_still_uncertain(seam: Seam, gen: int) -> None:
    def vague(_args: dict[str, Any]) -> dict[str, Any]:
        raise tools.ToolError("something happened after the step began")

    seam.hooks["run_execute"] = vague
    session_id, pending_id = _register(_plan_steps(gen), gen)

    with pytest.raises(approval_execution.ApprovalDispatchUncertainError) as raised:
        _execute(session_id, pending_id, gen)

    assert [s["state"] for s in raised.value.response()["steps"]] == ["done", "done", "uncertain"]


# ---- minor 4 / 5: plan rules for run steps


def test_a_plan_holds_at_most_one_run_step(gen: int) -> None:
    run = {"kind": "run_execute", "args": dict(OLD_CASE)}
    with pytest.raises(ToolError, match="at most one"):
        tools.approval_payload("action_plan", {"steps": [run, json.loads(json.dumps(run))]})


def test_a_bound_and_an_exact_run_step_also_count_as_two(gen: int) -> None:
    steps = _plan_steps(gen) + [{"kind": "run_execute", "args": dict(OLD_CASE)}]
    with pytest.raises(ToolError, match="at most one"):
        tools.approval_payload("action_plan", {"steps": steps})


def test_an_unbound_run_step_must_name_its_source(gen: int) -> None:
    steps = [{"kind": "run_execute", "args": {"selection_id": "sel-9", "timeout_s": 60}}]
    with pytest.raises(ToolError, match="source"):
        tools.approval_payload("action_plan", {"steps": steps})
    with pytest.raises(plan_model.PlanError, match="source"):
        plan_model.canonical_steps(steps)


# ---- minor 6: an uncertain plan keeps what finished


def test_an_uncertain_plan_keeps_the_results_of_its_completed_steps(
    seam: Seam, gen: int, tmp_path: Path
) -> None:
    (tmp_path / "old.genkey").write_text("CASE LABEL=old\nENDCASE\n", encoding="utf-8")

    def broken(_args: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("write started, then the connection dropped")

    seam.hooks["case_publish"] = broken
    steps = [{"kind": "run_execute", "args": dict(OLD_CASE)}, _plan_steps(gen)[1]]
    session_id, pending_id = _register(steps, gen)

    with pytest.raises(approval_execution.ApprovalDispatchUncertainError) as raised:
        _execute(session_id, pending_id, gen)

    shown = raised.value.response()["steps"]
    assert [s["state"] for s in shown] == ["done", "uncertain"]
    assert shown[0]["result"]["run_id"] == "run0001"
    _simulate_restart()
    assert plan_progress.report(pending_id)[0]["result"]["run_id"] == "run0001", "kept across a restart"


def test_the_prompt_says_what_an_uncertain_plan_means() -> None:
    segment = runtime.SYSTEM_PROMPT.split("action_plan", 1)[1][:2500].lower()
    assert "uncertain" in segment
    assert "outcome is unknown" in segment
    assert "before retrying" in segment
    assert "never assume" in segment


# ---- minor 7: no raw exception text, fixed sentences plus a safe code


@pytest.mark.parametrize(
    "raiser",
    [
        lambda: tools.ToolPreDispatchError(f"cannot read {SECRET_PATH}"),
        lambda: tools.ToolRefusedError(f"Approved OLGA runtime could not be contained safely: {SECRET_PATH}"),
        lambda: tools.ToolError(f"destination_collision: {SECRET_PATH}"),
    ],
)
def test_a_failed_step_never_stores_text_that_carries_a_path(
    seam: Seam, gen: int, raiser: Any
) -> None:
    def refuse(_args: dict[str, Any]) -> dict[str, Any]:
        raise raiser()

    seam.hooks["case_publish"] = refuse
    session_id, pending_id = _register(_plan_steps(gen), gen)

    body = _execute(session_id, pending_id, gen)

    assert _states(body) == ["done", "failed", "not_run"]
    failed = body["result"]["steps"][1]
    assert failed["error"] and re.fullmatch(r"[a-z0-9_]+", failed["code"])
    assert "secret" not in _row_json(body, pending_id)
    assert "C:" not in _row_json(body, pending_id)


def test_a_publish_refusal_reads_as_its_fixed_sentence(seam: Seam, gen: int) -> None:
    def collide(_args: dict[str, Any]) -> dict[str, Any]:
        raise tools.ToolError("destination_collision: exists")

    seam.hooks["case_publish"] = collide
    session_id, pending_id = _register(_plan_steps(gen), gen)

    failed = _execute(session_id, pending_id, gen)["result"]["steps"][1]

    assert failed["code"] == "destination_collision"
    assert failed["error"].startswith("destination_collision: ")
    assert failed["error"] != "destination_collision: exists"


def test_a_plan_closed_before_it_ran_names_why_in_a_stopped_result(seam: Seam, gen: int) -> None:
    session_id, pending_id = _register(_plan_steps(gen), gen)
    plan_progress.create(pending_id, "0" * 64, ["fluids_draft_mfl"], 9e12)

    body = _execute(session_id, pending_id, gen)

    assert body["result"]["state"] == "stopped" and body["result"]["ok"] is False
    assert seam.names() == []


# ---- minor 8: plan shape pins


def test_a_plan_inside_a_plan_is_refused(gen: int) -> None:
    nested = {"kind": "action_plan", "args": {"steps": _plan_steps(gen)}}
    with pytest.raises(ToolError, match="action_plan"):
        tools.approval_payload("action_plan", {"steps": [nested]})


def test_an_unknown_step_kind_is_refused(gen: int) -> None:
    with pytest.raises(ToolError, match="cannot be a plan step"):
        tools.approval_payload("action_plan", {"steps": [{"kind": "shell_exec", "args": {}}]})


def test_a_step_level_extra_key_is_refused(gen: int) -> None:
    steps = _plan_steps(gen)
    steps[0]["approval_token"] = "x"
    with pytest.raises(ToolError, match="unknown field"):
        tools.approval_payload("action_plan", {"steps": steps})


@pytest.mark.parametrize("source", [True, False, 2.0, "2", None, [2]])
def test_the_binding_must_be_a_real_integer(gen: int, source: Any) -> None:
    steps = _plan_steps(gen)
    steps[2]["source_from_step"] = source
    with pytest.raises(ToolError, match="earlier step"):
        tools.approval_payload("action_plan", {"steps": steps})


def test_the_reserved_table_kind_stays_in_the_list_and_refuses_until_it_exists(gen: int) -> None:
    assert "fluids_generate_tab" in plan_model.STEP_KINDS
    assert "fluids_generate_tab" not in plan_model.OFFERED_KINDS
    with pytest.raises(ToolError, match="not available"):
        tools.approval_payload("action_plan", {"steps": [{"kind": "fluids_generate_tab", "args": {}}]})


# ================================================ the real tools.dispatch (no Seam)

from types import SimpleNamespace  # noqa: E402

from case_spec_v2_support import PVT_TABLE_TEXT  # noqa: E402
from test_case_publish_tool_integration import _spec as _real_spec  # noqa: E402

from olga_companion.case_spec_validation import JsonObject  # noqa: E402,F401
from olga_companion.case_transactions import case_spec_hash, plan_case_edits  # noqa: E402


@pytest.fixture
def real(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """A real durable transaction and publish journal; only the OLGA process is faked."""
    root = tmp_path / "workspace"
    private = tmp_path / "private"
    root.mkdir()
    private.mkdir()
    (root / "fluid.tab").write_text(PVT_TABLE_TEXT, encoding="utf-8")
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(root))
    monkeypatch.setenv("OLGA_CASE_TRANSACTION_DIR", str(private / "transactions"))
    monkeypatch.setenv("OLGA_CASE_PUBLISH_JOURNAL_DIR", str(private / "journal"))
    generation = workspace.context_generation()
    spec = _real_spec()
    plan = plan_case_edits(
        spec,
        [{"op": "set_integration", "end_time_s": 7200.0}],
        expected_hash=case_spec_hash(spec),
        workspace_root=root,
        context_generation=generation,
    )
    assert plan.publishable is True, getattr(plan, "errors", plan)
    launch = SimpleNamespace(previews=[], launches=[], refusal=None)

    def preview(source: str, timeout_s: int = 3600, candidate_id: str | None = None) -> dict[str, Any]:
        launch.previews.append((Path(source).name, timeout_s))
        return {
            "source": source,
            "selection_id": "sel-real",
            "validation": {"valid": True},
            "timeout_s": timeout_s,
            "runtime_id": "olga-2025",
            "detection": {"exe": "OLGA-2025.exe"},
        }

    def execute(source: str, **kwargs: Any) -> dict[str, Any]:
        if launch.refusal is not None:
            raise launch.refusal
        launch.launches.append((Path(source).name, kwargs))
        return {"run_id": "run0001", "state": "running"}

    monkeypatch.setattr(runner, "preview_run", preview)
    monkeypatch.setattr(runner, "execute_run", execute)
    publish_args = {
        "transaction_id": plan.transaction_id,
        "source_hash": plan.source_hash,
        "compiled_hash": plan.compiled_hash,
        "destination_rel": "chat-built.genkey",
        "context_generation": generation,
    }
    return SimpleNamespace(
        root=root, generation=generation, plan=plan, launch=launch, publish_args=publish_args
    )


def _real_steps(real: SimpleNamespace) -> list[dict[str, Any]]:
    return [
        {"kind": "case_publish", "args": dict(real.publish_args)},
        {"kind": "run_execute", "args": {"timeout_s": 600}, "source_from_step": 1},
    ]


def test_real_dispatch_publishes_then_runs_the_published_case_once(real: SimpleNamespace) -> None:
    session_id, pending_id = _register(_real_steps(real), real.generation)

    body = _execute(session_id, pending_id, real.generation)

    assert _states(body) == ["done", "done"]
    published = real.root / "chat-built.genkey"
    assert hashlib.sha256(published.read_bytes()).hexdigest() == real.plan.compiled_hash
    assert real.launch.previews == [("chat-built.genkey", 600)]
    assert [(name, kw["approved"], kw["selection_id"]) for name, kw in real.launch.launches] == [
        ("chat-built.genkey", True, "sel-real")
    ]
    receipt = body["result"]["steps"][0]["result"]
    assert receipt["published_hash"] == real.plan.compiled_hash
    assert body["result"]["steps"][1]["result"]["run_id"] == "run0001"


def test_real_dispatch_replay_never_publishes_or_launches_twice(real: SimpleNamespace) -> None:
    session_id, pending_id = _register(_real_steps(real), real.generation)
    first = _execute(session_id, pending_id, real.generation)
    inode = (real.root / "chat-built.genkey").stat().st_ino

    second = _execute(session_id, pending_id, real.generation)

    assert _states(first) == _states(second) == ["done", "done"]
    assert len(real.launch.launches) == 1
    assert (real.root / "chat-built.genkey").stat().st_ino == inode


def test_real_dispatch_uses_a_valid_idempotency_key_and_a_fresh_token_per_step(
    real: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[tuple[str, str, str]] = []
    real_dispatch = tools.dispatch

    def spy(name: str, args: dict[str, Any]) -> dict[str, Any]:
        if name in {"case_publish", "run_execute"}:
            seen.append((name, str(args.get("approval_token")), str(args.get("idempotency_key"))))
        return real_dispatch(name, args)

    monkeypatch.setattr(tools, "dispatch", spy)
    session_id, pending_id = _register(_real_steps(real), real.generation)

    _execute(session_id, pending_id, real.generation)

    assert [name for name, _, _ in seen] == ["case_publish", "run_execute"]
    assert seen[0][1] != seen[1][1] and all(token for _, token, _ in seen)
    assert len({key for _, _, key in seen}) == 2
    assert all(re.fullmatch(r"[A-Za-z0-9_-]{32}", key) for _, _, key in seen)


def test_real_dispatch_refuses_a_run_when_the_published_file_was_touched(
    real: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_dispatch = tools.dispatch

    def tamper(name: str, args: dict[str, Any]) -> dict[str, Any]:
        result = real_dispatch(name, args)
        if name == "case_publish":
            (real.root / "chat-built.genkey").write_text("CASE LABEL=edited\nENDCASE\n", encoding="utf-8")
        return result

    monkeypatch.setattr(tools, "dispatch", tamper)
    session_id, pending_id = _register(_real_steps(real), real.generation)

    body = _execute(session_id, pending_id, real.generation)

    assert _states(body) == ["done", "failed"]
    assert real.launch.previews == [] and real.launch.launches == []


def test_real_dispatch_prelaunch_refusal_fails_the_run_step_with_its_reason(
    real: SimpleNamespace,
) -> None:
    real.launch.refusal = genkey_static.OlgaInputError(
        "Validation reported blocking errors. Fix the case or set override=true to run anyway."
    )
    session_id, pending_id = _register(_real_steps(real), real.generation)

    body = _execute(session_id, pending_id, real.generation)

    assert body["state"] == "resume_pending"
    assert _states(body) == ["done", "failed"]
    assert "Validation reported blocking errors" in body["result"]["steps"][1]["error"]


def test_real_display_for_a_plan_lists_the_reviewed_inputs_of_the_publish(real: SimpleNamespace) -> None:
    display = approval_display.build("action_plan", {"steps": _real_steps(real)}, locale="en")

    inputs = display["plan"]["steps"][0]["inputs"]
    assert inputs and all({"group", "name", "value"} <= set(item) for item in inputs)
    assert any(item["name"].endswith("Pressure") for item in inputs)
    assert "approval_token" not in json.dumps(display)


def test_real_display_refuses_a_plan_whose_transaction_changed(real: SimpleNamespace) -> None:
    steps = _real_steps(real)
    steps[0]["args"]["compiled_hash"] = "f" * 64

    with pytest.raises(ToolError):
        approval_display.build("action_plan", {"steps": steps})
