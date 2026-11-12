"""Codex ChatGPT-sign-in model contract.

Sources: https://github.com/openai/codex/blob/main/codex-rs/models-manager/models.json
and https://developers.openai.com/codex/changelog (GPT-5.5 retired 2026-10-14).
"""

from __future__ import annotations

import pytest

from olga_companion.llm import catalog, codex_oauth, copilot_clients, factory


GPT56_MODELS = (
    "gpt-5.6-sol",
    "gpt-5.6-terra",
    "gpt-5.6-luna",
)


CURRENT_MODELS = (
    "gpt-6.1-sol",
    "gpt-6-astra",
    "gpt-6-sol",
    "gpt-6-luna",
    *GPT56_MODELS,
)
REMOVED_MODELS = ("gpt-5.5", "gpt-5.3-codex-spark")


def test_gpt56_family_leads_catalog_and_sol_is_default() -> None:
    assert codex_oauth.SUPPORTED_MODELS == CURRENT_MODELS
    assert codex_oauth.DEFAULT_MODEL == "gpt-6.1-sol"
    assert set(REMOVED_MODELS).isdisjoint(codex_oauth.SUPPORTED_MODELS)

    models = catalog.available_models("openai")
    assert [model["id"] for model in models] == list(CURRENT_MODELS)
    labels = {model["id"]: model["label"] for model in models}
    assert [labels[model] for model in GPT56_MODELS] == [
        "GPT-5.6 Sol",
        "GPT-5.6 Terra",
        "GPT-5.6 Luna",
    ]


@pytest.mark.parametrize("model", GPT56_MODELS)
def test_gpt56_models_support_codex_efforts_through_max(model: str) -> None:
    expected = ("max", "xhigh", "high", "medium", "low")
    assert codex_oauth.supported_variants(model) == expected
    assert codex_oauth.resolve_variant(model, "max") == {
        "reasoning.effort": "max",
        "reasoning.summary": "detailed",
        "text.verbosity": "high",
    }

    advertised = next(
        item for item in catalog.available_models("openai") if item["id"] == model
    )
    assert advertised["reasoning_efforts"] == list(expected)
    assert advertised["default_effort"] == "medium"


@pytest.mark.parametrize("removed_model", REMOVED_MODELS)
def test_removed_chatgpt_sign_in_model_falls_back_to_default(removed_model: str) -> None:
    assert factory.resolve_llm_selection(
        {},
        {"active_llm_provider": "openai", "provider_models": {"openai": removed_model}},
    ) == ("openai", "gpt-6.1-sol", "medium")


def test_resolver_normalizes_effort_against_selected_model() -> None:
    assert factory.resolve_llm_selection(
        {
            "x-llm-provider": "openai",
            "x-llm-model": "gpt-5.6-terra",
            "x-llm-variant": "max",
        },
        {},
    ) == ("openai", "gpt-5.6-terra", "max")

    assert factory.resolve_llm_selection(
        {
            "x-llm-provider": "openai",
            "x-llm-model": "gpt-5.5",
            "x-llm-variant": "max",
        },
        {},
    ) == ("openai", "gpt-6.1-sol", "max")


def test_direct_agent_builder_rejects_an_invalid_model_effort_pair() -> None:
    with pytest.raises(codex_oauth.CodexAuthError):
        copilot_clients.build_openai_agent_client_from_codex(
            model="gpt-6-luna",
            variant="ultra",
        )
