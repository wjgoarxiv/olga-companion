"""Locks the real agent<->provider wiring that T5 deferred (the FakeClient hid it).

Three gaps made a real Codex turn fail with "Provider 'openai' is not connected":
  1. openai built from ~/.olga_copilot tokens, never bridged to ~/.codex/auth.json
  2. _build_real_client returned a PreviewLLMClient (string->string), not an ApiClient
  3. the Responses adapter's _convert_tools only accepted GenAI types.Tool, but the
     agent yields flat spec dicts (and google.genai isn't even installed)
See .litopencode/litgoal/lit-loop/evidence/v2-real-qa-finding.md.
"""
from olga_companion.agent import chat, tools
from olga_companion.llm import codex_oauth, copilot_clients
from olga_companion.llm.openai_responses_adapter import OpenAIResponsesApiClient


class _FakeCreds:
    access_token = "tok-abc"
    account_id = "acct-123"


class _MissingCredentialsError(RuntimeError):
    """Synthetic credential lookup failure for fail-closed wiring tests."""


def test_convert_tools_accepts_flat_agent_specs():
    """Gap 3: the agent's flat {name,description,parameters} specs convert cleanly."""
    specs = [
        {
            "name": "genkey_review",
            "description": "Review a case",
            "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
        }
    ]
    out = OpenAIResponsesApiClient._convert_tools(specs)
    assert len(out) == 1
    assert out[0]["type"] == "function"
    assert out[0]["name"] == "genkey_review"
    assert out[0]["description"] == "Review a case"
    assert isinstance(out[0]["parameters"], dict)


def test_convert_tools_handles_every_real_tool_spec():
    """The whole live tool belt must convert without an AttributeError."""
    specs = tools.tool_specs()
    out = OpenAIResponsesApiClient._convert_tools(specs)
    assert len(out) == len(specs)
    assert all(t["type"] == "function" and t["name"] for t in out)
    side_effect_names = {
        name for name, tool in tools.TOOLS.items() if tool.side_effect
    }
    for item in out:
        if item["name"] in side_effect_names:
            assert "approval_token" not in item["parameters"]["properties"]
            assert "approval_token" not in item["parameters"].get("required", [])


def test_build_openai_agent_client_from_codex_returns_apiclient(monkeypatch):
    """Gaps 1+2: openai builds the tool-calling ApiClient from Codex OAuth."""
    monkeypatch.setattr(codex_oauth, "get_fresh_credentials", lambda: _FakeCreds())
    client = copilot_clients.build_openai_agent_client_from_codex(model="gpt-6.1-sol")
    assert isinstance(client, OpenAIResponsesApiClient)
    assert hasattr(client, "create_conversation") and hasattr(client, "stream_generate")


def test_build_real_client_openai_is_apiclient_not_preview(monkeypatch):
    """The chat seam returns an ApiClient (run_turn contract), not a PreviewLLMClient."""
    monkeypatch.setattr(codex_oauth, "get_fresh_credentials", lambda: _FakeCreds())
    client = chat._build_real_client("openai", "gpt-6.1-sol", "")
    assert isinstance(client, OpenAIResponsesApiClient)
    conv = client.create_conversation("gpt-6.1-sol")
    assert hasattr(conv, "add_user_message") and hasattr(conv, "add_tool_result")


def test_build_real_client_openai_fails_closed_without_creds(monkeypatch):
    """No usable Codex credential -> None (caller surfaces 'connect this provider')."""
    def _raise():
        raise _MissingCredentialsError("no codex creds")

    monkeypatch.setattr(codex_oauth, "get_fresh_credentials", _raise)
    assert chat._build_real_client("openai", "gpt-6.1-sol", "") is None
