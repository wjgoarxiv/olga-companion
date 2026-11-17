"""QA-only sidecar bootstrap: injects a scripted FakeApiClient so the chat spine
runs deterministically in the browser without an LLM or OAuth. NOT shipped.

Builds a RUNNABLE demo case at startup (sample genkey with its PVTFILE reference
satisfied by a real fluid.tab beside it) so an approved run actually executes via
the fake-OLGA fixture and produces evidence — instead of failing the PVT preflight.
"""
import os
import shutil
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("OLGA_EXE_PATH", os.path.join(_ROOT, "tests", "fixtures", "fake_olga", "fake_olga.py"))

# Build a runnable case under var/demo/.
_SAMPLE = os.path.join(_ROOT, "tests", "fixtures", "cases", "simple_pipeline.genkey")
_DEMO_DIR = os.path.join(_ROOT, "var", "demo")
os.makedirs(_DEMO_DIR, exist_ok=True)
CASE = os.path.join(_DEMO_DIR, "demo_pipeline.genkey")
with open(_SAMPLE) as f:
    _text = f.read().replace('"./dummy_fluid.tab"', '"./fluid.tab"')
with open(CASE, "w") as f:
    f.write(_text)
shutil.copy2(os.path.join(_ROOT, "tests", "fixtures", "fluids", "fluid.tab"), os.path.join(_DEMO_DIR, "fluid.tab"))

from olga_companion.agent import chat  # noqa: E402
from olga_companion.llm.protocol import StreamResult, ToolCall  # noqa: E402


class Conv:
    def add_user_message(self, text, images=None):
        self.last = text

    def add_assistant_response(self, text, tool_calls=None, thought_signature=None):
        pass

    def add_tool_result(self, call_id, name, result):
        self.last_result = result


class FakeClient:
    """Keyword-driven scripted replies covering validate → run → approval → executed run."""

    def create_conversation(self, model=""):
        self._conv = Conv()
        self._state = "idle"
        return self._conv

    async def stream_generate(self, **kw):
        conv = kw.get("conversation")
        msg = getattr(conv, "last", "") or ""
        low = msg.lower()

        # Approved run: the UI's follow-up carries the minted token.
        if "approval_token" in msg:
            import re

            if self._state == "ran":
                return StreamResult(text="The run is underway in the sandbox (fake-OLGA). Ask me to check its status or diagnose the .out log.")
            self._state = "ran"
            tok = (re.search(r'approval_token "([^"]+)"', msg) or [None, ""])[1]
            return StreamResult(tool_calls=[ToolCall(name="run_execute", args={"source": CASE, "approval_token": tok, "timeout_s": 3600}, call_id="run1")])

        # Run request (no token yet) → the agent calls run_execute once, which the
        # runtime surfaces as approval_required + refuses (no token).
        if "run" in low and self._state != "awaiting":
            self._state = "awaiting"
            return StreamResult(tool_calls=[ToolCall(name="run_execute", args={"source": CASE, "timeout_s": 3600}, call_id="prev1")])
        if "run" in low and self._state == "awaiting":
            return StreamResult(text="I built the command and need your approval to run it — please review the card above.")

        # Validate / build / review.
        if any(k in low for k in ("validate", "review", "build", "case", "topology")):
            if self._state != "reviewed":
                self._state = "reviewed"
                return StreamResult(tool_calls=[ToolCall(name="genkey_review", args={"path": CASE}, call_id="rev1")])
            return StreamResult(text="I validated the case: it passes with no issues. The topology is a simple inlet → pipeline → outlet.")

        return StreamResult(text="Tell me what you'd like to do with your OLGA case — build, validate, run, analyze, or troubleshoot.")


chat.set_client_builder(lambda p, m, v: FakeClient())

import uvicorn  # noqa: E402
from olga_companion.sidecar import app  # noqa: E402

uvicorn.run(app, host="127.0.0.1", port=8865, reload=False)
