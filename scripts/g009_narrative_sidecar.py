"""Task-owned G009 browser-QA sidecar with a deterministic provider."""
from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from olga_companion import genkey_static, workspace
from olga_companion.agent import chat
from olga_companion.case_transactions import case_spec_hash
from olga_companion.llm.protocol import StreamResult, ToolCall

ROOT = Path(__file__).resolve().parents[1]
QA_ROOT = Path(os.environ["OLGA_WORKSPACE_DIR"]).resolve()
BASE_CASE = QA_ROOT / "qa_base.genkey"

CASE_SPEC: dict[str, Any] = {
    "version": "1",
    "nodes": [
        {"label": "SOURCE_A", "kind": "source", "pressure_pa": 2_000_000.0},
        {"label": "TEE_A", "kind": "junction"},
        {"label": "SINK_A", "kind": "sink", "pressure_pa": 1_000_000.0},
        {"label": "SINK_B", "kind": "sink", "pressure_pa": 900_000.0},
    ],
    "flowpaths": [
        {"label": "MAIN", "from": "SOURCE_A", "to": "TEE_A", "pipes": [{
            "label": "PIPE_A", "centerline_m": [[0, 0, 0], [100, 0, 5]],
            "diameter_m": 0.1, "sections": 10,
        }]},
        {"label": "BRANCH", "from": "TEE_A", "to": "SINK_A", "pipes": [{
            "label": "PIPE_B", "centerline_m": [[100, 0, 5], [160, 25, 0]],
            "diameter_m": 0.08, "sections": 6,
        }]},
        {"label": "BRANCH_B", "from": "TEE_A", "to": "SINK_B", "pipes": [{
            "label": "PIPE_C", "centerline_m": [[100, 0, 5], [150, -20, 2]],
            "diameter_m": 0.06, "sections": 17,
        }]},
    ],
    "pvt_reference": "fluids/fluid.tab",
    "integration": {"end_time_s": 3600},
    "outputs": ["PT", "TM"],
}


@dataclass(frozen=True, slots=True)
class Message:
    kind: str
    text: str
    name: str = ""


class Conversation:
    def __init__(self) -> None:
        self.messages: list[Message] = []

    def add_user_message(self, text: str, images=None) -> None:
        self.messages.append(Message("user", text))

    def add_assistant_response(self, text: str, tool_calls=None, thought_signature=None) -> None:
        self.messages.append(Message("assistant", text))

    def add_tool_result(self, call_id: str, name: str, result: str) -> None:
        self.messages.append(Message("tool_result", result, name))


class NarrativeClient:
    def __init__(self) -> None:
        self.counter = 0

    def create_conversation(self, model: str = "") -> Conversation:
        return Conversation()

    def call(self, name: str, args: dict[str, Any]) -> StreamResult:
        self.counter += 1
        return StreamResult(tool_calls=[ToolCall(name=name, args=args, call_id=f"g009-{self.counter}")])

    async def stream_generate(self, **kwargs) -> StreamResult:
        conversation: Conversation = kwargs["conversation"]
        users = [message.text for message in conversation.messages if message.kind == "user"]
        prompt = users[-1].casefold() if users else ""
        last = conversation.messages[-1] if conversation.messages else Message("", "")
        result = json.loads(last.text) if last.kind == "tool_result" else {}

        if "같은 플롯" in prompt and last.kind != "tool_result":
            return self.call("results_plot", _plot_args("png"))
        if "같은 플롯" in prompt:
            return StreamResult(text="직전 PT/TM overlay 선택을 유지해 같은 PNG artifact를 재생성했습니다.")
        if "강제 실패" in prompt or "트러블슈팅" in prompt:
            if last.kind != "tool_result":
                return self.call("diagnose_out", {"path": "qa_injected.out"})
            return StreamResult(text="진단 근거를 확인했습니다. 수정안은 제안 상태이며 자동 적용·게시·재실행하지 않았습니다.")
        if "결과" in prompt or "export" in prompt:
            return self._results(last, result)
        if "실행" in prompt or "patrol" in prompt:
            return self._run(last, result)
        if "수정" in prompt or "형상" in prompt:
            return self._edit(last, result)
        if "구축" in prompt or "생성" in prompt or "casespec" in prompt:
            return self._build(last, result)
        return StreamResult(text="QA 명령을 자연어로 입력하세요: 구축, 수정, 실행, 강제 실패, 결과 export.")

    def _build(self, last: Message, result: dict[str, Any]) -> StreamResult:
        if last.kind != "tool_result":
            return self.call("case_spec_validate", {"spec": CASE_SPEC})
        if last.name == "case_spec_validate":
            return self.call("case_spec_compile", {"spec": CASE_SPEC})
        if last.name == "case_spec_compile":
            return self.call("case_edit_plan", {
                "spec": CASE_SPEC, "spec_hash": case_spec_hash(CASE_SPEC),
                "operations": [{"op": "set_outputs", "outputs": ["PT", "TM"]}],
            })
        if last.name == "case_edit_plan":
            return self.call("case_publish", _publish_args(result, "qa_built.genkey"))
        return StreamResult(text="CaseSpec 검증·컴파일·게시가 완료됐습니다. 4-node branched geometry와 33 sections를 확인했습니다.")

    def _edit(self, last: Message, result: dict[str, Any]) -> StreamResult:
        if last.kind != "tool_result":
            return self.call("case_edit_plan", {
                "source": "qa_base.genkey",
                "source_hash": genkey_static.file_sha256(BASE_CASE),
                "operations": [
                    {"op": "set_pipe_geometry", "flowpath": "MAIN", "pipe": "PIPE_A", "z_offset_m": 10.0},
                    {"op": "set_pipe_geometry", "flowpath": "BRANCH", "pipe": "PIPE_B", "z_offset_m": 10.0},
                    {"op": "set_pipe_geometry", "flowpath": "BRANCH_B", "pipe": "PIPE_C", "z_offset_m": 10.0},
                    {"op": "set_pipe_sections", "flowpath": "MAIN", "pipe": "PIPE_A", "sections": 20},
                    {"op": "set_integration", "end_time_s": 10800.0},
                ],
            })
        if last.name == "case_edit_plan":
            return self.call("case_publish", _publish_args(result, "qa_modified.genkey"))
        return StreamResult(text="세 가지 변경을 한 트랜잭션으로 검증·게시했습니다. 원본 qa_base는 변경되지 않았습니다.")

    def _run(self, last: Message, result: dict[str, Any]) -> StreamResult:
        if last.kind != "tool_result":
            return self.call("run_preview", {"source": "qa_base.genkey", "timeout_s": 120})
        if last.name == "run_preview":
            return self.call("run_execute", {
                "source": "qa_base.genkey", "timeout_s": 120,
                "selection_id": result["selection_id"],
            })
        if last.name == "run_execute":
            return self.call("run_patrol", {
                "run_id": result["run_id"], "deadline_s": 30,
                "max_polls": 10, "backoff_s": 0.1,
            })
        if result.get("terminal") is not True:
            return StreamResult(text="bounded patrol에서 terminal 상태를 확인하지 못했습니다. 실행 성공으로 간주하지 않습니다.")
        return StreamResult(text="승인된 fake OLGA run을 bounded patrol로 terminal까지 확인했습니다.")

    def _results(self, last: Message, result: dict[str, Any]) -> StreamResult:
        if last.kind != "tool_result":
            return self.call("results_inventory", {"limit": 20})
        if last.name == "results_inventory":
            return self.call("results_series", _series_args("PT"))
        if last.name == "results_series" and result.get("variable") == "PT":
            return self.call("results_series", _series_args("TM"))
        if last.name == "results_series":
            return self.call("results_plot", _plot_args("png"))
        if last.name == "results_plot" and result.get("kind") == "png":
            return self.call("results_plot", _plot_args("pdf"))
        if last.name == "results_plot":
            return self.call("results_csv", {
                "path": "workspace:fixture.tpl", "variables": ["PT", "TM"]
            })
        return StreamResult(text="최신 결과에서 PT/TM 표, 겹친 plot, PNG·PDF·CSV artifact를 생성했습니다. 같은 플롯도 이어서 지정할 수 있습니다.")


def _series_args(variable: str) -> dict[str, Any]:
    position = "POSITION - INLET" if variable == "PT" else "SECTION - Br - PIPELINE - PIPE - PIPE-1 - NR - 1"
    return {"result_id": "workspace:fixture.tpl", "variable": variable, "position": position, "row_limit": 5}


def _plot_args(fmt: str) -> dict[str, Any]:
    if fmt == "pdf":
        return {
            "path": "workspace:fixture.tpl",
            "variables": ["PT"],
            "position": "POSITION - INLET",
            "format": fmt,
        }
    return {"path": "workspace:fixture.tpl", "variables": ["PT", "TM"], "format": fmt}


def _publish_args(result: dict[str, Any], destination: str) -> dict[str, Any]:
    return {key: result[key] for key in ("transaction_id", "source_hash", "compiled_hash", "context_generation")} | {"destination_rel": destination}


def configure_qa_runtime() -> None:
    os.environ["OLGA_EXE_PATH"] = str(ROOT / "tests" / "fixtures" / "fake_olga" / "fake_olga.py")
    os.environ["FAKE_OLGA_RESULTS"] = "1"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8866)
    parser.add_argument("--frontend-port", type=int, default=5274)
    args = parser.parse_args()
    configure_qa_runtime()
    workspace.set_active_rel("qa_base.genkey")
    client = NarrativeClient()
    chat.set_client_builder(lambda _provider, _model, _variant: client)
    from olga_companion.sidecar import app
    import uvicorn

    os.environ["OLGA_FRONTEND_PORT"] = str(args.frontend_port)
    os.environ["OLGA_SIDECAR_PORT"] = str(args.port)
    uvicorn.run(app, host="127.0.0.1", port=args.port, reload=False)


if __name__ == "__main__":
    main()
