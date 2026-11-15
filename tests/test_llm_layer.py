"""T1 gate — ported provider layer: protocol, catalog honesty, resolver, token isolation.

All offline: no network, no real home directory writes.
"""
from __future__ import annotations

import asyncio  # noqa: F401  # noqa: ANYIO_OK — directly drives provider coroutine contract
import json
from pathlib import Path

import pytest

from olga_companion.llm import catalog, factory
from olga_companion.llm.protocol import StreamResult, ToolCall, fix_schema


# ---------------------------------------------------------------- protocol

def test_fix_schema_repairs_bare_arrays_and_objects():
    fixed = fix_schema({"type": "object", "properties": {"xs": {"type": "array"}}})
    assert fixed["properties"]["xs"]["items"] == {}
    fixed2 = fix_schema({"type": "object"})
    assert fixed2["properties"] == {}


def test_toolcall_and_streamresult_shapes():
    call = ToolCall(name="genkey_validate", args={"path": "case.genkey"}, call_id="c1")
    result = StreamResult(text="ok", tool_calls=[call])
    assert result.tool_calls[0].name == "genkey_validate"
    assert result.usage == {}


# ---------------------------------------------------------------- catalog honesty

def test_unwired_providers_report_empty_catalog():
    assert catalog.available_models("anthropic") == []
    assert catalog.available_models("openrouter") == []
    assert catalog.available_models("definitely-not-a-provider") == []


def test_openai_catalog_is_nonempty_and_shaped():
    models = catalog.available_models("openai")
    assert models, "openai/codex catalog must list at least one model"
    assert all("id" in m for m in models)


def test_known_provider_registry():
    assert catalog.is_known_provider("openai")
    assert catalog.is_known_provider("copilot")
    assert not catalog.is_known_provider("skynet")


# ---------------------------------------------------------------- resolver precedence

def test_resolver_headers_beat_settings_beat_default():
    openai_models = catalog.available_models("openai")
    mid = openai_models[0]["id"]
    provider, model, variant = factory.resolve_llm_selection(
        {"X-LLM-Provider": "openai", "X-LLM-Model": mid, "X-LLM-Variant": "high"},
        {"active_llm_provider": "copilot"},
    )
    assert (provider, variant) == ("openai", "high")
    assert model == mid


def test_resolver_falls_back_to_settings_then_default():
    provider, _model, _variant = factory.resolve_llm_selection(
        {}, {"active_llm_provider": "copilot"}
    )
    assert provider == "copilot"
    provider2, _m2, variant2 = factory.resolve_llm_selection({}, {})
    assert provider2 == "openai"
    assert variant2 in ("xhigh", "high", "medium", "low")


def test_resolver_unknown_provider_falls_back_known_empty_keeps_identity():
    provider, _m, _v = factory.resolve_llm_selection(
        {"x-llm-provider": "skynet"}, {}
    )
    assert provider == "openai"  # unknown → default
    provider2, _m2, _v2 = factory.resolve_llm_selection(
        {"x-llm-provider": "copilot"}, {}
    )
    assert provider2 == "copilot"  # known (catalog may be live/empty) keeps identity


# ---------------------------------------------------------------- token isolation

def _reload_auth_modules():
    import importlib

    from olga_companion.llm import codex_oauth, copilot_auth, openai_auth
    from olga_companion.llm.antigravity import token as ag_token

    for mod in (codex_oauth, copilot_auth, openai_auth, ag_token):
        importlib.reload(mod)


@pytest.fixture
def isolated_home(monkeypatch, tmp_path):
    """Monkeypatch home + rebake auth-module path constants; restore real paths after."""
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    _reload_auth_modules()
    yield tmp_path
    monkeypatch.undo()
    _reload_auth_modules()


def test_token_paths_live_under_olga_copilot_dir(isolated_home):
    """All auth modules must persist under <home>/.olga_copilot/, never HYSYS names."""
    from olga_companion.llm import codex_oauth, copilot_auth, openai_auth
    from olga_companion.llm.antigravity import token as ag_token

    token_paths = [
        codex_oauth.APP_TOKENS_FILE,
        copilot_auth.COPILOT_TOKENS_FILE,
        openai_auth.OPENAI_TOKENS_FILE,
        ag_token.TOKENS_FILE,
    ]
    for p in token_paths:
        assert str(p).startswith(str(isolated_home)), p
        assert "/.olga_copilot/" in str(p).replace("\\", "/"), p
        assert "hysys" not in str(p).lower(), p


def test_copilot_token_write_creates_dir_and_restricts_mode(isolated_home):
    from olga_companion.llm import copilot_auth

    copilot_auth.save_tokens("gh-dummy-not-real", {"token": "dummy-not-real", "expires_at": 0})
    p = copilot_auth.COPILOT_TOKENS_FILE
    assert p.exists()
    data = json.loads(p.read_text())
    assert data["copilot_token"] == "dummy-not-real"
    assert data["github_token"] == "gh-dummy-not-real"
    assert (p.stat().st_mode & 0o777) in (0o600, 0o666), oct(p.stat().st_mode)
    # 0o666 tolerated only on DrvFS test envs without chmod support; CI target is 0600.


def test_antigravity_token_write_creates_dir_and_restricts_mode(isolated_home):
    """P1-2 regression lock: the 5th write site must mkdir + chmod like the others."""
    from datetime import datetime, timedelta, timezone

    from olga_companion.llm.antigravity import token as ag_token

    tokens = ag_token.OAuthTokens(
        access_token="dummy-not-real",
        refresh_token="dummy-refresh-not-real",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    ag_token.save_tokens(tokens)
    p = ag_token.TOKENS_FILE
    assert p.exists(), "save_tokens must create ~/.olga_copilot/ itself on fresh machines"
    assert (p.stat().st_mode & 0o777) in (0o600, 0o666), oct(p.stat().st_mode)


# ---------------------------------------------------------------- factory branches

def test_factory_branches_survive_module_rename(caplog):
    """P1-1 regression lock: no provider branch may die with ModuleNotFoundError
    (the preview_llm_adapter → copilot_clients rename once silently killed two)."""
    import logging

    from olga_companion.llm import factory

    with caplog.at_level(logging.WARNING):
        factory.build_llm_client("copilot", "gpt-5-mini", "medium")
        factory.build_llm_client("antigravity", "gemini-3-pro", "medium")
    assert "No module named" not in caplog.text


def test_copilot_tool_loop_redacts_unexpected_dispatch_exceptions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from olga_companion.llm import copilot_clients, openai_chat_adapter

    secret = "Bearer copilot-tool-secret /private/customer/case.genkey"
    captured_results: list[str] = []

    class Conversation:
        def add_user_message(self, _text):
            pass

        def add_assistant_response(self, _text, tool_calls=None):
            pass

        def add_tool_result(self, _call_id, _name, result):
            captured_results.append(result)

    class ApiClient:
        def __init__(self, **_kwargs):
            self.calls = 0

        def create_conversation(self, model):
            return Conversation()

        async def stream_generate(self, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                return StreamResult(
                    tool_calls=[ToolCall(name="run_detect", args={}, call_id="c1")]
                )
            return StreamResult(text="Handled safely.")

    def explode(_name, _args):
        raise RuntimeError(secret)

    monkeypatch.setattr(openai_chat_adapter, "OpenAIChatApiClient", ApiClient)
    client = copilot_clients.CopilotPreviewClient(model="gpt-5.4-mini", token="test-token")

    result = asyncio.run(
        client._generate_with_tools("system", "user", [], explode, 2, None)
    )

    assert result == "Handled safely."
    assert captured_results == [
        json.dumps({"error": "Tool execution failed unexpectedly. Retry the operation."})
    ]
    assert secret not in repr(captured_results)


# ---------------------------------------------------------------- no HYSYS identifiers

def test_no_hysys_identifiers_in_ported_layer():
    llm_dir = Path(__file__).resolve().parents[1] / "src" / "olga_companion" / "llm"
    offenders = []
    for py in llm_dir.rglob("*.py"):
        text = py.read_text(encoding="utf-8", errors="replace")
        if "hysys" in text.lower():
            offenders.append(py.name)
    assert not offenders, f"HYSYS identifiers leaked into ported layer: {offenders}"


def test_provisioned_secrets_not_ported():
    llm_dir = Path(__file__).resolve().parents[1] / "src" / "olga_companion" / "llm"
    assert not (llm_dir / "antigravity" / "_provisioned_secrets.py").exists()
