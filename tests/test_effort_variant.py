"""F1 — the reasoning-effort variant reaches the Responses-API request body.

Ported from HysysCompanion's X-LLM-Variant → reasoning.effort methodology.
"""
from olga_companion.llm import codex_oauth
from olga_companion.llm.openai_responses_adapter import OpenAIResponsesApiClient


def _body(client):
    return client._request_body(
        model="gpt-5.5", system_instruction="s", input_payload=[], resp_tools=None, force_tool=False
    )


def test_variant_profiles_cover_the_supported_tiers():
    assert set(codex_oauth._VARIANT_PROFILE) == {"max", "xhigh", "high", "medium", "low"}
    assert codex_oauth._VARIANT_PROFILE["max"] == {"effort": "max", "summary": "detailed", "verbosity": "high"}
    assert codex_oauth._VARIANT_PROFILE["xhigh"] == {"effort": "xhigh", "summary": "detailed", "verbosity": "high"}
    assert codex_oauth._VARIANT_PROFILE["low"]["effort"] == "low"


def test_request_body_carries_reasoning_effort_when_configured():
    client = OpenAIResponsesApiClient(
        base_url="http://x", access_token="t",
        reasoning={"effort": "xhigh", "summary": "detailed"},
        text={"verbosity": "high"},
    )
    body = _body(client)
    assert body["reasoning"] == {"effort": "xhigh", "summary": "detailed"}
    assert body["text"] == {"verbosity": "high"}


def test_request_body_omits_reasoning_when_unset():
    body = _body(OpenAIResponsesApiClient(base_url="http://x", access_token="t"))
    assert "reasoning" not in body
    assert "text" not in body
